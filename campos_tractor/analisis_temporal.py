"""Análisis temporal de rutas de tractor con timestamps reales.

No cambia la detección geométrica: añade sesiones por hueco temporal y métricas
por campo para que la revisión en QGIS pueda separar operaciones, ver continuidad
y usar velocidad/estado como señales —nunca como compuerta única—.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SESION_GAP_S = 7200.0


def _timestamp_utc(valor) -> pd.Timestamp:
    t = pd.Timestamp(valor)
    return t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')


def anotar_sesiones(frame: pd.DataFrame, ruta_hash: str,
                    gap_s: float = SESION_GAP_S) -> pd.DataFrame:
    """Añade ``sesion_id`` y ``fecha`` separando por huecos > ``gap_s``.

    Un hueco nocturno o un traslado corta la sesión. Los timestamps repetidos
    no cortan: pertenecen a la misma sesión.
    """
    if frame is None or len(frame) == 0:
        return frame
    trabajo = frame.copy()
    if 'Timestamp' not in trabajo.columns:
        trabajo['sesion_id'] = ''
        trabajo['fecha'] = ''
        return trabajo
    t = pd.to_datetime(trabajo['Timestamp'], errors='coerce')
    if t.isna().all():
        trabajo['sesion_id'] = ''
        trabajo['fecha'] = ''
        return trabajo
    dt = t.diff().dt.total_seconds().to_numpy()
    nuevo = np.isnan(dt) | (dt > float(gap_s)) | (dt < 0)
    indice = np.cumsum(nuevo) - 1
    inicios = t.groupby(indice).transform('min')
    trabajo['sesion_local'] = indice.astype(int)
    trabajo['sesion_id'] = [
        f'{ruta_hash}-{_timestamp_utc(x).strftime("%Y%m%dT%H%M%S")}'
        for x in inicios
    ]
    trabajo['fecha'] = t.dt.strftime('%Y-%m-%d')
    return trabajo


def resumen_temporal(frame: pd.DataFrame) -> dict:
    """Resumen por máquina: sesiones, días, duración y cobertura de señales."""
    if frame is None or len(frame) == 0:
        return {'n_puntos': 0, 'n_sesiones': 0, 'n_dias': 0}
    if 'Timestamp' in frame.columns:
        t = pd.to_datetime(frame['Timestamp'], errors='coerce')
    else:
        t = pd.Series(pd.NaT, index=frame.index)
    sesiones = frame.get('sesion_id', pd.Series([''] * len(frame)))
    tamanos = sesiones.value_counts()
    duraciones = []
    if 'Timestamp' in frame.columns:
        for _, grupo in frame.groupby('sesion_id', sort=False):
            ts = pd.to_datetime(grupo['Timestamp'], errors='coerce').dropna()
            if len(ts) >= 2:
                duraciones.append((ts.max() - ts.min()).total_seconds() / 3600.0)
    estado = frame.get('state_origen')
    velocidad = frame.get('speed_kmh_origen')
    return {
        'n_puntos': int(len(frame)),
        'n_sesiones': int(sesiones.nunique()),
        'n_sesiones_ge100': int((tamanos >= 100).sum()),
        'n_sesiones_ge500': int((tamanos >= 500).sum()),
        'puntos_sesion_mediana': int(tamanos.median()) if len(tamanos) else 0,
        'n_dias': int(t.dt.date.nunique()) if t.notna().any() else 0,
        'primer_timestamp': _iso(t.min()) if t.notna().any() else '',
        'ultimo_timestamp': _iso(t.max()) if t.notna().any() else '',
        'horas_span': round(float((t.max() - t.min()).total_seconds() / 3600.0), 2)
        if t.notna().any() else 0.0,
        'horas_sesion_suma': round(float(np.sum(duraciones)), 2),
        'state_cobertura': round(float(estado.notna().mean()), 3)
        if estado is not None else 0.0,
        'speed_cobertura': round(float(velocidad.notna().mean()), 3)
        if velocidad is not None else 0.0,
    }


def _iso(valor) -> str:
    if valor is None or pd.isna(valor):
        return ''
    return _timestamp_utc(valor).isoformat()


def _serie(frame: pd.DataFrame, *nombres: str):
    for nombre in nombres:
        if nombre in frame.columns:
            return frame[nombre]
    return None


def metricas_campo_tiempo(frame: pd.DataFrame, indices) -> dict:
    """Métricas temporales y de señales para un subconjunto de puntos."""
    grupo = frame.iloc[np.asarray(indices, dtype=int)]
    if len(grupo) == 0:
        return {}
    if 'Timestamp' in grupo.columns:
        t = pd.to_datetime(grupo['Timestamp'], errors='coerce')
    else:
        t = pd.Series(pd.NaT, index=grupo.index)
    sesiones = grupo.get('sesion_id', pd.Series([''] * len(grupo)))
    duraciones = []
    if 'Timestamp' in grupo.columns:
        for _, bloque in grupo.groupby('sesion_id', sort=False):
            ts = pd.to_datetime(bloque['Timestamp'], errors='coerce').dropna()
            if len(ts) >= 2:
                duraciones.append((ts.max() - ts.min()).total_seconds() / 3600.0)
    estado = _serie(grupo, 'state_origen', 'state')
    velocidad = _serie(grupo, 'speed_kmh_origen', 'Velocidad_kmh')
    estados = (estado.astype(str).str.strip().str.lower()
               if estado is not None else None)
    n_estado = int(estado.notna().sum()) if estado is not None else 0
    n_vel = int(velocidad.notna().sum()) if velocidad is not None else 0
    tiene_tiempo = bool(t.notna().any())
    salida = {
        'n_sesiones': int(sesiones.nunique()) if tiene_tiempo else 0,
        'n_dias': int(t.dt.date.nunique()) if tiene_tiempo else 0,
        't_inicio': _iso(t.min()) if t.notna().any() else '',
        't_fin': _iso(t.max()) if t.notna().any() else '',
        'horas_span': round(float((t.max() - t.min()).total_seconds() / 3600.0), 2)
        if t.notna().any() else 0.0,
        'horas_sesion': round(float(np.sum(duraciones)), 2),
        'puntos_sesion_mediana': (int(sesiones.value_counts().median())
                                  if tiene_tiempo else len(grupo)),
        'state_cobertura': round(n_estado / len(grupo), 3),
        'frac_working': round(float((estados == 'working').sum()) / n_estado, 3)
        if n_estado else 0.0,
        'frac_idle': round(float((estados == 'idle').sum()) / n_estado, 3)
        if n_estado else 0.0,
        'frac_transport': round(float((estados == 'transport').sum()) / n_estado, 3)
        if n_estado else 0.0,
        'speed_cobertura': round(n_vel / len(grupo), 3),
        'speed_p50': round(float(velocidad.quantile(0.50)), 2) if n_vel else None,
        'speed_p90': round(float(velocidad.quantile(0.90)), 2) if n_vel else None,
        'sesiones': set(sesiones.dropna().astype(str)),
    }
    return salida
