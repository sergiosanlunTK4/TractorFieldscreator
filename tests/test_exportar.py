"""Pruebas de GeoPackage, CRS, atributos y posición."""
from __future__ import annotations

import math
from pathlib import Path

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from campos_tractor.estados import CampoDetectado
from campos_tractor.utils import (agregar_diferencias,
                                  comparar_versiones, exportar_version)

LAT0 = 18.60
LON0 = -95.52
R = 111_320.0
X0 = LON0 * R * math.cos(math.radians(LAT0))
Y0 = LAT0 * R


def _frame(n: int = 80) -> pd.DataFrame:
    xg = X0 + np.arange(n, dtype=float) * 2.0
    yg = Y0 + np.arange(n, dtype=float) * 1.5
    return pd.DataFrame({
        'X': xg - xg.min(), 'Y': yg - yg.min(),
        'X_global': xg, 'Y_global': yg,
        'Bearing': np.full(n, 36.87), 't_s': np.arange(n) * 2.0,
        'Archivo': 'ruta_sintetica.csv',
        'Latitud': LAT0 + (yg - Y0) / R,
        'Longitud': LON0 + (xg - X0) / (R * math.cos(math.radians(LAT0))),
    })


def _campo(frame: pd.DataFrame) -> CampoDetectado:
    local = box(20.0, 20.0, 120.0, 120.0)
    return CampoDetectado(
        id_estable='id_estable_fijo', ruta_hash='ruta_hash_fijo',
        campo_id=1, geometry=local,
        indices=np.arange(len(frame)), n_puntos=len(frame),
        area_ha=1.0, perimetro_m=400.0, estado='CAMPO_PROBABLE',
        confianza=0.9, motivos=[], senales={
            'solidez': 0.9, 'compacidad': 0.78,
            'densidad_puntos_ha': 80.0, 'coherencia_orientacion': 0.99,
            'fraccion_dentro': 1.0},
        version_algoritmo='v1')


def test_exporta_capas_crs_y_atributos(tmp_path):
    frame = _frame()
    salida = exportar_version([frame], [[_campo(frame)]], 'v1', tmp_path,
                              revision_gpkg=tmp_path / 'revision_campos.gpkg')
    assert Path(salida['gpkg_4326']).is_file()
    assert salida['epsg_utms'] == [32615]
    ruta_utm = Path(salida['gpkg_utm_por_zona'][32615])
    assert ruta_utm.is_file()
    for ruta, epsg in ((Path(salida['gpkg_4326']), 4326), (ruta_utm, 32615)):
        capas = fiona.listlayers(ruta)
        for capa in ('campos', 'trazas', 'puntos_control', 'pasadas',
                     'cajas_ruta'):
            assert capa in capas
        with fiona.open(ruta, layer='campos') as src:
            assert src.crs.to_epsg() == epsg
            fila = next(iter(src))
            for campo in ('id_estable', 'ruta_hash', 'n_puntos', 'area_ha',
                          'perimetro_m', 'estado', 'confianza', 'motivo',
                          'version_algoritmo', 'solidez', 'compacidad',
                          'densidad_puntos_ha', 'coherencia_orientacion'):
                assert campo in fila['properties']
    control_utm = gpd.read_file(ruta_utm, layer='puntos_control')
    assert 'tipo' in control_utm.columns
    assert control_utm.geometry.notna().all()
    assert np.isfinite(control_utm.geometry.x).all()
    assert np.isfinite(control_utm.geometry.y).all()
    assert 'origen_0_0' not in set(control_utm['tipo'])
    control_wgs = gpd.read_file(salida['gpkg_4326'], layer='puntos_control')
    assert 'origen_0_0' in set(control_wgs['tipo'])
    campos = gpd.read_file(salida['gpkg_4326'], layer='campos')
    assert campos.iloc[0]['id_estable'] == 'id_estable_fijo'
    assert campos.iloc[0]['area_ha'] == pytest.approx(1.0, rel=0.005)
    assert campos.geometry.iloc[0].exterior.is_ccw
    assert Polygon(campos.geometry.iloc[0].exterior).is_valid


def test_ids_no_cambian_entre_versiones(tmp_path):
    frame = _frame()
    a = exportar_version([frame], [[_campo(frame)]], 'v1', tmp_path / 'a',
                         revision_gpkg=tmp_path / 'rev.gpkg')
    b = exportar_version([frame], [[_campo(frame)]], 'v2', tmp_path / 'b',
                         revision_gpkg=tmp_path / 'rev.gpkg')
    ca = gpd.read_file(a['gpkg_4326'], layer='campos')
    cb = gpd.read_file(b['gpkg_4326'], layer='campos')
    assert ca.id_estable.tolist() == cb.id_estable.tolist()


def test_verificacion_de_posicion_cumple_umbrales(tmp_path):
    frame = _frame()
    salida = exportar_version([frame], [[_campo(frame)]], 'v1', tmp_path,
                              revision_gpkg=tmp_path / 'rev.gpkg')
    ver = salida['verificacion']
    assert ver['segmento_ok'] is True
    assert ver['area_ok'] is True
    assert ver['max_error_segmento_rel'] < 0.01
    assert ver['max_error_area_rel'] < 0.005


def test_revision_es_archivo_aparte_y_no_se_pisa(tmp_path):
    frame = _frame()
    revision = tmp_path / 'revision_campos.gpkg'
    exportar_version([frame], [[_campo(frame)]], 'v1', tmp_path / 'a',
                     revision_gpkg=revision)
    with fiona.open(revision, layer='revision') as src:
        columnas = set(src.schema['properties'])
    for columna in ('id_estable', 'respuesta', 'comentario', 'revisor',
                    'fecha', 'version_revisada'):
        assert columna in columnas
    assert (tmp_path / 'a' / 'campos_v1_4326.gpkg').is_file()
    assert not (tmp_path / 'a' / 'revision_campos.gpkg').exists()


def test_comparacion_entre_versiones_genera_diferencias(tmp_path):
    def escribir(ruta, ids, cajas):
        gdf = gpd.GeoDataFrame({'id_estable': ids}, geometry=cajas, crs=32615)
        gdf.to_file(ruta, layer='campos', driver='GPKG')
    a = tmp_path / 'a.gpkg'
    b = tmp_path / 'b.gpkg'
    escribir(a, ['igual', 'desaparece'],
             [box(0, 0, 10, 10), box(50, 0, 60, 10)])
    escribir(b, ['igual', 'nuevo'],
             [box(0, 0, 10, 10), box(80, 0, 90, 10)])
    diferencias = comparar_versiones(a, b)
    tipos = set(diferencias.tipo)
    assert {'IGUAL', 'NUEVO', 'DESAPARECIDO'} <= tipos
    assert diferencias[diferencias.tipo == 'IGUAL'].iou.iloc[0] == 1.0
    agregar_diferencias(b, diferencias)
    assert 'diferencias' in fiona.listlayers(b)


def test_hoja_de_revision_tiene_una_fila_por_campo(tmp_path):
    frame = _frame()
    salida = exportar_version([frame], [[_campo(frame)]], 'v1', tmp_path,
                              revision_gpkg=tmp_path / 'rev.gpkg')
    hoja = Path(salida['hoja_revision'])
    assert hoja.is_file()
    contenido = hoja.read_text(encoding='utf-8').splitlines()
    assert len(contenido) == 2
    assert 'respuesta' in contenido[0]
