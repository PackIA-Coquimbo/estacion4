"""
Convierte el historial de baches en las entradas de la IA.

La IA predice cómo terminará el bache actual en dos momentos:
  1. Al apretar "Nuevo Bache" (0 frutas vistas): usa los 3 baches anteriores,
     el tiempo muerto y la hora.
  2. En vivo, mientras pasan frutas: además usa cuántas de las primeras frutas
     fueron a cada caja. Con ~20 frutas la predicción mejora harto.

Para entrenar el caso "en vivo" sin guardar cada fruta, se sortean las primeras n
frutas de cada bache a partir de su conteo final (muestreo sin reemplazo). Esto
supone que dentro de un mismo bache el orden de las frutas es aleatorio.
"""
import numpy as np
import pandas as pd

K = 3   # cuántos baches anteriores mira la IA
VARS = ["duracion_s", "tiempo_muerto_s", "total_frutas", "frutas_por_min",
        "pct_pasable", "pct_chica", "pct_mediana", "pct_grande"]
TENDENCIAS = ["pct_pasable", "pct_chica", "frutas_por_min", "total_frutas", "duracion_s"]
OBJ_PCT = ["pct_pasable", "pct_chica", "pct_mediana", "pct_grande"]
CONTEOS = ["n_pasable", "n_chica", "n_mediana", "n_grande"]
MAX_MUERTO_S = 2 * 3600                       # una noche cuenta como "más de 2 h"
PRIMERAS_GRID = [0, 5, 10, 15, 20, 30, 40, 50]  # cuántas frutas vistas se simulan al entrenar


def _features(prev: pd.DataFrame, tiempo_muerto_s: float, hora: float, primeras=None) -> dict:
    prev = prev.copy()
    prev["tiempo_muerto_s"] = prev["tiempo_muerto_s"].clip(upper=MAX_MUERTO_S)
    f = {}
    for lag in range(1, K + 1):                 # lag1 = bache inmediatamente anterior
        fila = prev.iloc[-lag]
        for v in VARS:
            f[f"{v}_lag{lag}"] = fila[v]
    for v in VARS:
        f[f"{v}_media{K}"] = prev[v].mean()
    for v in TENDENCIAS:                        # positivo = va subiendo
        f[f"{v}_tendencia"] = prev[v].iloc[-1] - prev[v].iloc[0]
    f["tiempo_muerto_actual_min"] = min(tiempo_muerto_s, MAX_MUERTO_S) / 60
    f["hora_actual"] = hora

    # Frutas ya vistas del bache actual (orden: pasable, chica, mediana, grande)
    n = 0 if primeras is None else int(np.sum(primeras))
    f["n_primeras"] = n
    for c, x in zip(OBJ_PCT, primeras if n else [0] * 4):
        f[f"{c}_primeras"] = 100.0 * x / n if n else np.nan
    return f


def dataset_entrenamiento(df: pd.DataFrame, grid=PRIMERAS_GRID, semilla=0):
    """
    Devuelve X, y_cls, y_reg y `meta` (posición del bache y frutas vistas de cada fila).
    Cada bache aparece una vez por cada n de `grid` que sea menor que su total.
    """
    rng = np.random.default_rng(semilla)
    df = df.sort_values("bache").reset_index(drop=True)
    X, y_cls, y_reg, meta = [], [], [], []
    for i in range(K, len(df)):
        actual = df.iloc[i]
        prev = df.iloc[i - K:i]
        conteo = actual[CONTEOS].to_numpy(dtype=np.int64)
        for n in grid:
            if n and n >= conteo.sum():
                continue
            primeras = rng.multivariate_hypergeometric(conteo, n) if n else None
            X.append(_features(prev, actual["tiempo_muerto_s"], actual["hora_inicio"], primeras))
            y_cls.append(actual["etiqueta"])
            y_reg.append(actual[OBJ_PCT].to_numpy(dtype=float))
            meta.append((i, n))
    return (pd.DataFrame(X), pd.Series(y_cls, name="etiqueta"),
            pd.DataFrame(np.array(y_reg), columns=OBJ_PCT),
            pd.DataFrame(meta, columns=["pos_bache", "n_primeras"]))


def features_prediccion(df: pd.DataFrame, tiempo_muerto_s: float, hora: float, primeras=None) -> pd.DataFrame:
    df = df.sort_values("bache")
    if len(df) < K:
        raise ValueError(f"Se necesitan al menos {K} baches en el historial (hay {len(df)}).")
    return pd.DataFrame([_features(df.iloc[-K:], tiempo_muerto_s, hora, primeras)])
