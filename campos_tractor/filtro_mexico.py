"""Y0: filtro geográfico de puntos fuera de México.

No hay polígono Natural Earth local; se usa la caja de respaldo
14,5–32,8 N / -118,5 a -86,5 O con colchón de 10 km. Se avisa en el reporte.
"""
from __future__ import annotations

import math

import pandas as pd
from shapely.geometry import Point

from . import proyeccion

CFG_MEXICO = {
    'bbox': (14.5, 32.8, -118.5, -86.5),  # sur, norte, oeste, este
    'buffer_km': 10.0,
    'poligono_disponible': False,
}


def _latlon(frame: pd.DataFrame):
    primera = frame.iloc[0]
    origen = proyeccion.origen_desde_primera({
        'x_m': float(primera['X_global']),
        'y_m': float(primera['Y_global']),
        'pasada': 0,
        'origen_lat0': primera.get('origen_lat0'),
        'origen_lon0': primera.get('origen_lon0'),
        'origen_x_m': primera.get('origen_x_m'),
        'origen_y_m': primera.get('origen_y_m'),
    })
    x = frame['X_global'].to_numpy(dtype=float)
    y = frame['Y_global'].to_numpy(dtype=float)
    lon, lat = proyeccion.invertir_xy(x, y, origen)
    return lon, lat


def filtrar_mexico(frame: pd.DataFrame, ruta_hash: str,
                   cfg: dict | None = None) -> tuple[pd.DataFrame, list[dict], dict]:
    """Devuelve frame limpio, puntos fuera y conteos. No borra del CSV."""
    cfg = {**CFG_MEXICO, **(cfg or {})}
    if frame is None or len(frame) == 0:
        return frame, [], {'n_puntos': 0, 'n_fuera': 0}
    lon, lat = _latlon(frame)
    sur, norte, oeste, este = cfg['bbox']
    colchon = float(cfg['buffer_km']) / 111.0
    dentro = ((lat >= sur - colchon) & (lat <= norte + colchon) &
              (lon >= oeste - colchon) & (lon <= este + colchon))
    trabajo = frame.copy()
    trabajo['lon_real'] = lon
    trabajo['lat_real'] = lat
    fuera = []
    for pos in trabajo.index[~dentro]:
        fila = trabajo.loc[pos]
        fuera.append({
            'ruta_hash': ruta_hash,
            'timestamp': str(fila.get('Timestamp') or ''),
            'lon': round(float(fila['lon_real']), 9),
            'lat': round(float(fila['lat_real']), 9),
            'motivo': 'fuera de la caja de México (respaldo Natural Earth)',
            'geometry': Point(float(fila['lon_real']), float(fila['lat_real'])),
        })
    limpio = trabajo.loc[dentro].copy()
    resumen = {
        'n_puntos': int(len(frame)),
        'n_fuera': int((~dentro).sum()),
        'n_dentro': int(dentro.sum()),
        'bbox': cfg['bbox'],
        'buffer_km': cfg['buffer_km'],
        'poligono_disponible': bool(cfg['poligono_disponible']),
        'motivo': ('polígono Natural Earth local no disponible; '
                   'se usó caja de respaldo con colchón de 10 km'),
    }
    return limpio, fuera, resumen
