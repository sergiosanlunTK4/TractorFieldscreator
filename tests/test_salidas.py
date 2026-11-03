"""Pruebas de las salidas por estado para integración con AGMS2OC."""
from __future__ import annotations

from types import SimpleNamespace

from campos_tractor.salidas import resumen_salidas, separar_por_estado


def _campo(estado, area):
    return SimpleNamespace(estado=estado, area_ha=area, cuenta_ha=area)


def test_separar_por_estado():
    campos = [
        _campo('CAMPO_PROBABLE', 2.0),
        _campo('CAMPO_FRAGMENTO', 1.0),
        _campo('DUDOSO', 0.5),
        _campo('NO_ES_CAMPO', 0.2),
        _campo('TRAYECTO_DISPERSO', 0.1),
    ]
    grupos = separar_por_estado(campos)
    assert len(grupos['campos']) == 1
    assert len(grupos['campos_fragmento']) == 1
    assert len(grupos['campos_dudosos']) == 1
    assert len(grupos['no_campo']) == 1
    assert len(grupos['trayectos_dispersos']) == 1

    resumen = resumen_salidas(campos)
    assert resumen['campos']['n'] == 1
    assert resumen['campos']['cuenta_ha'] == 2.0
    assert resumen['campos_fragmento']['cuenta_ha'] == 1.0
