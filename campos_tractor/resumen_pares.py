"""W5: resumen de la revisión de pares candidatos (MISMO_CAMPO / DISTINTOS).

No ajusta parámetros. Marca etiquetas invalidadas sin borrarlas.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .evaluacion import wilson_interval
from .utils import _asegurar_revision_pares

RESPUESTAS = ('MISMO_CAMPO', 'CAMPOS_DISTINTOS', 'NO_SE')


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()[:16]


def leer(ruta: Path) -> list[dict]:
    with sqlite3.connect(ruta) as c:
        c.row_factory = sqlite3.Row
        tablas = {f[0] for f in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if 'revision_pares' not in tablas:
            raise ValueError(f'{ruta}: no existe revision_pares')
        return [dict(f) for f in c.execute('SELECT * FROM revision_pares')]


def ids_actuales(campos_gpkg: Path) -> set[str]:
    import geopandas as gpd
    g = gpd.read_file(campos_gpkg, layer='pares_contiguos')
    return {str(x) for x in g['id_par'].tolist()}


def marcar(ruta: Path, ids: set[str], version: str,
           dry_run: bool = False) -> dict:
    if not dry_run:
        _asegurar_revision_pares(ruta)
    registros = leer(ruta)
    cambios, estados = [], {}
    for fila in registros:
        clave_id = str(fila.get('id_par') or '').strip()
        if not clave_id:
            vigente, motivo = 'SIN_EVALUAR', 'id_par vacío'
        elif clave_id not in ids:
            vigente = 'NO'
            motivo = f'id_par ausente en la versión {version}'
        else:
            vigente, motivo = 'SI', ''
        estados[clave_id] = (vigente, motivo)
        if (str(fila.get('vigente') or ''),
                str(fila.get('motivo_invalidez') or '')) != (vigente, motivo):
            cambios.append((clave_id, vigente, motivo))
    if not dry_run and cambios:
        with sqlite3.connect(ruta) as c:
            for clave_id, vigente, motivo in cambios:
                c.execute('UPDATE revision_pares SET vigente=?, '
                          'motivo_invalidez=? WHERE id_par=?',
                          (vigente, motivo, clave_id))
    if dry_run:
        for fila in registros:
            clave_id = str(fila.get('id_par') or '').strip()
            fila['vigente'], fila['motivo_invalidez'] = estados.get(
                clave_id, ('SIN_EVALUAR', 'id_par vacío'))
    return {'registros': registros, 'cambios': cambios}


def _dedup(registros: list[dict]) -> list[dict]:
    ultima = {}
    for i, fila in enumerate(registros):
        clave_id = str(fila.get('id_par') or '').strip()
        if not clave_id:
            continue
        fecha = str(fila.get('fecha') or '')
        if clave_id not in ultima or (fecha, i) >= (
                str(ultima[clave_id][1].get('fecha') or ''), ultima[clave_id][0]):
            ultima[clave_id] = (i, fila)
    return [f for _, f in sorted(ultima.values(), key=lambda x: x[0])]


def resumir(revision: Path, pares_gpkg: Path, version: str,
            salida: Path | None = None, dry_run: bool = False) -> dict:
    datos = marcar(revision, ids_actuales(pares_gpkg), version, dry_run)
    registros = _dedup(datos['registros'] if dry_run else leer(revision))
    desconocidas = sorted({str(f.get('respuesta')).strip()
                           for f in registros
                           if str(f.get('respuesta') or '').strip()
                           and str(f.get('respuesta')).strip() not in RESPUESTAS})
    if desconocidas:
        raise ValueError('Respuestas fuera de la lista cerrada: ' +
                         ', '.join(desconocidas))
    validos = [f for f in registros if str(f.get('vigente') or '') == 'SI'
               and str(f.get('respuesta') or '').strip()]
    invalidos = [f for f in registros if str(f.get('vigente') or '') == 'NO']
    n = len(validos)
    por = []
    for respuesta in RESPUESTAS:
        k = sum(1 for f in validos
                if str(f.get('respuesta')).strip() == respuesta)
        w = wilson_interval(k, n)
        por.append({'respuesta': respuesta, 'k': k, 'n': n, **w,
                    'indicativo': n < 30})
    resumen = {
        'generado_en': datetime.now(timezone.utc).isoformat(),
        'version': version, 'n_total': len(registros), 'n_validas': n,
        'n_invalidadas': len(invalidos), 'n_pequeno': n < 30,
        'nota_n': 'Con n<30 las proporciones son indicativas.',
        'por_respuesta': por,
        'invalidas': [{'id_par': f.get('id_par'),
                       'respuesta': f.get('respuesta'),
                       'motivo': f.get('motivo_invalidez')} for f in invalidos],
        'nota_ajuste': ('No se ajustan parámetros con estas etiquetas. '
                        'La partición ajuste/retención se reserva si n>=30.'),
    }
    if n >= 30:
        rutas = {}
        for f in validos:
            r = str(f.get('ruta_a') or 'SIN_RUTA')
            rutas[r] = rutas.get(r, 0) + 1
        orden = sorted(rutas, key=lambda x: (_hash(x), x))
        conteo = {'AJUSTE': 0, 'RETENCION': 0}
        asignacion = {}
        for r in orden:
            g = min(conteo, key=lambda x: (conteo[x], x))
            asignacion[r] = g
            conteo[g] += rutas[r]
        resumen['particion'] = [{'ruta_a': r, 'grupo': asignacion[r],
                                 'n': rutas[r]} for r in orden]
        for grupo in ('AJUSTE', 'RETENCION'):
            sub = [f for f in validos
                   if asignacion.get(str(f.get('ruta_a') or 'SIN_RUTA')) == grupo]
            resumen[grupo.lower()] = {'n': len(sub)}
    if salida is not None:
        salida.mkdir(parents=True, exist_ok=True)
        (salida / 'resumen_pares.json').write_text(
            json.dumps(resumen, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8')
        with open(salida / 'resumen_pares.csv', 'w', newline='',
                  encoding='utf-8') as a:
            e = csv.DictWriter(a, fieldnames=['respuesta', 'k', 'n', 'p',
                                              'bajo', 'alto', 'indicativo'])
            e.writeheader()
            for f in por:
                e.writerow(f)
    return resumen


def main() -> int:
    p = argparse.ArgumentParser(description='Resumen de la revisión de pares')
    p.add_argument('--revision', required=True)
    p.add_argument('--pares', required=True,
                   help='GPKG con capa pares_contiguos')
    p.add_argument('--version', default='actual')
    p.add_argument('--salida', default=None)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    r = resumir(Path(args.revision), Path(args.pares), args.version,
                Path(args.salida) if args.salida else None, args.dry_run)
    print(f"Pares: {r['n_validas']} válidos, {r['n_invalidadas']} invalidados, "
          f"{r['n_total']} filas")
    for f in r['por_respuesta']:
        if f['n']:
            print(f"  {f['respuesta']:18} {f['k']:3}/{f['n']:<3} "
                  f"p={f['p']:.3f} IC95 [{f['bajo']:.3f}, {f['alto']:.3f}]")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
