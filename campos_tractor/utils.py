"""Exporta campos de tractor a GeoPackage, QML y CSV.

Reglas de la entrega:
  · un GeoPackage completo en EPSG:4326;
  · un GeoPackage por zona UTM usada (EPSG:326xx/327xx), con las mismas capas;
  · todas las capas de un archivo comparten el CRS declarado;
  · área y perímetro se calculan en la UTM de cada ruta, no con una fórmula
    esférica;
  · los ids son deterministas y NO dependen de la versión, para que las
    etiquetas de revisión sobrevivan a una reejecución.

No ejecuta nada remoto.
"""
from __future__ import annotations

import csv
import hashlib
import random
from shapely import STRtree
from shapely.ops import unary_union
import pandas as pd
import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point, box
from shapely.ops import orient, transform as shapely_transform

from ._compat import _epsg_utm
from ._compat import _cfg, _pasadas_todas
from . import proyeccion
from .analisis_temporal import (anotar_sesiones, metricas_campo_tiempo,
                                 resumen_temporal)
from .estados import CFG_DETECCION, CampoDetectado
from .vecindad import analizar_vecindad

COLORES = {
    'CAMPO_PROBABLE': '#2e7d32',
    'CAMPO_FRAGMENTO': '#f9a825',
    'DUDOSO': '#ef6c00',
    'NO_ES_CAMPO': '#c62828',
}

RESPUESTAS = ('CORRECTO', 'DEMASIADO_GRANDE', 'PARCIAL_O_PEQUEÑO',
              'FUNDIDO_VARIOS', 'PARTIDO_EN_VARIOS', 'NO_ES_CAMPO', 'NO_SE')

CAPAS = ('campos', 'trazas', 'pasadas', 'puntos_control', 'cajas_ruta',
         'campos_descartados', 'grupos_vecindad')


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()[:16]


def etiqueta_archivo(version: str) -> str:
    """Evita ``campos_vv1`` cuando la versión ya empieza por ``v``."""
    texto = str(version).strip()
    return texto[1:] if texto.lower().startswith('v') else texto


def _origen_y_desplazamiento(frame):
    primera = frame.iloc[0]
    origen = proyeccion.origen_desde_primera({
        'x_m': float(primera['X_global']), 'y_m': float(primera['Y_global']),
        'pasada': 0,
    })
    x0 = float(frame['X_global'].iloc[0] - frame['X'].iloc[0])
    y0 = float(frame['Y_global'].iloc[0] - frame['Y'].iloc[0])
    return origen, x0, y0


def _a_wgs84(geom, origen, x0=0.0, y0=0.0):
    def convertir(x, y):
        return proyeccion.invertir_xy(np.asarray(x) + x0,
                                      np.asarray(y) + y0, origen)
    return shapely_transform(convertir, geom)


def _a_utm(geom, epsg: int):
    transformer = Transformer.from_crs('EPSG:4326', f'EPSG:{epsg}',
                                       always_xy=True)
    return shapely_transform(transformer.transform, geom)


def _de_utm_a_wgs84(geom, epsg: int):
    transformer = Transformer.from_crs(f'EPSG:{epsg}', 'EPSG:4326',
                                       always_xy=True)
    return shapely_transform(transformer.transform, geom)


def _config(cfg: dict | None) -> dict:
    return {**CFG_DETECCION, **(cfg or {})}


def _info_ruta(frame) -> dict:
    origen, x0, y0 = _origen_y_desplazamiento(frame)
    xg = frame['X_global'].to_numpy(dtype=float)
    yg = frame['Y_global'].to_numpy(dtype=float)
    lon_c, lat_c = proyeccion.invertir_xy(float(xg.mean()),
                                          float(yg.mean()), origen)
    return {
        'origen': origen,
        'x0': x0,
        'y0': y0,
        'epsg': int(_epsg_utm(lon_c, lat_c)),
        'ruta_hash': _hash(str(frame['Archivo'].iloc[0])),
        'x': xg,
        'y': yg,
    }


def _orientar(geom):
    if geom.geom_type in ('Polygon', 'MultiPolygon'):
        return orient(geom, 1.0)
    return geom


def _pasadas_wgs84(frame, campo, cfg, info):
    grupo = frame.iloc[campo.indices]
    pasadas = _pasadas_todas(grupo, _cfg(cfg))
    salida = []
    for pasada in pasadas:
        idx = pasada.get('indices')
        if idx is None or len(idx) < 2:
            continue
        pts = grupo.iloc[np.asarray(idx, dtype=int)]
        xx = pts['X_global'].to_numpy(dtype=float)
        yy = pts['Y_global'].to_numpy(dtype=float)
        coords = list(zip(*proyeccion.invertir_xy(xx, yy, info['origen'])))
        salida.append({
            'n_puntos': int(pasada.get('n', len(idx))),
            'largo_m': round(float(pasada.get('largo', 0.0)), 1),
            'rumbo': round(float(pasada.get('rumbo', 0.0)), 1),
            'geometry': LineString(coords),
        })
    return salida


def _qml() -> str:
    categorias = ''.join(
        f'<category value="{estado}" symbol="{i}" label="{estado}"/>'
        for i, estado in enumerate(COLORES))
    simbolos = ''.join(
        f'<symbol type="fill" name="{i}" alpha="0.65"><layer class="SimpleFill" '
        f'pass="0" locked="0"><prop k="color" v="{int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},255"/>'
        f'<prop k="outline_color" v="40,40,40,255"/></layer></symbol>'
        for i, color in enumerate(COLORES.values()))
    return f'''<!DOCTYPE qgis>
<qgis version="3.40.0-Bratislava">
  <renderer-referencia type="categorizedSymbol" attr="estado" symbollevels="0" forceraster="0">
    <categories>{categorias}</categories>
    <symbols>{simbolos}</symbols>
  </renderer-referencia>
  <labelling type="simple">
    <settings>
      <text-style fieldName="id_estable" fontSize="8" textColor="0,0,0,255"/>
      <placement placement="0" placementFlags="10"/>
    </settings>
  </labelling>
</qgis>
'''


def _escribir_estilos(gpkg: Path, qml: Path) -> None:
    qml.write_text(_qml(), encoding='utf-8')
    with sqlite3.connect(gpkg) as conexion:
        conexion.execute('''CREATE TABLE IF NOT EXISTS layer_styles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            f_table_catalog TEXT, f_table_schema TEXT, f_table_name TEXT,
            f_geometry_column TEXT, styleName TEXT, styleQML TEXT,
            styleSLD TEXT, useAsDefault INTEGER, description TEXT,
            owner TEXT, ui TEXT, update_time TEXT)''')
        conexion.execute('DELETE FROM layer_styles WHERE f_table_name=?',
                         ('campos',))
        conexion.execute('''INSERT INTO layer_styles
            (f_table_name,f_geometry_column,styleName,styleQML,useAsDefault,description)
            VALUES ('campos','geometry','estado_campo',?,1,'Color por estado')''',
                         (qml.read_text(encoding='utf-8'),))


def _gdf(filas: list[dict], crs, columnas: list[str]) -> gpd.GeoDataFrame:
    datos = [{k: v for k, v in fila.items() if not k.startswith('_')}
             for fila in filas]
    return gpd.GeoDataFrame(datos, columns=columnas + ['geometry'],
                            geometry='geometry', crs=crs)


def _escribir_capas(ruta: Path, capas: dict[str, gpd.GeoDataFrame]) -> None:
    if ruta.exists():
        ruta.unlink()
    for nombre in CAPAS:
        gdf = capas[nombre]
        gdf.to_file(ruta, layer=nombre, driver='GPKG')


COLUMNAS_REVISION = ['id_estable', 'respuesta', 'comentario', 'revisor',
                     'fecha', 'version_revisada', 'vigente',
                     'motivo_invalidez']


def _rehacer_revision_sin_geom(ruta: Path) -> None:
    """Convierte una tabla creada como capa en tabla de atributos.

    Fiona crea ``geom`` y triggers de R*Tree que llaman a funciones SpatiaLite.
    El ``sqlite3`` de Python no las tiene y un UPDATE fallaría. Se eliminan
    sólo esos artefactos geométricos; las respuestas se conservan.
    """
    with sqlite3.connect(ruta) as conexion:
        triggers = [fila[0] for fila in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='revision'")]
        for nombre in triggers:
            conexion.execute(f'DROP TRIGGER IF EXISTS "{nombre}"')
        tablas = {fila[0] for fila in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for nombre in ('rtree_revision_geom', 'rtree_revision_geom_rowid',
                       'rtree_revision_geom_node',
                       'rtree_revision_geom_parent'):
            if nombre in tablas:
                conexion.execute(f'DROP TABLE IF EXISTS "{nombre}"')
        columnas = {fila[1] for fila in conexion.execute(
            'PRAGMA table_info(revision)')}
        if 'geom' in columnas:
            conexion.execute('ALTER TABLE revision DROP COLUMN geom')
        conexion.execute(
            "UPDATE gpkg_contents SET data_type='attributes', srs_id=NULL, "
            "min_x=NULL, min_y=NULL, max_x=NULL, max_y=NULL "
            "WHERE table_name='revision'")
        conexion.execute(
            "DELETE FROM gpkg_geometry_columns WHERE table_name='revision'")
        conexion.execute(
            "DELETE FROM gpkg_extensions WHERE table_name='revision'")


def _asegurar_revision(ruta: Path) -> Path:
    """Crea o migra la tabla no espacial de revisión, sin borrar respuestas."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        import pandas as pd
        import pyogrio
        vacio = pd.DataFrame({c: pd.Series(dtype='object')
                              for c in COLUMNAS_REVISION})
        pyogrio.write_dataframe(vacio, ruta, layer='revision', driver='GPKG')
        return ruta
    with sqlite3.connect(ruta) as conexion:
        fila = conexion.execute(
            "SELECT data_type FROM gpkg_contents WHERE table_name='revision'"
        ).fetchone()
    if fila and fila[0] != 'attributes':
        _rehacer_revision_sin_geom(ruta)
    with sqlite3.connect(ruta) as conexion:
        existentes = {fila[1] for fila in
                      conexion.execute('PRAGMA table_info(revision)')}
        for columna in COLUMNAS_REVISION:
            if columna not in existentes:
                conexion.execute(f'ALTER TABLE revision ADD COLUMN {columna} TEXT')
    return ruta


def _columnas_campos() -> list[str]:
    return ['id_estable', 'ruta_hash', 'campo_id', 'n_puntos', 'n_pasadas',
            'area_ha', 'perimetro_m', 'estado', 'confianza', 'motivo',
            'version_algoritmo', 'epsg_utm', 'solidez', 'compacidad',
            'densidad_puntos_ha', 'coherencia_orientacion', 'fraccion_dentro',
            'n_sesiones', 'n_dias', 't_inicio', 't_fin', 'horas_span',
            'horas_sesion', 'puntos_sesion_mediana', 'state_cobertura',
            'frac_working', 'frac_idle', 'frac_transport', 'speed_cobertura',
            'speed_p50', 'speed_p90', 'descartado_area', 'vecinos',
            'distancia_min_m', 'grupo_espacial', 'n_campos_espacial',
            'grupo_vecindad', 'n_campos_grupo',
            'candidato_fusion', 'sesiones_compartidas_max']


def exportar_version(frames: list, campos: list[CampoDetectado],
                     version: str, salida: Path,
                     cfg: dict | None = None,
                     revision_gpkg: Path | None = None) -> dict:
    cfg = _config(cfg)
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    area_descarte_ha = float(cfg.get('area_descarte_ha', 0.0) or 0.0)
    sesion_gap_s = float(cfg.get('sesion_gap_s', 7200.0) or 7200.0)
    vecindad_dist_m = float(cfg.get('vecindad_dist_m', 0.0) or 0.0)
    vecindad_candidata_m = float(cfg.get('vecindad_candidata_m', 50.0) or 50.0)
    filas, trazas, pasadas, controles, cajas = [], [], [], [], []
    resumen_maquinas = []
    zonas = set()
    for frame, lista in zip(frames, campos):
        info = _info_ruta(frame)
        zonas.add(info['epsg'])
        frame_t = anotar_sesiones(frame, info['ruta_hash'], sesion_gap_s)
        resumen_maquinas.append({
            'archivo': str(frame['Archivo'].iloc[0]),
            'ruta_hash': info['ruta_hash'],
            'epsg_utm': info['epsg'],
            **resumen_temporal(frame_t),
        })
        for campo in lista:
            geom_wgs = _orientar(_a_wgs84(campo.geometry, info['origen'],
                                          info['x0'], info['y0']))
            # La zona UTM se decide por el centro del CAMPO, no por el centro
            # de la ruta: una ruta de traslado puede cruzar de zona y dejar el
            # campo a 8° del meridiano central (error de área > 0,5 %).
            centro_campo = geom_wgs.centroid
            epsg_campo = int(_epsg_utm(centro_campo.x, centro_campo.y))
            zonas.add(epsg_campo)
            geom_utm = _a_utm(geom_wgs, epsg_campo)
            area_ha = round(float(geom_utm.area) / 10000.0, 6)
            descartado = int(area_ha < area_descarte_ha)
            tiempo = metricas_campo_tiempo(frame_t, campo.indices)
            lineas = _pasadas_wgs84(frame, campo, cfg, info)
            filas.append({
                'id_estable': campo.id_estable,
                'ruta_hash': campo.ruta_hash,
                'campo_id': int(campo.campo_id),
                'n_puntos': int(campo.n_puntos),
                'n_pasadas': len(lineas),
                # 6 decimales: con 4, un campo de 50 m² redondea ~1 %.
                'area_ha': area_ha,
                'perimetro_m': round(float(geom_utm.length), 1),
                'estado': campo.estado,
                'confianza': round(float(campo.confianza), 3),
                'motivo': '; '.join(campo.motivos),
                'version_algoritmo': campo.version_algoritmo,
                'epsg_utm': epsg_campo,
                'solidez': round(float(campo.senales.get('solidez', 0.0)), 3),
                'compacidad': round(float(campo.senales.get('compacidad', 0.0)), 3),
                'densidad_puntos_ha': round(float(campo.senales.get(
                    'densidad_puntos_ha', 0.0)), 1),
                'coherencia_orientacion': round(float(campo.senales.get(
                    'coherencia_orientacion', 0.0)), 3),
                'fraccion_dentro': round(float(campo.senales.get(
                    'fraccion_dentro', 0.0)), 3),
                'n_sesiones': tiempo.get('n_sesiones', 0),
                'n_dias': tiempo.get('n_dias', 0),
                't_inicio': tiempo.get('t_inicio', ''),
                't_fin': tiempo.get('t_fin', ''),
                'horas_span': tiempo.get('horas_span', 0.0),
                'horas_sesion': tiempo.get('horas_sesion', 0.0),
                'puntos_sesion_mediana': tiempo.get('puntos_sesion_mediana', 0),
                'state_cobertura': tiempo.get('state_cobertura', 0.0),
                'frac_working': tiempo.get('frac_working', 0.0),
                'frac_idle': tiempo.get('frac_idle', 0.0),
                'frac_transport': tiempo.get('frac_transport', 0.0),
                'speed_cobertura': tiempo.get('speed_cobertura', 0.0),
                'speed_p50': tiempo.get('speed_p50'),
                'speed_p90': tiempo.get('speed_p90'),
                'descartado_area': descartado,
                'vecinos': '', 'distancia_min_m': None,
                'grupo_espacial': '', 'n_campos_espacial': 1,
                'grupo_vecindad': '', 'n_campos_grupo': 1,
                'candidato_fusion': 0, 'sesiones_compartidas_max': 0,
                'geometry': geom_wgs,
                '_epsg': epsg_campo,
                '_geometry_utm': geom_utm,
                '_sesiones': tiempo.get('sesiones', set()),
            })
            for linea in lineas:
                pasadas.append({
                    'id_estable': campo.id_estable,
                    'ruta_hash': campo.ruta_hash,
                    'campo_id': int(campo.campo_id),
                    'n_puntos': linea['n_puntos'],
                    'largo_m': linea['largo_m'],
                    'rumbo': linea['rumbo'],
                    'epsg_utm': epsg_campo,
                    'descartado_area': descartado,
                    'geometry': linea['geometry'],
                    '_epsg': epsg_campo,
                    '_geometry_utm': _a_utm(linea['geometry'], epsg_campo),
                })
        # Traza submuestreada por ruta; el criterio queda como atributo.
        paso = max(1, int(cfg['submuestreo_trazas']))
        puntos = frame.iloc[::paso]
        coords = list(zip(*proyeccion.invertir_xy(
            puntos['X_global'].to_numpy(dtype=float),
            puntos['Y_global'].to_numpy(dtype=float), info['origen'])))
        if len(coords) >= 2:
            linea = LineString(coords)
            trazas.append({
                'ruta_hash': info['ruta_hash'],
                'n_puntos': len(puntos),
                'n_puntos_ruta': len(frame),
                'criterio': f'1 de cada {paso} puntos',
                'epsg_utm': info['epsg'],
                'geometry': linea,
                '_epsg': info['epsg'],
                '_geometry_utm': _a_utm(linea, info['epsg']),
            })
        xy = np.column_stack([info['x'], info['y']])
        minimo, maximo = xy.min(axis=0), xy.max(axis=0)
        centro = (minimo + maximo) / 2.0
        for tipo, (x, y) in (
                ('origen_0_0', (0.0, 0.0)),
                ('ancla_local', (float(info['x'][0]), float(info['y'][0]))),
                ('inicio', (float(info['x'][0]), float(info['y'][0]))),
                ('fin', (float(info['x'][-1]), float(info['y'][-1]))),
                ('centro_ruta', (float(centro[0]), float(centro[1]))),
                ('bbox_sw', (float(minimo[0]), float(minimo[1]))),
                ('bbox_ne', (float(maximo[0]), float(maximo[1])))):
            lon, lat = proyeccion.invertir_xy(x, y, info['origen'])
            p = Point(lon, lat)
            controles.append({
                'ruta_hash': info['ruta_hash'], 'tipo': tipo,
                'x_m': round(x, 3), 'y_m': round(y, 3),
                'lon': round(float(lon), 9), 'lat': round(float(lat), 9),
                'epsg_utm': info['epsg'],
                'geometry': p, '_epsg': info['epsg'],
                '_geometry_utm': _a_utm(p, info['epsg'])})
        caja_wgs = shapely_transform(
            lambda x, y: proyeccion.invertir_xy(np.asarray(x),
                                                np.asarray(y), info['origen']),
            box(float(minimo[0]), float(minimo[1]),
                float(maximo[0]), float(maximo[1])))
        cajas.append({
            'ruta_hash': info['ruta_hash'], 'epsg_utm': info['epsg'],
            'x_min': round(float(minimo[0]), 1),
            'y_min': round(float(minimo[1]), 1),
            'x_max': round(float(maximo[0]), 1),
            'y_max': round(float(maximo[1]), 1),
            'geometry': caja_wgs, '_epsg': info['epsg'],
            '_geometry_utm': _a_utm(caja_wgs, info['epsg'])})

    incluidos = [f for f in filas if not f['descartado_area']]
    descartados = [f for f in filas if f['descartado_area']]
    pares = []
    grupos = []
    if vecindad_dist_m > 0 and len(incluidos) > 1:
        entrada = [{
            'id_estable': f['id_estable'], 'geometry': f['geometry'],
            'geometry_utm': f['_geometry_utm'], 'epsg_utm': f['_epsg'],
            'area_ha': f['area_ha'], 'solidez': f['solidez'],
            'compacidad': f['compacidad'], 'ruta_hash': f['ruta_hash'],
            'estado': f['estado'], 'sesiones': f['_sesiones'],
        } for f in incluidos]
        pares, vecindad = analizar_vecindad(
            entrada, dist_junto_m=vecindad_dist_m,
            dist_candidata_m=vecindad_candidata_m)
        for fila in incluidos:
            fila.update(vecindad['campos'].get(fila['id_estable'], {}))
        for grupo in vecindad['grupos']:
            grupos.append({
                'grupo_id': grupo['grupo_id'],
                'tipo_grupo': grupo['tipo_grupo'],
                'n_campos': grupo['n_campos'],
                'area_ha': grupo['area_ha'],
                'solidez_union': grupo['solidez_union'],
                'compacidad_union': grupo['compacidad_union'],
                'candidato_fusion': grupo['candidato_fusion'],
                'rutas': grupo['rutas'],
                'ids': ';'.join(grupo['ids']),
                'geometry': _de_utm_a_wgs84(grupo['geometry_utm'],
                                            grupo['epsg_utm']),
                '_geometry_utm': grupo['geometry_utm'],
                '_epsg': grupo['epsg_utm'],
            })

    columnas_campos = _columnas_campos()
    columnas_trazas = ['ruta_hash', 'n_puntos', 'n_puntos_ruta', 'criterio',
                       'epsg_utm']
    columnas_pasadas = ['id_estable', 'ruta_hash', 'campo_id', 'n_puntos',
                        'largo_m', 'rumbo', 'epsg_utm', 'descartado_area']
    columnas_grupos = ['grupo_id', 'tipo_grupo', 'n_campos', 'area_ha',
                       'solidez_union', 'compacidad_union',
                       'candidato_fusion', 'rutas', 'ids']
    columnas_control = ['ruta_hash', 'tipo', 'x_m', 'y_m', 'lon', 'lat',
                        'epsg_utm']
    columnas_cajas = ['ruta_hash', 'epsg_utm', 'x_min', 'y_min', 'x_max',
                      'y_max']

    def capas_utm(items, columnas, epsg):
        datos = [{k: v for k, v in f.items() if k != 'geometry'}
                 | {'geometry': f['_geometry_utm']}
                 for f in items if f['_epsg'] == epsg]
        return gpd.GeoDataFrame(datos, columns=columnas + ['geometry'],
                                geometry='geometry', crs=f'EPSG:{epsg}')

    def conjunto_utm(epsg):
        # El origen (0°, 0°) no es representable en una UTM concreta (pyproj
        # devuelve infinito). Se conserva en el GPKG 4326 y en los atributos
        # del resto de puntos de control; en la UTM se omiten esos puntos.
        controles_utm = [f for f in controles if f['tipo'] != 'origen_0_0']
        return {
            'campos': capas_utm(incluidos, columnas_campos, epsg),
            'trazas': capas_utm(trazas, columnas_trazas, epsg),
            'pasadas': capas_utm(pasadas, columnas_pasadas, epsg),
            'puntos_control': capas_utm(controles_utm, columnas_control, epsg),
            'cajas_ruta': capas_utm(cajas, columnas_cajas, epsg),
            'campos_descartados': capas_utm(descartados, columnas_campos, epsg),
            'grupos_vecindad': capas_utm(grupos, columnas_grupos, epsg),
        }

    nombre = etiqueta_archivo(version)
    ruta_wgs = salida / f'campos_v{nombre}_4326.gpkg'
    capas_wgs = {
        'campos': _gdf(incluidos, 'EPSG:4326', columnas_campos),
        'trazas': _gdf(trazas, 'EPSG:4326', columnas_trazas),
        'pasadas': _gdf(pasadas, 'EPSG:4326', columnas_pasadas),
        'puntos_control': _gdf(controles, 'EPSG:4326', columnas_control),
        'cajas_ruta': _gdf(cajas, 'EPSG:4326', columnas_cajas),
        'campos_descartados': _gdf(descartados, 'EPSG:4326',
                                   columnas_campos),
        'grupos_vecindad': _gdf(grupos, 'EPSG:4326', columnas_grupos),
    }
    _escribir_capas(ruta_wgs, capas_wgs)
    qml = salida / f'campos_v{nombre}.qml'
    _escribir_estilos(ruta_wgs, qml)

    rutas_utm = {}
    for epsg in sorted(zonas):
        ruta = salida / f'campos_v{nombre}_utm{epsg}.gpkg'
        _escribir_capas(ruta, conjunto_utm(epsg))
        _escribir_estilos(ruta, qml)
        rutas_utm[int(epsg)] = ruta

    csv_ruta = salida / f'campos_v{nombre}.csv'
    with open(csv_ruta, 'w', newline='', encoding='utf-8') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas_campos)
        escritor.writeheader()
        for fila in incluidos:
            escritor.writerow({k: fila.get(k) for k in columnas_campos})
    descartados_csv = salida / f'campos_descartados_v{nombre}.csv'
    with open(descartados_csv, 'w', newline='', encoding='utf-8') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas_campos)
        escritor.writeheader()
        for fila in descartados:
            escritor.writerow({k: fila.get(k) for k in columnas_campos})
    vecindad_csv = salida / f'vecindad_v{nombre}.csv'
    columnas_vecindad = ['id_a', 'id_b', 'ruta_a', 'ruta_b', 'misma_ruta',
                         'distancia_m', 'nivel', 'area_a_ha', 'area_b_ha',
                         'area_union_ha', 'solidez_union', 'compacidad_union',
                         'delta_solidez', 'delta_compacidad',
                         'sesiones_compartidas', 'candidato_fusion',
                         'estado_a', 'estado_b']
    with open(vecindad_csv, 'w', newline='', encoding='utf-8') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas_vecindad)
        escritor.writeheader()
        for fila in pares:
            escritor.writerow({k: fila.get(k) for k in columnas_vecindad})

    # Hoja de revisión de una fila por campo; las respuestas cerradas se
    # rellenan preferentemente en la tabla revision_campos.gpkg de QGIS.
    hoja = salida / f'revision_v{nombre}.csv'
    columnas_hoja = ['id_estable', 'ruta_hash', 'estado', 'area_ha',
                     'respuesta', 'comentario', 'revisor', 'fecha',
                     'version_revisada']
    with open(hoja, 'w', newline='', encoding='utf-8') as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas_hoja)
        escritor.writeheader()
        for fila in incluidos:
            escritor.writerow({'id_estable': fila['id_estable'],
                               'ruta_hash': fila['ruta_hash'],
                               'estado': fila['estado'],
                               'area_ha': fila['area_ha'],
                               'respuesta': '', 'comentario': '',
                               'revisor': '', 'fecha': '',
                               'version_revisada': version})

    revision = _asegurar_revision(
        Path(revision_gpkg) if revision_gpkg else salida / 'revision_campos.gpkg')
    verificacion = verificar_posicion(frames, incluidos)

    return {
        'version': version,
        'epsg_utm': next(iter(rutas_utm)) if len(rutas_utm) == 1 else None,
        'epsg_utms': sorted(rutas_utm),
        'gpkg_4326': str(ruta_wgs),
        'gpkg_utm': str(next(iter(rutas_utm.values()))) if len(rutas_utm) == 1 else None,
        'gpkg_utm_por_zona': {k: str(v) for k, v in rutas_utm.items()},
        'qml': str(qml), 'csv': str(csv_ruta),
        'csv_descartados': str(descartados_csv),
        'csv_vecindad': str(vecindad_csv),
        'hoja_revision': str(hoja),
        'revision_gpkg': str(revision),
        'n_campos': len(incluidos),
        'n_descartados_area': len(descartados),
        'n_grupos_vecindad': sum(1 for g in grupos
                                 if g['tipo_grupo'] == 'SESION'),
        'n_grupos_espaciales': sum(1 for g in grupos
                                   if g['tipo_grupo'] == 'ESPACIAL'),
        'n_pares_vecindad': len(pares),
        'n_trazas': len(trazas),
        'n_pasadas': len(pasadas),
        'resumen_tiempo': resumen_maquinas,
        'verificacion': verificacion,
    }


def verificar_posicion(frames: list, filas: list[dict]) -> dict:
    """Comprobaciones V0 que el usuario repetirá en QGIS.

    · segmento UTM vs distancia original x_m/y_m (error < 1 %);
    · área elipsoidal WGS84 vs ``area_ha`` (error < 0,5 %).
    """
    geod = Geod(ellps='WGS84')
    peor_segmento = 0.0
    peor_area = 0.0
    detalle = []
    excluidas = []
    for frame in frames:
        info = _info_ruta(frame)
        xg, yg = info['x'], info['y']
        if len(xg) < 2:
            continue
        # La proyección equirectangular usa la latitud del primer punto como
        # escala fija. En un traslado de cientos de km esa aproximación deja
        # de ser local y la distancia UTM no puede coincidir con x_m/y_m.
        # Se excluye de la comprobación y se informa; los campos son locales.
        extension = max(float(np.ptp(xg)), float(np.ptp(yg)))
        if extension > 50_000.0:
            excluidas.append({'ruta_hash': info['ruta_hash'],
                              'extension_m': round(extension, 1),
                              'motivo': 'ruta no local (traslado); la escala '
                                        'equirectangular fija no aplica'})
            continue
        for i in np.linspace(0, len(xg) - 2, min(5, len(xg) - 1),
                             dtype=int):
            d_original = float(np.hypot(xg[i + 1] - xg[i], yg[i + 1] - yg[i]))
            if d_original <= 0:
                continue
            lon1, lat1 = proyeccion.invertir_xy(xg[i], yg[i], info['origen'])
            lon2, lat2 = proyeccion.invertir_xy(xg[i + 1], yg[i + 1],
                                                info['origen'])
            p1 = _a_utm(Point(lon1, lat1), info['epsg'])
            p2 = _a_utm(Point(lon2, lat2), info['epsg'])
            error = abs(p1.distance(p2) - d_original) / d_original
            peor_segmento = max(peor_segmento, error)
            detalle.append({'ruta_hash': info['ruta_hash'],
                            'tipo': 'segmento', 'error_rel': round(error, 6)})
    for fila in filas:
        geom = fila.get('geometry')
        if geom is None or geom.geom_type not in ('Polygon', 'MultiPolygon'):
            continue
        area_elipsoide, _ = geod.geometry_area_perimeter(geom)
        area_ha = fila.get('area_ha', 0.0)
        if area_ha <= 0:
            continue
        error = abs(abs(area_elipsoide) / 10000.0 - area_ha) / area_ha
        peor_area = max(peor_area, error)
        detalle.append({'id_estable': fila.get('id_estable'),
                        'tipo': 'area', 'error_rel': round(error, 6)})
    return {'max_error_segmento_rel': round(peor_segmento, 6),
            'max_error_area_rel': round(peor_area, 6),
            'segmento_ok': peor_segmento < 0.01,
            'area_ok': peor_area < 0.005,
            'rutas_excluidas': excluidas,
            'detalle': detalle}


def comparar_versiones(ruta_a: Path, ruta_b: Path) -> gpd.GeoDataFrame:
    """Compara campos de dos GPKG por id y por IoU; devuelve capa de diferencias."""
    from .metricas import iou
    a = gpd.read_file(ruta_a, layer='campos')
    b = gpd.read_file(ruta_b, layer='campos')
    por_id_a = {str(r.id_estable): r for r in a.itertuples()}
    por_id_b = {str(r.id_estable): r for r in b.itertuples()}
    filas = []
    for key in sorted(set(por_id_a) | set(por_id_b)):
        if key in por_id_a and key in por_id_b:
            filas.append({'id_estable': key, 'tipo': 'IGUAL',
                          'iou': round(float(iou(por_id_a[key].geometry,
                                                 por_id_b[key].geometry)), 3),
                          'geometry': por_id_b[key].geometry})
        elif key in por_id_b:
            filas.append({'id_estable': key, 'tipo': 'NUEVO', 'iou': None,
                          'geometry': por_id_b[key].geometry})
        else:
            filas.append({'id_estable': key, 'tipo': 'DESAPARECIDO',
                          'iou': None, 'geometry': por_id_a[key].geometry})
    for fila_a in a.itertuples():
        solapados = [f for f in b.itertuples()
                     if iou(fila_a.geometry, f.geometry) >= 0.10]
        if len(solapados) > 1:
            filas.append({'id_estable': str(fila_a.id_estable),
                          'tipo': 'PARTIDO', 'iou': None,
                          'geometry': fila_a.geometry})
    for fila_b in b.itertuples():
        cubiertos = [f for f in a.itertuples()
                     if iou(f.geometry, fila_b.geometry) >= 0.10]
        if len(cubiertos) > 1:
            filas.append({'id_estable': str(fila_b.id_estable),
                          'tipo': 'FUSIONADO', 'iou': None,
                          'geometry': fila_b.geometry})
    return gpd.GeoDataFrame(filas, geometry='geometry', crs=b.crs)


def agregar_diferencias(gpkg: Path, diferencias: gpd.GeoDataFrame) -> None:
    if diferencias is None or len(diferencias) == 0:
        return
    import fiona
    if 'diferencias' in fiona.listlayers(gpkg):
        with sqlite3.connect(gpkg) as conexion:
            conexion.execute('DROP TABLE diferencias')
    diferencias.to_file(gpkg, layer='diferencias', driver='GPKG')


COLUMNAS_PARES_REVISION = [
    'id_par', 'respuesta', 'comentario', 'revisor', 'fecha',
    'version_revisada', 'vigente', 'motivo_invalidez']

def _muestra_campos(campos: list, semilla: int = 20261107) -> set[str]:
    cuotas = {'CAMPO_FRAGMENTO': 40, 'DUDOSO': 20, 'CAMPO_PROBABLE': 10,
              'NO_ES_CAMPO': 10}
    rng = random.Random(semilla)
    elegidos = set()
    for estado, cuota in cuotas.items():
        disponibles = sorted([c.id_estable for c in campos
                              if c.estado == estado])
        elegidos.update(rng.sample(disponibles,
                                   min(cuota, len(disponibles))))
    # Completar hasta 80 con el resto, sin cambiar la estratificación pedida.
    resto = sorted([c.id_estable for c in campos
                    if c.id_estable not in elegidos])
    if len(elegidos) < 80 and resto:
        elegidos.update(rng.sample(resto, min(80 - len(elegidos), len(resto))))
    return elegidos

def _asegurar_revision_pares(ruta: Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        import pyogrio
        vacio = pd.DataFrame({c: pd.Series(dtype='object')
                              for c in COLUMNAS_PARES_REVISION})
        pyogrio.write_dataframe(vacio, ruta, layer='revision_pares',
                                driver='GPKG')
        return ruta
    with sqlite3.connect(ruta) as conexion:
        tablas = {f[0] for f in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    if 'revision_pares' not in tablas:
        import pyogrio
        vacio = pd.DataFrame({c: pd.Series(dtype='object')
                              for c in COLUMNAS_PARES_REVISION})
        pyogrio.write_dataframe(vacio, ruta, layer='revision_pares',
                                driver='GPKG')
    else:
        with sqlite3.connect(ruta) as conexion:
            existentes = {f[1] for f in conexion.execute(
                'PRAGMA table_info(revision_pares)')}
            for columna in COLUMNAS_PARES_REVISION:
                if columna not in existentes:
                    conexion.execute(
                        f'ALTER TABLE revision_pares ADD COLUMN {columna} TEXT')
    return ruta

def comparar_huellas(referencia_gpkg: Path, actual: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Diferencias por huella, no por id: referencia frente a actual."""
    referencia = gpd.read_file(referencia_gpkg, layer='campos')
    if referencia.crs != actual.crs:
        actual = actual.to_crs(referencia.crs)
    arbol_actual = STRtree(list(actual.geometry))
    arbol_referencia = STRtree(list(referencia.geometry))
    filas = []
    for f2 in referencia.itertuples():
        ids = [int(j) for j in arbol_actual.query(f2.geometry)]
        overlaps = []
        for j in ids:
            f3 = actual.iloc[j]
            inter = f2.geometry.intersection(f3.geometry)
            if not inter.is_empty and inter.area > 0:
                union = f2.geometry.union(f3.geometry).area
                overlaps.append((j, inter.area / f2.geometry.area,
                                 inter.area / union if union else 0.0))
        overlaps.sort(key=lambda x: -x[1])
        if not overlaps:
            filas.append({'tipo': 'DESAPARECIDO', 'id_referencia': f2.id_estable,
                          'id_actual': '', 'n_partes': 0, 'n_referencia': 1,
                          'iou_max': 0.0, 'area_referencia_ha': f2.area_ha,
                          'area_actual_ha': 0.0, 'geometry': f2.geometry})
            continue
        partes = [o for o in overlaps if o[1] >= 0.10]
        if len(partes) == 1 and partes[0][2] >= 0.50:
            j = partes[0][0]
            filas.append({'tipo': 'IGUAL', 'id_referencia': f2.id_estable,
                          'id_actual': actual.iloc[j].id_estable, 'n_partes': 1,
                          'n_referencia': 1, 'iou_max': round(partes[0][2], 3),
                          'area_referencia_ha': f2.area_ha,
                          'area_actual_ha': actual.iloc[j].area_ha,
                          'geometry': actual.iloc[j].geometry})
        else:
            geoms = [actual.iloc[o[0]].geometry for o in partes] or [f2.geometry]
            filas.append({'tipo': 'PARTIDO', 'id_referencia': f2.id_estable,
                          'id_actual': ';'.join(actual.iloc[o[0]].id_estable
                                            for o in partes),
                          'n_partes': len(partes),
                          'n_referencia': 1,
                          'iou_max': round(max(o[2] for o in overlaps), 3),
                          'area_referencia_ha': f2.area_ha,
                          'area_actual_ha': round(sum(actual.iloc[o[0]].area_ha
                                                  for o in partes), 4),
                          'geometry': unary_union(geoms)})
    # Fusiones: un campo actual cubierto por más de un campo referencia.
    for f3 in actual.itertuples():
        ids = [int(j) for j in arbol_referencia.query(f3.geometry)]
        cubiertos = []
        for j in ids:
            f2 = referencia.iloc[j]
            inter = f3.geometry.intersection(f2.geometry)
            if not inter.is_empty and inter.area > 0:
                if inter.area / f3.geometry.area >= 0.10:
                    cubiertos.append(f2.id_estable)
        if len(cubiertos) > 1:
            filas.append({'tipo': 'FUSIONADO', 'id_referencia': ';'.join(cubiertos),
                          'id_actual': f3.id_estable, 'n_partes': 1,
                          'n_referencia': len(cubiertos), 'iou_max': 0.0,
                          'area_referencia_ha': round(sum(referencia[referencia.id_estable == x].area_ha.iloc[0]
                                                  for x in cubiertos), 4),
                          'area_actual_ha': f3.area_ha, 'geometry': f3.geometry})
    return gpd.GeoDataFrame(filas, geometry='geometry', crs=actual.crs)
