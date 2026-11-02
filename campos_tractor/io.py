"""Contrato de entrada: tabla con timestamp UTC, lat, lon, machine_id.

Opcionales: ``speed_kmh`` y ``state``. La ruta de los datos se recibe por
parámetro; el paquete no incluye datos reales.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

RADIO_M_POR_GRADO = 111_320.0


def _columna(columnas: dict[str, str], *nombres: str) -> str | None:
    for nombre in nombres:
        if nombre in columnas:
            return columnas[nombre]
    return None


def cargar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    columnas = {str(c).strip().lower(): c for c in df.columns}
    c_t = _columna(columnas, 'timestamp', 'stamp', 'fecha_hora')
    c_lat = _columna(columnas, 'lat', 'latitud')
    c_lon = _columna(columnas, 'lon', 'longitud')
    c_maq = _columna(columnas, 'machine_id', 'maquina_id', 'maquina')
    if not all((c_t, c_lat, c_lon, c_maq)):
        raise ValueError(
            'La entrada requiere columnas timestamp, lat, lon y machine_id')
    trabajo = pd.DataFrame({
        'timestamp': pd.to_datetime(df[c_t], utc=True, errors='coerce'),
        'lat': pd.to_numeric(df[c_lat], errors='coerce'),
        'lon': pd.to_numeric(df[c_lon], errors='coerce'),
        'machine_id': df[c_maq].astype(str),
        'speed_kmh': (pd.to_numeric(df[columnas['speed_kmh']], errors='coerce')
                      if 'speed_kmh' in columnas else np.nan),
        'state': (df[columnas['state']].astype(str)
                  if 'state' in columnas else ''),
    })
    trabajo = trabajo.dropna(subset=['timestamp', 'lat', 'lon'])
    trabajo = trabajo.sort_values(['machine_id', 'timestamp']).reset_index(drop=True)
    salida = []
    for maquina, grupo in trabajo.groupby('machine_id', sort=False):
        grupo = grupo.copy()
        if len(grupo) < 2:
            continue
        lat0 = float(grupo['lat'].iloc[0])
        escala = math.cos(math.radians(lat0))
        x = grupo['lon'].to_numpy(dtype=float) * RADIO_M_POR_GRADO * escala
        y = grupo['lat'].to_numpy(dtype=float) * RADIO_M_POR_GRADO
        x0, y0 = float(np.min(x)), float(np.min(y))
        t = grupo['timestamp']
        t_s = (t - t.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
        dx = np.diff(x, prepend=x[0])
        dy = np.diff(y, prepend=y[0])
        rumbo = np.degrees(np.arctan2(dy, dx)) % 360.0
        salida.append(pd.DataFrame({
            'Timestamp': t.dt.tz_localize(None).to_numpy(),
            'Latitud': grupo['lat'].to_numpy(dtype=float),
            'Longitud': grupo['lon'].to_numpy(dtype=float),
            'Maquina': maquina,
            'Archivo': maquina,
            'Bearing': rumbo,
            't_s': t_s,
            'X': x - x0,
            'Y': y - y0,
            'X_global': x,
            'Y_global': y,
            'tiempo_origen': 'REAL',
            'speed_kmh_origen': grupo['speed_kmh'].to_numpy(),
            'state_origen': grupo['state'].to_numpy(),
        }))
    if not salida:
        return pd.DataFrame()
    return pd.concat(salida, ignore_index=True)


def cargar_csv(ruta: str | Path) -> pd.DataFrame:
    return cargar_dataframe(pd.read_csv(Path(ruta)))


def cargar_por_maquina(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if df is None or len(df) == 0:
        return {}
    return {str(maquina): grupo.reset_index(drop=True)
            for maquina, grupo in df.groupby('Archivo', sort=False)}
