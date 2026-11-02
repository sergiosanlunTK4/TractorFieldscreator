"""V0: proyección equirectangular usada por el importador de tractores.

El importador calcula:
    x_m = lon * 111320 * cos(lat0)
    y_m = lat * 111320

No resta un origen local: el origen es (lon=0, lat=0), y ``lat0`` es la latitud
del primer punto de la ruta. Es una proyección equirectangular en metros:
x_m es este, y_m es norte, unidades metros. La inversa es directa si se
conserva el primer punto (o su y_m) y el orden de la ruta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

RADIO_M_POR_GRADO = 111_320.0


@dataclass(frozen=True)
class OrigenProyeccion:
    tipo: str
    lat0: float
    lon0: float
    x0: float
    y0: float

    def como_dict(self) -> dict:
        return {'tipo': self.tipo, 'lat0': round(self.lat0, 9),
                'lon0': round(self.lon0, 9), 'x0': self.x0, 'y0': self.y0}


def origen_desde_primera(fila: dict) -> OrigenProyeccion:
    """Reconstruye el origen implícito a partir de la primera fila.

    Exige que la fila sea realmente el primer punto (``pasada=0`` u
    ``Orden=0``). Si no, el origen es ambiguo y se falla en vez de adivinar.
    """
    if 'x_m' not in fila or 'y_m' not in fila:
        raise ValueError('La fila no tiene x_m/y_m')
    if 'pasada' in fila and int(fila['pasada']) != 0:
        raise ValueError('La primera fila no es el punto 0: origen ambiguo')
    if 'Orden' in fila and int(fila['Orden']) != 0:
        raise ValueError('La primera fila no es el punto 0: origen ambiguo')
    y0 = float(fila['y_m'])
    x0 = float(fila['x_m'])
    # Si el importador nuevo guardó el origen, se usa. Si no, se reconstruye
    # con la primera fila (CSV históricos). No se inventa un origen.
    valor_origen = fila.get('origen_lat0')
    explicito = (valor_origen is not None and
                 str(valor_origen).strip().lower() not in ('', 'nan', 'none'))
    if explicito:
        lat0 = float(valor_origen)
        lon0 = float(fila.get('origen_lon0') or 0.0)
        x0 = float(fila.get('origen_x_m') or 0.0)
        y0 = float(fila.get('origen_y_m') or 0.0)
    else:
        lat0 = y0 / RADIO_M_POR_GRADO
        lon0 = 0.0
    return OrigenProyeccion('equirectangular', lat0=lat0, lon0=lon0,
                            x0=x0, y0=y0)


def invertir_xy(x_m, y_m, origen: OrigenProyeccion):
    """Inversa escalar o vectorizada.

    ``shapely.ops.transform`` entrega arrays de coordenadas; devolver arrays
    evita el camino lento de punto por punto y mantiene la misma fórmula.
    """
    import numpy as np

    escala = math.cos(math.radians(origen.lat0))
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    lat = y / RADIO_M_POR_GRADO
    lon = x / (RADIO_M_POR_GRADO * escala)
    if lon.ndim == 0:
        return float(lon), float(lat)
    return lon, lat


def invertir_filas(filas: list[dict]) -> list[dict]:
    if not filas:
        return []
    origen = origen_desde_primera(filas[0])
    salida = []
    for fila in filas:
        lon, lat = invertir_xy(fila['x_m'], fila['y_m'], origen)
        salida.append({**fila, 'lon': lon, 'lat': lat,
                       'origen_lat0': origen.lat0,
                       'origen_lon0': origen.lon0})
    return salida


def distancia_xy(a: dict, b: dict) -> float:
    return math.hypot(float(b['x_m']) - float(a['x_m']),
                      float(b['y_m']) - float(a['y_m']))
