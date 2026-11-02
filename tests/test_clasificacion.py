"""Pruebas del clasificador estricto y del aspect ratio (MBB)."""
from __future__ import annotations

from shapely.geometry import box

from campos_tractor.estados import clasificar_cobertura_estricta
from campos_tractor.metricas import calcular_aspect_ratio


def test_aspect_ratio_cuadrado_y_rectangulo():
    assert abs(calcular_aspect_ratio(box(0, 0, 10, 10)) - 1.0) < 1e-9
    assert abs(calcular_aspect_ratio(box(0, 0, 100, 10)) - 10.0) < 1e-9
    assert calcular_aspect_ratio(None) == 1.0


def test_regla_1_camino_por_geometria_lineal():
    r = clasificar_cobertura_estricta(
        area_ha=2.0, n_puntos=200, n_unidades=1, horas=1.0,
        solidez=0.95, compacidad=0.015, densidad_puntos_ha=100.0,
        coherencia_orientacion=0.99, aspect_ratio=25.0)
    assert r['categoria_final'] == 'TRAYECTO_DISPERSO'
    assert r['subcategoria'] == 'NO_ES_CAMPO'
    assert r['cuenta_ha_valida'] is False
    assert r['metrica_detonante'] in ('solidez', 'compacidad')


def test_regla_2_esfuerzo_insuficiente():
    r = clasificar_cobertura_estricta(
        area_ha=0.4, n_puntos=20, n_unidades=1, horas=0.10,
        solidez=0.80, compacidad=0.30, densidad_puntos_ha=50.0,
        coherencia_orientacion=0.80, aspect_ratio=2.0)
    assert r['categoria_final'] == 'TRAYECTO_DISPERSO'
    assert r['cuenta_ha_valida'] is False


def test_regla_3_ruido_de_cobertura():
    r = clasificar_cobertura_estricta(
        area_ha=0.05, n_puntos=100, n_unidades=3, horas=0.5,
        solidez=0.30, compacidad=0.20, densidad_puntos_ha=2000.0,
        coherencia_orientacion=0.70, aspect_ratio=1.5)
    assert r['categoria_final'] == 'TRAYECTO_DISPERSO'
    assert r['subcategoria'] == 'RUIDO_COBERURA'
    assert r['cuenta_ha_valida'] is False


def test_regla_4_campo_y_fragmento():
    campo = clasificar_cobertura_estricta(
        area_ha=2.0, n_puntos=500, n_unidades=5, horas=8.0,
        solidez=0.75, compacidad=0.35, densidad_puntos_ha=250.0,
        coherencia_orientacion=0.80, aspect_ratio=2.0)
    assert campo['categoria_final'] == 'CAMPO'
    assert campo['subcategoria'] == 'TRABAJO_AGRICOLA'
    assert campo['cuenta_ha_valida'] is True

    fragmento = clasificar_cobertura_estricta(
        area_ha=0.40, n_puntos=80, n_unidades=1, horas=0.8,
        solidez=0.75, compacidad=0.35, densidad_puntos_ha=200.0,
        coherencia_orientacion=0.80, aspect_ratio=2.0)
    assert fragmento['categoria_final'] == 'CAMPO_FRAGMENTO'
    assert fragmento['cuenta_ha_valida'] is True
