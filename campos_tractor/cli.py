"""Ejecuta el detector actual sobre una carpeta con el contrato documentado.

No incluye datos ni llamadas remotas. La ruta se pasa con --datos o
CAMPOS_DATA_DIR; la salida con --salida o CAMPOS_OUTPUT_DIR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pickle
import time
import tracemalloc

import yaml

from .exportar import exportar
from .filtro_mexico import filtrar_mexico
from .io import cargar_csv, cargar_por_maquina
from .pares import construir_pares_unidades
from .unidades import (CFG_CAMPOS, Unidad, detectar_unidades,
                          fusionar_por_rutas, resumen_campos)

RAIZ = Path(__file__).resolve().parents[1]
DATOS = Path(os.environ.get('CAMPOS_DATA_DIR', RAIZ / 'data'))
SALIDA = Path(os.environ.get('CAMPOS_OUTPUT_DIR', RAIZ / 'output'))


def _hash_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, 'rb') as a:
        for b in iter(lambda: a.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def _hash_cfg(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(
        {k: cfg[k] for k in sorted(cfg) if k != 'version'},
        sort_keys=True, default=str).encode()).hexdigest()[:16]


def _entradas(carpeta: Path) -> list[Path]:
    salida = []
    for ruta in sorted(carpeta.glob('*.csv')):
        with open(ruta, encoding='utf-8') as a:
            cab = a.readline().lower()
        if all(x in cab for x in ('timestamp', 'lat', 'lon', 'machine_id')):
            salida.append(ruta)
    return salida


def _cargar_cache(clave_id: str, cache: Path) -> list[Unidad] | None:
    p = cache / f'{clave_id}.pkl'
    if not p.is_file():
        return None
    try:
        with open(p, 'rb') as a:
            return pickle.load(a).get('unidades')
    except Exception:  # noqa: BLE001
        return None


def _guardar_cache(clave_id: str, unidades: list[Unidad], cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    with open(cache / f'{clave_id}.pkl', 'wb') as a:
        pickle.dump({'unidades': unidades}, a)


def main() -> int:
    p = argparse.ArgumentParser(description='Detector de campos de tractor')
    p.add_argument('--datos', default=str(DATOS),
                   help='Carpeta de CSV con timestamp, lat, lon, machine_id')
    p.add_argument('--salida', default=str(SALIDA))
    p.add_argument('--config', default=str(RAIZ / 'config_campos.yaml'))
    p.add_argument('--version', default=None)
    p.add_argument('--anterior', default=None,
                   help='GPKG de una versi?n anterior para la capa diferencias')
    p.add_argument('--sin-cache', action='store_true')
    p.add_argument('--sin-qgz', action='store_true')
    args = p.parse_args()
    cfg = dict(CFG_CAMPOS)
    config_path = Path(args.config)
    if config_path.is_file():
        datos_cfg = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
        cfg.update({k: v for bloque in ('tiempo', 'forma', 'fusion',
                                        'compuertas', 'base')
                    for k, v in (datos_cfg.get(bloque) or {}).items()})
    if args.version is None:
        from . import __version__
        args.version = __version__
    cfg['version'] = args.version
    carpeta = Path(args.datos)
    if not carpeta.is_dir():
        raise SystemExit(f'No existe la carpeta de datos: {carpeta}')
    archivos = _entradas(carpeta)
    if not archivos:
        raise SystemExit('No hay CSV con timestamp, lat, lon y machine_id')
    cache = Path(args.salida) / 'cache_unidades'
    inicio = time.perf_counter()
    tracemalloc.start()
    frames, unidades, fuera, tiempos = [], [], [], []
    clave_id_cfg = _hash_cfg(cfg)
    for ruta in archivos:
        t0 = time.perf_counter()
        datos = cargar_csv(ruta)
        for maquina, frame in cargar_por_maquina(datos).items():
            ruta_hash = hashlib.sha256(f'{ruta.name}|{maquina}'.encode()).hexdigest()[:16]
            limpio, fuera_ruta, resumen_filtro = filtrar_mexico(frame, ruta_hash)
            fuera.extend(fuera_ruta)
            frames.append(limpio)
            clave_id = f'{_hash_archivo(ruta)}_{maquina}_{clave_id_cfg}'
            unidades_cache = None if args.sin_cache else _cargar_cache(clave_id, cache)
            if unidades_cache is not None:
                unidades.extend(unidades_cache)
            else:
                nuevas = detectar_unidades(limpio, ruta_hash, cfg)
                unidades.extend(nuevas)
                if not args.sin_cache:
                    _guardar_cache(clave_id, nuevas, cache)
            tiempos.append({'archivo': ruta.name, 'maquina_hash': ruta_hash,
                            'n_puntos': len(limpio),
                            'n_fuera': len(fuera_ruta),
                            'n_unidades': len(unidades_cache) if unidades_cache is not None else len(nuevas),
                            'segundos': round(time.perf_counter() - t0, 2)})
    t_unidades = time.perf_counter()
    campos, rechazos = fusionar_por_rutas(unidades, cfg)
    t_fusion = time.perf_counter()
    pares = construir_pares_unidades(unidades, campos)
    destino = Path(args.salida) / args.version
    salida = exportar(
        frames, campos, unidades, fuera, args.version, destino, cfg=cfg,
        revision_gpkg=Path(args.salida) / 'revision_campos.gpkg',
        anterior_gpkg=Path(args.anterior) if args.anterior else None,
        pares=pares)
    t_export = time.perf_counter()
    resumen = {
        'version': args.version, 'n_archivos': len(archivos),
        'n_puntos': sum(len(f) for f in frames),
        **resumen_campos(campos),
        **{k: salida[k] for k in ('n_campos', 'n_descartados_area',
                                  'n_dispersos', 'n_unidades', 'n_pares',
                                  'n_fuera_mexico', 'area_confirmada_ha',
                                  'area_pendiente_grande_ha', 'diferencias')},
        'filtro_mexico': {'n_puntos_fuera': len(fuera),
                          'bbox': [14.5, 32.8, -118.5, -86.5],
                          'buffer_km': 10.0,
                          'poligono_disponible': False},
        'tiempos': {'unidades_s': round(t_unidades - inicio, 2),
                    'fusion_s': round(t_fusion - t_unidades, 2),
                    'export_s': round(t_export - t_fusion, 2),
                    'total_s': round(t_export - inicio, 2),
                    'por_archivo': tiempos},
        'rechazos_fusion': len(rechazos),
        'verificacion': salida['verificacion'],
    }
    actual, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    resumen['memoria'] = {'pico_mb': round(pico / 1024 / 1024, 1),
                          'actual_mb': round(actual / 1024 / 1024, 1)}
    destino.mkdir(parents=True, exist_ok=True)
    (destino / 'resumen.json').write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    if not args.sin_qgz:
        qgis = Path(os.getenv('QGIS_PYTHON', ''))
        if qgis.is_file():
            qgz = destino / f'campos_v{args.version.lstrip("v")}.qgz'
            # QGIS abre el GeoPackage en otro proceso y, en Windows, GDAL
            # mantiene bloqueadas las últimas capas hasta que este proceso
            # termina. Por eso el .qgz se genera en una segunda ejecución.
            print('QGZ: para crearlo, ejecuta:')
            print(f'  "{qgis}" -m campos_tractor.crear_qgz '
                  f'--gpkg "{salida["gpkg_4326"]}" '
                  f'--revision "{salida["revision_gpkg"]}" '
                  f'--qml "{salida["qml"]}" --salida "{qgz}"')
    print(f"campos: {salida['n_campos']} campos, {salida['n_dispersos']} dispersos, "
          f"{salida['n_unidades']} unidades, {salida['n_pares']} pares")
    print(f"GPKG: {salida['gpkg_4326']}")
    print(f"Tiempo: {resumen['tiempos']['total_s']} s; pico {resumen['memoria']['pico_mb']} MB")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
