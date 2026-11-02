"""Banco sintético del detector actual.

Semilla y parámetros congelados antes de correr. No lee datos reales.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.ops import transform as shapely_transform

from .detector import detectar_campos
from .metricas import iou
from .sintetico import LAT0, LON0, R, SEMILLA, X0, Y0, generar

TRANS = Transformer.from_crs(4326, 32615, always_xy=True)


def _local_a_utm(geom):
    def conv(x, y):
        return ((X0 + np.asarray(x)) / (R * np.cos(np.radians(LAT0))),
                (Y0 + np.asarray(y)) / R)
    return shapely_transform(TRANS.transform,
                             shapely_transform(conv, geom))


def _evaluar(detectados, verdad):
    detectados = [g for g in detectados if g is not None and not g.is_empty]
    verdad = [g for g in verdad if g is not None and not g.is_empty]
    cubre = []
    areas = []
    for d in detectados:
        fila = [d.intersection(t).area / t.area if t.area else 0.0
                for t in verdad]
        cubre.append(fila)
        areas.append(d.area)
    fusiones = sum(1 for f in cubre if sum(1 for x in f if x >= 0.20) > 1)
    partidos = sum(1 for j in range(len(verdad))
                   if sum(1 for f in cubre if f[j] >= 0.20) > 1)
    ious, errores, emp = [], [], 0
    for i, fila in enumerate(cubre):
        if not fila:
            continue
        j = int(np.argmax(fila))
        if fila[j] >= 0.20:
            emp += 1
            ious.append(float(iou(detectados[i], verdad[j])))
            errores.append((areas[i] - verdad[j].area) / verdad[j].area)
    perdidos = len(verdad) - len({int(np.argmax(f)) for f in cubre
                                  if f and max(f) >= 0.20})
    return {
        'n_verdad': len(verdad), 'n_detectados': len(detectados),
        'emparejados': emp, 'falsos_campos': len(detectados) - emp,
        'campos_perdidos': max(0, perdidos),
        'fusiones_erroneas': fusiones, 'particiones_erroneas': partidos,
        'iou_mediana': round(float(np.median(ious)), 3) if ious else 0.0,
        'error_area_mediana': round(float(np.median(errores)), 3) if errores else 0.0,
        'sobreextension': int(sum(1 for e in errores if e > 0.10)),
    }


def ejecutar():
    filas = []
    for esc in generar(SEMILLA):
        campos, _, _ = detectar_campos(esc.frame, esc.nombre)
        geoms = [c.geometry_utm for c in campos
                 if c.estado not in ('NO_ES_CAMPO', 'TRAYECTO_DISPERSO')
                 and c.area_ha >= 0.10]
        filas.append({'escenario': esc.nombre, 'separacion_m': esc.separacion_m,
                      'resultado': _evaluar(geoms, esc.verdad)})
    fusion = [f['separacion_m'] for f in filas
              if f['separacion_m'] is not None
              and f['resultado']['fusiones_erroneas'] == 0]
    return {
        'version': 'benchmark-actual',
        'generado_en': datetime.now(timezone.utc).isoformat(),
        'semilla': SEMILLA,
        'resultados': filas,
        'deja_de_fusionar_desde_m': min(fusion) if fusion else None,
        'nota': 'Verdad geométrica sintética; no es exactitud real.',
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--salida', default='benchmark.json')
    args = p.parse_args()
    datos = ejecutar()
    Path(args.salida).write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(json.dumps(datos, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
