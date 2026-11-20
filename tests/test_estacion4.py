"""Pruebas de la Estación 4. Correr desde la carpeta estacion4:  python -m unittest -v"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arduino import ArduinoSimulado  # noqa: E402
import normalizar  # noqa: E402
from clasificador import ColaFIFO, GestorBache, decidir, PaqueteFruta  # noqa: E402
from fuentes import FuenteArchivos, FuenteE5, ReporteE4  # noqa: E402


def paquete(estado, tamano, conf=0.9):
    return PaqueteFruta(1, 0.0, "L", "G-1", "F1", True, estado, conf, tamano)


class TestNormalizar(unittest.TestCase):
    def test_vocabularios_de_e2(self):
        self.assertEqual(normalizar.estado("buen_estado"), "Buena")              # código real de E2
        self.assertEqual(normalizar.estado("marginalmente_buena"), "Pasable")
        self.assertEqual(normalizar.estado("mal_estado"), "Mala")
        self.assertEqual(normalizar.estado("alta"), "Buena")                     # contrato de E5
        self.assertEqual(normalizar.estado("media"), "Pasable")
        self.assertEqual(normalizar.estado("defectos_visibles"), "Mala")
        self.assertEqual(normalizar.estado("revision"), "Revision")
        self.assertIsNone(normalizar.estado("otra_cosa"))

    def test_vocabularios_de_e3(self):
        self.assertEqual(normalizar.tamano("chico"), "Chica")                     # código real de E3
        self.assertEqual(normalizar.tamano("pequeno"), "Chica")                   # contrato de E5
        self.assertEqual(normalizar.tamano("mediano"), "Mediana")
        self.assertEqual(normalizar.tamano(None, 58.4), "Chica")                  # solo diámetro
        self.assertEqual(normalizar.tamano(None, 58.5), "Mediana")
        self.assertEqual(normalizar.tamano(None, 65.0), "Grande")

    def test_confianza_en_porcentaje(self):
        self.assertAlmostEqual(normalizar.confianza(87.42), 0.8742)
        self.assertAlmostEqual(normalizar.confianza(0.92), 0.92)


class TestRegla(unittest.TestCase):
    def test_cajas(self):
        self.assertEqual(decidir(paquete("Pasable", "Grande")).caja, 1)
        self.assertEqual(decidir(paquete("Pasable", None)).caja, 1)     # pasable no necesita tamaño
        self.assertEqual(decidir(paquete("Buena", "Chica")).caja, 2)
        self.assertEqual(decidir(paquete("Buena", "Mediana")).caja, 3)
        self.assertEqual(decidir(paquete("Buena", "Grande")).caja, 4)

    def test_categorias_para_e5(self):
        self.assertEqual(decidir(paquete("Buena", "Grande")).categoria_final, "exportacion")
        self.assertEqual(decidir(paquete("Mala", "Grande")).categoria_final, "rechazo")
        d = decidir(paquete("Buena", None))
        self.assertEqual((d.categoria_final, d.motivo, d.requiere_revision_manual),
                         ("revision_manual", "incompleto", True))
        self.assertTrue(decidir(paquete("Buena", "Grande", conf=0.5)).requiere_revision_manual)
        invalida = paquete("Buena", "Grande")
        invalida.foto_valida = False
        d = decidir(invalida)
        self.assertEqual((d.caja, d.categoria_final, d.probabilidad), (1, "revision_manual", 0.0))


class TestCola(unittest.TestCase):
    def test_relleno_por_id_y_fruta_perdida(self):
        c = ColaFIFO(max_transito_s=20)
        c.nueva_fruta(0, "L", "G-1", "F1")
        c.nueva_fruta(25, "L", "G-1", "F2")
        c.rellenar_por_id("G-1", "F2", estado="Buena", tamano="Grande", confianza=0.9)
        d = c.disparo_sensor(30)               # F1 lleva 30 s: se perdió
        self.assertEqual(d.paquete.id_fruta, "F2")
        self.assertEqual([p.id_fruta for p in c.perdidos], ["F1"])

    def test_e2_salta_fotos_invalidas(self):
        c = ColaFIFO()
        c.nueva_fruta(None, foto_valida=False)
        c.nueva_fruta(None, foto_valida=True)
        p = c.rellenar_siguiente("estado", "Buena")
        self.assertEqual(p.n, 2)

    def test_lote_nuevo_cierra_el_anterior(self):
        g = GestorBache()
        c = ColaFIFO()
        for lote in ("L1", "L1", "L2"):
            c.nueva_fruta(0, lote)
            c.rellenar_siguiente("estado", "Pasable")
            g.registrar(c.disparo_sensor(0), 0)
        self.assertEqual(len(g.historial), 1)
        self.assertEqual(g.historial[0]["id_lote"], "L1")
        self.assertEqual(g.historial[0]["total_frutas"], 2)


class TestFuenteArchivos(unittest.TestCase):
    """Usa el formato real de los manifiestos de E1 y del resultado de E2."""

    def test_simulacion_archivos_con_arduino_y_reporte_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "salidas" / "LOTE-X").mkdir(parents=True)
            fuente = FuenteArchivos([str(tmp / "salidas")], str(tmp / "e2.json"), str(tmp / "e3.json"))
            cola = ColaFIFO()
            reporte = ReporteE4(None, fuente.esperadas)

            for i, estado in ((1, "aceptada"), (2, "repetir_captura")):
                (tmp / "salidas" / "LOTE-X" / f"captura_{i}.json").write_text(json.dumps({
                    "id_lote": "LOTE-X", "id_fruta": f"fruta_00{i}",
                    "timestamp": f"2026-11-18T10:00:0{i}Z", "estado_captura": estado,
                }), encoding="utf-8")
            (tmp / "e2.json").write_text(json.dumps({
                "station_id": 2, "timestamp": 1731950000.123,
                "predicted_class": "buen_estado", "confidence_percent": 91.0,
            }), encoding="utf-8")
            # Muestra simulada de E3: la estación actual aún no publica este archivo.
            (tmp / "e3.json").write_text(json.dumps({
                "timestamp": 1731950001.0, "tamano": "grande", "diametro_mm": 67.2,
            }), encoding="utf-8")

            fuente.leer(cola)
            arduino = ArduinoSimulado(cola, retardo_s=0)
            decisiones = []
            mensajes = []
            while len(cola):
                self.assertEqual(arduino.eventos(), ["FRUTA"])
                decision = cola.disparo_sensor()
                decisiones.append(decision)
                arduino.mover(decision.caja)
                mensajes.extend(reporte.agregar(decision))

            self.assertEqual([d.categoria_final for d in decisiones],
                             ["exportacion", "revision_manual"])
            self.assertEqual(arduino.movimientos, [4, 1])
            reportes = [json.loads(msg.split("E4 -> ", 1)[1]) for msg in mensajes]
            self.assertEqual([m["frutas"][0]["categoria_final"] for m in reportes],
                             ["exportacion", "revision_manual"])
            arduino.cerrar()

    def test_tamano_desconocido_no_se_convierte_en_mediano(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "salidas" / "LOTE-X").mkdir(parents=True)
            fuente = FuenteArchivos([str(tmp / "salidas")], str(tmp / "e2.json"), str(tmp / "e3.json"))
            cola = ColaFIFO()

            (tmp / "salidas" / "LOTE-X" / "captura.json").write_text(json.dumps({
                "id_lote": "LOTE-X", "id_fruta": "fruta_001",
                "timestamp": "2026-11-18T10:00:01Z", "estado_captura": "aceptada",
            }), encoding="utf-8")
            (tmp / "e2.json").write_text(json.dumps({
                "timestamp": 1, "predicted_class": "buen_estado", "confidence_percent": 91,
            }), encoding="utf-8")
            (tmp / "e3.json").write_text(json.dumps({
                "timestamp": 2, "tamano": "desconocido",
            }), encoding="utf-8")

            fuente.leer(cola)

            self.assertIsNone(cola.cola[0].tamano)
            decision = cola.disparo_sensor()
            self.assertEqual((decision.caja, decision.categoria_final), (1, "revision_manual"))

    def test_e1_e2_e3_por_archivos(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "salidas" / "LOTE-X").mkdir(parents=True)
            fuente = FuenteArchivos([str(tmp / "salidas")], str(tmp / "e2.json"), str(tmp / "e3.json"))
            cola = ColaFIFO()

            for i, estado in ((1, "aceptada"), (2, "repetir_captura")):
                (tmp / "salidas" / "LOTE-X" / f"captura_{i}.json").write_text(json.dumps({
                    "version_interfaz": 2, "estacion_origen": 1, "id_lote": "LOTE-X",
                    "id_fruta": f"fruta_00{i}", "timestamp": f"2026-11-18T10:00:0{i}Z",
                    "estado_captura": estado}), encoding="utf-8")
            (tmp / "e2.json").write_text(json.dumps({
                "station_id": 2, "timestamp": 1731950000.123, "predicted_class": "buen_estado",
                "confidence_percent": 91.0}), encoding="utf-8")
            (tmp / "e3.json").write_text(json.dumps({
                "timestamp": 1731950001.0, "tamano": "grande", "diametro_mm": 67.2}), encoding="utf-8")
            fuente.leer(cola)

            self.assertEqual(len(cola), 2)
            p1, p2 = cola.cola
            self.assertEqual((p1.id_lote, p1.id_grupo, p1.estado, p1.tamano), ("LOTE-X", "fruta_001", "Buena", "Grande"))
            self.assertAlmostEqual(p1.confianza, 0.91)
            self.assertFalse(p2.foto_valida)
            self.assertEqual(decidir(p1).caja, 4)

    def test_reporte_e4_cumple_contrato(self):
        reporte = ReporteE4(None, {"G-1": 2})
        c = ColaFIFO()
        for f in ("F1", "F2"):
            c.nueva_fruta(time.time(), "L", "G-1", f)
            c.rellenar_por_id("G-1", f, estado="Buena", tamano="Mediana", confianza=0.8)
        self.assertEqual(reporte.agregar(c.disparo_sensor()), [])          # espera la 2.ª fruta
        msg = json.loads(reporte.agregar(c.disparo_sensor())[0].split("E4 -> ", 1)[1])
        self.assertEqual(set(msg), {"id_lote", "id_grupo", "estacion", "timestamp", "frutas"})
        self.assertEqual(msg["estacion"], "E4")
        self.assertTrue(msg["timestamp"].endswith("Z"))
        self.assertEqual(set(msg["frutas"][0]),
                         {"id_fruta", "categoria_final", "probabilidad", "requiere_revision_manual"})


class ClienteE5Falso:
    def __init__(self, validez_imagen):
        self.consultas_grupos = 0
        self.detalle = {
            "grupo": {"validez_imagen": validez_imagen},
            "frutas": [{
                "id_fruta": "F1",
                "calidad_visual": "alta",
                "confianza_visual": 0.9,
                "tamano": "grande",
                "diametro_mm": 67,
            }],
        }

    def get(self, ruta):
        if ruta == "/api/v1/lotes":
            return [{"id_lote": "LOTE-X"}]
        if ruta.endswith("/grupos?limit=100"):
            self.consultas_grupos += 1
            if self.consultas_grupos == 1:
                return []
            return [{"id_grupo": "G-1", "frutas_detectadas": 1}]
        if ruta == "/api/v1/grupos/G-1":
            return self.detalle
        raise AssertionError(f"Ruta inesperada: {ruta}")


class TestFuenteE5(unittest.TestCase):
    def test_respeta_validez_de_imagen_anidada_en_detalle(self):
        for validez, esperada in ((True, "exportacion"), (False, "revision_manual")):
            with self.subTest(validez=validez):
                fuente = FuenteE5(ClienteE5Falso(validez))
                cola = ColaFIFO()
                fuente.leer(cola)  # E4 ignora los grupos que ya existían al arrancar.
                fuente.leer(cola)

                self.assertEqual(len(cola), 1)
                self.assertEqual(cola.disparo_sensor().categoria_final, esperada)


if __name__ == "__main__":
    unittest.main()
