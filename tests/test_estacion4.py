"""Pruebas de la Estación 4. Correr desde la carpeta estacion4:  python -m unittest -v"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import normalizar  # noqa: E402
from clasificador import ColaFIFO, GestorBache, decidir, PaqueteFruta  # noqa: E402
from fuentes import FuenteArchivos, ReporteE4  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
