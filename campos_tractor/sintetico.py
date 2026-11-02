"""Y5: banco sintético con muestreo realista (30-120 s, 5-10 km/h)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

import numpy as np
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform as shapely_transform

SEMILLA = 20261108
LAT0 = 18.60
LON0 = -95.52
R = 111_320.0
X0 = LON0 * R * math.cos(math.radians(LAT0))
Y0 = LAT0 * R
BASE = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
TRANS = Transformer.from_crs(4326, 32615, always_xy=True)


@dataclass
class Escenario:
    nombre: str
    frame: object
    verdad: list
    separacion_m: float | None = None


def _utm(box_local):
    x0, y0, x1, y1 = box_local
    def conv(x, y):
        return ((X0 + np.asarray(x)) / (R * math.cos(math.radians(LAT0))),
                (Y0 + np.asarray(y)) / R)
    wgs = shapely_transform(conv, box(x0, y0, x1, y1))
    return shapely_transform(TRANS.transform, wgs)


def _frame(puntos, archivo, inicio=BASE):
    filas = []
    for x, y, h, t, speed, state in puntos:
        filas.append({'X': float(x), 'Y': float(y),
                      'X_global': X0 + float(x), 'Y_global': Y0 + float(y),
                      'Bearing': float(h), 't_s': float(t),
                      'Timestamp': (inicio + timedelta(seconds=t)).replace(tzinfo=None),
                      'Archivo': archivo,
                      'speed_kmh_origen': float(speed),
                      'state_origen': state})
    import pandas as pd
    return pd.DataFrame(filas)


def _campo(x0, y0, w, h, rng, dt_min=30, dt_max=90, speed_min=5,
           speed_max=8, dt0=0, quitar_centro=False, paso_y=10.0):
    puntos = []
    t = dt0
    for fila, y in enumerate(np.arange(y0, y0 + h + 0.1, paso_y)):
        x = x0 if fila % 2 == 0 else x0 + w
        while (x <= x0 + w) if fila % 2 == 0 else (x >= x0):
            if quitar_centro and (x0 + w * 0.35 <= x <= x0 + w * 0.65
                                  and y0 + h * 0.35 <= y <= y0 + h * 0.65):
                x += (w if fila % 2 == 0 else -w)
                continue
            speed = rng.uniform(speed_min, speed_max)
            puntos.append((x, y, 0.0 if fila % 2 == 0 else 180.0,
                           t, speed, 'Working'))
            dt_paso = rng.uniform(dt_min, dt_max)
            paso = speed * dt_paso / 3.6
            t += dt_paso
            siguiente = x + paso if fila % 2 == 0 else x - paso
            if (fila % 2 == 0 and siguiente > x0 + w) or                (fila % 2 == 1 and siguiente < x0):
                break
            x = siguiente
    return puntos, t



def _campo_dias(x0, y0, w, h, rng, dias=3, paso_y=10.0, dt0=0):
    puntos = []
    for d in range(dias):
        p, _ = _campo(x0, y0, w, h, rng, dt0=dt0 + d * 86400, paso_y=paso_y)
        puntos.extend(p)
    return puntos

def _traslado(x0, y0, x1, y1, t0, speed=20.0):
    dist = math.hypot(x1 - x0, y1 - y0)
    n = max(2, int(dist / (speed * 30 / 3.6)))
    puntos = []
    for i in range(n):
        f = i / max(n - 1, 1)
        puntos.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f,
                       0.0, t0 + i * 30, speed, 'Transport'))
    return puntos, t0 + n * 30


def generar(seed: int = SEMILLA) -> list[Escenario]:
    rng = np.random.default_rng(seed)
    salida = []
    for gap in (0, 3, 5, 10, 20, 30, 40):
        a = _campo_dias(0, 0, 100, 100, rng, dias=20)
        b = _campo_dias(100 + gap, 0, 100, 100, rng, dias=20, dt0=20 * 86400 + 600)
        salida.append(Escenario(
            f'contiguos_{gap}m', _frame(a + b, f'g{gap}.csv'),
            [_utm((0, 0, 100, 100)),
             _utm((100 + gap, 0, 200 + gap, 100))], gap))

    a = _campo_dias(0, 0, 100, 100, rng, dias=20)
    tr, t = _traslado(100, 0, 300, 0, 20 * 86400 + 600)
    b = _campo_dias(300, 0, 100, 100, rng, dias=20, dt0=20 * 86400 + 600)
    salida.append(Escenario(
        'cruce_transporte', _frame(a + tr + b, 'cruce.csv'),
        [_utm((0, 0, 100, 100)), _utm((300, 0, 400, 100))]))

    grande = _campo_dias(0, 0, 300, 300, rng, dias=20)
    salida.append(Escenario(
        'grande_compacto', _frame(grande, 'grande.csv'),
        [_utm((0, 0, 300, 300))]))

    hueco = []
    for d in range(20):
        p, _ = _campo(0, 0, 150, 150, rng, dt0=d * 86400, quitar_centro=True)
        hueco.extend(p)
    salida.append(Escenario(
        'hueco_muestreo', _frame(hueco, 'hueco.csv'),
        [_utm((0, 0, 150, 150))]))

    # Transporte aislado: no debe ser campo.
    tr, _ = _traslado(0, 0, 3000, 0, 0)
    salida.append(Escenario(
        'transporte_largo', _frame(tr, 'transporte.csv'), []))
    return salida
