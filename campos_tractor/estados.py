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


def clasificar_cobertura_estricta(
        area_ha: float, n_puntos: int, n_unidades: int, horas: float,
        solidez: float, compacidad: float, densidad_puntos_ha: float,
        coherencia_orientacion: float,
        aspect_ratio: float = 1.0,
        ancho_m: float = 0.0) -> dict | None:
    """Aplica las reglas estrictas de caminos, ruido y campo.

    Devuelve ``None`` cuando ninguna regla concluyente aplica; en ese caso el
    llamador conserva la clasificación histórica. El dictamen sigue el contrato
    ``categoria_final / subcategoria / cuenta_ha_valida / metrica_detonante``.
    """
    # 1. Geometría lineal: camino, acotamiento o traslado.
    # Señales: ancho físico insuficiente (<25m), elongación extrema o moderada,
    # o bien trazado poco sólido / poco compacto (camino serpenteante).
    es_camino = False
    metrica_camino = ''

    # 1a. Ancho estrecho (<25m): incompatible con el ancho útil de un campo agrícola.
    if 0 < ancho_m < 25.0:
        if aspect_ratio > 2.0 or n_unidades <= 2:
            es_camino = True
            metrica_camino = 'ancho_m'

    # 1b. Elongación extrema (aspect_ratio >= 8.0).
    elif aspect_ratio >= 8.0:
        # Solo un campo agrícola muy grande y ancho con muchas unidades puede tener AR >= 8.
        if not (area_ha >= 2.0 and n_unidades >= 10 and ancho_m >= 50.0):
            es_camino = True
            metrica_camino = 'solidez' if solidez < 0.25 else ('compacidad' if compacidad < 0.08 else 'aspect_ratio')

    # 1c. Elongación moderada (aspect_ratio >= 5.0) con características de camino/traslado.
    elif aspect_ratio >= 5.0:
        if (0 < ancho_m < 35.0) or n_unidades <= 3 or horas < 0.50:
            es_camino = True
            metrica_camino = 'solidez' if solidez < 0.25 else ('compacidad' if compacidad < 0.08 else 'aspect_ratio')

    # 1d. Trazado poco sólido o poco compacto (camino curvo/serpenteante o acotamiento).
    elif solidez < 0.25 or compacidad < 0.08:
        if (n_unidades <= 2 or coherencia_orientacion >= 0.95 or aspect_ratio > 4.0):
            if ancho_m < 35.0 or n_unidades <= 2 or horas < 0.30:
                es_camino = True
                metrica_camino = 'solidez' if solidez < 0.25 else 'compacidad'

    if es_camino:
        return {
            'categoria_final': 'TRAYECTO_DISPERSO',
            'subcategoria': 'NO_ES_CAMPO',
            'cuenta_ha_valida': False,
            'metrica_detonante': metrica_camino,
            'causa': 'forma_lineal',
            'motivo': ('Geometría extremadamente alargada o estrecha '
                       'compatible con camino o acotamiento'),
        }
    # 2. Esfuerzo insuficiente: pocos puntos y menos de 9 minutos.
    if n_puntos < 40 and horas < 0.15:
        if densidad_puntos_ha < 70 or n_unidades == 1:
            metrica = ('densidad_puntos_ha'
                       if densidad_puntos_ha < 70 else 'n_unidades')
            return {
                'categoria_final': 'TRAYECTO_DISPERSO',
                'subcategoria': 'NO_ES_CAMPO',
                'cuenta_ha_valida': False,
                'metrica_detonante': metrica,
                'causa': 'esfuerzo_insuficiente',
                'motivo': ('Baja densidad de puntos y corta duración sin '
                           'iteración de pasadas'),
            }
    # 3. Micro-fragmento por ruido de cobertura.
    if area_ha < 0.10 and solidez < 0.40:
        metrica = 'cuenta_ha' if area_ha < 0.10 else 'solidez'
        return {
            'categoria_final': 'TRAYECTO_DISPERSO',
            'subcategoria': 'RUIDO_COBERTURA',
            'cuenta_ha_valida': False,
            'metrica_detonante': metrica,
            'causa': 'ruido_cobertura',
            'motivo': 'Área inferior al umbral mínimo con baja solidez',
        }
    # 4. Campo o fragmento válido.
    if solidez >= 0.25 and compacidad >= 0.08:
        if area_ha >= 0.60 or (n_unidades >= 3 and n_puntos >= 40):
            metrica = 'cuenta_ha' if area_ha >= 0.60 else 'n_unidades'
            return {
                'categoria_final': 'CAMPO',
                'subcategoria': 'TRABAJO_AGRICOLA',
                'cuenta_ha_valida': True,
                'metrica_detonante': metrica,
                'causa': 'trabajo_agricola',
                'motivo': ('Cobertura sólida con pasadas estructuradas de '
                           'trabajo agrícola'),
            }
        return {
            'categoria_final': 'CAMPO_FRAGMENTO',
            'subcategoria': 'TRABAJO_AGRICOLA',
            'cuenta_ha_valida': True,
            'metrica_detonante': 'cuenta_ha',
            'causa': 'trabajo_agricola',
            'motivo': ('Área de trabajo agrícola fraccionada con parámetros '
                       'aceptables de solidez'),
        }
    return None


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



