"""P1: evaluación de polígonos contra fronteras de referencia.

No ejecuta datos reales. Acepta GeoJSON, GeoPackage o Shapefile en CUALQUIER
CRS declarado (geográfico o proyectado), lo reproyecta a la UTM que
corresponde y sólo falla si el archivo no declara CRS.

  · valida CRS, anillos y auto-intersecciones;
  · empareja por IoU máximo (Hungarian);
  · calcula IoU, error de área con signo, Hausdorff P95;
  · reporta fracciones de campos fusionados, partidos, no detectados y extra;
  · agrega intervalos de Wilson cuando n < 30.

Uso:
    from .evaluacion import evaluar_geojson
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import orient
from shapely.validation import explain_validity

from ._compat import _epsg_utm
from . import metricas


def wilson_interval(k: int, n: int, z: float = 1.96) -> dict:
    """Intervalo de Wilson 95 % para una proporción; n pequeño es indicativo."""
    if n <= 0:
        return {'k': k, 'n': n, 'p': 0.0, 'bajo': 0.0, 'alto': 0.0}
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {'k': k, 'n': n, 'p': round(p, 3),
            'bajo': round(max(0.0, centro - margen), 3),
            'alto': round(min(1.0, centro + margen), 3)}


def _poligonos(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return []


def validar_geometrias(geometrias, etiqueta: str = 'capa') -> list[dict]:
    errores = []
    for i, geom in enumerate(geometrias):
        if geom is None or geom.is_empty:
            errores.append({'indice': i, 'error': 'VACIA', 'detalle': etiqueta})
            continue
        if not geom.is_valid:
            errores.append({'indice': i, 'error': 'AUTOINTERSECCION',
                            'detalle': explain_validity(geom)})
            continue
        for poly in _poligonos(geom):
            if not poly.exterior.is_ccw:
                errores.append({'indice': i, 'error': 'ANILLO_EXTERIOR_HORARIO',
                                'detalle': 'el exterior debe ser CCW'})
            for anillo in poly.interiors:
                if anillo.is_ccw:
                    errores.append({'indice': i, 'error': 'HUECO_ANTIHORARIO',
                                    'detalle': 'los huecos deben ser CW'})
    return errores


def validar_o_error(geometrias, etiqueta: str = 'capa') -> None:
    errores = validar_geometrias(geometrias, etiqueta)
    if errores:
        raise ValueError(f'{etiqueta} inválida: {errores[:3]}')


def _orientar(geom):
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type in ('Polygon', 'MultiPolygon'):
        return orient(geom, 1.0)
    return geom


def _epsg_utm_de_capa(gdf) -> int:
    """Zona UTM a partir del centro de la capa, en WGS84."""
    geografico = gdf.to_crs(4326)
    minx, miny, maxx, maxy = geografico.total_bounds
    lon = float((minx + maxx) / 2.0)
    lat = float((miny + maxy) / 2.0)
    return int(_epsg_utm(lon, lat))


def cargar_geojson(ruta: str | Path, capa: str | None = None,
                   epsg: int | None = None):
    """Carga GeoJSON/GPKG/Shapefile y lo lleva a UTM.

    Acepta cualquier CRS declarado. Si no hay CRS, falla: no se asume ninguno.
    Si ``epsg`` se indica, se usa esa zona (para alinear dos capas).
    """
    import geopandas as gpd
    ruta = Path(ruta)
    gdf = gpd.read_file(ruta, layer=capa) if capa else gpd.read_file(ruta)
    if gdf.crs is None:
        raise ValueError(f'{ruta.name}: la capa no declara CRS; no se asume '
                         'ninguno. Declara el CRS y vuelve a exportar.')
    if len(gdf) == 0:
        raise ValueError(f'{ruta.name}: la capa no tiene geometrías')
    if epsg is not None:
        destino = int(epsg)
    else:
        actual = gdf.crs.to_epsg()
        # Si ya viene en una UTM, se conserva; si viene en geográfico, 3857 u
        # otra proyección, se lleva a la UTM de su centro.
        if actual and 32600 <= int(actual) <= 32799:
            destino = int(actual)
        else:
            destino = _epsg_utm_de_capa(gdf)
    gdf = gdf.to_crs(f'EPSG:{destino}')
    gdf.geometry = gdf.geometry.apply(_orientar)
    validar_o_error(list(gdf.geometry), ruta.name)
    return gdf


def _solape(detectado, referencia) -> float:
    if referencia.area <= 0:
        return 0.0
    return float(detectado.intersection(referencia).area / referencia.area)


def evaluar_poligonos(detectados, referencias,
                      umbral_iou: float = 0.10) -> dict:
    detectados = list(detectados)
    referencias = list(referencias)
    validar_o_error(detectados, 'detectados')
    validar_o_error(referencias, 'referencias')
    pares = metricas.emparejar(detectados, referencias, umbral_iou=umbral_iou)
    base = metricas.evaluar_campos(detectados, referencias,
                                   umbral_iou=umbral_iou)
    area_con_signo = []
    for par in pares:
        det = detectados[par.indice_detectado]
        ref = referencias[par.indice_referencia]
        if ref.area > 0:
            area_con_signo.append(float((det.area - ref.area) / ref.area))
    refs_con_detectados = {p.indice_referencia for p in pares}
    dets_con_referencias = {p.indice_detectado for p in pares}
    fusionados = 0
    partidos = 0
    for i, ref in enumerate(referencias):
        solapados = [j for j, det in enumerate(detectados)
                     if _solape(det, ref) >= umbral_iou]
        if len(solapados) >= 2:
            partidos += 1
    for j, det in enumerate(detectados):
        cubiertos = [i for i, ref in enumerate(referencias)
                     if _solape(det, ref) >= umbral_iou]
        if len(cubiertos) >= 2:
            fusionados += 1
    n_ref = len(referencias)
    n_det = len(detectados)
    return {
        **base,
        'area_error_con_signo_mediana': round(float(np.median(area_con_signo)), 4)
        if area_con_signo else 0.0,
        'area_error_con_signo_media': round(float(np.mean(area_con_signo)), 4)
        if area_con_signo else 0.0,
        'fusionados': fusionados,
        'partidos': partidos,
        'no_detectados': n_ref - len(refs_con_detectados),
        'detectados_extra': n_det - len(dets_con_referencias),
        'fraccion_fusionados': wilson_interval(fusionados, n_ref),
        'fraccion_partidos': wilson_interval(partidos, n_ref),
        'fraccion_no_detectados': wilson_interval(n_ref - len(refs_con_detectados),
                                                  n_ref),
        'fraccion_extra': wilson_interval(n_det - len(dets_con_referencias),
                                          n_det),
        'n_pequeno': n_ref < 30,
        'nota': 'Con n<30 las fracciones son indicativas; no afirmar exactitud.',
    }


def evaluar_geojson(referencia: str | Path, detectado: str | Path,
                    capa_ref: str | None = None,
                    capa_det: str | None = None) -> dict:
    ref = cargar_geojson(referencia, capa_ref)
    det = cargar_geojson(detectado, capa_det,
                         epsg=int(ref.crs.to_epsg()))
    return evaluar_poligonos(list(det.geometry), list(ref.geometry))
