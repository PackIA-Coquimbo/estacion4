"""
Configuración de la Estación 4 (decisión y servo). Todo lo ajustable está aquí.
"""

# ---------------------------------------------------------------------------
# Red (plan de conexiones de E5)
# ---------------------------------------------------------------------------
URL_E5 = "http://192.168.0.10:8000"     # API de E5 en la Raspberry Pi 5
CONSULTA_E5_CADA_S = 0.5                # cada cuánto se piden datos nuevos a E5
TIMEOUT_HTTP_S = 2.0
API_KEY_E5 = None                       # si el equipo activa X-API-Key, ponerla aquí

# ---------------------------------------------------------------------------
# Arduino (servo + barrera infrarroja + botón de lote)
# ---------------------------------------------------------------------------
PUERTO_ARDUINO = "COM3"                 # en Linux/Raspberry: "/dev/ttyACM0"
BAUDIOS = 9600

# ---------------------------------------------------------------------------
# Tamaño: lo calcula E3. Si E3 manda solo el diámetro, se usan sus mismos límites
# (estacion3/clasificador_naranjas.py: LIMITE_CHICO_MM y LIMITE_GRANDE_MM).
# ---------------------------------------------------------------------------
LIMITE_CHICO_MM = 58.5
LIMITE_GRANDE_MM = 65.0


def tamano_por_diametro(diametro_mm: float) -> str:
    if diametro_mm < LIMITE_CHICO_MM:
        return "Chica"
    if diametro_mm >= LIMITE_GRANDE_MM:
        return "Grande"
    return "Mediana"


# ---------------------------------------------------------------------------
# Cajas y regla del servo
# ---------------------------------------------------------------------------
CAJAS = {1: "Pasable", 2: "Buena-Chica", 3: "Buena-Mediana", 4: "Buena-Grande"}
CAJA_RECHAZO = 1        # fruta en mal estado (no debería llegar, pero E2 puede marcarla)
CAJA_REVISION = 1       # faltan datos o E2 pidió revisión
CONFIANZA_MINIMA = 0.70  # igual que E5: bajo esto se marca requiere_revision_manual

# Categoría comercial que se informa a E5 (contrato E4.json). Propuesta: confirmar con el equipo.
CATEGORIA_POR_CAJA = {
    1: "proceso",
    2: "mercado_nacional",
    3: "exportacion",
    4: "exportacion",
}

# ---------------------------------------------------------------------------
# Cola FIFO y lote
# ---------------------------------------------------------------------------
TIEMPO_MAX_TRANSITO_S = 20.0    # si un paquete espera más que esto, se asume fruta perdida
INACTIVIDAD_CIERRE_S = 300      # cierre automático del lote tras 5 min sin frutas


# ---------------------------------------------------------------------------
# Etiqueta de calidad del lote (lo que la IA aprende a predecir)
# Los % son sobre el TOTAL de frutas del lote, por caja (los 4 suman 100).
# ---------------------------------------------------------------------------
def etiquetar_bache(pct_pasable: float, pct_mediana: float, pct_grande: float) -> str:
    if pct_pasable >= 40:
        return "Deficiente"
    if pct_pasable < 25 and (pct_mediana + pct_grande) >= 50:
        return "Bueno"
    return "Regular"


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
RUTA_HISTORIAL = "datos/historial_lotes.csv"
RUTA_HISTORIAL_SIMULADO = "datos/historial_simulado.csv"
RUTA_MODELO = "modelos/modelo_lotes.joblib"
