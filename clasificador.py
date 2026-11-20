"""
Cola FIFO de frutas, regla del servo y registro del lote.

Flujo:
  1. Llega una fruta nueva (E1 la registró)  -> cola.nueva_fruta(...)
  2. Llegan datos de E2 y E3                 -> cola.rellenar_por_id(...)   si traen id
                                                cola.rellenar_siguiente(...) si no traen id
  3. La fruta corta la barrera IR del servo  -> d = cola.disparo_sensor()
  4. Se mueve el servo a d.caja y se suma al lote -> gestor.registrar(d)
"""
from __future__ import annotations

import csv
import itertools
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import config


def _ahora(t: float | None) -> float:
    return time.time() if t is None else t


# ---------------------------------------------------------------------------
# Paquete virtual de cada fruta
# ---------------------------------------------------------------------------
@dataclass
class PaqueteFruta:
    n: int                              # número correlativo interno
    t_entrada: float
    id_lote: str | None = None
    id_grupo: str | None = None
    id_fruta: str | None = None
    foto_valida: bool = True            # E1 aceptó la captura (si no, E2 no la analiza)
    estado: str | None = None           # Buena | Pasable | Mala | Revision   (E2)
    confianza: float | None = None      # 0 a 1                              (E2)
    tamano: str | None = None           # Chica | Mediana | Grande           (E3)
    diametro_mm: float | None = None    #                                    (E3)

    @property
    def clave(self):
        return (self.id_grupo, self.id_fruta)


@dataclass
class Decision:
    paquete: PaqueteFruta
    caja: int
    categoria_final: str        # exportacion | mercado_nacional | proceso | rechazo | revision_manual
    probabilidad: float
    requiere_revision_manual: bool
    motivo: str                 # ok | incompleto | mala | revision


def decidir(p: PaqueteFruta) -> Decision:
    """
    Regla del servo:
      Pasable -> Caja 1 (sin importar tamaño)
      Buena   -> Chica: Caja 2 | Mediana: Caja 3 | Grande: Caja 4
      Mala    -> CAJA_RECHAZO, categoría "rechazo"
      Revisión o faltan datos -> CAJA_REVISION, categoría "revision_manual"
    """
    conf = p.confianza if p.confianza is not None else 0.0
    if not p.foto_valida:
        return Decision(p, config.CAJA_REVISION, "revision_manual", 0.0, True, "revision")
    if p.estado == "Mala":
        return Decision(p, config.CAJA_RECHAZO, "rechazo", conf, conf < config.CONFIANZA_MINIMA, "mala")
    if p.estado == "Pasable":
        caja = 1
    elif p.estado == "Buena" and p.tamano in ("Chica", "Mediana", "Grande"):
        caja = {"Chica": 2, "Mediana": 3, "Grande": 4}[p.tamano]
    else:
        motivo = "revision" if p.estado == "Revision" else "incompleto"
        return Decision(p, config.CAJA_REVISION, "revision_manual", conf, True, motivo)
    return Decision(p, caja, config.CATEGORIA_POR_CAJA[caja], conf,
                    conf < config.CONFIANZA_MINIMA, "ok")


# ---------------------------------------------------------------------------
# Cola FIFO
# ---------------------------------------------------------------------------
class ColaFIFO:
    def __init__(self, max_transito_s: float = config.TIEMPO_MAX_TRANSITO_S):
        self.cola: deque[PaqueteFruta] = deque()
        self.max_transito_s = max_transito_s
        self._n = itertools.count(1)
        self.perdidos: list[PaqueteFruta] = []
        self.datos_huerfanos: list[tuple] = []
        self._t_pausa: float | None = None

    def __len__(self):
        return len(self.cola)

    def __iter__(self):
        return iter(self.cola)

    def nueva_fruta(self, t: float | None = None, id_lote=None, id_grupo=None, id_fruta=None,
                    foto_valida: bool = True) -> PaqueteFruta:
        p = PaqueteFruta(next(self._n), _ahora(t), id_lote, id_grupo, id_fruta, foto_valida)
        self.cola.append(p)
        return p

    def contiene(self, id_grupo, id_fruta) -> bool:
        return any(p.clave == (id_grupo, id_fruta) for p in self.cola)

    def rellenar_por_id(self, id_grupo, id_fruta, **campos) -> PaqueteFruta | None:
        """Cuando E2/E3 informan con id (contrato de E5)."""
        for p in self.cola:
            if p.clave == (id_grupo, id_fruta):
                for k, v in campos.items():
                    if v is not None:
                        setattr(p, k, v)
                return p
        self.datos_huerfanos.append((id_grupo, id_fruta, campos))
        return None

    def rellenar_siguiente(self, campo: str, valor, **extra) -> PaqueteFruta | None:
        """
        Cuando la estación NO manda id: el dato es del paquete más antiguo al que le falte.
        E2 solo analiza fotos válidas, por eso salta los paquetes con foto_valida=False.
        """
        for p in self.cola:
            if getattr(p, campo) is None and (campo != "estado" or p.foto_valida):
                setattr(p, campo, valor)
                for k, v in extra.items():
                    if v is not None:
                        setattr(p, k, v)
                return p
        self.datos_huerfanos.append((campo, valor))
        return None

    def disparo_sensor(self, t: float | None = None) -> Decision | None:
        """La fruta cortó la barrera frente al servo. None = disparo sin paquete (falso positivo)."""
        t = _ahora(t)
        while self.cola and t - self.cola[0].t_entrada > self.max_transito_s:
            self.perdidos.append(self.cola.popleft())     # fruta caída: no desfasar la fila
        if not self.cola:
            return None
        return decidir(self.cola.popleft())

    def pausar(self, t: float | None = None):
        """Cinta detenida (E6): el tiempo detenido no cuenta como tránsito."""
        if self._t_pausa is None:
            self._t_pausa = _ahora(t)

    def reanudar(self, t: float | None = None):
        if self._t_pausa is None:
            return
        delta = _ahora(t) - self._t_pausa
        for p in self.cola:
            p.t_entrada += delta
        self._t_pausa = None


# ---------------------------------------------------------------------------
# Lote (el "bache")
# ---------------------------------------------------------------------------
COLUMNAS = [
    "bache", "id_lote", "timestamp_inicio", "timestamp_fin", "hora_inicio",
    "duracion_s", "tiempo_muerto_s", "total_frutas", "frutas_por_min",
    "n_pasable", "n_chica", "n_mediana", "n_grande", "n_rechazo", "n_revision",
    "pct_pasable", "pct_chica", "pct_mediana", "pct_grande", "etiqueta",
]


class GestorBache:
    """
    Cuenta las frutas por caja de cada lote y al cerrarlo guarda una fila de métricas.
    Un lote empieza con el botón físico o cuando aparece un id_lote nuevo, y termina con
    el botón, con un id_lote nuevo o tras INACTIVIDAD_CIERRE_S sin frutas.
    """

    def __init__(self, ruta_csv: str | None = None):
        self.ruta_csv = ruta_csv
        self.historial: list[dict] = []
        self.activo = False
        self.numero = 0
        self.id_lote = None
        self.fin_anterior: float | None = None
        if ruta_csv and os.path.exists(ruta_csv):
            with open(ruta_csv, newline="", encoding="utf-8") as f:
                filas = list(csv.DictReader(f))
            if filas:
                self.numero = int(filas[-1]["bache"])
                self.fin_anterior = datetime.fromisoformat(filas[-1]["timestamp_fin"]).timestamp()

    def boton(self, t: float | None = None):
        return self.cerrar(t) if self.activo else self.iniciar(t)

    def iniciar(self, t: float | None = None, id_lote: str | None = None):
        t = _ahora(t)
        if self.activo:
            self.cerrar(t)
        self.numero += 1
        self.id_lote = id_lote or f"LOTE-E4-{self.numero:04d}"
        self.t_inicio = self.t_ultimo = t
        self.conteo = {1: 0, 2: 0, 3: 0, 4: 0}
        self.n_rechazo = self.n_revision = 0
        self.activo = True

    def registrar(self, d: Decision, t: float | None = None):
        t = _ahora(t)
        if d.paquete.id_lote and d.paquete.id_lote != self.id_lote:
            self.iniciar(t, d.paquete.id_lote)          # cambió el lote en la línea
        elif not self.activo:
            self.iniciar(t)
        self.conteo[d.caja] += 1
        self.n_rechazo += d.motivo == "mala"
        self.n_revision += d.motivo in ("incompleto", "revision")
        self.t_ultimo = t

    def conteo_actual(self) -> list[int]:
        """Frutas del lote abierto por caja [1, 2, 3, 4] (para la predicción en vivo)."""
        return [self.conteo[c] for c in (1, 2, 3, 4)] if self.activo else [0, 0, 0, 0]

    def tiempo_muerto_actual(self) -> float:
        if not self.activo or self.fin_anterior is None:
            return 0.0
        return max(self.t_inicio - self.fin_anterior, 0.0)

    def revisar_inactividad(self, t: float | None = None, limite_s: float = config.INACTIVIDAD_CIERRE_S):
        if self.activo and _ahora(t) - self.t_ultimo > limite_s:
            return self.cerrar(self.t_ultimo)
        return None

    def cerrar(self, t: float | None = None) -> dict | None:
        if not self.activo:
            return None
        t = _ahora(t)
        self.activo = False
        total = sum(self.conteo.values())
        if total == 0:
            self.numero -= 1
            return None
        dur = max(t - self.t_inicio, 1.0)
        muerto = 0.0 if self.fin_anterior is None else max(self.t_inicio - self.fin_anterior, 0.0)
        pct = lambda n: round(100.0 * n / total, 2)
        ini = datetime.fromtimestamp(self.t_inicio)
        fila = {
            "bache": self.numero, "id_lote": self.id_lote,
            "timestamp_inicio": ini.isoformat(timespec="seconds"),
            "timestamp_fin": datetime.fromtimestamp(t).isoformat(timespec="seconds"),
            "hora_inicio": round(ini.hour + ini.minute / 60, 3),
            "duracion_s": round(dur, 1), "tiempo_muerto_s": round(muerto, 1),
            "total_frutas": total, "frutas_por_min": round(total / (dur / 60), 2),
            "n_pasable": self.conteo[1], "n_chica": self.conteo[2],
            "n_mediana": self.conteo[3], "n_grande": self.conteo[4],
            "n_rechazo": self.n_rechazo, "n_revision": self.n_revision,
            "pct_pasable": pct(self.conteo[1]), "pct_chica": pct(self.conteo[2]),
            "pct_mediana": pct(self.conteo[3]), "pct_grande": pct(self.conteo[4]),
        }
        fila["etiqueta"] = config.etiquetar_bache(fila["pct_pasable"], fila["pct_mediana"], fila["pct_grande"])
        self.historial.append(fila)
        self.fin_anterior = t
        if self.ruta_csv:
            nuevo = not os.path.exists(self.ruta_csv)
            os.makedirs(os.path.dirname(self.ruta_csv) or ".", exist_ok=True)
            with open(self.ruta_csv, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNAS)
                if nuevo:
                    w.writeheader()
                w.writerow(fila)
        return fila
