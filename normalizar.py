"""
Traduce lo que mandan E2 y E3 a un vocabulario único para la Estación 4.

Hoy cada estación usa nombres distintos, así que se aceptan todos:

  E2 (calidad)        código real de E2           contrato E5 (E2.json)
  ------------        -----------------           ---------------------
  Buena               buen_estado                 alta
  Pasable             marginalmente_buena         media, baja
  Mala                mal_estado                  defectos_visibles
  Revision            (sin dato)                  revision

  E3 (tamaño)         código real de E3           contrato E5 (E3.json)
  Chica               chico                       pequeno
  Mediana             mediano                     mediano
  Grande              grande                      grande
"""
import config

_ESTADOS = {
    "buena": "Buena", "buen_estado": "Buena", "alta": "Buena",
    "pasable": "Pasable", "marginalmente_buena": "Pasable", "media": "Pasable", "baja": "Pasable",
    "mala": "Mala", "mal_estado": "Mala", "defectos_visibles": "Mala",
    "revision": "Revision", "revision_manual": "Revision",
}
_TAMANOS = {
    "chica": "Chica", "chico": "Chica", "pequeno": "Chica", "pequeño": "Chica", "pequena": "Chica",
    "mediana": "Mediana", "mediano": "Mediana",
    "grande": "Grande",
}


def estado(valor) -> str | None:
    if valor is None:
        return None
    return _ESTADOS.get(str(valor).strip().lower())


def tamano(valor=None, diametro_mm=None) -> str | None:
    if valor is not None:
        t = _TAMANOS.get(str(valor).strip().lower())
        if t:
            return t
    if diametro_mm is not None and float(diametro_mm) > 0:
        return config.tamano_por_diametro(float(diametro_mm))
    return None


def confianza(valor) -> float | None:
    """Acepta 0-1 (contrato E5) o 0-100 (confidence_percent de E2)."""
    if valor is None:
        return None
    v = float(valor)
    return v / 100 if v > 1 else v
