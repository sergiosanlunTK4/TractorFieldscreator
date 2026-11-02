"""Fachada del detector actual: unidades temporales + fusión jerárquica."""
from __future__ import annotations

from .unidades import (CFG_CAMPOS, Campo, detectar_unidades,
                       fusionar_unidades)


def detectar_campos(frame, ruta_hash: str, cfg: dict | None = None):
    unidades = detectar_unidades(frame, ruta_hash, cfg)
    campos, rechazos = fusionar_unidades(unidades, cfg or CFG_CAMPOS)
    return campos, unidades, rechazos
