"""Pruebas del detector: filtro México, unidades temporales y compuertas."""
from __future__ import annotations

import numpy as np

from campos_tractor.detector import detectar_campos
from campos_tractor.filtro_mexico import filtrar_mexico
from campos_tractor.sintetico import SEMILLA, generar


def _escenario(nombre):
    return [e for e in generar(SEMILLA) if e.nombre == nombre][0]


def test_filtro_mexico_no_descarta_interiores():
    e = _escenario('contiguos_10m')
    limpio, fuera, resumen = filtrar_mexico(e.frame, 'ruta')
    assert resumen['n_fuera'] == 0
    assert len(limpio) == len(e.frame)
    assert fuera == []


def test_filtro_mexico_marca_punto_exterior():
    e = _escenario('contiguos_10m')
    frame = e.frame.copy()
    frame.loc[0, 'X_global'] = 0.0
    frame.loc[0, 'Y_global'] = 0.0
    _, fuera, resumen = filtrar_mexico(frame, 'ruta')
    assert resumen['n_fuera'] >= 1
    assert fuera and fuera[0]['ruta_hash'] == 'ruta'


def test_detector_separa_contiguos_y_no_deja_densidad_baja():
    e = _escenario('contiguos_10m')
    campos, unidades, _ = detectar_campos(e.frame, e.nombre)
    incluidos = [c for c in campos
                 if c.estado not in ('NO_ES_CAMPO', 'TRAYECTO_DISPERSO')
                 and c.area_ha >= 0.10]
    assert len(incluidos) == 2
    assert all(c.densidad_puntos_ha >= 20 for c in incluidos)
    assert all(c.max_gap_m <= 300 for c in incluidos)
    assert max(c.area_ha for c in incluidos) < 100


def test_detector_no_parte_campo_grande_compacto():
    e = _escenario('grande_compacto')
    campos, _, _ = detectar_campos(e.frame, e.nombre)
    incluidos = [c for c in campos
                 if c.estado not in ('NO_ES_CAMPO', 'TRAYECTO_DISPERSO')]
    assert len(incluidos) == 1
    assert incluidos[0].area_ha > 5


def test_camino_largo_no_cuenta_como_campo():
    from campos_tractor.sintetico import _frame, _traslado
    puntos, _ = _traslado(0, 0, 2000, 0, 0, speed=3.0)
    campos, _, _ = detectar_campos(_frame(puntos, 'camino.csv'), 'camino')
    assert campos
    assert all(c.estado in ('TRAYECTO_DISPERSO', 'NO_ES_CAMPO')
               for c in campos)
    assert sum(c.cuenta_ha for c in campos) == 0.0
    assert any('camino' in c.motivos[0] for c in campos)


def test_detector_marca_disperso_por_densidad_o_hueco():
    # Un campo de un solo día con muestreo muy ralo no debe pasar la compuerta.
    from campos_tractor.sintetico import _campo, _frame
    rng = np.random.default_rng(7)
    puntos, _ = _campo(0, 0, 100, 100, rng, dt_min=120, dt_max=120)
    campos, _, _ = detectar_campos(_frame(puntos, 'ralo.csv'), 'ralo')
    assert all(c.estado in ('TRAYECTO_DISPERSO', 'NO_ES_CAMPO')
               or c.densidad_puntos_ha < 20 for c in campos)
