"""Salidas estables por estado para integrar con AGMS2OC.

El detector conserva la clasificación completa en ``Campo.estado``. Este
módulo ofrece tres grupos de consumo directo:

  - ``campos``: CAMPO_PROBABLE
  - ``campos_fragmento``: CAMPO_FRAGMENTO
  - ``campos_dudosos``: DUDOSO

Los demás estados quedan en ``trayectos_dispersos`` y ``no_campo``.
"""
from __future__ import annotations

from .detector import detectar_campos
from .unidades import CFG_CAMPOS, Campo

GRUPOS = {
    'CAMPO_PROBABLE': 'campos',
    'CAMPO_FRAGMENTO': 'campos_fragmento',
    'DUDOSO': 'campos_dudosos',
    'NO_ES_CAMPO': 'no_campo',
    'TRAYECTO_DISPERSO': 'trayectos_dispersos',
}


def separar_por_estado(campos: list[Campo]) -> dict[str, list[Campo]]:
    """Agrupa los campos detectados en las salidas que consume AGMS2OC."""
    salida = {nombre: [] for nombre in GRUPOS.values()}
    for campo in campos:
        salida[GRUPOS.get(campo.estado, 'no_campo')].append(campo)
    return salida


def resumen_salidas(campos: list[Campo]) -> dict:
    """Conteos y hectáreas por grupo de consumo."""
    grupos = separar_por_estado(campos)
    return {
        nombre: {
            'n': len(lista),
            'area_ha': round(sum(c.area_ha for c in lista), 4),
            'cuenta_ha': round(sum(c.cuenta_ha for c in lista), 4),
        }
        for nombre, lista in grupos.items()
    }


def detectar_campos_por_estado(frame, ruta_hash: str,
                               cfg: dict | None = None) -> dict:
    """Ejecuta el detector y devuelve las salidas separadas por estado.

    Contrato de uso desde AGMS2OC::

        resultado = detectar_campos_por_estado(frame, ruta_hash)
        for campo in resultado['campos']: ...
        for campo in resultado['campos_fragmento']: ...
        for campo in resultado['campos_dudosos']: ...

    Cada elemento es un ``Campo`` con ``to_dict()``, geometría WGS84/UTM y
    ``cuenta_ha`` ya calculada.
    """
    campos, unidades, rechazos = detectar_campos(
        frame, ruta_hash, cfg or CFG_CAMPOS)
    grupos = separar_por_estado(campos)
    return {
        **grupos,
        'unidades': unidades,
        'rechazos': rechazos,
        'resumen': resumen_salidas(campos),
    }
