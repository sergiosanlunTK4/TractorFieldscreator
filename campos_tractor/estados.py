"""Detección de campos de tractor sin ancho.

Los estados son de campo:
  CAMPO_PROBABLE, CAMPO_FRAGMENTO, DUDOSO, NO_ES_CAMPO.
Las señales se calculan sobre la geometría y la traza.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon


CFG_DETECCION = {
    'version': 'campos-tractor-v1',
    'area_min_ha': 0.20,
    'area_fragmento_ha': 1.00,
    'puntos_min': 60,
    'solidez_min': 0.35,
    'compacidad_min': 0.025,
    'coherencia_min': 0.20,
    'densidad_min_puntos_ha': 15.0,
    'fraccion_dentro_min': 0.70,
    'concave_ratio': 0.35,
    'simplificar_m': 0.0,
    'buffer_m': 0.0,
    'submuestreo_trazas': 20,
}

ESTADOS = ('CAMPO_PROBABLE', 'CAMPO_FRAGMENTO', 'DUDOSO', 'NO_ES_CAMPO')


@dataclass
class CampoDetectado:
    id_estable: str
    ruta_hash: str
    campo_id: int
    geometry: Polygon
    indices: np.ndarray
    n_puntos: int
    area_ha: float
    perimetro_m: float
    estado: str
    confianza: float
    motivos: list[str]
    senales: dict
    version_algoritmo: str
    agrupacion: str = 'CAMPO'

    def to_dict(self) -> dict:
        return {
            'id_estable': self.id_estable,
            'ruta_hash': self.ruta_hash,
            'campo_id': int(self.campo_id),
            'n_puntos': int(self.n_puntos),
            'area_ha': round(float(self.area_ha), 4),
            'perimetro_m': round(float(self.perimetro_m), 1),
            'estado': self.estado,
            'confianza': round(float(self.confianza), 3),
            'motivos': list(self.motivos),
            'solidez': round(float(self.senales.get('solidez', 0.0)), 3),
            'compacidad': round(float(self.senales.get('compacidad', 0.0)), 3),
            'densidad_puntos_ha': round(float(self.senales.get('densidad_puntos_ha', 0.0)), 1),
            'coherencia_orientacion': round(float(self.senales.get('coherencia_orientacion', 0.0)), 3),
            'fraccion_dentro': round(float(self.senales.get('fraccion_dentro', 0.0)), 3),
            'version_algoritmo': self.version_algoritmo,
            'agrupacion': self.agrupacion,
        }


def _clasificar(area_ha: float, n: int, solidez: float, compacidad: float,
                coherencia: float, densidad: float, dentro: float,
                cfg: dict) -> tuple[str, list[str]]:
    fallos = []
    if area_ha < cfg['area_min_ha']:
        fallos.append('área menor al mínimo')
    if n < cfg['puntos_min']:
        fallos.append('pocos puntos')
    if solidez < cfg['solidez_min']:
        fallos.append('forma poco sólida (posible camino)')
    if compacidad < cfg['compacidad_min']:
        fallos.append('forma alargada o irregular')
    if coherencia < cfg['coherencia_min']:
        fallos.append('orientación de pasadas incoherente')
    if densidad < cfg['densidad_min_puntos_ha']:
        fallos.append('densidad de puntos baja')
    if dentro < cfg['fraccion_dentro_min']:
        fallos.append('traza poco contenida en el polígono')
    if len(fallos) >= 3:
        return 'NO_ES_CAMPO', fallos
    if area_ha < cfg['area_fragmento_ha'] or len(fallos) >= 1:
        if not fallos:
            fallos = ['área menor a 1 ha: se conserva como fragmento']
        return 'CAMPO_FRAGMENTO', fallos
    if solidez >= 0.50 and compacidad >= 0.04 and coherencia >= 0.35:
        return 'CAMPO_PROBABLE', ['cumple mínimos de área, forma y coherencia']
    return 'DUDOSO', (fallos or
                      ['no alcanza los mínimos de CAMPO_PROBABLE'])



