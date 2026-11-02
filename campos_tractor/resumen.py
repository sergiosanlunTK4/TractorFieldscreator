"""V5: resumen del paquete de revisión y control de etiquetas invalidadas.

Lee ``revision_campos.gpkg`` (tabla no espacial ``revision``), valida que las
respuestas pertenezcan a la lista cerrada, marca —sin borrar— las etiquetas
cuyo ``id_estable`` ya no existe en la versión actual y resume proporciones con
intervalo de Wilson.

La partición ajuste/retención se reserva cuando hay >= 30 etiquetas. Este script
NO ajusta parámetros automáticamente: hacerlo sobre las mismas etiquetas que
luego se usarían para declarar éxito invalidaría la afirmación.
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
from .utils import _asegurar_revision

RESPUESTAS = ('CORRECTO', 'DEMASIADO_GRANDE', 'PARCIAL_O_PEQUEÑO',
              'FUNDIDO_VARIOS', 'PARTIDO_EN_VARIOS', 'NO_ES_CAMPO', 'NO_SE')

# Qué parámetro del detector es el candidato más probable para cada tipo de fallo.
CANDIDATOS = {
    'DEMASIADO_GRANDE': ['concave_ratio (bajar)', 'buffer_m (quitar)',
                         'simplificar_m (subir)'],
    'PARCIAL_O_PEQUEÑO': ['buffer_m (subir)', 'concave_ratio (subir)',
                          'simplificar_m (bajar)'],
    'FUNDIDO_VARIOS': ['campo_eps_m (bajar)', 'pasada_cluster_eps_m (bajar)',
                       'tolerancia_fusion_grados (bajar)'],
    'PARTIDO_EN_VARIOS': ['campo_eps_m (subir)', 'pasada_cluster_eps_m (subir)',
                          'area_min_ha (revisar)'],
    'NO_ES_CAMPO': ['area_min_ha (subir)', 'solidez_min (subir)',
                    'compacidad_min (subir)', 'densidad_min_puntos_ha (subir)'],
    'CORRECTO': [],
    'NO_SE': [],
}


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()[:16]


def leer_revision(ruta: str | Path) -> list[dict]:
    ruta = Path(ruta)
    if not ruta.is_file():
        raise FileNotFoundError(f'No existe {ruta}')
    with sqlite3.connect(ruta) as conexion:
        conexion.row_factory = sqlite3.Row
        tablas = {fila[0] for fila in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if 'revision' not in tablas:
            raise ValueError(f'{ruta}: no existe la tabla revision')
        return [dict(fila) for fila in conexion.execute('SELECT * FROM revision')]


def _deduplicar(registros: list[dict]) -> tuple[list[dict], int]:
    """Una respuesta por id: conserva la fila más reciente."""
    ultima = {}
    for indice, fila in enumerate(registros):
        clave_id = str(fila.get('id_estable') or '').strip()
        if not clave_id:
            continue
        fecha = str(fila.get('fecha') or '')
        actual = ultima.get(clave_id)
        if actual is None or (fecha, indice) >= (str(actual[1].get('fecha') or ''),
                                                actual[0]):
            ultima[clave_id] = (indice, fila)
    salida = [fila for _, fila in sorted(ultima.values(), key=lambda x: x[0])]
    return salida, len(registros) - len(salida)


def ids_de_version(campos_gpkg: str | Path) -> set[str]:
    import geopandas as gpd
    ruta = Path(campos_gpkg)
    capa = 'campos'
    if ruta.suffix.lower() == '.gpkg':
        gdf = gpd.read_file(ruta, layer=capa)
    else:
        gdf = gpd.read_file(ruta)
    return {str(x) for x in gdf['id_estable'].tolist()}


def marcar_vigencia(revision: str | Path, ids_actuales: set[str],
                    version_actual: str, dry_run: bool = False) -> dict:
    """Marca SI/NO sin borrar filas. Devuelve el conteo de cambios."""
    ruta = Path(revision)
    if dry_run:
        registros = leer_revision(ruta)
    else:
        # Migra una tabla de revisión antigua creada como capa (con triggers
        # R*Tree que sqlite3 no puede evaluar) a tabla de atributos.
        _asegurar_revision(ruta)
        registros = leer_revision(ruta)
    cambios = []
    estados = {}
    for fila in registros:
        clave_id = str(fila.get('id_estable') or '').strip()
        if not clave_id:
            vigente, motivo = 'SIN_EVALUAR', 'id_estable vacío'
        elif clave_id not in ids_actuales:
            vigente = 'NO'
            motivo = f'id_estable ausente en la versión {version_actual}'
        else:
            vigente, motivo = 'SI', ''
        estados[clave_id] = (vigente, motivo)
        anterior = str(fila.get('vigente') or '')
        if (anterior, str(fila.get('motivo_invalidez') or '')) != (vigente, motivo):
            cambios.append((clave_id, vigente, motivo, anterior))
    if not dry_run and cambios:
        with sqlite3.connect(ruta) as conexion:
            for clave_id, vigente, motivo, _ in cambios:
                conexion.execute(
                    'UPDATE revision SET vigente=?, motivo_invalidez=? '
                    'WHERE id_estable=?', (vigente, motivo, clave_id))
    return {'n_marcadas': len(cambios),
            'n_invalidadas': sum(1 for c in cambios if c[1] == 'NO'),
            'estados': estados,
            'detalle': [{'id_estable': c[0], 'vigente': c[1],
                         'motivo': c[2], 'vigente_anterior': c[3]}
                        for c in cambios]}


def _validar_respuestas(registros: list[dict]) -> None:
    desconocidas = sorted({str(f.get('respuesta')).strip()
                           for f in registros
                           if str(f.get('respuesta') or '').strip()
                           and str(f.get('respuesta')).strip() not in RESPUESTAS})
    if desconocidas:
        raise ValueError('Respuestas fuera de la lista cerrada: '
                         + ', '.join(desconocidas))


def _resumen_respuestas(registros: list[dict]) -> list[dict]:
    total = len(registros)
    salida = []
    for respuesta in RESPUESTAS:
        k = sum(1 for f in registros
                if str(f.get('respuesta') or '').strip() == respuesta)
        intervalo = wilson_interval(k, total)
        salida.append({'respuesta': respuesta, 'k': k, 'n': total,
                       **{c: intervalo[c] for c in ('p', 'bajo', 'alto')},
                       'indicativo': total < 30})
    sin = sum(1 for f in registros if not str(f.get('respuesta') or '').strip())
    return salida + [{'respuesta': 'SIN_RESPUESTA', 'k': sin, 'n': total,
                      'p': round(sin / total, 3) if total else 0.0,
                      'bajo': None, 'alto': None,
                      'indicativo': total < 30}]


def _particion_por_ruta(registros: list[dict]) -> list[dict]:
    rutas = {}
    for fila in registros:
        ruta = str(fila.get('ruta_hash') or 'SIN_RUTA')
        rutas[ruta] = rutas.get(ruta, 0) + 1
    if len(rutas) < 2:
        return []
    orden = sorted(rutas, key=lambda r: (_hash(r), r))
    conteo = {'AJUSTE': 0, 'RETENCION': 0}
    asignacion = {}
    for ruta in orden:
        grupo = min(conteo, key=lambda g: (conteo[g], g))
        asignacion[ruta] = grupo
        conteo[grupo] += rutas[ruta]
    return [{'ruta_hash': r, 'grupo': asignacion[r], 'n_etiquetas': rutas[r]}
            for r in orden]


def _resumen_grupo(registros: list[dict]) -> dict:
    return {'n': len(registros),
            'por_respuesta': _resumen_respuestas(registros) if registros else []}


def resumir(revision: str | Path, campos_gpkg: str | Path,
            version_actual: str, salida: str | Path | None = None,
            dry_run: bool = False) -> dict:
    ruta_revision = Path(revision)
    registros, duplicados = _deduplicar(leer_revision(ruta_revision))
    _validar_respuestas(registros)
    ids = ids_de_version(campos_gpkg)
    cambios = marcar_vigencia(ruta_revision, ids, version_actual, dry_run)
    if dry_run:
        for fila in registros:
            clave_id = str(fila.get('id_estable') or '').strip()
            vigente, motivo = cambios['estados'].get(
                clave_id, ('SIN_EVALUAR', 'id_estable vacío'))
            fila['vigente'], fila['motivo_invalidez'] = vigente, motivo
    else:
        # Releer para usar la vigencia recién marcada.
        registros, _ = _deduplicar(leer_revision(ruta_revision))
    validos = [f for f in registros if str(f.get('vigente') or '') == 'SI'
               and str(f.get('respuesta') or '').strip()]
    invalidos = [f for f in registros if str(f.get('vigente') or '') == 'NO']
    problemas = {}
    for fila in validos:
        respuesta = str(fila.get('respuesta') or '').strip()
        if respuesta in ('', 'CORRECTO', 'NO_SE'):
            continue
        problemas.setdefault(respuesta, []).append({
            'id_estable': fila.get('id_estable'),
            'ruta_hash': fila.get('ruta_hash'),
            'comentario': fila.get('comentario'),
            'version_revisada': fila.get('version_revisada'),
        })
    resumen = {
        'generado_en': datetime.now(timezone.utc).isoformat(),
        'version_actual': version_actual,
        'revision_gpkg': str(ruta_revision),
        'campos_gpkg': str(campos_gpkg),
        'n_filas': len(registros),
        'n_duplicados_descartados': duplicados,
        'n_validas': len(validos),
        'n_invalidadas': len(invalidos),
        'n_sin_respuesta': len(registros) - len(validos) - len(invalidos),
        'n_pequeno': len(validos) < 30,
        'nota_n': ('Con n<30 las proporciones son indicativas; no afirmar '
                   'exactitud.'),
        'por_respuesta': _resumen_respuestas(validos),
        'invalidas': [{'id_estable': f.get('id_estable'),
                       'respuesta': f.get('respuesta'),
                       'version_revisada': f.get('version_revisada'),
                       'motivo': f.get('motivo_invalidez')} for f in invalidos],
        'cambios_vigencia': cambios['detalle'],
        'campos_problematicos': problemas,
        'candidatos_por_fallo': {
            respuesta: CANDIDATOS.get(respuesta, [])
            for respuesta in RESPUESTAS
            if any(str(f.get('respuesta') or '').strip() == respuesta
                   for f in validos)},
        'nota_ajuste': ('No se ajustan parámetros automáticamente. Si hay '
                        '>=30 etiquetas, la partición ajuste/retención queda '
                        'reservada para que el ajuste no use la mitad que '
                        'luego declararía el éxito.'),
    }
    particion = _particion_por_ruta(validos) if len(validos) >= 30 else []
    resumen['particion'] = particion
    if particion:
        mapa = {fila['ruta_hash']: fila['grupo'] for fila in particion}
        ajuste = [f for f in validos
                  if mapa.get(str(f.get('ruta_hash') or 'SIN_RUTA')) == 'AJUSTE']
        retencion = [f for f in validos
                     if mapa.get(str(f.get('ruta_hash') or 'SIN_RUTA')) == 'RETENCION']
        resumen['resumen_ajuste'] = _resumen_grupo(ajuste)
        resumen['resumen_retencion'] = _resumen_grupo(retencion)
    if salida is not None:
        _escribir_salidas(Path(salida), resumen, validos, invalidos)
    return resumen


def _escribir_salidas(salida: Path, resumen: dict, validos: list[dict],
                      invalidos: list[dict]) -> None:
    salida.mkdir(parents=True, exist_ok=True)
    (salida / 'resumen_revision.json').write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    with open(salida / 'revision_resumen.csv', 'w', newline='',
              encoding='utf-8') as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=['respuesta', 'k', 'n', 'p', 'bajo', 'alto',
                                 'indicativo'])
        escritor.writeheader()
        for fila in resumen['por_respuesta']:
            escritor.writerow(fila)
    with open(salida / 'revision_invalidadas.csv', 'w', newline='',
              encoding='utf-8') as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=['id_estable', 'respuesta', 'version_revisada',
                                 'motivo'])
        escritor.writeheader()
        for fila in resumen['invalidas']:
            escritor.writerow(fila)
    if resumen['particion']:
        with open(salida / 'revision_particion.csv', 'w', newline='',
                  encoding='utf-8') as archivo:
            escritor = csv.DictWriter(
                archivo, fieldnames=['ruta_hash', 'grupo', 'n_etiquetas'])
            escritor.writeheader()
            for fila in resumen['particion']:
                escritor.writerow(fila)
    with open(salida / 'revision_problematicos.csv', 'w', newline='',
              encoding='utf-8') as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=['tipo_fallo', 'id_estable', 'ruta_hash',
                                 'comentario', 'version_revisada',
                                 'parametros_candidatos'])
        escritor.writeheader()
        for tipo, filas in resumen['campos_problematicos'].items():
            for fila in filas:
                escritor.writerow({
                    'tipo_fallo': tipo,
                    'id_estable': fila.get('id_estable'),
                    'ruta_hash': fila.get('ruta_hash'),
                    'comentario': fila.get('comentario'),
                    'version_revisada': fila.get('version_revisada'),
                    'parametros_candidatos': '; '.join(
                        CANDIDATOS.get(tipo, [])),
                })
    with open(salida / 'revision_etiquetas_validas.csv', 'w', newline='',
              encoding='utf-8') as archivo:
        campos = ['id_estable', 'ruta_hash', 'respuesta', 'comentario',
                  'revisor', 'fecha', 'version_revisada']
        escritor = csv.DictWriter(archivo, fieldnames=campos)
        escritor.writeheader()
        for fila in validos:
            escritor.writerow({k: fila.get(k) for k in campos})


def main() -> int:
    parser = argparse.ArgumentParser(description='V5: resumir revisión')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--campos', required=True,
                        help='GPKG de la versión actual (capa campos)')
    parser.add_argument('--version', default='actual')
    parser.add_argument('--salida', default=None)
    parser.add_argument('--dry-run', action='store_true',
                        help='No marca vigencia; sólo resume')
    args = parser.parse_args()
    resumen = resumir(args.revision, args.campos, args.version,
                      args.salida, dry_run=args.dry_run)
    print(f"Revisión: {resumen['n_filas']} filas, "
          f"{resumen['n_validas']} válidas, "
          f"{resumen['n_invalidadas']} invalidadas, "
          f"{resumen['n_sin_respuesta']} sin respuesta")
    for fila in resumen['por_respuesta']:
        if fila['respuesta'] == 'SIN_RESPUESTA':
            continue
        if fila['n']:
            print(f"  {fila['respuesta']:20} {fila['k']:3}/{fila['n']:<3} "
                  f"p={fila['p']:.3f} IC95 [{fila['bajo']:.3f}, "
                  f"{fila['alto']:.3f}]"
                  + ('  (indicativo n<30)' if fila['indicativo'] else ''))
    if resumen['n_pequeno']:
        print('Aviso: n<30; las proporciones son indicativas.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
