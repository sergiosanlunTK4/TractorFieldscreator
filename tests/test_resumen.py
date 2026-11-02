"""Pruebas V5: validación de respuestas, invalidez y resumen con Wilson."""
from __future__ import annotations

import sqlite3

import fiona
import geopandas as gpd
import pytest
from shapely.geometry import box

from campos_tractor.resumen import (_particion_por_ruta,
                                                   leer_revision, resumir)


def _campos(tmp_path):
    gdf = gpd.GeoDataFrame(
        {'id_estable': ['a', 'b']},
        geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)], crs=32615)
    ruta = tmp_path / 'campos.gpkg'
    gdf.to_file(ruta, layer='campos', driver='GPKG')
    return ruta


def _revision(tmp_path, filas):
    ruta = tmp_path / 'revision.gpkg'
    schema = {'properties': {
        'id_estable': 'str', 'respuesta': 'str', 'comentario': 'str',
        'revisor': 'str', 'fecha': 'str', 'version_revisada': 'str'}}
    with fiona.open(ruta, 'w', driver='GPKG', layer='revision',
                    schema=schema) as dst:
        for fila in filas:
            dst.write({'geometry': None, 'properties': fila})
    return ruta


def test_resumen_marca_invalidadas_sin_borrar(tmp_path):
    campos = _campos(tmp_path)
    revision = _revision(tmp_path, [
        {'id_estable': 'a', 'respuesta': 'CORRECTO', 'comentario': '',
         'revisor': 'r1', 'fecha': '2026-11-01', 'version_revisada': 'v1'},
        {'id_estable': 'b', 'respuesta': 'DEMASIADO_GRANDE', 'comentario': '',
         'revisor': 'r1', 'fecha': '2026-11-01', 'version_revisada': 'v1'},
        {'id_estable': 'c', 'respuesta': 'NO_ES_CAMPO', 'comentario': '',
         'revisor': 'r1', 'fecha': '2026-11-01', 'version_revisada': 'v1'},
    ])
    resumen = resumir(revision, campos, 'v2', tmp_path / 'salida')
    assert resumen['n_validas'] == 2
    assert resumen['n_invalidadas'] == 1
    assert resumen['invalidas'][0]['id_estable'] == 'c'
    assert resumen['n_pequeno'] is True
    correcto = [f for f in resumen['por_respuesta']
                if f['respuesta'] == 'CORRECTO'][0]
    assert correcto['k'] == 1
    assert correcto['bajo'] < correcto['p'] < correcto['alto']
    assert resumen['campos_problematicos']['DEMASIADO_GRANDE'][0][
        'id_estable'] == 'b'
    assert resumen['candidatos_por_fallo']['DEMASIADO_GRANDE']
    assert (tmp_path / 'salida' / 'resumen_revision.json').is_file()
    assert (tmp_path / 'salida' / 'revision_problematicos.csv').is_file()
    # La fila inválida sigue existiendo, marcada.
    filas = {f['id_estable']: f for f in leer_revision(revision)}
    assert set(filas) == {'a', 'b', 'c'}
    assert filas['a']['vigente'] == 'SI'
    assert filas['c']['vigente'] == 'NO'
    assert 'ausente' in filas['c']['motivo_invalidez']


def test_respuesta_fuera_de_lista_falla(tmp_path):
    campos = _campos(tmp_path)
    revision = _revision(tmp_path, [
        {'id_estable': 'a', 'respuesta': 'MAS_O_MENOS', 'comentario': '',
         'revisor': '', 'fecha': '', 'version_revisada': 'v1'}])
    with pytest.raises(ValueError, match='lista cerrada'):
        resumir(revision, campos, 'v1')


def test_dry_run_no_modifica_la_tabla(tmp_path):
    campos = _campos(tmp_path)
    revision = _revision(tmp_path, [
        {'id_estable': 'a', 'respuesta': 'CORRECTO', 'comentario': '',
         'revisor': '', 'fecha': '', 'version_revisada': 'v1'}])
    resumen = resumir(revision, campos, 'v1', dry_run=True)
    assert resumen['n_validas'] == 1
    with sqlite3.connect(revision) as conexion:
        columnas = {fila[1] for fila in conexion.execute(
            'PRAGMA table_info(revision)')}
    assert 'vigente' not in columnas


def test_particion_por_ruta_reserva_mitad():
    filas = ([{'ruta_hash': 'r1'}] * 10 + [{'ruta_hash': 'r2'}] * 8 +
             [{'ruta_hash': 'r3'}] * 6 + [{'ruta_hash': 'r4'}] * 5)
    particion = _particion_por_ruta(filas)
    assert {f['grupo'] for f in particion} == {'AJUSTE', 'RETENCION'}
    total = sum(f['n_etiquetas'] for f in particion)
    ajuste = sum(f['n_etiquetas'] for f in particion if f['grupo'] == 'AJUSTE')
    assert total == 29
    assert abs(ajuste - total / 2) <= 6
