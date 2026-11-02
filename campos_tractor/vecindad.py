"""Vecindad entre campos: qué polígonos están juntos y cuáles no.

No fusiona ni borra nada. Calcula pares, distancias, mejora de forma al unir y
dos agrupaciones para filtrar en QGIS:

  · ``grupo_espacial``: componentes conexas por distancia <= ``dist_junto_m``;
  · ``grupo_vecindad``: además exige al menos una sesión compartida, para no
    unir parcelas vecinas que nunca se trabajaron en la misma operación.

La distancia se mide en metros (geodésica entre los puntos más cercanos); la
forma se mide en la UTM del campo.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
from pyproj import Geod, Transformer
from shapely.geometry import MultiPolygon
from shapely.ops import nearest_points, transform

GEOD = Geod(ellps='WGS84')


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()[:16]


def _distancia_m(a_wgs, b_wgs) -> float:
    if a_wgs is None or b_wgs is None:
        return math.inf
    if a_wgs.intersects(b_wgs):
        return 0.0
    pa, pb = nearest_points(a_wgs, b_wgs)
    _, _, distancia = GEOD.inv(pa.x, pa.y, pb.x, pb.y)
    return float(distancia)


def distancia_entre_campos(a: dict, b: dict) -> float:
    return _distancia_m(a.get('geometry'), b.get('geometry'))


def _a_utm(geom, desde: int, hacia: int):
    if desde == hacia:
        return geom
    trans = Transformer.from_crs(f'EPSG:{desde}', f'EPSG:{hacia}',
                                 always_xy=True)
    return transform(trans.transform, geom)


def _forma(geom) -> tuple[float, float]:
    area = float(geom.area)
    if area <= 0:
        return 0.0, 0.0
    hull = geom.convex_hull
    solidez = area / float(hull.area) if hull.area > 0 else 0.0
    perimetro = float(geom.length)
    compacidad = 4 * math.pi * area / (perimetro ** 2) if perimetro else 0.0
    return solidez, compacidad


def analizar_vecindad(campos: list[dict], dist_junto_m: float = 10.0,
                      dist_candidata_m: float = 50.0) -> tuple[list[dict], dict]:
    """Devuelve pares candidatos, atributos por campo y grupos.

    ``campos`` necesita ``id_estable``, ``geometry`` (WGS84),
    ``geometry_utm``, ``epsg_utm``, ``area_ha``, ``solidez``, ``compacidad``,
    ``ruta_hash`` y, si existe, ``sesiones`` (conjunto de ids).
    """
    pares = []
    atributos = {
        c['id_estable']: {
            'vecinos': '', 'distancia_min_m': None,
            'grupo_espacial': '', 'n_campos_espacial': 1,
            'grupo_vecindad': '', 'n_campos_grupo': 1,
            'candidato_fusion': 0, 'sesiones_compartidas_max': 0,
        }
        for c in campos
    }
    aristas_espaciales = []
    aristas_sesion = []
    for i in range(len(campos)):
        for j in range(i + 1, len(campos)):
            a, b = campos[i], campos[j]
            distancia = distancia_entre_campos(a, b)
            if distancia > dist_candidata_m:
                continue
            epsg = int(a['epsg_utm'])
            try:
                ga = _a_utm(a['geometry_utm'], int(a['epsg_utm']), epsg)
                gb = _a_utm(b['geometry_utm'], int(b['epsg_utm']), epsg)
                union = ga.union(gb)
                solidez_union, compacidad_union = _forma(union)
            except Exception:  # noqa: BLE001
                continue
            if union.is_empty or union.area <= 0:
                continue
            misma_ruta = a.get('ruta_hash') == b.get('ruta_hash')
            sesiones_a = set(a.get('sesiones') or [])
            sesiones_b = set(b.get('sesiones') or [])
            compartidas = len(sesiones_a & sesiones_b)
            delta_solidez = solidez_union - max(float(a.get('solidez', 0)),
                                                float(b.get('solidez', 0)))
            delta_compacidad = compacidad_union - max(
                float(a.get('compacidad', 0)), float(b.get('compacidad', 0)))
            if distancia <= 5:
                nivel = 'MUY_CERCA'
            elif distancia <= dist_junto_m:
                nivel = 'JUNTO'
            elif distancia <= dist_candidata_m:
                nivel = 'CERCA'
            else:
                nivel = 'LEJOS'
            # Un campo partido en dos suele dejar dos polígonos a pocos metros
            # y visitados en las mismas sesiones. No se exige que el casco
            # convexo de la unión sea más sólido: el hueco entre partes lo baja.
            candidato = int(
                nivel == 'MUY_CERCA' and compartidas > 0 or
                (nivel == 'JUNTO' and misma_ruta and compartidas > 0 and
                 delta_solidez >= -0.05))
            pares.append({
                'id_a': a['id_estable'], 'id_b': b['id_estable'],
                'ruta_a': a.get('ruta_hash'), 'ruta_b': b.get('ruta_hash'),
                'misma_ruta': int(misma_ruta),
                'distancia_m': round(float(distancia), 2),
                'nivel': nivel,
                'area_a_ha': round(float(a.get('area_ha', 0)), 4),
                'area_b_ha': round(float(b.get('area_ha', 0)), 4),
                'area_union_ha': round(float(union.area) / 10000.0, 4),
                'solidez_union': round(float(solidez_union), 3),
                'compacidad_union': round(float(compacidad_union), 3),
                'delta_solidez': round(float(delta_solidez), 3),
                'delta_compacidad': round(float(delta_compacidad), 3),
                'sesiones_compartidas': int(compartidas),
                'candidato_fusion': candidato,
                'estado_a': a.get('estado'), 'estado_b': b.get('estado'),
            })
            if distancia <= dist_junto_m:
                aristas_espaciales.append((a['id_estable'], b['id_estable']))
                if compartidas > 0:
                    aristas_sesion.append((a['id_estable'], b['id_estable']))
                for clave, otro in ((a['id_estable'], b['id_estable']),
                                    (b['id_estable'], a['id_estable'])):
                    attrs = atributos[clave]
                    vecinos = [v for v in attrs['vecinos'].split(';') if v]
                    if otro not in vecinos:
                        vecinos.append(otro)
                    attrs['vecinos'] = ';'.join(sorted(vecinos))
                    actual = attrs['distancia_min_m']
                    attrs['distancia_min_m'] = (
                        round(float(distancia), 2) if actual is None else
                        min(actual, round(float(distancia), 2)))
                if candidato:
                    atributos[a['id_estable']]['candidato_fusion'] = 1
                    atributos[b['id_estable']]['candidato_fusion'] = 1
            atributos[a['id_estable']]['sesiones_compartidas_max'] = max(
                atributos[a['id_estable']]['sesiones_compartidas_max'], compartidas)
            atributos[b['id_estable']]['sesiones_compartidas_max'] = max(
                atributos[b['id_estable']]['sesiones_compartidas_max'], compartidas)

    grupos_espaciales = _grupos(campos, aristas_espaciales, atributos,
                                dist_junto_m, 'ESPACIAL')
    grupos_sesion = _grupos(campos, aristas_sesion, atributos,
                            dist_junto_m, 'SESION')
    for grupo in grupos_espaciales:
        for clave in grupo['ids']:
            atributos[clave]['grupo_espacial'] = grupo['grupo_id']
            atributos[clave]['n_campos_espacial'] = len(grupo['ids'])
    for grupo in grupos_sesion:
        for clave in grupo['ids']:
            atributos[clave]['grupo_vecindad'] = grupo['grupo_id']
            atributos[clave]['n_campos_grupo'] = len(grupo['ids'])
    return pares, {'campos': atributos,
                   'grupos': grupos_sesion + grupos_espaciales}


def _grupos(campos: list[dict], aristas: list[tuple[str, str]],
            atributos: dict, dist_junto_m: float,
            tipo: str) -> list[dict]:
    """Componentes conexas de un conjunto de aristas."""
    indices = {c['id_estable']: i for i, c in enumerate(campos)}
    padre = list(range(len(campos)))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for a, b in aristas:
        if a not in indices or b not in indices:
            continue
        ra, rb = raiz(indices[a]), raiz(indices[b])
        if ra != rb:
            padre[rb] = ra
    componentes = {}
    for clave, indice in indices.items():
        componentes.setdefault(raiz(indice), []).append(clave)
    por_id = {c['id_estable']: c for c in campos}
    salida = []
    for miembros in componentes.values():
        if len(miembros) < 2:
            continue
        miembros = sorted(miembros)
        grupo_id = _hash(tipo + '|' + '|'.join(miembros))
        epsg = int(por_id[miembros[0]]['epsg_utm'])
        geometrias = [_a_utm(por_id[clave]['geometry_utm'],
                             int(por_id[clave]['epsg_utm']), epsg)
                      for clave in miembros]
        union = geometrias[0]
        for geom in geometrias[1:]:
            union = union.union(geom)
        if union.geom_type == 'Polygon':
            union = MultiPolygon([union])
        solidez, compacidad = _forma(union)
        salida.append({
            'grupo_id': grupo_id, 'tipo_grupo': tipo,
            'ids': miembros, 'n_campos': len(miembros),
            'area_ha': round(float(union.area) / 10000.0, 4),
            'solidez_union': round(float(solidez), 3),
            'compacidad_union': round(float(compacidad), 3),
            'candidato_fusion': int(any(
                atributos[m]['candidato_fusion'] for m in miembros)),
            'rutas': ';'.join(sorted({str(por_id[m].get('ruta_hash'))
                                      for m in miembros})),
            'distancia_junto_m': dist_junto_m,
            'geometry_utm': union, 'epsg_utm': epsg,
        })
    return salida
