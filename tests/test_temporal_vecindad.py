"""Pruebas V2-tiempo: sesiones, filtro de área y vecindad entre campos."""
from __future__ import annotations

import math
from pathlib import Path

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from campos_tractor.analisis_temporal import (anotar_sesiones,
                                                    metricas_campo_tiempo)
from campos_tractor.estados import CampoDetectado
from campos_tractor.utils import exportar_version
from campos_tractor.vecindad import analizar_vecindad

LAT0 = 18.60
LON0 = -95.52
R = 111_320.0
X0 = LON0 * R * math.cos(math.radians(LAT0))
Y0 = LAT0 * R


def _frame(n: int = 120) -> pd.DataFrame:
    xg = X0 + np.arange(n, dtype=float) * 2.0
    yg = Y0 + np.arange(n, dtype=float) * 1.5
    return pd.DataFrame({
        'X': xg - xg.min(), 'Y': yg - yg.min(),
        'X_global': xg, 'Y_global': yg,
        'Bearing': np.full(n, 36.87), 't_s': np.arange(n) * 60.0,
        'Timestamp': pd.date_range('2026-05-01 08:00:00', periods=n,
                                   freq='60s'),
        'Archivo': 'ruta_tiempo.csv',
        'Velocidad_kmh': np.full(n, 6.0),
        'speed_kmh_origen': np.full(n, 6.0),
        'state_origen': np.where(np.arange(n) < 80, 'Working', 'Idle'),
    })


def _campo(campo_id, geom, indices, ruta_hash='ruta_hash'):
    return CampoDetectado(
        id_estable=f'id{campo_id}', ruta_hash=ruta_hash, campo_id=campo_id,
        geometry=geom, indices=np.asarray(indices), n_puntos=len(indices),
        area_ha=geom.area / 10000.0, perimetro_m=geom.length,
        estado='CAMPO_PROBABLE', confianza=0.9,
        motivos=['cumple mínimos'], senales={
            'solidez': 0.9, 'compacidad': 0.8, 'densidad_puntos_ha': 100.0,
            'coherencia_orientacion': 0.99, 'fraccion_dentro': 1.0},
        version_algoritmo='v2')


def test_sesiones_por_hueco_y_metricas():
    frame = _frame(6)
    frame.loc[3:, 'Timestamp'] = frame.loc[3:, 'Timestamp'] + pd.Timedelta(hours=3)
    anotado = anotar_sesiones(frame, 'ruta', gap_s=7200)
    assert anotado['sesion_id'].nunique() == 2
    metricas = metricas_campo_tiempo(anotado, np.arange(len(anotado)))
    assert metricas['n_sesiones'] == 2
    assert metricas['state_cobertura'] == 1.0
    assert metricas['frac_working'] > 0
    assert metricas['speed_p50'] == 6.0


def test_vecindad_agrupa_campos_muy_cercanos():
    frame = _frame()
    a = _campo(1, box(20, 20, 120, 120), np.arange(40))
    b = _campo(2, box(125, 20, 225, 120), np.arange(40, 80))
    campos = []
    for campo in (a, b):
        campos.append({
            'id_estable': campo.id_estable, 'geometry': None,
            'geometry_utm': None, 'epsg_utm': 32615,
            'area_ha': campo.area_ha, 'solidez': 0.9, 'compacidad': 0.8,
            'ruta_hash': 'ruta', 'estado': campo.estado,
            'sesiones': {'s1', 's2'},
        })
    # Geometrías WGS84 para distancia y UTM para forma.
    from pyproj import Transformer
    from shapely.ops import transform
    trans = Transformer.from_crs(4326, 32615, always_xy=True)
    wgs_a = box(-95.52, 18.60, -95.519, 18.601)
    wgs_b = box(-95.519, 18.60, -95.518, 18.601)
    campos[0]['geometry'], campos[1]['geometry'] = wgs_a, wgs_b
    campos[0]['geometry_utm'] = transform(trans.transform, wgs_a)
    campos[1]['geometry_utm'] = transform(trans.transform, wgs_b)
    pares, datos = analizar_vecindad(campos, dist_junto_m=10,
                                     dist_candidata_m=50)
    assert len(pares) == 1
    assert pares[0]['nivel'] == 'MUY_CERCA'
    assert datos['campos']['id1']['n_campos_grupo'] == 2
    assert datos['grupos'][0]['n_campos'] == 2


def test_exportacion_filtra_area_y_exporta_vecindad(tmp_path):
    frame = _frame()
    grande = _campo(1, box(20, 20, 120, 120), np.arange(0, 60))
    cercano = _campo(2, box(125, 20, 225, 120), np.arange(60, 120))
    pequeno = _campo(3, box(300, 300, 320, 320), np.arange(0, 20))
    cfg = {'area_descarte_ha': 0.10, 'vecindad_dist_m': 10.0,
           'vecindad_candidata_m': 50.0, 'sesion_gap_s': 7200}
    salida = exportar_version([frame], [[grande, cercano, pequeno]], 'v2',
                              tmp_path, cfg=cfg,
                              revision_gpkg=tmp_path / 'revision.gpkg')
    assert salida['n_campos'] == 2
    assert salida['n_descartados_area'] == 1
    assert salida['n_grupos_vecindad'] == 1
    assert salida['n_pares_vecindad'] == 1
    capas = fiona.listlayers(salida['gpkg_4326'])
    assert 'campos_descartados' in capas
    assert 'grupos_vecindad' in capas
    campos = gpd.read_file(salida['gpkg_4326'], layer='campos')
    descartados = gpd.read_file(salida['gpkg_4326'],
                                layer='campos_descartados')
    assert len(campos) == 2 and len(descartados) == 1
    assert set(campos['grupo_vecindad']) != {''}
    assert campos['n_campos_grupo'].max() == 2
    assert Path(salida['csv_vecindad']).is_file()
