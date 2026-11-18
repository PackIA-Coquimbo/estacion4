# Estación 4 — Decisión, servo e IA de lotes

Recibe lo que informan E1, E2 y E3, decide a qué caja va cada naranja, mueve el servo,
informa la decisión a E5 y predice con IA cómo vendrá el lote.

```
E1 (foto) ─┐                               ┌─> Arduino (main.cpp): servo a la caja
E2 (estado)├─> API de E5 ─> estacion4.py ──┤
E3 (tamaño)┘   (o archivos)   cola FIFO    ├─> POST /api/v1/ingest/e4 (contrato E4.json de E5)
                              regla + IA   └─> datos/historial_lotes.csv -> IA
```

## Flujo físico

La caja de frutas llega a E1 y desde ahí las frutas salen **en fila, una detrás de
otra**, por E2, E3 y E4. Por eso:

- **Cola FIFO:** el orden en que E1 registra las frutas es el orden en que llegan al servo.
- **Datos sin id:** si E2 o E3 no mandan id, su dato es de la fruta más antigua que aún no
  lo tiene.
- **Lote:** cada caja que llega a E1 es un lote (el `--lot` de E1). El lote de E4 cambia
  cuando llega al servo la **primera fruta** de la caja nueva, no cuando la caja llega a
  E1. Así las frutas de la caja anterior que aún van en la cinta se cuentan donde
  corresponde.
- **Tiempo muerto:** el tiempo entre la última fruta de una caja y la primera de la
  siguiente. La IA lo usa para detectar cambios de proveedor.

## Archivos

| Archivo | Qué hace |
|---|---|
| `estacion4.py` | Programa principal |
| `config.py` | IP de E5, puerto del Arduino, límites de tamaño, cajas y categorías. **Lo ajustable está aquí.** |
| `normalizar.py` | Traduce los nombres que usa cada estación a uno solo |
| `clasificador.py` | Cola FIFO por fruta, regla del servo y métricas del lote |
| `fuentes.py` | Lee a E1/E2/E3 desde E5 o desde archivos, y envía E4 a E5 |
| `arduino.py` | Comunicación serial con el Arduino (y uno simulado para probar) |
| `main.cpp` | Código del Arduino: servo, barrera infrarroja y botón de lote |
| `simulador.py`, `features.py`, `entrenar.py`, `predecir.py` | La IA que predice el lote |
| `tests/` | Pruebas: `python -m unittest discover -s tests -v` |

## Cómo correrlo

```
pip install -r requirements.txt
python simulador.py        # genera datos/historial_simulado.csv (~3.000 lotes)
python entrenar.py         # genera modelos/modelo_lotes.joblib (~40 s)

# Línea real: datos desde E5 y Arduino por USB
python estacion4.py --fuente e5 --e5 http://192.168.0.10:8000 --puerto COM3

# Sin Arduino (prueba): la fruta "llega" al servo 3 s después
python estacion4.py --fuente e5 --e5 http://192.168.0.10:8000 --simular-arduino
```

`datos/` y `modelos/` no se suben a GitHub: se regeneran con los dos primeros comandos.

## Cómo recibe los datos de E1, E2 y E3

**Modo `e5` (lo acordado en el plan de E5):** cada estación envía a la API de E5 y E4
consulta cada 0,5 s:
- `GET /api/v1/lotes` para obtener el lote activo.
- `GET /api/v1/lotes/{lote}/grupos` para detectar grupos nuevos (E1 informa `frutas_detectadas`).
- `GET /api/v1/grupos/{grupo}` para obtener el estado (E2) y el tamaño (E3) de cada fruta.

Cada fruta se identifica por `id_grupo` + `id_fruta`. Al salir hacia el servo se envía un
mensaje por grupo a `POST /api/v1/ingest/e4`.

**Modo `archivos` (lo que las estaciones producen hoy, sin red):**
- **E1:** manifiestos JSON por fruta en una carpeta (`--e1 ../estacion1/salidas_estacion2`).
- **E2:** `estacion2_result.json`, que se sobrescribe en cada fruta (`--e2 /dev/shm/estacion2_result.json`).
- **E3:** todavía no emite nada. Se propone que escriba un JSON igual al de E2:
  `{"timestamp": 1731950001.0, "tamano": "mediano", "diametro_mm": 61.1}`.

Como E2 y E3 no mandan id, sus datos se asignan en orden a la fruta más antigua que no
los tenga (cola FIFO).

## Regla del servo

| Estado (E2) | Tamaño (E3) | Caja | Categoría para E5 |
|---|---|---|---|
| Pasable | cualquiera | 1 | proceso |
| Buena | Chica | 2 | mercado_nacional |
| Buena | Mediana | 3 | exportacion |
| Buena | Grande | 4 | exportacion |
| Mala | — | 1 (`CAJA_RECHAZO`) | rechazo |
| Revisión o faltan datos | — | 1 (`CAJA_REVISION`) | revision_manual |

Equivalencias aceptadas (`normalizar.py`):
- **Buena:** `buen_estado` (E2) o `alta` (contrato E5).
- **Pasable:** `marginalmente_buena`, `media` o `baja`.
- **Mala:** `mal_estado` o `defectos_visibles`.
- **Tamaño:** `chico` o `pequeno` → Chica. Si solo llega el diámetro, se usan los límites
  de E3: < 58,5 mm Chica, < 65 mm Mediana, si no Grande.
- Si la confianza de E2 es < 0,70 se marca `requiere_revision_manual`, igual que en E5.

## Arduino (`main.cpp`)

| Pin | Uso |
|---|---|
| 9 | Señal del servo |
| 2 | Sensor infrarrojo justo antes del servo (LOW = hay fruta) |
| 3 | Botón de nuevo lote, a GND |

- **Del PC al Arduino:** `C1`..`C4` para mover el servo.
- **Del Arduino al PC:** `FRUTA` cuando se corta la barrera, `BOTON` cuando se aprieta el
  botón y `OK C3` como confirmación.
- Los ángulos de cada caja están en `ANGULO_CAJA`.
- En el Arduino IDE hay que renombrar el archivo a `.ino` dentro de una carpeta con el mismo nombre.

## La IA (predicción del lote)

- Cada "bache" es un **lote**. Al cerrarse, se guarda una fila en `datos/historial_lotes.csv`
  con duración, tiempo muerto, frutas por minuto y el % de cada caja.
- La IA es un Random Forest. Mira los 3 lotes anteriores, la pausa y la hora, y en vivo
  también las frutas ya clasificadas del lote actual. Predice el % de cada caja y la
  categoría del lote (Bueno, Regular o Deficiente).
- **Resultados con datos simulados:** 68 % de acierto al iniciar el lote, 77 % con 20 frutas
  vistas y 80 % con 50. La regla "igual al lote anterior" acierta 66 %.
- `estacion4.py` muestra la predicción cada 10 frutas.
- Cuando haya cientos de lotes reales, se reentrena: `python entrenar.py datos/historial_lotes.csv`.

## Pendiente de confirmar con otras estaciones

1. **E1:** que numere las frutas en el orden en que salen en fila (su código ya lo hace:
   `fruta_001`, `fruta_002`, …). Si manda grupos a E5, `F1` debe ser la primera en salir.
2. **E2 y E3:** todavía no envían a E5, y E2 usa `buen_estado`/`marginalmente_buena`/`mal_estado`
   en vez de `alta`/`media`/`baja`. E4 acepta ambos.
3. **Equipo:** confirmar la tabla de categorías comerciales y qué caja recibe el rechazo.
4. **E6:** ¿cuántas cajas o salidas físicas hay? Hoy el servo tiene 4 posiciones.
