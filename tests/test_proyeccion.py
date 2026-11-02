"""Pruebas de proyección local y contrato de entrada."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from campos_tractor.io import cargar_dataframe
from campos_tractor.proyeccion import invertir_xy, origen_desde_primera

LAT0 = 18.60
LON0 = -95.52


def _tabla():
    filas = []
    for i in range(4):
        filas.append({
            'timestamp': f'2026-06-01T08:00:0{i}Z',
            'lat': LAT0 + i * 0.0001,
            'lon': LON0 + i * 0.0001,
            'machine_id': 'maquina_sintetica',
            'speed_kmh': 6.0,
            'state': 'Working',
        })
    return pd.DataFrame(filas)


def test_contrato_y_roundtrip_menor_1_cm():
    frame = cargar_dataframe(_tabla())
    assert len(frame) == 4
    assert {'X', 'Y', 'X_global', 'Y_global', 'Bearing', 'Timestamp',
            'speed_kmh_origen', 'state_origen'} <= set(frame.columns)
    primera = frame.iloc[0]
    origen = origen_desde_primera({'x_m': primera['X_global'],
                                    'y_m': primera['Y_global'], 'pasada': 0})
    for _, fila in frame.iterrows():
        lon, lat = invertir_xy(fila['X_global'], fila['Y_global'], origen)
        dlat = abs(lat - fila['Latitud']) * 111_320.0
        dlon = abs(lon - fila['Longitud']) * 111_320.0 * math.cos(math.radians(lat))
        assert math.hypot(dlat, dlon) < 0.01


def test_origen_ambiguo_falla():
    frame = cargar_dataframe(_tabla())
    fila = {'x_m': frame.iloc[1]['X_global'],
            'y_m': frame.iloc[1]['Y_global'], 'pasada': 1}
    with pytest.raises(ValueError, match='origen ambiguo'):
        origen_desde_primera(fila)
