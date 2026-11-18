"""
Predice cómo terminará el lote actual (la IA de la Estación 4).

Desde el sistema real:
    from predecir import cargar_modelo, predecir_proximo
    modelo = cargar_modelo()
    # al apretar "Nuevo Bache":
    r = predecir_proximo(modelo, historial_df, tiempo_muerto_s=420, hora=10.5)
    # en vivo, con las frutas que ya pasaron (pasable, chica, mediana, grande):
    r = predecir_proximo(modelo, historial_df, 420, 10.5, primeras=gestor.conteo_actual())

Desde la terminal:
    python predecir.py                                   # 5 min de tiempo muerto
    python predecir.py --tiempo-muerto 30 --hora 11      # minutos, hora decimal
    python predecir.py --tiempo-muerto 30 --hora 11 --primeras 9 1 8 2
"""
import argparse

import joblib
import numpy as np
import pandas as pd

import config
from features import OBJ_PCT, features_prediccion

CLASES = ["Bueno", "Regular", "Deficiente"]


def cargar_modelo(ruta=config.RUTA_MODELO):
    return joblib.load(ruta)


def _etiquetas(p: np.ndarray) -> np.ndarray:
    """config.etiquetar_bache aplicado a un arreglo (..., 4) de % de una sola vez."""
    a, _, m, g = np.moveaxis(p, -1, 0)
    return np.vectorize(config.etiquetar_bache, otypes=[object])(a, m, g)


def predecir_pct_y_categoria(regresor, X: pd.DataFrame):
    """
    Para cada fila devuelve % esperados, categoría y probabilidades.
    Las probabilidades salen de cuántos árboles del bosque "votan" por cada categoría.
    """
    Xn = X.to_numpy(dtype=float)
    por_arbol = np.stack([arbol.predict(Xn) for arbol in regresor.estimators_])   # (arboles, filas, 4)
    votos = _etiquetas(por_arbol)                                                 # (arboles, filas)
    pct = por_arbol.mean(axis=0)
    pct = 100 * pct / pct.sum(axis=1, keepdims=True)                              # que sumen 100
    resultados = []
    for i in range(len(X)):
        probs = {k: round(float((votos[:, i] == k).mean()), 3) for k in CLASES}
        resultados.append({
            "categoria": max(probs, key=probs.get),       # la más votada por los árboles
            "probabilidades": probs,
            "pct": dict(zip(OBJ_PCT, np.round(pct[i], 1).tolist())),
        })
    return resultados


def historial_para_prediccion() -> pd.DataFrame | None:
    """Usa el historial real de la línea; si aún no hay 3 lotes, el simulado."""
    import os
    for ruta in (config.RUTA_HISTORIAL, config.RUTA_HISTORIAL_SIMULADO):
        if os.path.exists(ruta):
            df = pd.read_csv(ruta)
            if len(df) >= 3:
                return df
    return None


def predecir_proximo(modelo, historial: pd.DataFrame, tiempo_muerto_s: float, hora: float,
                     primeras=None) -> dict:
    """`primeras`: frutas ya vistas del bache actual [pasable, chica, mediana, grande] o None."""
    X = features_prediccion(historial, tiempo_muerto_s, hora, primeras)[modelo["columnas"]]
    return predecir_pct_y_categoria(modelo["regresor"], X)[0]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--historial", default=None, help="por defecto el real, o el simulado si no hay 3 lotes")
    ap.add_argument("--tiempo-muerto", type=float, default=5, help="minutos desde que terminó el último bache")
    ap.add_argument("--hora", type=float, default=None, help="hora decimal (ej. 14.5 = 14:30)")
    ap.add_argument("--primeras", type=int, nargs=4, default=None, metavar=("PAS", "CHI", "MED", "GRA"),
                    help="frutas ya vistas del bache actual en cada caja")
    a = ap.parse_args()

    hist = pd.read_csv(a.historial) if a.historial else historial_para_prediccion()
    if a.hora is None:   # por defecto: hora de fin del último bache + tiempo muerto
        fin = pd.Timestamp(hist.sort_values("bache").iloc[-1]["timestamp_fin"])
        a.hora = fin.hour + fin.minute / 60 + a.tiempo_muerto / 60

    r = predecir_proximo(cargar_modelo(), hist, a.tiempo_muerto * 60, a.hora, a.primeras)
    print("Últimos 3 baches:")
    print(hist.sort_values("bache").tail(3)[["bache", "total_frutas", "frutas_por_min", "pct_pasable",
                                             "pct_chica", "pct_mediana", "pct_grande", "etiqueta"]].to_string(index=False))
    vistas = f", {sum(a.primeras)} frutas vistas {a.primeras}" if a.primeras else ""
    print(f"\nBache actual (tiempo muerto {a.tiempo_muerto:g} min, hora {a.hora:.2f}{vistas}):")
    print(f"  Categoría probable: {r['categoria']}")
    print("  Probabilidades:    " + "  ".join(f"{k} {v:.0%}" for k, v in r["probabilidades"].items()))
    print("  % esperado:        " + "  ".join(f"{k.replace('pct_', '')} {v:.1f}%" for k, v in r["pct"].items()))
