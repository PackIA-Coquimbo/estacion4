"""
Parte 3: genera baches simulados CON lógica de negocio, fruta por fruta,
pasando por la misma ColaFIFO + regla del servo + GestorBache que usa estacion4.py.
Cada "bache" es un lote. Diámetros en mm con los límites de E3.

Lógica oculta (la IA NO la ve, la tiene que descubrir):
  - Cada proveedor/cosecha tiene una "calidad" q (0 a 1).
      q alta  -> más fruta buena y grande, ritmo rápido           (Perfil A, cosecha óptima)
      q baja  -> más pasables y chicas, ritmo lento, más atascos  (Perfil B, cosecha regular)
  - Mientras se trabaja el mismo proveedor, q cambia poco a poco (suele empeorar a
    medida que se vacía el camión).
  - ~20% de las veces cambia el proveedor: tiempo muerto largo (15-45 min) y q nueva.
  - Desde las 16:00 (Perfil C, fin de jornada): baches cortos, tiempos muertos largos,
    calidad mixta.

Uso:  python simulador.py --dias 90 --semilla 42
"""
import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

import config
from clasificador import ColaFIFO, GestorBache

HORA_INICIO, HORA_FIN, HORA_FIN_JORNADA = 8.0, 18.0, 16.0


def nuevo_proveedor(rng):
    q = rng.choice([0.85, 0.60, 0.30], p=[0.40, 0.35, 0.25]) + rng.normal(0, 0.05)
    deriva = rng.uniform(-0.04, 0.01)
    return float(np.clip(q, 0.05, 0.98)), deriva


def parametros_bache(q, fin_jornada, rng):
    p = {
        "p_buena": 0.40 + 0.50 * q + rng.normal(0, 0.03),
        "diam_media": 58.0 + 6.8 * q,      # mm (límites de E3: 58,5 y 65 mm)
        "diam_sd": 2.4,
        "ritmo": max(6.0, 12 + 22 * q + rng.normal(0, 2)),        # frutas/min
        "n": int(max(20, rng.normal(60 + 160 * q, 20))),
        "p_atasco": 0.10 + 0.30 * (1 - q),
    }
    if fin_jornada:   # Perfil C
        p["n"] = max(15, int(p["n"] * rng.uniform(0.3, 0.5)))
        p["diam_media"] = 0.5 * p["diam_media"] + 0.5 * 61.0
        p["diam_sd"] = 3.8
        p["p_buena"] = 0.5 * p["p_buena"] + 0.5 * 0.65
    p["p_buena"] = float(np.clip(p["p_buena"], 0.2, 0.97))
    return p


def nombre_perfil(q, fin_jornada):
    if fin_jornada:
        return "C"
    if q >= 0.70:
        return "A"
    if q < 0.45:
        return "B"
    return "Mixto"


def simular(dias=90, semilla=42, fecha_inicio="2026-03-02"):
    rng = np.random.default_rng(semilla)
    gestor = GestorBache()
    cola = ColaFIFO(max_transito_s=1e9)     # en simulación ninguna fruta se cae
    perfiles, calidades = [], []
    base0 = datetime.fromisoformat(fecha_inicio).timestamp()

    for dia in range(dias):
        base = base0 + dia * 86400
        t = base + HORA_INICIO * 3600 + rng.uniform(0, 1200)
        fin_dia = base + HORA_FIN * 3600
        q, deriva = nuevo_proveedor(rng)          # cada día parte con un proveedor nuevo
        primero = True

        while True:
            if not primero:                        # tiempo muerto antes del bache
                if rng.random() < 0.20:            # cambio de proveedor
                    q, deriva = nuevo_proveedor(rng)
                    muerto = rng.uniform(900, 2700)
                else:
                    q = float(np.clip(q + deriva + rng.normal(0, 0.04), 0.05, 0.98))
                    muerto = rng.uniform(60, 480)
                if (t - base) / 3600 >= HORA_FIN_JORNADA:
                    muerto *= rng.uniform(2, 4)
                t += muerto
            primero = False
            if t >= fin_dia:
                break

            fin_jornada = (t - base) / 3600 >= HORA_FIN_JORNADA
            p = parametros_bache(q, fin_jornada, rng)
            lote = f"SIM-{gestor.numero + 1:05d}"
            gestor.iniciar(t, lote)
            i_atasco = rng.integers(p["n"]) if rng.random() < p["p_atasco"] else -1

            for i in range(p["n"]):
                t += rng.exponential(60.0 / p["ritmo"])
                if i == i_atasco:
                    t += rng.uniform(30, 180)       # fruta atascada / cinta detenida
                cola.nueva_fruta(t, id_lote=lote)
                cola.rellenar_siguiente("estado", "Buena" if rng.random() < p["p_buena"] else "Pasable",
                                        confianza=0.9)
                diametro = rng.normal(p["diam_media"], p["diam_sd"])
                cola.rellenar_siguiente("tamano", config.tamano_por_diametro(diametro), diametro_mm=diametro)
                if len(cola) > 3:                   # ~3 frutas viajando entre estaciones y servo
                    gestor.registrar(cola.disparo_sensor(t), t)
            while len(cola):
                t += 60.0 / p["ritmo"]
                gestor.registrar(cola.disparo_sensor(t), t)

            if gestor.cerrar(t):
                perfiles.append(nombre_perfil(q, fin_jornada))
                calidades.append(round(q, 3))

    df = pd.DataFrame(gestor.historial)
    # Columnas ocultas: solo para revisar la simulación; la IA NO las usa
    df["perfil_oculto"] = perfiles
    df["q_oculto"] = calidades
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--salida", default=config.RUTA_HISTORIAL_SIMULADO)
    a = ap.parse_args()

    df = simular(a.dias, a.semilla)
    os.makedirs(os.path.dirname(a.salida) or ".", exist_ok=True)
    df.to_csv(a.salida, index=False, encoding="utf-8")

    print(f"{len(df)} baches simulados ({df.total_frutas.sum()} frutas) -> {a.salida}\n")
    print("Etiquetas:\n", df.etiqueta.value_counts().to_string(), "\n")
    print("Promedios por perfil oculto:")
    print(df.groupby("perfil_oculto")[["total_frutas", "frutas_por_min", "tiempo_muerto_s",
                                        "pct_pasable", "pct_chica", "pct_mediana", "pct_grande"]]
          .mean().round(1).to_string())
