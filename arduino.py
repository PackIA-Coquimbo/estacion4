"""
Comunicación con el Arduino de la Estación 4 (main.cpp), por USB serial a 9600 baudios.

PC -> Arduino:  "C1".."C4"  mover el servo a la caja
                "P"         ping
Arduino -> PC:  "LISTO"     arrancó
                "FRUTA"     una fruta cortó la barrera infrarroja frente al servo
                "BOTON"     el operario apretó el botón de lote
                "OK C3"     confirmó el movimiento
"""
from __future__ import annotations

import time


class Arduino:
    def __init__(self, puerto: str, baudios: int = 9600):
        import serial  # pip install pyserial
        self.s = serial.Serial(puerto, baudios, timeout=0)
        time.sleep(2.0)            # el Arduino se reinicia al abrir el puerto
        self._buffer = ""

    def eventos(self) -> list[str]:
        self._buffer += self.s.read(self.s.in_waiting or 1).decode("ascii", "ignore")
        *lineas, self._buffer = self._buffer.split("\n")
        return [l.strip() for l in lineas if l.strip()]

    def mover(self, caja: int):
        self.s.write(f"C{caja}\n".encode("ascii"))

    def cerrar(self):
        self.s.close()


class ArduinoSimulado:
    """Para probar sin hardware: cada fruta 'llega' al servo `retardo_s` después de aparecer en la cola."""

    def __init__(self, cola, retardo_s: float = 3.0):
        self.cola = cola
        self.retardo_s = retardo_s
        self.movimientos: list[int] = []
        self._avisados: set[int] = set()

    def eventos(self) -> list[str]:
        ahora = time.time()
        if self.cola.cola:
            p = self.cola.cola[0]
            if p.n not in self._avisados and ahora - p.t_entrada >= self.retardo_s:
                self._avisados.add(p.n)
                return ["FRUTA"]
        return []

    def mover(self, caja: int):
        self.movimientos.append(caja)

    def cerrar(self):
        pass
