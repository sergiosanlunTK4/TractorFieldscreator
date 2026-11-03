"""Exportación con trazas cortadas, dispersos y pares contiguos."""
from __future__ import annotations

import csv
from pathlib import Path
import random
import sqlite3

try:
    import fiona
except ImportError:
    fiona = None
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box
from shapely.ops import transform as shapely_transform

from . import proyeccion
from .unidades import Campo
from .utils import (
    _a_utm, _asegurar_revision, _asegurar_revision_pares, _escribir_estilos,
    _gdf, _hash, _info_ruta, _muestra_campos, comparar_huellas,
    etiqueta_archivo, verificar_posicion)
from .unidades import Unidad

CAPAS = ('campos', 'campos_descartados', 'trayectos_dispersos', 'unidades',
         'trazas', 'trazas_puntos', 'pares_contiguos', 'puntos_fuera_mexico',
         'puntos_control', 'cajas_ruta')


def _columnas_campos() -> list[str]:
    return ['id_estable', 'ruta_hash', 'rutas_hash', 'campo_id', 'n_puntos',
            'n_unidades', 'n_dias', 'n_maquinas', 'n_sesiones', 'horas',
            't_inicio', 't_fin', 'area_ha', 'perimetro_m', 'estado',
            'confianza', 'motivo', 'causa_fragmento', 'categoria',
            'requiere_revision', 'cuenta_ha', 'diagnostico_grande',
            'parece_campo', 'subcategoria', 'metrica_detonante',
            'cuenta_ha_valida', 'version_algoritmo', 'epsg_utm', 'solidez',
            'compacidad', 'aspect_ratio', 'ancho_mbb', 'densidad_puntos_ha',
            'coherencia_orientacion',
            'max_gap_m', 'orientacion', 'speed_p50', 'speed_p90',
            'state_cobertura', 'frac_working', 'frac_idle', 'frac_transport',
            'unidades', 'descartado_area', 'en_muestra']


def _columnas_unidades() -> list[str]:
    return ['id_unidad', 'ruta_hash', 'archivo', 'n_puntos', 't_inicio',
            't_fin', 'sesion_id', 'area_ha', 'perimetro_m', 'solidez',
            'compacidad', 'orientacion', 'coherencia', 'densidad_puntos_ha',
            'max_gap_m', 'speed_p50', 'speed_p90', 'state_cobertura',
            'frac_working', 'frac_idle', 'frac_transport', 'tipo', 'motivo',
            'epsg_utm']


def _columnas_pares() -> list[str]:
    return ['id_par', 'id_visita_a', 'id_visita_b', 'ruta_hash', 'gap_s',
            'dist_m', 'vel_implicita_kmh', 'solape', 'dif_orientacion_deg',
            'campo_a', 'campo_b', 'frac_a', 'frac_b', 'clasificacion',
            'motivo', 'en_muestra', 'epsg_utm']


def _capa_utm(filas, columnas, epsg):
    datos = [{k: v for k, v in f.items() if k != 'geometry'}
             | {'geometry': f['_geometry_utm']}
             for f in filas if int(f.get('_epsg', -1)) == int(epsg)]
    return gpd.GeoDataFrame(datos, columns=columnas + ['geometry'],
                            geometry='geometry', crs=f'EPSG:{epsg}')


def _escribir(ruta: Path, capas: dict) -> None:
    if ruta.exists():
        ruta.unlink()
    for nombre in CAPAS:
        if nombre in capas and capas[nombre] is not None:
            capas[nombre].to_file(ruta, layer=nombre, driver='GPKG')


def _traza_unidad(unidad: Unidad, frame: pd.DataFrame) -> LineString:
    info = _info_ruta(frame)
    x0 = float(frame['X_global'].iloc[0] - frame['X'].iloc[0])
    y0 = float(frame['Y_global'].iloc[0] - frame['Y'].iloc[0])
    coords = list(zip(*proyeccion.invertir_xy(
        unidad.xy[:, 0] + x0, unidad.xy[:, 1] + y0, info['origen'])))
    return LineString(coords)


def exportar(frames: list, campos: list[Campo], unidades: list[Unidad],
                fuera: list[dict], version: str, salida: Path,
                cfg: dict | None = None, revision_gpkg: Path | None = None,
                anterior_gpkg: Path | None = None,
                pares: list[dict] | None = None) -> dict:
    cfg = cfg or {}
    nombre = etiqueta_archivo(version)
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    area_descarte = float(cfg.get('area_descarte_ha', 0.10) or 0.0)
    campos_ok = [c for c in campos if c.estado != 'TRAYECTO_DISPERSO']
    muestra = _muestra_campos([c for c in campos_ok if c.area_ha >= area_descarte])
    filas, dispersos, descartados = [], [], []
    for campo in campos:
        fila = campo.to_dict()
        fila['descartado_area'] = int(campo.area_ha < area_descarte
                                      and campo.estado != 'TRAYECTO_DISPERSO')
        fila['en_muestra'] = int(campo.id_estable in muestra)
        fila['geometry'] = campo.geometry
        fila['_geometry_utm'] = campo.geometry_utm
        fila['_epsg'] = campo.epsg_utm
        if campo.estado == 'TRAYECTO_DISPERSO':
            dispersos.append(fila)
        elif fila['descartado_area']:
            descartados.append(fila)
        else:
            filas.append(fila)

    unidades_rows = []
    for u in unidades:
        unidades_rows.append({
            'id_unidad': u.id_unidad, 'ruta_hash': u.ruta_hash,
            'archivo': u.archivo, 'n_puntos': u.n_puntos,
            't_inicio': u.t_inicio.isoformat() if u.t_inicio is not None else '',
            't_fin': u.t_fin.isoformat() if u.t_fin is not None else '',
            'sesion_id': u.sesion_id, 'area_ha': round(u.area_ha, 6),
            'perimetro_m': round(u.perimetro_m, 1),
            'solidez': round(u.solidez, 3), 'compacidad': round(u.compacidad, 3),
            'orientacion': round(u.orientacion, 1),
            'coherencia': round(u.coherencia, 3),
            'densidad_puntos_ha': round(u.densidad_puntos_ha, 1),
            'max_gap_m': round(u.max_gap_m, 1), 'speed_p50': u.speed_p50,
            'speed_p90': u.speed_p90, 'state_cobertura': u.state_cobertura,
            'frac_working': u.frac_working, 'frac_idle': u.frac_idle,
            'frac_transport': u.frac_transport, 'tipo': u.tipo,
            'motivo': u.motivo, 'epsg_utm': u.epsg_utm,
            'geometry': u.geometry_wgs84, '_geometry_utm': u.geometry_utm,
            '_epsg': u.epsg_utm,
        })

    frames_por_archivo = {str(f['Archivo'].iloc[0]): f for f in frames}
    trazas, trazas_puntos, controles, cajas = [], [], [], []
    paso = max(1, int(cfg.get('submuestreo_trazas', 20)))
    for u in unidades:
        frame = frames_por_archivo.get(u.archivo)
        if frame is None or len(u.xy) < 2:
            continue
        linea = _traza_unidad(u, frame)
        info = _info_ruta(frame)
        trazas.append({'id_unidad': u.id_unidad, 'ruta_hash': u.ruta_hash,
                       'n_puntos': u.n_puntos, 't_inicio': u.t_inicio,
                       't_fin': u.t_fin, 'criterio': 'unidad temporal',
                       'epsg_utm': info['epsg'], 'geometry': linea,
                       '_epsg': info['epsg'],
                       '_geometry_utm': _a_utm(linea, info['epsg'])})
        x0 = float(frame['X_global'].iloc[0] - frame['X'].iloc[0])
        y0 = float(frame['Y_global'].iloc[0] - frame['Y'].iloc[0])
        for i in range(0, len(u.xy), paso):
            lon, lat = proyeccion.invertir_xy(u.xy[i, 0] + x0,
                                              u.xy[i, 1] + y0, info['origen'])
            p = Point(lon, lat)
            trazas_puntos.append({
                'id_unidad': u.id_unidad, 'ruta_hash': u.ruta_hash,
                'timestamp': str(u.tiempos[i]) if len(u.tiempos) > i else '',
                't_s': None, 'epsg_utm': info['epsg'],
                'geometry': p, '_epsg': info['epsg'],
                '_geometry_utm': _a_utm(p, info['epsg'])})
    for frame in frames:
        info = _info_ruta(frame)
        xy = np.column_stack([info['x'], info['y']])
        minimo, maximo = xy.min(axis=0), xy.max(axis=0)
        centro = (minimo + maximo) / 2.0
        for tipo, (x, y) in (
                ('origen_0_0', (0.0, 0.0)),
                ('inicio', (float(info['x'][0]), float(info['y'][0]))),
                ('fin', (float(info['x'][-1]), float(info['y'][-1]))),
                ('centro_ruta', (float(centro[0]), float(centro[1]))),
                ('bbox_sw', (float(minimo[0]), float(minimo[1]))),
                ('bbox_ne', (float(maximo[0]), float(maximo[1])))):
            lon, lat = proyeccion.invertir_xy(x, y, info['origen'])
            p = Point(lon, lat)
            controles.append({'ruta_hash': info['ruta_hash'], 'tipo': tipo,
                              'x_m': round(x, 3), 'y_m': round(y, 3),
                              'lon': round(float(lon), 9),
                              'lat': round(float(lat), 9),
                              'epsg_utm': info['epsg'], 'geometry': p,
                              '_epsg': info['epsg'],
                              '_geometry_utm': _a_utm(p, info['epsg'])})
        caja = shapely_transform(
            lambda x, y: proyeccion.invertir_xy(np.asarray(x),
                                                np.asarray(y), info['origen']),
            box(float(minimo[0]), float(minimo[1]),
                float(maximo[0]), float(maximo[1])))
        cajas.append({'ruta_hash': info['ruta_hash'],
                      'epsg_utm': info['epsg'],
                      'x_min': round(float(minimo[0]), 1),
                      'y_min': round(float(minimo[1]), 1),
                      'x_max': round(float(maximo[0]), 1),
                      'y_max': round(float(maximo[1]), 1),
                      'geometry': caja, '_epsg': info['epsg'],
                      '_geometry_utm': _a_utm(caja, info['epsg'])})

    pares = pares or []
    for p in pares:
        p['epsg_utm'] = p['_epsg']
        p['_geometry_utm'] = _a_utm(p['geometry'], int(p['_epsg']))

    col_campos = _columnas_campos()
    col_unidades = _columnas_unidades()
    col_pares = _columnas_pares()
    col_trazas = ['id_unidad', 'ruta_hash', 'n_puntos', 't_inicio', 't_fin',
                  'criterio', 'epsg_utm']
    col_puntos = ['id_unidad', 'ruta_hash', 'timestamp', 't_s', 'epsg_utm']
    col_control = ['ruta_hash', 'tipo', 'x_m', 'y_m', 'lon', 'lat', 'epsg_utm']
    col_cajas = ['ruta_hash', 'epsg_utm', 'x_min', 'y_min', 'x_max', 'y_max']
    zonas = {int(f['epsg_utm']) for f in filas + descartados + dispersos}
    zonas |= {int(u.epsg_utm) for u in unidades if u.epsg_utm}
    zonas |= {int(_info_ruta(f)['epsg']) for f in frames}

    def capas_wgs():
        return {
            'campos': _gdf(filas, 'EPSG:4326', col_campos),
            'campos_descartados': _gdf(descartados, 'EPSG:4326', col_campos),
            'trayectos_dispersos': _gdf(dispersos, 'EPSG:4326', col_campos),
            'unidades': _gdf(unidades_rows, 'EPSG:4326', col_unidades),
            'trazas': _gdf(trazas, 'EPSG:4326', col_trazas),
            'trazas_puntos': _gdf(trazas_puntos, 'EPSG:4326', col_puntos),
            'pares_contiguos': _gdf(pares, 'EPSG:4326', col_pares),
            'puntos_fuera_mexico': _gdf(fuera, 'EPSG:4326',
                                        ['ruta_hash', 'timestamp', 'lon',
                                         'lat', 'motivo']),
            'puntos_control': _gdf(controles, 'EPSG:4326', col_control),
            'cajas_ruta': _gdf(cajas, 'EPSG:4326', col_cajas),
        }

    def capas_utm(epsg):
        return {
            'campos': _capa_utm(filas, col_campos, epsg),
            'campos_descartados': _capa_utm(descartados, col_campos, epsg),
            'trayectos_dispersos': _capa_utm(dispersos, col_campos, epsg),
            'unidades': _capa_utm(unidades_rows, col_unidades, epsg),
            'trazas': _capa_utm(trazas, col_trazas, epsg),
            'trazas_puntos': _capa_utm(trazas_puntos, col_puntos, epsg),
            'pares_contiguos': _capa_utm(pares, col_pares, epsg),
            'puntos_fuera_mexico': gpd.GeoDataFrame(
                [], geometry=[], crs=f'EPSG:{epsg}'),
            'puntos_control': _capa_utm(
                [c for c in controles if c['tipo'] != 'origen_0_0'],
                col_control, epsg),
            'cajas_ruta': _capa_utm(cajas, col_cajas, epsg),
        }

    ruta_wgs = salida / f'campos_v{nombre}_4326.gpkg'
    _escribir(ruta_wgs, capas_wgs())
    qml = salida / f'campos_v{nombre}.qml'
    _escribir_estilos(ruta_wgs, qml)
    rutas_utm = {}
    for epsg in sorted(zonas):
        ruta = salida / f'campos_v{nombre}_utm{epsg}.gpkg'
        _escribir(ruta, capas_utm(epsg))
        _escribir_estilos(ruta, qml)
        rutas_utm[int(epsg)] = ruta

    for nombre_csv, rows, cols in (
            (f'campos_v{nombre}.csv', filas, col_campos),
            (f'campos_descartados_v{nombre}.csv', descartados, col_campos),
            (f'trayectos_dispersos_v{nombre}.csv', dispersos, col_campos),
            (f'unidades_v{nombre}.csv', unidades_rows, col_unidades),
            (f'pares_contiguos_v{nombre}.csv', pares, col_pares)):
        with open(salida / nombre_csv, 'w', newline='', encoding='utf-8') as a:
            escritor = csv.DictWriter(a, fieldnames=cols)
            escritor.writeheader()
            for fila in rows:
                escritor.writerow({k: fila.get(k) for k in cols})
    revision = _asegurar_revision(
        Path(revision_gpkg) if revision_gpkg else salida / 'revision_campos.gpkg')
    _asegurar_revision_pares(revision)
    diferencias = 0
    if anterior_gpkg is not None and Path(anterior_gpkg).is_file() and filas:
        try:
            actual = gpd.read_file(ruta_wgs, layer='campos')
            dif = comparar_huellas(Path(anterior_gpkg), actual)
            for ruta in [ruta_wgs] + list(rutas_utm.values()):
                d = dif
                if 'utm' in ruta.name:
                    epsg = int(ruta.stem.split('utm')[-1])
                    d = dif.to_crs(epsg)
                tiene_dif = False
                if fiona is not None:
                    try:
                        tiene_dif = 'diferencias' in fiona.listlayers(ruta)
                    except Exception:
                        tiene_dif = False
                if not tiene_dif:
                    try:
                        with sqlite3.connect(ruta) as con:
                            cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='diferencias'")
                            tiene_dif = bool(cur.fetchone())
                    except Exception:
                        tiene_dif = False
                if tiene_dif:
                    with sqlite3.connect(ruta) as con:
                        con.execute('DROP TABLE diferencias')
                d.to_file(ruta, layer='diferencias', driver='GPKG')
            diferencias = len(dif)
        except Exception as error:  # noqa: BLE001
            print('Aviso: no se pudo comparar la versi?n anterior:', error)
    verificacion = verificar_posicion(frames, filas)
    return {
        'version': version, 'epsg_utms': sorted(rutas_utm),
        'gpkg_4326': str(ruta_wgs),
        'gpkg_utm_por_zona': {k: str(v) for k, v in rutas_utm.items()},
        'qml': str(qml), 'revision_gpkg': str(revision),
        'n_campos': len(filas), 'n_descartados_area': len(descartados),
        'n_dispersos': len(dispersos), 'n_unidades': len(unidades_rows),
        'n_pares': len(pares),
        'n_fuera_mexico': len(fuera),
        'verificacion': verificacion, 'diferencias': diferencias,
        'area_confirmada_ha': round(sum(c.cuenta_ha for c in campos_ok), 2),
        'area_pendiente_grande_ha': round(sum(c.area_ha for c in campos_ok
                                              if c.requiere_revision), 2),
    }
