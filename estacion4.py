"""
Programa principal de la Estación 4: recibe E1/E2/E3, decide la caja, mueve el servo,
lleva las métricas del lote, informa a E5 y muestra la predicción de la IA.

Ejemplos:
  # Línea real: datos desde la API de E5 y Arduino en COM3
  python estacion4.py --fuente e5 --e5 http://192.168.0.10:8000 --puerto COM3

  # Datos desde los archivos que generan hoy E1 y E2 (sin red)
  python estacion4.py --fuente archivos --e1 ../estacion1/salidas_estacion2 \
      --e2 /dev/shm/estacion2_result.json --e3 /dev/shm/estacion3_result.json --puerto /dev/ttyACM0

  # Probar sin Arduino (las frutas "llegan" al servo 3 s después)
  python estacion4.py --fuente e5 --e5 http://localhost:8000 --simular-arduino
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

import config
from clasificador import ColaFIFO, GestorBache
from fuentes import ClienteE5, FuenteArchivos, FuenteE5, ReporteE4


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


class PrediccionLote:
    """Predicción en vivo de cómo terminará el lote (IA). Opcional: si no hay modelo, se omite."""

    def __init__(self, cada_n: int = 10):
        self.cada_n = cada_n
        self.modelo = None
        if os.path.exists(config.RUTA_MODELO):
            from predecir import cargar_modelo
            self.modelo = cargar_modelo()
            log(f"IA cargada desde {config.RUTA_MODELO}")
        else:
            log(f"IA no disponible (falta {config.RUTA_MODELO}; correr entrenar.py)")

    def tal_vez_predecir(self, gestor: GestorBache):
        if self.modelo is None or not gestor.activo:
            return
        vistas = gestor.conteo_actual()
        if sum(vistas) == 0 or sum(vistas) % self.cada_n:
            return
        from predecir import historial_para_prediccion, predecir_proximo
        hist = historial_para_prediccion()
        if hist is None:
            return
        ahora = datetime.now()
        r = predecir_proximo(self.modelo, hist, gestor.tiempo_muerto_actual(),
                             ahora.hour + ahora.minute / 60, vistas)
        probs = "  ".join(f"{k} {v:.0%}" for k, v in r["probabilidades"].items())
        log(f"IA lote {gestor.id_lote} ({sum(vistas)} frutas): {r['categoria']}  [{probs}]")


def main():
    ap = argparse.ArgumentParser(description="Estación 4: decisión y servo")
    ap.add_argument("--fuente", choices=["e5", "archivos"], default="e5")
    ap.add_argument("--e5", default=config.URL_E5, help="URL de la API de E5")
    ap.add_argument("--sin-envio", action="store_true", help="no enviar las decisiones a E5")
    ap.add_argument("--e1", nargs="*", default=[], help="carpeta(s) donde E1 deja sus manifiestos JSON")
    ap.add_argument("--e2", default=None, help="archivo de resultado de E2 (estacion2_result.json)")
    ap.add_argument("--e3", default=None, help="archivo de resultado de E3")
    ap.add_argument("--puerto", default=config.PUERTO_ARDUINO)
    ap.add_argument("--simular-arduino", action="store_true")
    ap.add_argument("--retardo-sim", type=float, default=3.0, help="segundos hasta el servo (simulado)")
    ap.add_argument("--duracion", type=float, default=0, help="segundos a correr (0 = sin fin)")
    a = ap.parse_args()

    cola = ColaFIFO()
    gestor = GestorBache(config.RUTA_HISTORIAL)
    cliente = ClienteE5(a.e5)
    if a.fuente == "e5":
        fuente = FuenteE5(cliente)
        log(f"Leyendo E1/E2/E3 desde E5 en {a.e5}")
    else:
        fuente = FuenteArchivos(a.e1, a.e2, a.e3)
        log(f"Leyendo archivos: E1={a.e1} E2={a.e2} E3={a.e3}")
    reporte = ReporteE4(None if a.sin_envio else cliente, fuente.esperadas)

    if a.simular_arduino:
        from arduino import ArduinoSimulado
        arduino = ArduinoSimulado(cola, a.retardo_sim)
        log("Arduino SIMULADO")
    else:
        from arduino import Arduino
        arduino = Arduino(a.puerto, config.BAUDIOS)
        log(f"Arduino en {a.puerto}")
    ia = PrediccionLote()

    ultima_consulta = 0.0
    inicio = time.time()
    error_mostrado = None
    try:
        while not a.duracion or time.time() - inicio < a.duracion:
            t = time.time()
            if t - ultima_consulta >= config.CONSULTA_E5_CADA_S:
                ultima_consulta = t
                for ev in fuente.leer(cola):
                    log(ev)
                if a.fuente == "e5" and cliente.ultimo_error != error_mostrado:
                    error_mostrado = cliente.ultimo_error
                    if error_mostrado:
                        log(error_mostrado)

            for ev in arduino.eventos():
                if ev == "FRUTA":
                    fuente.refrescar(cola)          # última oportunidad de completar datos
                    t = time.time()
                    perdidos = len(cola.perdidos)
                    d = cola.disparo_sensor(t)
                    for p in cola.perdidos[perdidos:]:
                        log(f"fruta perdida: {p.id_grupo}/{p.id_fruta} (nunca llegó al servo)")
                    if d is None:
                        log("barrera cortada pero no hay frutas en la cola (falso positivo)")
                        continue
                    arduino.mover(d.caja)
                    gestor.registrar(d, t)
                    p = d.paquete
                    log(f"{p.id_grupo}/{p.id_fruta}: {p.estado} {p.tamano} -> Caja {d.caja} "
                        f"({config.CAJAS[d.caja]}) = {d.categoria_final} [{d.motivo}]")
                    for msg in reporte.agregar(d, t):
                        log(msg)
                    ia.tal_vez_predecir(gestor)
                elif ev == "BOTON":
                    fila = gestor.boton(t)
                    log(f"lote cerrado: {fila}" if fila else f"lote iniciado: {gestor.id_lote}")
                else:
                    log(f"Arduino: {ev}")

            fila = gestor.revisar_inactividad(t)
            if fila:
                log(f"lote cerrado por inactividad: {fila}")
            for msg in reporte.revisar(t):
                log(msg)
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        fila = gestor.cerrar()
        if fila:
            log(f"lote cerrado al salir: {fila}")
        for msg in reporte.revisar(float("inf")):
            log(msg)
        arduino.cerrar()


if __name__ == "__main__":
    main()
