"""
Entrena la IA con el historial de baches (simulado o real).

Modelo: Random Forest de regresión que predice el % de Pasable, Chica, Mediana y
Grande con que terminará el bache. Con esos % se calcula la categoría
(Bueno / Regular / Deficiente) con config.etiquetar_bache, y la probabilidad de
cada categoría sale del voto de los 300 árboles.

Un solo modelo sirve para predecir al inicio del bache (0 frutas vistas) y en vivo
(con las primeras frutas ya clasificadas).

Evaluación honesta: se entrena con el 80% más antiguo de los baches y se prueba con
el 20% más reciente, comparando contra la regla "igual al anterior".

Uso:  python entrenar.py                         (historial simulado)
      python entrenar.py datos/historial_lotes.csv (historial real de la línea)
"""
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import confusion_matrix

import config
from features import OBJ_PCT, dataset_entrenamiento
from predecir import predecir_pct_y_categoria

CLASES = ["Bueno", "Regular", "Deficiente"]
CAMBIO_PROVEEDOR_MIN = 15      # pausa que consideramos "cambio de proveedor/turno"
MOSTRAR_N = [0, 10, 20, 30, 50]


def crear_modelo():
    # Elegido comparando variantes (hojas de 3/10, % de variables por corte, ExtraTrees, HistGB)
    return RandomForestRegressor(n_estimators=300, min_samples_leaf=10, max_features=0.33,
                                 random_state=0, n_jobs=-1)


def techo_teorico(df, corte):
    """Solo con datos simulados: cuánto acertaría alguien que conoce la calidad oculta."""
    if "q_oculto" not in df:
        return
    y = df["etiqueta"].to_numpy()
    print("\n== Techo teórico (solo simulación) ==")
    for nombre, X in [("conoce la calidad oculta del bache ANTERIOR", pd.DataFrame({
                          "q": df["q_oculto"].shift(1).fillna(0.5), "tm": df["tiempo_muerto_s"].clip(upper=7200),
                          "h": df["hora_inicio"]})),
                      ("conoce la calidad oculta del bache ACTUAL", pd.DataFrame({
                          "q": df["q_oculto"], "h": df["hora_inicio"]}))]:
        m = RandomForestClassifier(300, min_samples_leaf=10, random_state=0, n_jobs=-1)
        m.fit(X.iloc[1:corte], y[1:corte])
        print(f"  Alguien que {nombre}: {(m.predict(X.iloc[corte:]) == y[corte:]).mean():.1%}")
    print("  (El resto es azar: la fruta de un bache es una muestra limitada.)")


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else config.RUTA_HISTORIAL_SIMULADO
    print(f"Historial: {ruta}")
    df = pd.read_csv(ruta).sort_values("bache").reset_index(drop=True)
    X, y_cls, y_reg, meta = dataset_entrenamiento(df)
    corte = int(len(df) * 0.8)
    tr = (meta["pos_bache"] < corte).to_numpy()
    te = ~tr
    print(f"Baches: {len(df)}  |  entrenamiento: {corte}  |  prueba: {len(df) - corte} (los más recientes)")
    print(f"Filas de entrenamiento (cada bache con 0, 5, 10... frutas vistas): {tr.sum()}\n")

    reg = crear_modelo().fit(X[tr], y_reg[tr])
    pred = predecir_pct_y_categoria(reg, X[te])
    y_true = y_cls[te].to_numpy()
    y_pred = np.array([p["categoria"] for p in pred])
    r_true = y_reg[te].to_numpy()
    r_pred = np.array([[p["pct"][c] for c in OBJ_PCT] for p in pred])
    n_vistas = meta.loc[te, "n_primeras"].to_numpy()
    pos = meta.loc[te, "pos_bache"].to_numpy()

    # --- Al inicio del bache, contra la regla tonta ---
    m0 = n_vistas == 0
    y_base = df["etiqueta"].to_numpy()[pos[m0] - 1]
    cambio = X[te]["tiempo_muerto_actual_min"].to_numpy()[m0] > CAMBIO_PROVEEDOR_MIN
    print("== Al apretar 'Nuevo Bache' (0 frutas vistas): exactitud de la categoría ==")
    print(f"  {'':34s}{'IA':>7s}{'igual al anterior':>20s}")
    for nombre, m in [("Todos", np.ones_like(cambio)),
                      (f"Tras pausa larga (>{CAMBIO_PROVEEDOR_MIN} min)", cambio),
                      ("Mismo flujo", ~cambio)]:
        print(f"  {nombre + f' (n={m.sum()})':34s}{(y_pred[m0][m] == y_true[m0][m]).mean():7.1%}"
              f"{(y_base[m] == y_true[m0][m]).mean():20.1%}")

    # --- En vivo ---
    print("\n== En vivo: precisión según cuántas frutas del bache ya pasaron ==")
    print(f"  {'frutas vistas':>14s}{'exactitud':>11s}   error medio en % (pasable, chica, mediana, grande)")
    for n in MOSTRAR_N:
        m = n_vistas == n
        mae = np.abs(r_pred[m] - r_true[m]).mean(axis=0)
        print(f"  {n:14d}{(y_pred[m] == y_true[m]).mean():11.1%}   " + "  ".join(f"{e:4.1f}" for e in mae))

    print("\n  Matriz de confusión con 20 frutas vistas (filas = real, columnas = predicho):")
    m = n_vistas == 20
    cm = pd.DataFrame(confusion_matrix(y_true[m], y_pred[m], labels=CLASES), index=CLASES, columns=CLASES)
    print("  " + cm.to_string().replace("\n", "\n  "))

    techo_teorico(df, corte)

    imp = pd.Series(reg.feature_importances_, index=X.columns).sort_values(ascending=False)
    print("\n== Lo que más pesa en la predicción ==")
    print("  " + imp.head(8).round(3).to_string().replace("\n", "\n  "))

    # --- Modelo final con TODOS los datos ---
    reg = crear_modelo().fit(X, y_reg)
    os.makedirs(os.path.dirname(config.RUTA_MODELO), exist_ok=True)
    joblib.dump({"regresor": reg, "columnas": list(X.columns)}, config.RUTA_MODELO, compress=3)
    print(f"\nModelo final (entrenado con todo) guardado en {config.RUTA_MODELO}")


if __name__ == "__main__":
    main()
