"""
De dónde saca la Estación 4 los datos de E1, E2 y E3.

FuenteE5       (la arquitectura acordada): todas las estaciones envían a la API de E5
               y E4 la consulta. Datos con id_grupo/id_fruta -> se rellena por id.
FuenteArchivos (lo que las estaciones producen HOY, sin red):
               E1: manifiestos JSON por fruta en una carpeta (estacion1/src/client_e2.py)
               E2: estacion2_result.json, se sobrescribe por fruta (estacion2/src/station_listener.py)
               E3: todavía no emite nada; se propone un JSON igual al de E2 (ver README)
               Sin id en E2/E3 -> se rellena en orden (FIFO).

ClienteE5 también envía las decisiones de E4 a POST /api/v1/ingest/e4 (contrato E4.json).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import config
import normalizar
from clasificador import ColaFIFO, Decision


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _orden_natural(s: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s or "")]


# ---------------------------------------------------------------------------
# HTTP con E5 (solo librería estándar)
# ---------------------------------------------------------------------------
class ClienteE5:
    def __init__(self, url=config.URL_E5, api_key=config.API_KEY_E5, timeout=config.TIMEOUT_HTTP_S):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.ultimo_error: str | None = None

    def _pedir(self, metodo, ruta, cuerpo=None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
        req = urllib.request.Request(self.url + ruta, data=datos, method=metodo)
        req.add_header("Accept", "application/json")
        if datos is not None:
            req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                texto = r.read().decode("utf-8")
                self.ultimo_error = None
                return r.status, (json.loads(texto) if texto else None)
        except urllib.error.HTTPError as e:
            self.ultimo_error = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            return e.code, None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self.ultimo_error = f"sin conexión con E5 ({e})"
            return None, None

    def get(self, ruta):
        status, datos = self._pedir("GET", ruta)
        return datos if status == 200 else None

    def post(self, ruta, cuerpo) -> int | None:
        return self._pedir("POST", ruta, cuerpo)[0]


class FuenteE5:
    def __init__(self, cliente: ClienteE5):
        self.cliente = cliente
        self.lote: str | None = None
        self.grupos_vistos: set[str] = set()
        self.esperadas: dict[str, int] = {}     # id_grupo -> cuántas frutas tiene
        self._arranco = False

    def leer(self, cola: ColaFIFO) -> list[str]:
        eventos = []
        lotes = self.cliente.get("/api/v1/lotes")
        if not lotes:
            return eventos
        lote = lotes[0]["id_lote"]                       # E5 los ordena del más nuevo al más viejo
        if lote != self.lote:
            self.lote = lote
            eventos.append(f"lote activo en E5: {lote}")

        grupos = self.cliente.get(f"/api/v1/lotes/{quote(lote)}/grupos?limit=100") or []
        if not self._arranco:
            # Lo que ya estaba en E5 al encender E4 no está en la cinta: no se procesa
            self._arranco = True
            self.grupos_vistos.update(g["id_grupo"] for g in grupos)
            if grupos:
                eventos.append(f"se ignoran {len(grupos)} grupos que ya estaban en E5 al arrancar")
            return eventos
        nuevos = sorted((g for g in grupos if g["id_grupo"] not in self.grupos_vistos),
                        key=lambda g: (g.get("ingreso") or "", _orden_natural(g["id_grupo"])))
        for g in nuevos:
            ids = self._ids_frutas(g)
            if not ids:
                continue                                  # aún no se sabe cuántas frutas trae
            self.grupos_vistos.add(g["id_grupo"])
            self.esperadas[g["id_grupo"]] = len(ids)
            for id_fruta in ids:
                cola.nueva_fruta(None, lote, g["id_grupo"], id_fruta, g.get("validez_imagen") is not False)
            eventos.append(f"grupo nuevo {g['id_grupo']} con {len(ids)} frutas")

        pendientes = {p.id_grupo for p in cola if p.id_grupo and (p.estado is None or p.tamano is None)}
        for id_grupo in sorted(pendientes, key=_orden_natural):
            self._rellenar_grupo(cola, id_grupo)
        return eventos

    def refrescar(self, cola: ColaFIFO):
        """Justo antes de decidir: si a la primera fruta le faltan datos, se pregunta una vez más a E5."""
        if cola.cola:
            p = cola.cola[0]
            if p.id_grupo and (p.estado is None or p.tamano is None):
                self._rellenar_grupo(cola, p.id_grupo)

    def _ids_frutas(self, g) -> list[str]:
        # Por defecto E1 numera F1..Fn (docs/formato_datos/README.md de E5)
        if g.get("frutas_detectadas"):
            return [f"F{k}" for k in range(1, int(g["frutas_detectadas"]) + 1)]
        det = self.cliente.get(f"/api/v1/grupos/{quote(g['id_grupo'])}")
        if det and det.get("frutas"):
            return sorted((f["id_fruta"] for f in det["frutas"]), key=_orden_natural)
        return []

    def _rellenar_grupo(self, cola: ColaFIFO, id_grupo: str):
        det = self.cliente.get(f"/api/v1/grupos/{quote(id_grupo)}")
        for f in (det or {}).get("frutas", []):
            cola.rellenar_por_id(
                id_grupo, f["id_fruta"],
                estado=normalizar.estado(f.get("calidad_visual")),
                confianza=normalizar.confianza(f.get("confianza_visual")),
                tamano=normalizar.tamano(f.get("tamano"), f.get("diametro_mm")),
                diametro_mm=f.get("diametro_mm"),
            )


# ---------------------------------------------------------------------------
# Archivos (formato actual de E1 y E2)
# ---------------------------------------------------------------------------
def _leer_json(ruta: Path):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None          # no existe o se está escribiendo: se reintenta en la próxima vuelta


class FuenteArchivos:
    def __init__(self, carpetas_e1: list[str], archivo_e2: str | None, archivo_e3: str | None):
        self.carpetas_e1 = [Path(c) for c in carpetas_e1]
        self.archivo_e2 = Path(archivo_e2) if archivo_e2 else None
        self.archivo_e3 = Path(archivo_e3) if archivo_e3 else None
        self.vistos: set[Path] = set()
        self.ts_e2 = self.ts_e3 = None
        self.esperadas: dict[str, int] = {}
        # Lo que ya estaba antes de partir no se procesa
        for c in self.carpetas_e1:
            self.vistos.update(c.rglob("*.json") if c.exists() else [])
        for attr, arch in (("ts_e2", self.archivo_e2), ("ts_e3", self.archivo_e3)):
            datos = _leer_json(arch) if arch else None
            setattr(self, attr, datos.get("timestamp") if datos else None)

    def refrescar(self, cola: ColaFIFO):
        pass                      # los archivos ya se leen en cada vuelta

    def leer(self, cola: ColaFIFO) -> list[str]:
        eventos = []
        nuevos = []
        for c in self.carpetas_e1:
            if c.exists():
                nuevos += [p for p in c.rglob("*.json") if p not in self.vistos]
        manifiestos = []
        for ruta in nuevos:
            m = _leer_json(ruta)
            if m is None:
                continue
            self.vistos.add(ruta)
            if "id_fruta" in m:
                manifiestos.append(m)
        for m in sorted(manifiestos, key=lambda m: m.get("timestamp", "")):
            aceptada = m.get("estado_captura") == "aceptada"
            # E1 no arma grupos: cada fruta es su propio grupo de 1
            cola.nueva_fruta(None, m.get("id_lote"), m["id_fruta"], "F1", aceptada)
            self.esperadas[m["id_fruta"]] = 1
            eventos.append(f"E1: fruta {m['id_fruta']} ({m.get('estado_captura')})")

        r2 = _leer_json(self.archivo_e2) if self.archivo_e2 else None
        if r2 and r2.get("timestamp") != self.ts_e2:
            self.ts_e2 = r2.get("timestamp")
            clase = r2.get("predicted_class") or r2.get("calidad_visual")
            conf = r2.get("confidence_percent", r2.get("confianza_visual"))
            if conf is None and clase in (r2.get("probabilities") or {}):
                conf = r2["probabilities"][clase]
            p = cola.rellenar_siguiente("estado", normalizar.estado(clase) or "Revision",
                                        confianza=normalizar.confianza(conf))
            eventos.append(f"E2: {clase} -> fruta #{p.n if p else '¿sin paquete?'}")

        r3 = _leer_json(self.archivo_e3) if self.archivo_e3 else None
        if r3 and r3.get("timestamp") != self.ts_e3:
            self.ts_e3 = r3.get("timestamp")
            tam = normalizar.tamano(r3.get("tamano"), r3.get("diametro_mm"))
            p = cola.rellenar_siguiente("tamano", tam or "Mediana", diametro_mm=r3.get("diametro_mm"))
            eventos.append(f"E3: {tam} -> fruta #{p.n if p else '¿sin paquete?'}")
        return eventos


# ---------------------------------------------------------------------------
# Envío de decisiones a E5 (un mensaje por grupo, contrato E4.json)
# ---------------------------------------------------------------------------
class ReporteE4:
    def __init__(self, cliente: ClienteE5 | None, esperadas: dict[str, int], espera_max_s: float = 15.0):
        self.cliente = cliente
        self.esperadas = esperadas
        self.espera_max_s = espera_max_s
        self.grupos: dict[tuple, dict] = {}       # (id_lote, id_grupo) -> {"t": ..., "frutas": [...]}
        self.pendientes: list[tuple[dict, int]] = []   # mensajes que fallaron (mensaje, intentos)
        self.enviados = 0

    def agregar(self, d: Decision, t: float | None = None) -> list[str]:
        p = d.paquete
        if not p.id_grupo:
            return []
        clave = (p.id_lote or "SIN-LOTE", p.id_grupo)
        g = self.grupos.setdefault(clave, {"t": time.time() if t is None else t, "frutas": []})
        g["frutas"].append({
            "id_fruta": p.id_fruta or f"F{len(g['frutas']) + 1}",
            "categoria_final": d.categoria_final,
            "probabilidad": round(min(max(d.probabilidad, 0.0), 1.0), 3),
            "requiere_revision_manual": bool(d.requiere_revision_manual),
        })
        if len(g["frutas"]) >= self.esperadas.get(p.id_grupo, 1):
            return self._enviar(clave)
        return []

    def revisar(self, t: float | None = None) -> list[str]:
        """Envía grupos incompletos que esperaron demasiado y reintenta los fallidos."""
        t = time.time() if t is None else t
        log = []
        for clave in [c for c, g in self.grupos.items() if t - g["t"] > self.espera_max_s]:
            log += self._enviar(clave)
        reintentar, self.pendientes = self.pendientes, []
        for msg, intentos in reintentar:
            log += self._post(msg, intentos)
        return log

    def _enviar(self, clave) -> list[str]:
        g = self.grupos.pop(clave)
        msg = {"id_lote": clave[0], "id_grupo": clave[1], "estacion": "E4",
               "timestamp": ahora_iso(), "frutas": g["frutas"]}
        return self._post(msg, 0)

    def _post(self, msg, intentos) -> list[str]:
        if self.cliente is None:
            return [f"(sin E5) E4 -> {json.dumps(msg, ensure_ascii=False)}"]
        status = self.cliente.post("/api/v1/ingest/e4", msg)
        if status in (200, 201):
            self.enviados += 1
            return [f"E5 recibió E4 de {msg['id_grupo']} ({len(msg['frutas'])} frutas)"]
        if status == 422:
            return [f"E5 rechazó E4 de {msg['id_grupo']}: {self.cliente.ultimo_error}"]
        if intentos + 1 < 5:
            self.pendientes.append((msg, intentos + 1))
        return [f"no se pudo enviar E4 de {msg['id_grupo']} (intento {intentos + 1}/5): {self.cliente.ultimo_error}"]

# Bloque para enviar la predicción de la IA
payload_prediccion = {
    "id_lote": gestor.id_lote,
    "estacion": "E4",
    "timestamp": ahora_iso(),
    "frutas_vistas": sum(vistas),
    "categoria_predicha": r["categoria"],        
    "probabilidades": r["probabilidades"],       
    "pct_esperado": r["pct"],                    # {'pct_pasable', 'pct_chica', 'pct_mediana', 'pct_grande'}
}