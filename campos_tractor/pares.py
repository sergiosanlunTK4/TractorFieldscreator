"""Pares consecutivos de unidades y su clasificación contra campos."""
from __future__ import annotations

import hashlib
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod
from shapely import STRtree
from shapely.geometry import LineString
from shapely.ops import nearest_points

GEOD = Geod(ellps='WGS84')


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()[:16]


def _inicio(geom):
    return geom.boundary.interpolate(0.5, normalized=True)


def _distancia_inicios(a, b):
    pa, pb = _inicio(a), _inicio(b)
    _, _, d = GEOD.inv(pa.x, pa.y, pb.x, pb.y)
    return float(d), LineString([(pa.x, pa.y), (pb.x, pb.y)])


def _campo_de_visita(visita, campos, arbol, epsg):
    candidatos = [int(j) for j in arbol.query(visita)]
    mejor, mejor_frac = '', 0.0
    for j in candidatos:
        campo = campos.iloc[j]
        try:
            inter = visita.intersection(campo.geometry)
            frac = inter.area / visita.area if visita.area > 0 else 0.0
        except Exception:  # noqa: BLE001
            continue
        if frac > mejor_frac:
            mejor, mejor_frac = campo.id_estable, frac
    return mejor if mejor_frac >= 0.20 else '', mejor_frac


def construir_pares_unidades(unidades, campos, max_gap_s: float = 600.0,
                             max_dist_m: float = 150.0):
    """Pares consecutivos de unidades y su clasificación contra campos."""
    campo_de_unidad = {}
    for campo in campos:
        for unidad in campo.unidades:
            campo_de_unidad[unidad.id_unidad] = campo.id_estable
    pares = []
    unidades_por_ruta = {}
    for unidad in unidades:
        unidades_por_ruta.setdefault(unidad.ruta_hash, []).append(unidad)
    for ruta, lista in unidades_por_ruta.items():
        lista = sorted(lista, key=lambda u: (u.t_inicio is None, u.t_inicio))
        for a, b in zip(lista, lista[1:]):
            if a.t_fin is None or b.t_inicio is None:
                continue
            gap = (b.t_inicio - a.t_fin).total_seconds()
            if abs(gap) > max_gap_s:
                continue
            if a.core_wgs84 is not None:
                pa = a.core_wgs84.centroid
            else:
                pa = a.geometry_wgs84.centroid
            if b.core_wgs84 is not None:
                pb = b.core_wgs84.centroid
            else:
                pb = b.geometry_wgs84.centroid
            _, _, distancia = GEOD.inv(pa.x, pa.y, pb.x, pb.y)
            if distancia > max_dist_m:
                continue
            ca = campo_de_unidad.get(a.id_unidad, '')
            cb = campo_de_unidad.get(b.id_unidad, '')
            if ca and ca == cb:
                clasificacion, motivo = 'UNIDO', 'mismo campo'
            elif not ca or not cb:
                clasificacion, motivo = 'NO_UNIDO', 'sin campo'
            elif gap > 300:
                clasificacion, motivo = 'NO_UNIDO', 'gap temporal > 5 min'
            else:
                clasificacion, motivo = 'NO_UNIDO', 'campos distintos'
            linea = LineString([(pa.x, pa.y), (pb.x, pb.y)])
            pares.append({
                'id_par': _hash('|'.join(sorted([a.id_unidad, b.id_unidad]))),
                'id_visita_a': a.id_unidad, 'id_visita_b': b.id_unidad,
                'ruta_hash': ruta, 'gap_s': round(float(gap), 1),
                'dist_m': round(float(distancia), 2),
                'vel_implicita_kmh': round(float(distancia / abs(gap) * 3.6), 2)
                if gap else None,
                'solape': 0.0,
                'dif_orientacion_deg': round(min(abs(a.orientacion - b.orientacion) % 180.0,
                                                 180.0 - abs(a.orientacion - b.orientacion) % 180.0), 1),
                'campo_a': ca, 'campo_b': cb, 'frac_a': 1.0, 'frac_b': 1.0,
                'clasificacion': clasificacion, 'motivo': motivo,
                'en_muestra': 1, 'geometry': linea, '_epsg': a.epsg_utm,
            })
    return pares
