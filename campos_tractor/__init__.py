"""Detección y agrupación de campos de tractor a partir de trayectorias.

Entrada: timestamp UTC, lat, lon, machine_id y, opcionalmente, speed_kmh/state.
Salida: campos, unidades, pares y GeoPackage/QGZ de revisión.

El paquete no contiene clientes de API, base de datos, datos reales ni
estimación de ancho.
"""
from ._compat import CFG_SESIONES
from .detector import detectar_campos
from .estados import (CFG_DETECCION, CampoDetectado, ESTADOS,
                      clasificar_cobertura_estricta)
from .filtro_mexico import CFG_MEXICO, filtrar_mexico
from .io import cargar_csv, cargar_dataframe, cargar_por_maquina
from .metricas import calcular_aspect_ratio
from .salidas import (detectar_campos_por_estado, resumen_salidas,
                      separar_por_estado)
from .unidades import (CFG_CAMPOS, Campo, Unidad, detectar_unidades,
                       fusionar_por_rutas, fusionar_unidades, resumen_campos)

__all__ = [
    'CFG_SESIONES', 'CFG_DETECCION', 'CFG_CAMPOS', 'CFG_MEXICO',
    'CampoDetectado', 'Campo', 'Unidad', 'ESTADOS',
    'cargar_csv', 'cargar_dataframe', 'cargar_por_maquina',
    'calcular_aspect_ratio', 'clasificar_cobertura_estricta',
    'detectar_campos', 'detectar_campos_por_estado', 'detectar_unidades',
    'filtrar_mexico', 'fusionar_por_rutas', 'fusionar_unidades',
    'resumen_campos', 'resumen_salidas', 'separar_por_estado',
]

__version__ = '0.4.0'
