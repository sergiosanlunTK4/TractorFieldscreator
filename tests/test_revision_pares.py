"""Pruebas de pares persistentes, lista cerrada e invalidez."""
from __future__ import annotations

import sqlite3

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from campos_tractor.utils import _asegurar_revision_pares
from campos_tractor.resumen_pares import (ids_actuales, marcar,
                                                         resumir)


def _pares(tmp_path):
    gdf = gpd.GeoDataFrame(
        {'id_par': ['p1', 'p2'],
         'ruta_a': ['r1', 'r1']},
        geometry=[LineString([(0, 0), (1, 1)]),
                  LineString([(2, 2), (3, 3)])], crs=4326)
    ruta = tmp_path / 'pares.gpkg'
    gdf.to_file(ruta, layer='pares_contiguos', driver='GPKG')
    return ruta


def _revision(tmp_path, filas):
    ruta = tmp_path / 'revision.gpkg'
    _asegurar_revision_pares(ruta)
    with sqlite3.connect(ruta) as c:
        for fila in filas:
            c.execute('INSERT INTO revision_pares '
                      '(id_par,respuesta,comentario,revisor,fecha,version_revisada) '
                      'VALUES (?,?,?,?,?,?)',
                      (fila['id_par'], fila['respuesta'], '', 'r',
                       '2026-11-01', 'actual'))
    return ruta


def test_resumen_pares_marca_invalidos(tmp_path):
    pares = _pares(tmp_path)
    revision = _revision(tmp_path, [
        {'id_par': 'p1', 'respuesta': 'MISMO_CAMPO'},
        {'id_par': 'p2', 'respuesta': 'CAMPOS_DISTINTOS'},
        {'id_par': 'p3', 'respuesta': 'NO_SE'},
    ])
    r = resumir(revision, pares, 'actual', tmp_path / 'salida')
    assert r['n_validas'] == 2
    assert r['n_invalidadas'] == 1
    assert r['invalidas'][0]['id_par'] == 'p3'
    with sqlite3.connect(revision) as c:
        estado = dict(c.execute(
            'SELECT id_par, vigente FROM revision_pares').fetchall())
    assert estado['p1'] == 'SI' and estado['p3'] == 'NO'


def test_respuesta_de_par_fuera_de_lista_falla(tmp_path):
    pares = _pares(tmp_path)
    revision = _revision(tmp_path, [
        {'id_par': 'p1', 'respuesta': 'TAL_VEZ'}])
    with pytest.raises(ValueError, match='lista cerrada'):
        resumir(revision, pares, 'actual')


def test_dry_run_no_modifica_tabla(tmp_path):
    pares = _pares(tmp_path)
    revision = _revision(tmp_path, [
        {'id_par': 'p1', 'respuesta': 'MISMO_CAMPO'}])
    r = resumir(revision, pares, 'actual', dry_run=True)
    assert r['n_validas'] == 1
    with sqlite3.connect(revision) as c:
        valor = c.execute("SELECT vigente FROM revision_pares WHERE id_par='p1'").fetchone()[0]
    assert valor in (None, '')
