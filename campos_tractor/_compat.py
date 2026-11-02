"""Segmentación de pasadas y utilidades puras del detector.

No contiene clientes de API, base de datos ni configuración del programa.
"""
from __future__ import annotations

import numpy as np

from . import _pasadas as we

CFG_SESIONES = {
    'campo_eps_m': 50.0,
    'campo_min_puntos': 20,
    'pasada_cluster_eps_m': 30.0,
    'pasada_cluster_min': 3,
    'salto_offset_m': 30.0,
    'hueco_max_m': 5.0,
    'solape_max_m': 2.0,
    'session_gap_s': 1800.0,
    'ventana_direccion': 11,
    'tolerancia_orientacion_grados': 25.0,
    'min_puntos_sesion': 60,
    'min_pasadas': 3,
    'ventana_curvatura': 20,
    'curvatura_max': 0.012,
    'curvatura_penalizacion': 0.5,
    'ambiguedad_rel': 0.15,
    'umbral_confianza': 0.45,
    'split_mitad_min_pasadas': 3,
    'max_puntos_sesion': 50000,
    'bootstrap_iteraciones': 200,
    'bootstrap_semilla': 20261102,
    'bootstrap_radio_rel': 0.15,
    'cobertura_min': 0.70,
    'cobertura_max': 1.35,
    'version_segmentacion': 'tractor-sessions-v2',
    'min_largo_pasada_m': 40.0,
    'min_puntos_pasada': 8,
    'fusion_campo_m': 20.0,
    'dividir_orientacion_pasadas': True,
    'min_pasadas_por_orientacion': 3,
    'categoria_no_campo': True,
    'fusion_fragmento_m': 30.0,
    'tolerancia_fragmento_grados': 25.0,
    'residuo_max': 0.20,
    'hueco_max_pasada': 0.20,
}


def _cfg(cfg: dict | None) -> dict:
    salida = dict(we.CFG_PASADAS)
    salida.update(CFG_SESIONES)
    if cfg:
        salida.update({k: v for k, v in cfg.items() if v is not None})
    return salida


def _epsg_utm(lon_media, lat_media):
    zona = int((lon_media + 180.0) // 6) + 1
    return (32600 if lat_media >= 0 else 32700) + zona


def _direccion_local(puntos: np.ndarray, ventana: int) -> np.ndarray:
    n = len(puntos)
    if n < 3:
        return np.full(n, np.nan)
    mitad = max(1, int(ventana) // 2)
    dx = np.full(n, np.nan)
    dy = np.full(n, np.nan)
    if n > 2 * mitad:
        dx[mitad:-mitad] = puntos[2 * mitad:, 0] - puntos[:-2 * mitad, 0]
        dy[mitad:-mitad] = puntos[2 * mitad:, 1] - puntos[:-2 * mitad, 1]
    return np.degrees(np.arctan2(dy, dx)) % 180.0


def asignar_campos(df, cfg: dict | None = None) -> np.ndarray:
    """Asigna un id de campo por densidad espacial (DBSCAN)."""
    from sklearn.cluster import DBSCAN
    cfg = _cfg(cfg)
    if df is None or len(df) < cfg['campo_min_puntos']:
        return np.zeros(len(df), dtype=int)
    xy = np.column_stack([df['X'].to_numpy(dtype=float),
                          df['Y'].to_numpy(dtype=float)])
    etiquetas = DBSCAN(eps=cfg['campo_eps_m'],
                       min_samples=cfg['campo_min_puntos']).fit_predict(xy)
    mapa = {}
    siguiente = 1
    salida = np.zeros(len(df), dtype=int)
    for i, etiqueta in enumerate(etiquetas):
        if etiqueta < 0:
            continue
        if etiqueta not in mapa:
            mapa[etiqueta] = siguiente
            siguiente += 1
        salida[i] = mapa[etiqueta]
    return salida


def _pasadas_todas(campo, cfg: dict) -> list[dict]:
    puntos = np.column_stack([campo['X'].to_numpy(dtype=float),
                              campo['Y'].to_numpy(dtype=float)])
    rumbos = (campo['Bearing'].to_numpy(dtype=float)
              if 'Bearing' in campo.columns else np.full(len(campo), np.nan))
    if 't_s' in campo.columns:
        tiempos = campo['t_s'].to_numpy(dtype=float)
    elif 'Timestamp' in campo.columns:
        tiempos = (campo['Timestamp'].astype('int64') / 1e9).to_numpy(dtype=float)
    else:
        tiempos = np.arange(len(campo), dtype=float)
    rectas = we.unir_colineales(
        we.segmentar_por_rumbo(puntos, rumbos, tiempos, cfg),
        puntos, tiempos, cfg)
    pasadas: list[dict] = []
    for familia in we._familias_orientacion(
            rectas, cfg['tolerancia_fusion_grados']):
        pasadas.extend(we.pasadas_desde_rectas(familia, cfg))
    return pasadas
