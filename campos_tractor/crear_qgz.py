"""Crea un proyecto QGIS (.qgz) para revisar los campos exportados.

Uso (Python de QGIS):
    "<ruta-a-QGIS>/bin/python-qgis-ltr.bat" -m campos_tractor.crear_qgz \
        --gpkg salida/0.4.0/campos_v0.4.0_4326.gpkg \
        --revision salida/revision_campos.gpkg \
        --qml salida/0.4.0/campos_v0.4.0.qml \
        --salida salida/0.4.0/campos_v0.4.0.qgz
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import time

RESPUESTAS = ('CORRECTO', 'DEMASIADO_GRANDE', 'PARCIAL_O_PEQUEÑO',
              'FUNDIDO_VARIOS', 'PARTIDO_EN_VARIOS', 'NO_ES_CAMPO', 'NO_SE')
RESPUESTAS_PARES = ('MISMO_CAMPO', 'CAMPOS_DISTINTOS', 'NO_SE')
CAPAS = ('campos', 'campos_descartados', 'trayectos_dispersos', 'unidades',
         'trazas', 'trazas_puntos', 'pares_contiguos')


def _capas_disponibles(ruta: Path, intentos: int = 20) -> set[str]:
    """Espera a que el GeoPackage recién escrito quede legible.

    En Windows, GDAL puede mantener bloqueadas las últimas capas durante unos
    segundos después de exportar. QGIS abortaría esas capas si abrimos antes.
    """
    if not ruta.is_file():
        return set()
    for intento in range(intentos):
        try:
            with sqlite3.connect(ruta) as conexion:
                return {fila[0] for fila in conexion.execute(
                    'SELECT table_name FROM gpkg_contents')}
        except sqlite3.OperationalError:
            if intento == intentos - 1:
                return set()
            time.sleep(0.5)
    return set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--gpkg', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--qml', required=True)
    parser.add_argument('--salida', required=True)
    args = parser.parse_args()

    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,
                           QgsEditorWidgetSetup, QgsProject,
                           QgsReferencedRectangle, QgsRectangle,
                           QgsVectorLayer, QgsVectorLayerJoinInfo)
    app = QgsApplication([], False)
    app.initQgis()
    proyecto = QgsProject.instance()
    proyecto.clear()
    gpkg = Path(args.gpkg).resolve()
    qml = Path(args.qml).resolve()
    disponibles = _capas_disponibles(gpkg)
    capas = {}
    for capa in CAPAS:
        if capa not in disponibles:
            continue
        layer = QgsVectorLayer(f'{gpkg}|layername={capa}', capa, 'ogr')
        if not layer.isValid():
            print(f'Aviso: capa inválida {capa}')
            continue
        if capa in ('campos', 'campos_descartados') and qml.is_file():
            layer.loadNamedStyle(str(qml))
        if (capa in ('pares_candidatos', 'pares_contiguos') and
                layer.fields().indexOf('en_muestra') >= 0):
            layer.setSubsetString('"en_muestra" = 1')
        capas[capa] = layer
        proyecto.addMapLayer(layer)
    # Estas capas ayudan a revisar, pero no deben tapar los campos al abrir.
    for capa in ('pares_contiguos', 'trayectos_dispersos', 'unidades',
                 'trazas_puntos', 'campos_descartados'):
        if capa in capas:
            nodo = proyecto.layerTreeRoot().findLayer(capas[capa].id())
            if nodo is not None:
                nodo.setItemVisibilityChecked(False)
    revision = Path(args.revision).resolve()
    capas_revision = _capas_disponibles(revision)
    rev = QgsVectorLayer(f'{revision}|layername=revision', 'revision', 'ogr')
    if 'revision' in capas_revision and rev.isValid():
        # Lista cerrada para la respuesta, tal como exige el paquete V5.
        idx = rev.fields().indexOf('respuesta')
        if idx >= 0:
            # QGIS 3.40 espera pares {key,value}; las tuplas hacen fallar la
            # lectura posterior del proyecto con una violación de acceso.
            rev.setEditorWidgetSetup(idx, QgsEditorWidgetSetup(
                'ValueMap', {'map': [{'key': v, 'value': v}
                                     for v in RESPUESTAS]}))
        idx = rev.fields().indexOf('comentario')
        if idx >= 0:
            rev.setEditorWidgetSetup(idx, QgsEditorWidgetSetup('TextEdit', {}))
        proyecto.addMapLayer(rev)
        if 'campos' in capas:
            join = QgsVectorLayerJoinInfo()
            join.setJoinLayer(rev)
            join.setJoinFieldName('id_estable')
            join.setTargetFieldName('id_estable')
            join.setUsingMemoryCache(True)
            join.setPrefix('rev_')
            capas['campos'].addJoin(join)
    else:
        print('Aviso: no se pudo cargar la tabla de revisión')
    revp = QgsVectorLayer(f'{revision}|layername=revision_pares',
                          'revision_pares', 'ogr')
    if 'revision_pares' in capas_revision and revp.isValid():
        idx = revp.fields().indexOf('respuesta')
        if idx >= 0:
            revp.setEditorWidgetSetup(idx, QgsEditorWidgetSetup(
                'ValueMap', {'map': [{'key': v, 'value': v}
                                     for v in RESPUESTAS_PARES]}))
        idx = revp.fields().indexOf('comentario')
        if idx >= 0:
            revp.setEditorWidgetSetup(idx, QgsEditorWidgetSetup('TextEdit', {}))
        proyecto.addMapLayer(revp)
        for destino in ('pares_contiguos',):
            if destino not in capas:
                continue
            join = QgsVectorLayerJoinInfo()
            join.setJoinLayer(revp)
            join.setJoinFieldName('id_par')
            join.setTargetFieldName('id_par')
            join.setUsingMemoryCache(True)
            join.setPrefix('revp_')
            capas[destino].addJoin(join)
    proyecto.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
    if 'campos' in capas:
        ext = capas['campos'].extent()
        if not ext.isEmpty():
            proyecto.viewSettings().setDefaultViewExtent(
                QgsReferencedRectangle(
                    QgsRectangle(ext), QgsCoordinateReferenceSystem('EPSG:4326')))
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    proyecto.write(str(salida))
    app.exitQgis()
    print(f'Proyecto escrito en {salida}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
