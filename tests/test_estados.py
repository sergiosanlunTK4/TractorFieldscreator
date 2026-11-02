"""Pruebas de clasificación de estados (sin ancho)."""
from __future__ import annotations

from campos_tractor.estados import CFG_DETECCION, ESTADOS, _clasificar


def test_estados_y_motivos_legibles():
    estado, motivos = _clasificar(4.0, 500, 0.85, 0.70, 0.90, 100.0, 1.0,
                                  CFG_DETECCION)
    assert estado == 'CAMPO_PROBABLE'
    assert motivos and 'cumple' in motivos[0]

    estado, motivos = _clasificar(0.05, 10, 0.10, 0.01, 0.05, 1.0, 0.2,
                                  CFG_DETECCION)
    assert estado == 'NO_ES_CAMPO'
    assert len(motivos) >= 3

    estado, motivos = _clasificar(0.40, 100, 0.60, 0.30, 0.80, 250.0, 1.0,
                                  CFG_DETECCION)
    assert estado == 'CAMPO_FRAGMENTO'
    assert motivos
    assert estado in ESTADOS


def test_no_hay_parametro_de_ancho():
    assert all('ancho' not in clave for clave in CFG_DETECCION)
