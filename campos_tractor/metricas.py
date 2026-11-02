"""Métricas geométricas y de tiempo para comparar campos detectados.

Todas las geometrías deben estar en un CRS proyectado en metros (por ejemplo,
UTM). El módulo no reproyecta: quien lo usa decide el CRS y lo mantiene igual
para detección y referencia.

Definiciones:
  · IoU: área de la intersección / área de la unión.
  · Error relativo de área: |área_detectada - área_referencia| / área_referencia.
  · Hausdorff: distancia máxima entre las geometrías, en metros.
  · Tiempo: milisegundos de reloj de pared.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import time
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely import make_valid, normalize
from shapely.geometry.base import BaseGeometry


def geometria_valida(geom: BaseGeometry | None) -> BaseGeometry | None:
    """Devuelve una geometría no vacía y válida, o None."""
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = make_valid(geom)
    if geom.is_empty:
        return None
    return geom


def iou(detectado: BaseGeometry | None, referencia: BaseGeometry | None) -> float:
    """Intersección sobre unión; 0.0 si alguna geometría es vacía."""
    detectado = geometria_valida(detectado)
    referencia = geometria_valida(referencia)
    if detectado is None or referencia is None:
        return 0.0
    union = detectado.union(referencia).area
    if union <= 0:
        return 0.0
    return float(detectado.intersection(referencia).area / union)


def error_relativo_area(detectado: BaseGeometry | None,
                        referencia: BaseGeometry | None) -> float:
    """|área_detectada - área_referencia| / área_referencia.

    Si la referencia no tiene área, devuelve 0.0 cuando ambas son vacías y
    ``inf`` cuando sólo la detección tiene área.
    """
    detectado = geometria_valida(detectado)
    referencia = geometria_valida(referencia)
    area_ref = 0.0 if referencia is None else float(referencia.area)
    area_det = 0.0 if detectado is None else float(detectado.area)
    if area_ref <= 0:
        return 0.0 if area_det <= 0 else float('inf')
    return float(abs(area_det - area_ref) / area_ref)


def hausdorff_m(detectado: BaseGeometry | None,
                referencia: BaseGeometry | None) -> float:
    """Distancia de Hausdorff en metros; ``inf`` si falta alguna geometría."""
    detectado = geometria_valida(detectado)
    referencia = geometria_valida(referencia)
    if detectado is None or referencia is None:
        return float('inf')
    return float(detectado.hausdorff_distance(referencia))


@dataclass(frozen=True)
class Emparejamiento:
    indice_detectado: int
    indice_referencia: int
    iou: float
    error_area: float
    hausdorff_m: float

    def como_dict(self) -> dict:
        return {
            'indice_detectado': self.indice_detectado,
            'indice_referencia': self.indice_referencia,
            'iou': round(self.iou, 6),
            'error_area': round(self.error_area, 6),
            'hausdorff_m': round(self.hausdorff_m, 3),
        }


def emparejar(detectados: Sequence[BaseGeometry],
              referencias: Sequence[BaseGeometry],
              umbral_iou: float = 0.10) -> list[Emparejamiento]:
    """Empareja detecciones y referencias maximizando la suma de IoU.

    Se usa el algoritmo húngaro (``linear_sum_assignment``) para que una
    detección no se lleve dos referencias. Los pares con IoU menor que
    ``umbral_iou`` se descartan y quedan como no emparejados.
    """
    if not detectados or not referencias:
        return []
    matriz = np.array([[iou(d, r) for r in referencias] for d in detectados], dtype=float)
    filas, columnas = linear_sum_assignment(-matriz)
    pares = []
    for i, j in zip(filas, columnas):
        valor = float(matriz[i, j])
        if valor < umbral_iou:
            continue
        pares.append(Emparejamiento(
            indice_detectado=int(i),
            indice_referencia=int(j),
            iou=valor,
            error_area=error_relativo_area(detectados[i], referencias[j]),
            hausdorff_m=hausdorff_m(detectados[i], referencias[j]),
        ))
    return pares


def _percentil(valores: Iterable[float], q: float) -> float:
    datos = [v for v in valores if np.isfinite(v)]
    return float(np.percentile(datos, q)) if datos else 0.0


def evaluar_campos(detectados: Sequence[BaseGeometry],
                   referencias: Sequence[BaseGeometry],
                   umbral_iou: float = 0.10) -> dict:
    """Evalúa un conjunto de campos detectados contra la verdad de referencia."""
    detectados = [g for g in detectados if geometria_valida(g) is not None]
    referencias = [g for g in referencias if geometria_valida(g) is not None]
    pares = emparejar(detectados, referencias, umbral_iou=umbral_iou)

    ious = [p.iou for p in pares]
    errores = [p.error_area for p in pares]
    hausdorffs = [p.hausdorff_m for p in pares]
    emparejados_det = {p.indice_detectado for p in pares}
    emparejados_ref = {p.indice_referencia for p in pares}

    n_det = len(detectados)
    n_ref = len(referencias)
    n_pares = len(pares)
    precision = n_pares / n_det if n_det else 0.0
    recall = n_pares / n_ref if n_ref else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    area_det = sum(float(g.area) for g in detectados)
    area_ref = sum(float(g.area) for g in referencias)
    interseccion = sum(float(detectados[p.indice_detectado].intersection(
        referencias[p.indice_referencia]).area) for p in pares)

    return {
        'n_detectados': n_det,
        'n_referencias': n_ref,
        'n_emparejados': n_pares,
        'iou_mediana': round(_percentil(ious, 50), 6),
        'iou_media': round(float(np.mean(ious)) if ious else 0.0, 6),
        'iou_min': round(float(np.min(ious)) if ious else 0.0, 6),
        'error_area_mediana': round(_percentil(errores, 50), 6),
        'error_area_media': round(float(np.mean(errores)) if errores else 0.0, 6),
        'hausdorff_mediana_m': round(_percentil(hausdorffs, 50), 3),
        'hausdorff_p95_m': round(_percentil(hausdorffs, 95), 3),
        'hausdorff_max_m': round(max(hausdorffs) if hausdorffs else 0.0, 3),
        'precision': round(precision, 6),
        'recall': round(recall, 6),
        'f1': round(f1, 6),
        'area_detectada_m2': round(area_det, 3),
        'area_referencia_m2': round(area_ref, 3),
        'area_detectada_ha': round(area_det / 10000.0, 4),
        'area_referencia_ha': round(area_ref / 10000.0, 4),
        'cobertura_area': round(interseccion / area_ref, 6) if area_ref > 0 else 0.0,
        'emparejamientos': [p.como_dict() for p in pares],
        'sin_emparejar_detectados': sorted(set(range(n_det)) - emparejados_det),
        'sin_emparejar_referencias': sorted(set(range(n_ref)) - emparejados_ref),
    }


@dataclass
class Cronometro:
    """Cronómetro mínimo para medir el pipeline sin dependencias externas."""
    inicio: float = field(default=0.0, init=False)
    ms: float = field(default=0.0, init=False)

    def __enter__(self) -> 'Cronometro':
        self.inicio = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        self.ms = (time.perf_counter() - self.inicio) * 1000.0


def resumen_tiempos(valores_ms: Iterable[float]) -> dict:
    datos = [float(v) for v in valores_ms if np.isfinite(v)]
    if not datos:
        return {'n': 0, 'mediana_ms': 0.0, 'media_ms': 0.0,
                'p95_ms': 0.0, 'max_ms': 0.0}
    return {
        'n': len(datos),
        'mediana_ms': round(float(np.median(datos)), 3),
        'media_ms': round(float(np.mean(datos)), 3),
        'p95_ms': round(float(np.percentile(datos, 95)), 3),
        'max_ms': round(float(np.max(datos)), 3),
    }


def huella_geometrias(geometrias: Iterable[BaseGeometry]) -> str:
    """SHA-256 estable de un conjunto de geometrías (detecta cambios de salida)."""
    partes = []
    for geom in geometrias:
        geom = geometria_valida(geom)
        if geom is None:
            continue
        partes.append(normalize(geom).wkb_hex)
    return hashlib.sha256('|'.join(sorted(partes)).encode('ascii')).hexdigest()


def agregar_evaluaciones(resultados: Sequence[dict]) -> dict:
    """Agrega varias evaluaciones por campo (no promedia medianas)."""
    pares = [p for r in resultados for p in r.get('emparejamientos', [])]
    ious = [p['iou'] for p in pares]
    errores = [p['error_area'] for p in pares]
    hausdorffs = [p['hausdorff_m'] for p in pares]
    n_det = sum(int(r.get('n_detectados', 0)) for r in resultados)
    n_ref = sum(int(r.get('n_referencias', 0)) for r in resultados)
    n_pares = len(pares)
    precision = n_pares / n_det if n_det else 0.0
    recall = n_pares / n_ref if n_ref else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    area_det = sum(float(r.get('area_detectada_m2', 0)) for r in resultados)
    area_ref = sum(float(r.get('area_referencia_m2', 0)) for r in resultados)
    return {
        'n_detectados': n_det,
        'n_referencias': n_ref,
        'n_emparejados': n_pares,
        'iou_mediana': round(_percentil(ious, 50), 6),
        'iou_media': round(float(np.mean(ious)) if ious else 0.0, 6),
        'error_area_mediana': round(_percentil(errores, 50), 6),
        'error_area_media': round(float(np.mean(errores)) if errores else 0.0, 6),
        'hausdorff_mediana_m': round(_percentil(hausdorffs, 50), 3),
        'hausdorff_p95_m': round(_percentil(hausdorffs, 95), 3),
        'precision': round(precision, 6),
        'recall': round(recall, 6),
        'f1': round(f1, 6),
        'area_detectada_m2': round(area_det, 3),
        'area_referencia_m2': round(area_ref, 3),
        'area_detectada_ha': round(area_det / 10000.0, 4),
        'area_referencia_ha': round(area_ref / 10000.0, 4),
    }
