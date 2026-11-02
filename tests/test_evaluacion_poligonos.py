"""Pruebas P1: evaluación de polígonos contra fronteras sintéticas."""
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from campos_tractor import evaluacion as ep


def test_wilson_intervalo():
    r = ep.wilson_interval(2, 34)
    assert r['p'] == pytest.approx(0.059, abs=0.001)
    assert r['bajo'] < r['p'] < r['alto']
    assert ep.wilson_interval(0, 0)['n'] == 0


def test_poligono_exacto():
    ref = [box(0, 0, 10, 10)]
    det = [box(0, 0, 10, 10)]
    r = ep.evaluar_poligonos(det, ref)
    assert r['iou_mediana'] == 1.0
    assert r['error_area_mediana'] == 0.0
    assert r['fusionados'] == 0 and r['partidos'] == 0
    assert r['no_detectados'] == 0 and r['detectados_extra'] == 0
    assert r['n_pequeno'] is True


def test_poligono_partido():
    ref = [box(0, 0, 10, 10)]
    det = [box(0, 0, 5, 10), box(5, 0, 10, 10)]
    r = ep.evaluar_poligonos(det, ref)
    assert r['partidos'] == 1
    assert r['detectados_extra'] == 1
    assert r['no_detectados'] == 0
    assert r['fraccion_partidos']['p'] == 1.0


def test_poligonos_fusionados():
    ref = [box(0, 0, 10, 10), box(20, 0, 30, 10)]
    det = [box(0, 0, 30, 10)]
    r = ep.evaluar_poligonos(det, ref)
    assert r['fusionados'] == 1
    assert r['no_detectados'] == 1
    assert r['detectados_extra'] == 0


def test_no_detectado_y_extra():
    ref = [box(0, 0, 10, 10)]
    det = [box(50, 50, 60, 60)]
    r = ep.evaluar_poligonos(det, ref)
    assert r['no_detectados'] == 1
    assert r['detectados_extra'] == 1
    assert r['fraccion_no_detectados']['p'] == 1.0


def test_anillo_horario_es_invalido():
    geom = Polygon([(0, 0), (0, 10), (10, 10), (10, 0)])
    assert not geom.exterior.is_ccw
    errores = ep.validar_geometrias([geom])
    assert any(e['error'] == 'ANILLO_EXTERIOR_HORARIO' for e in errores)


def test_auto_interseccion_es_invalida():
    geom = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert not geom.is_valid
    errores = ep.validar_geometrias([geom])
    assert any(e['error'] == 'AUTOINTERSECCION' for e in errores)


def test_geojson_geografico_se_reproyecta_a_utm(tmp_path):
    gdf = gpd.GeoDataFrame({'id': [1]}, geometry=[box(-95.52, 18.6, -95.51, 18.61)],
                           crs=4326)
    ruta = tmp_path / 'ref.geojson'
    gdf.to_file(ruta, driver='GeoJSON')
    leido = ep.cargar_geojson(ruta)
    assert leido.crs.to_epsg() == 32615
    assert leido.crs.is_projected
    assert leido.geometry.iloc[0].area > 1000


def test_capa_vacia_falla_con_mensaje_claro(tmp_path):
    ruta = tmp_path / 'vacia.geojson'
    ruta.write_text('{"type":"FeatureCollection","features":[]}', encoding='utf-8')
    with pytest.raises(ValueError, match='no tiene geometrías'):
        ep.cargar_geojson(ruta)


def test_capa_sin_crs_falla_con_mensaje_claro(tmp_path):
    gdf = gpd.GeoDataFrame({'id': [1]}, geometry=[box(-95.52, 18.6, -95.51, 18.61)],
                           crs=4326)
    ruta = tmp_path / 'sin_crs.shp'
    gdf.to_file(ruta, driver='ESRI Shapefile')
    for prj in tmp_path.glob('*.prj'):
        prj.unlink()
    with pytest.raises(ValueError, match='no declara CRS'):
        ep.cargar_geojson(ruta)


def test_shapefile_en_otro_crs_se_reproyecta(tmp_path):
    gdf = gpd.GeoDataFrame({'id': [1]}, geometry=[box(-95.52, 18.6, -95.51, 18.61)],
                           crs=4326)
    ruta = tmp_path / 'ref.shp'
    gdf.to_file(ruta, driver='ESRI Shapefile')
    leido = ep.cargar_geojson(ruta)
    assert leido.crs.is_projected
    assert leido.crs.to_epsg() == 32615


def test_geojson_proyectado_valido(tmp_path):
    gdf = gpd.GeoDataFrame({'id': [1]}, geometry=[box(0, 0, 10, 10)],
                           crs=32615)
    ruta = tmp_path / 'ref.geojson'
    gdf.to_file(ruta, driver='GeoJSON')
    leido = ep.cargar_geojson(ruta)
    assert leido.crs.to_epsg() == 32615
    assert len(leido) == 1
