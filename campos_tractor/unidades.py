"""Y2-Y4: unidades de trabajo en orden temporal, huella bufferizada y fusión
jerárquica sin encadenamiento.

El tiempo define la conectividad; el espacio define la forma. No usa ancho.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, MultiPoint, Point, Polygon, MultiPolygon
from shapely.ops import transform as shapely_transform, unary_union

from ._compat import _epsg_utm
from .estados import (CFG_DETECCION, _clasificar,
                      clasificar_cobertura_estricta)
from .metricas import calcular_aspect_ratio, calcular_dimensiones_mbb
from .proyeccion import invertir_xy, origen_desde_primera

CFG_CAMPOS = {
    **CFG_DETECCION,
    'version': 'campos-tractor',
    # Y2: puente temporal.
    'trabajo_gap_s': 300.0,
    'vel_min_kmh': 1.0,
    'vel_max_kmh': 15.0,
    'paso_max_m': 350.0,
    'giro_ventana': 3,
    'giro_sostenido_deg': 220.0,
    'unidad_min_puntos': 10,
    'traslado_min_m': 300.0,
    'traslado_vel_min_kmh': 15.0,
    # Y3: huella.
    'buffer_factor': 0.20,
    'buffer_min_m': 3.0,
    'buffer_max_m': 5.0,
    'closing_m': 2.0,
    # Y4: fusión jerárquica.
    'union_dist_m': 0.0,
    'union_query_buffer_m': 0.0,
    'union_overlap_min': 0.08,
    'union_gap_s': 300.0,
    'union_orient_deg': 30.0,
    'union_solidez_min': 0.30,
    'union_compacidad_min': 0.020,
    'union_densidad_min': 20.0,
    'union_max_extension_m': 10_000.0,
    'union_max_area_ha': 2_000.0,
    # Y1: compuertas explícitas.
    'densidad_min_puntos_ha': 20.0,
    'max_gap_m': 300.0,
    'grande_area_ha': 100.0,
    'area_descarte_ha': 0.10,
    'ancho_min_campo_m': 25.0,
    'aspect_ratio_max': 6.0,
    'compacidad_fragmento_min': 0.05,
    # Base/patio.
    'base_min_sesiones': 20,
    'base_min_dias': 15,
    'base_min_horas': 20.0,
    'base_speed_max': 3.0,
    'base_frac_idle_min': 0.30,
    'base_min_evidencias': 3,
    'concave_ratio_visita': 0.35,
}

ESTADOS_CAMPO = ('CAMPO_PROBABLE', 'CAMPO_FRAGMENTO', 'DUDOSO', 'NO_ES_CAMPO',
              'TRAYECTO_DISPERSO')


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()[:16]


def _a_utm(geom, epsg: int):
    trans = Transformer.from_crs('EPSG:4326', f'EPSG:{epsg}', always_xy=True)
    return shapely_transform(trans.transform, geom)


def _forma(geom):
    area = float(geom.area)
    if area <= 0:
        return 0.0, 0.0, 0.0
    hull = geom.convex_hull
    solidez = area / hull.area if hull.area > 0 else 0.0
    perimetro = float(geom.length)
    compacidad = 4 * math.pi * area / (perimetro ** 2) if perimetro else 0.0
    return area, solidez, compacidad


@dataclass
class Unidad:
    id_unidad: str
    ruta_hash: str
    archivo: str
    indices: np.ndarray
    xy: np.ndarray
    tiempos: np.ndarray
    geometry_local: Polygon | MultiPolygon
    core_local: Polygon | MultiPolygon | None
    core_wgs84: Polygon | MultiPolygon | None
    core_utm: Polygon | MultiPolygon | None
    geometry_wgs84: Polygon | MultiPolygon | None
    geometry_utm: Polygon | MultiPolygon | None
    epsg_utm: int
    n_puntos: int
    t_inicio: pd.Timestamp | None
    t_fin: pd.Timestamp | None
    area_ha: float
    perimetro_m: float
    solidez: float
    compacidad: float
    orientacion: float
    coherencia: float
    densidad_puntos_ha: float
    max_gap_m: float
    speed_p50: float | None
    speed_p90: float | None
    state_cobertura: float
    frac_working: float
    frac_idle: float
    frac_transport: float
    tipo: str = 'TRABAJO'
    motivo: str = ''
    sesion_id: str = ''


@dataclass
class Campo:
    id_estable: str
    campo_id: int
    geometry: Polygon | MultiPolygon
    geometry_utm: Polygon | MultiPolygon
    epsg_utm: int
    unidades: list[Unidad]
    puntos: np.ndarray
    tiempos: np.ndarray
    rutas: np.ndarray
    n_puntos: int
    n_unidades: int
    n_dias: int
    n_maquinas: int
    n_sesiones: int
    horas: float
    t_inicio: str
    t_fin: str
    area_ha: float
    perimetro_m: float
    solidez: float
    compacidad: float
    aspect_ratio: float
    orientacion: float
    coherencia: float
    densidad_puntos_ha: float
    max_gap_m: float
    speed_p50: float | None
    speed_p90: float | None
    state_cobertura: float
    frac_working: float
    frac_idle: float
    frac_transport: float
    estado: str
    confianza: float
    motivos: list[str]
    causa_fragmento: str
    categoria: str
    requiere_revision: int
    cuenta_ha: float
    diagnostico_grande: str
    parece_campo: str
    rutas_hash: str
    ruta_principal: str
    subcategoria: str = ''
    metrica_detonante: str = ''
    cuenta_ha_valida: bool = False
    ancho_mbb: float = 0.0
    largo_mbb: float = 0.0
    version_algoritmo: str = 'campos-tractor'

    def to_dict(self) -> dict:
        return {
            'id_estable': self.id_estable,
            'ruta_hash': self.ruta_principal,
            'rutas_hash': self.rutas_hash,
            'campo_id': int(self.campo_id),
            'n_puntos': int(self.n_puntos),
            'n_unidades': int(self.n_unidades),
            'n_dias': int(self.n_dias),
            'n_maquinas': int(self.n_maquinas),
            'n_sesiones': int(self.n_sesiones),
            'horas': round(float(self.horas), 2),
            't_inicio': self.t_inicio,
            't_fin': self.t_fin,
            'area_ha': round(float(self.area_ha), 6),
            'perimetro_m': round(float(self.perimetro_m), 1),
            'estado': self.estado,
            'confianza': round(float(self.confianza), 3),
            'motivo': '; '.join(self.motivos),
            'causa_fragmento': self.causa_fragmento,
            'categoria': self.categoria,
            'requiere_revision': int(self.requiere_revision),
            'cuenta_ha': round(float(self.cuenta_ha), 6),
            'diagnostico_grande': self.diagnostico_grande,
            'parece_campo': self.parece_campo,
            'version_algoritmo': self.version_algoritmo,
            'epsg_utm': int(self.epsg_utm),
            'solidez': round(float(self.solidez), 3),
            'compacidad': round(float(self.compacidad), 3),
            'aspect_ratio': round(float(self.aspect_ratio), 3),
            'ancho_mbb': round(float(self.ancho_mbb), 1),
            'largo_mbb': round(float(self.largo_mbb), 1),
            'subcategoria': self.subcategoria,
            'metrica_detonante': self.metrica_detonante,
            'cuenta_ha_valida': int(bool(self.cuenta_ha_valida)),
            'densidad_puntos_ha': round(float(self.densidad_puntos_ha), 1),
            'coherencia_orientacion': round(float(self.coherencia), 3),
            'max_gap_m': round(float(self.max_gap_m), 1),
            'orientacion': round(float(self.orientacion), 1),
            'speed_p50': self.speed_p50,
            'speed_p90': self.speed_p90,
            'state_cobertura': round(float(self.state_cobertura), 3),
            'frac_working': round(float(self.frac_working), 3),
            'frac_idle': round(float(self.frac_idle), 3),
            'frac_transport': round(float(self.frac_transport), 3),
            'unidades': ';'.join(u.id_unidad for u in self.unidades),
            'descartado_area': 0,
            'en_muestra': 0,
        }


def _senales(grupo: pd.DataFrame) -> dict:
    velocidad = pd.to_numeric(grupo.get('speed_kmh_origen'), errors='coerce') \
        if 'speed_kmh_origen' in grupo else None
    estado = grupo.get('state_origen')
    n = len(grupo)
    n_vel = int(velocidad.notna().sum()) if velocidad is not None else 0
    n_est = int(estado.notna().sum()) if estado is not None else 0
    est = estado.astype(str).str.strip().str.lower() if estado is not None else None
    return {
        'speed_p50': round(float(velocidad.quantile(.5)), 2) if n_vel else None,
        'speed_p90': round(float(velocidad.quantile(.9)), 2) if n_vel else None,
        'state_cobertura': round(n_est / n, 3),
        'frac_working': round(float((est == 'working').sum()) / n_est, 3) if n_est else 0.0,
        'frac_idle': round(float((est == 'idle').sum()) / n_est, 3) if n_est else 0.0,
        'frac_transport': round(float((est == 'transport').sum()) / n_est, 3) if n_est else 0.0,
    }


def _huella(xy: np.ndarray, cfg: dict) -> Polygon | MultiPolygon | None:
    if len(xy) < 2:
        return None
    dif = np.diff(xy, axis=0)
    distancias = np.hypot(dif[:, 0], dif[:, 1])
    validas = distancias[(distancias > 0) & np.isfinite(distancias)]
    mediana = float(np.median(validas)) if len(validas) else 0.0
    radio = max(float(cfg['buffer_min_m']),
                min(float(cfg['buffer_max_m']),
                    float(cfg['buffer_factor']) * mediana))
    try:
        linea = LineString(xy)
        geom = linea.buffer(radio, cap_style=1, join_style=1)
        cierre = min(float(cfg['closing_m']), radio)
        if cierre > 0:
            geom = geom.buffer(cierre, join_style=1).buffer(-cierre, join_style=1)
        if geom.is_valid and not geom.is_empty and geom.area > 0:
            return geom
    except Exception:  # noqa: BLE001
        pass
    return MultiPoint(xy).convex_hull


def _georreferenciar(unidad: Unidad, frame: pd.DataFrame) -> None:
    primera = frame.iloc[0]
    origen = origen_desde_primera({
        'x_m': float(primera['X_global']), 'y_m': float(primera['Y_global']),
        'pasada': 0,
        'origen_lat0': primera.get('origen_lat0'),
        'origen_lon0': primera.get('origen_lon0'),
        'origen_x_m': primera.get('origen_x_m'),
        'origen_y_m': primera.get('origen_y_m'),
    })
    x0 = float(frame['X_global'].iloc[0] - frame['X'].iloc[0])
    y0 = float(frame['Y_global'].iloc[0] - frame['Y'].iloc[0])

    def convertir(x, y):
        return invertir_xy(np.asarray(x) + x0, np.asarray(y) + y0, origen)

    wgs = shapely_transform(convertir, unidad.geometry_local)
    centro = wgs.centroid
    epsg = int(_epsg_utm(centro.x, centro.y))
    unidad.geometry_wgs84 = wgs
    unidad.geometry_utm = _a_utm(wgs, epsg)
    if unidad.core_local is not None:
        core_wgs = shapely_transform(convertir, unidad.core_local)
        unidad.core_wgs84 = core_wgs
        unidad.core_utm = _a_utm(core_wgs, epsg)
    unidad.epsg_utm = epsg


def _crear_unidad(frame: pd.DataFrame, posiciones: np.ndarray, ruta_hash: str,
                  archivo: str, cfg: dict, sesiones: np.ndarray) -> Unidad | None:
    if len(posiciones) < int(cfg['unidad_min_puntos']):
        return None
    grupo = frame.iloc[posiciones]
    xy = grupo[['X', 'Y']].to_numpy(dtype=float)
    geom = _huella(xy, cfg)
    if geom is None or geom.is_empty:
        return None
    geom = geom.simplify(1.5, preserve_topology=True)
    area, solidez, compacidad = _forma(geom)
    if area <= 0:
        return None
    rumbos = pd.to_numeric(grupo.get('Bearing'), errors='coerce').to_numpy(dtype=float)
    validos = np.isfinite(rumbos)
    if validos.sum() >= 2:
        vector = np.exp(1j * np.radians(2.0 * rumbos[validos])).mean()
        orientacion = float((math.degrees(np.angle(vector)) / 2.0) % 180.0)
        coherencia = float(abs(vector))
    else:
        orientacion, coherencia = 0.0, 0.0
    dif = np.diff(xy, axis=0)
    distancias = np.hypot(dif[:, 0], dif[:, 1])
    max_gap = float(np.max(distancias)) if len(distancias) else 0.0
    t = pd.to_datetime(grupo['Timestamp'], errors='coerce') if 'Timestamp' in grupo else pd.Series([])
    t_inicio = t.min() if len(t) and t.notna().any() else None
    t_fin = t.max() if len(t) and t.notna().any() else None
    blandas = _senales(grupo)
    centro = geom.centroid
    id_unidad = _hash(
        f'{ruta_hash}|{t_inicio}|{t_fin}|{round(centro.x, 1)}|'
        f'{round(centro.y, 1)}|{len(xy)}')
    sesion = str(sesiones[0]) if len(sesiones) else ''
    return Unidad(
        id_unidad=id_unidad, ruta_hash=ruta_hash, archivo=archivo,
        indices=np.asarray(posiciones), xy=xy,
        tiempos=t.to_numpy() if len(t) else np.array([]),
        geometry_local=geom,
        core_local=MultiPoint(xy).convex_hull.simplify(1.5, preserve_topology=True),
        core_wgs84=None, core_utm=None,
        geometry_wgs84=None, geometry_utm=None,
        epsg_utm=0, n_puntos=len(grupo), t_inicio=t_inicio, t_fin=t_fin,
        area_ha=area / 10000.0, perimetro_m=float(geom.length),
        solidez=solidez, compacidad=compacidad, orientacion=orientacion,
        coherencia=coherencia, densidad_puntos_ha=len(grupo) / (area / 10000.0),
        max_gap_m=max_gap, speed_p50=blandas['speed_p50'],
        speed_p90=blandas['speed_p90'],
        state_cobertura=blandas['state_cobertura'],
        frac_working=blandas['frac_working'], frac_idle=blandas['frac_idle'],
        frac_transport=blandas['frac_transport'], tipo='TRABAJO',
        sesion_id=sesion)


def detectar_unidades(frame: pd.DataFrame, ruta_hash: str, cfg: dict | None = None) -> list[Unidad]:
    """Y2: corta la ruta en orden temporal real y devuelve unidades de trabajo."""
    cfg = {**CFG_CAMPOS, **(cfg or {})}
    if frame is None or len(frame) < 2:
        return []
    trabajo = frame.copy()
    if 'Timestamp' not in trabajo.columns:
        trabajo['Timestamp'] = pd.NaT
    orden = np.argsort(pd.to_datetime(trabajo['Timestamp'], errors='coerce').to_numpy())
    trabajo = trabajo.iloc[orden].reset_index(drop=True)
    # Sesiones para no unir d?as distintos en la misma unidad.
    if 'Timestamp' in trabajo.columns:
        t = pd.to_datetime(trabajo['Timestamp'], errors='coerce')
        dt = t.diff().dt.total_seconds().to_numpy()
        sesion = (np.isnan(dt) | (dt > 7200) | (dt < 0)).cumsum() - 1
    else:
        sesion = np.zeros(len(trabajo), dtype=int)
    xy = trabajo[['X', 'Y']].to_numpy(dtype=float)
    rumbos = pd.to_numeric(trabajo.get('Bearing'), errors='coerce').to_numpy(dtype=float)
    dt = (t.diff().dt.total_seconds().fillna(0).to_numpy()
          if 'Timestamp' in trabajo else np.full(len(trabajo), 10.0))
    dist = np.hypot(np.diff(xy[:, 0], prepend=xy[0, 0]),
                    np.diff(xy[:, 1], prepend=xy[0, 1]))
    with np.errstate(divide='ignore', invalid='ignore'):
        vel = np.where(dt > 0, dist / dt * 3.6, np.inf)
    cambios = np.abs((np.diff(rumbos, prepend=rumbos[0]) + 180.0) % 360.0 - 180.0)
    ventana = int(cfg['giro_ventana'])
    giro = np.convolve(cambios, np.ones(ventana), mode='full')[:len(cambios)]
    # Un giro de cabecera aislado no corta la unidad; s? lo hace un cambio
    # sostenido de rumbo, un hueco temporal, una velocidad fuera de rango o un
    # paso demasiado largo.
    cortes = (dt > float(cfg['trabajo_gap_s'])) | \
             (vel < float(cfg['vel_min_kmh'])) | \
             (vel > float(cfg['vel_max_kmh'])) | \
             (dist > float(cfg['paso_max_m'])) | \
             ((giro > float(cfg['giro_sostenido_deg'])) &
              (dist > float(cfg['paso_max_m']) * 0.5))
    # El primer punto siempre empieza unidad.
    cortes[0] = True
    unidades = []
    inicio = 0
    for i in range(1, len(trabajo) + 1):
        if i == len(trabajo) or cortes[i]:
            posiciones = np.arange(inicio, i)
            if len(posiciones) >= int(cfg['unidad_min_puntos']):
                unidad = _crear_unidad(trabajo, posiciones, ruta_hash,
                                       str(trabajo['Archivo'].iloc[0]),
                                       cfg, sesion[posiciones])
                if unidad is not None:
                    _georreferenciar(unidad, trabajo)
                    unidades.append(unidad)
            inicio = i
    return unidades


def _metricas_union(unidades: list[Unidad], epsg: int) -> dict:
    geoms = [_a_utm(u.geometry_wgs84, epsg) for u in unidades]
    geom = unary_union(geoms)
    area, solidez, compacidad = _forma(geom)
    n = sum(u.n_puntos for u in unidades)
    return {
        'geometry': geom, 'area_ha': area / 10000.0,
        'solidez': solidez, 'compacidad': compacidad,
        'densidad': n / (area / 10000.0) if area > 0 else 0.0,
        'extension': math.hypot(geom.bounds[2] - geom.bounds[0],
                                geom.bounds[3] - geom.bounds[1]) if not geom.is_empty else 0.0,
    }


def _puede_unir(a: Unidad, b: Unidad, cfg: dict) -> tuple[bool, str]:
    ga = a.core_utm if a.core_utm is not None else a.geometry_utm
    gb = b.core_utm if b.core_utm is not None else b.geometry_utm
    if a.epsg_utm != b.epsg_utm:
        gb = _a_utm(b.core_wgs84 if b.core_wgs84 is not None else b.geometry_wgs84,
                    a.epsg_utm)
    inter = ga.intersection(gb)
    menor = min(ga.area, gb.area)
    solape = float(inter.area / menor) if menor > 0 else 0.0
    distancia = 0.0 if not inter.is_empty else float(ga.distance(gb))
    if solape >= float(cfg['union_overlap_min']):
        return True, 'solape'
    # Sin solape de la huella de puntos NO se fusiona por cercan?a. La
    # contig?idad solo se admite si el hueco es 0 y comparten tiempo/rumbo.
    if distancia > float(cfg.get('union_dist_m', 0.0)):
        return False, 'sin solape'
    if a.coherencia >= 0.20 and b.coherencia >= 0.20:
        dif = abs(a.orientacion - b.orientacion) % 180.0
        dif = min(dif, 180.0 - dif)
        if dif > float(cfg['union_orient_deg']):
            return False, 'orientaci?n incompatible'
    if a.t_fin is None or b.t_inicio is None:
        return False, 'sin tiempo'
    if a.t_fin <= b.t_inicio:
        gap = (b.t_inicio - a.t_fin).total_seconds()
    elif b.t_fin <= a.t_inicio:
        gap = (a.t_inicio - b.t_fin).total_seconds()
    else:
        gap = 0.0
    if gap > float(cfg['union_gap_s']):
        return False, 'gap temporal'
    return True, 'contig?idad temporal'

def fusionar_unidades(unidades: list[Unidad], cfg: dict) -> tuple[list[Campo], list[dict]]:
    """Y4: fusi?n jer?rquica con validaci?n de forma/densidad/extensi?n."""
    cfg = {**CFG_CAMPOS, **(cfg or {})}
    if not unidades:
        return [], []
    geoms = [u.core_wgs84 if u.core_wgs84 is not None else u.geometry_wgs84 for u in unidades]
    arbol = STRtree(geoms)
    # Solo se consultan geometrías que se tocan o se cruzan. El buffer de
    # 0,0002° anterior (~22 m) generaba cientos de miles de pares que luego
    # fallaban por 'sin solape'. Si union_dist_m > 0 se conserva la búsqueda
    # por cercanía equivalente en grados; si no, la consulta es exacta.
    margen_m = max(float(cfg.get('union_dist_m', 0.0)),
                   float(cfg.get('union_query_buffer_m', 1.0)))
    distancia_grados = max(0.0, margen_m) / 111_320.0
    aristas = []
    rechazos = []
    for i, a in enumerate(unidades):
        consulta = geoms[i]
        if consulta is None:
            continue
        if distancia_grados > 0:
            consulta = consulta.buffer(distancia_grados)
        for j in arbol.query(consulta, predicate='intersects'):
            j = int(j)
            if j <= i:
                continue
            b = unidades[j]
            ok, motivo = _puede_unir(a, b, cfg)
            if ok:
                if a.epsg_utm != b.epsg_utm:
                    gb = _a_utm(b.geometry_wgs84, a.epsg_utm)
                else:
                    gb = b.geometry_utm
                inter = a.geometry_utm.intersection(gb)
                solape = float(inter.area / min(a.geometry_utm.area, gb.area))
                distancia = 0.0 if not inter.is_empty else float(a.geometry_utm.distance(gb))
                aristas.append((0 if solape > 0 else 1, -solape, distancia,
                                i, j, motivo))
            else:
                rechazos.append({'id_a': a.id_unidad, 'id_b': b.id_unidad,
                                 'motivo': motivo})
    aristas.sort(key=lambda x: x[:3])
    padre = list(range(len(unidades)))
    grupos = {i: [unidades[i]] for i in range(len(unidades))}
    geo = {i: u.geometry_utm.simplify(1.0, preserve_topology=True)
           for i, u in enumerate(unidades)}
    npts = {i: u.n_puntos for i, u in enumerate(unidades)}

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for _, _, _, i, j, motivo in aristas:
        ri, rj = raiz(i), raiz(j)
        if ri == rj:
            continue
        try:
            geom = geo[ri].union(geo[rj])
            area, solidez, compacidad = _forma(geom)
            extension = math.hypot(geom.bounds[2] - geom.bounds[0],
                                   geom.bounds[3] - geom.bounds[1])
        except Exception:  # noqa: BLE001
            continue
        razon = ''
        if extension > float(cfg['union_max_extension_m']):
            razon = 'extension maxima'
        elif solidez < float(cfg['union_solidez_min']):
            razon = 'solidez'
        elif compacidad < float(cfg['union_compacidad_min']):
            razon = 'compacidad'
        elif area / 10000.0 > float(cfg['union_max_area_ha']):
            razon = 'area maxima'
        if razon:
            rechazos.append({'id_a': unidades[i].id_unidad,
                             'id_b': unidades[j].id_unidad,
                             'motivo': razon})
            continue
        padre[rj] = ri
        grupos[ri] = grupos[ri] + grupos[rj]
        geo[ri] = geom
        npts[ri] = npts[ri] + npts[rj]
        del grupos[rj]
        del geo[rj]
        del npts[rj]
    campos = []
    for unidades_grupo in grupos.values():
        campo = _crear_campo(unidades_grupo, cfg)
        if campo is not None:
            campos.append(campo)
    campos.sort(key=lambda c: (round(c.geometry.centroid.y, 5),
                               round(c.geometry.centroid.x, 5), c.id_estable))
    for i, campo in enumerate(campos, 1):
        campo.campo_id = i
    return campos, rechazos


def _crear_campo(unidades: list[Unidad], cfg: dict) -> Campo | None:
    if not unidades:
        return None
    epsg = int(unidades[0].epsg_utm)
    metricas = _metricas_union(unidades, epsg)
    geom_utm = metricas['geometry']
    # WGS84 union para la capa principal.
    geoms_wgs = [u.geometry_wgs84 for u in unidades]
    geom_wgs = unary_union(geoms_wgs)
    puntos = np.vstack([u.xy for u in unidades])
    tiempos = np.concatenate([u.tiempos for u in unidades])
    rutas = np.concatenate([[u.ruta_hash] * u.n_puntos for u in unidades])
    n_puntos = len(puntos)
    n_dias = len({u.t_inicio.date() for u in unidades if u.t_inicio is not None})
    n_maquinas = len({u.ruta_hash for u in unidades})
    n_sesiones = len({u.sesion_id for u in unidades if u.sesion_id})
    horas = sum((u.t_fin - u.t_inicio).total_seconds() / 3600.0
                for u in unidades if u.t_inicio is not None and u.t_fin is not None)
    t_inicio = min((u.t_inicio for u in unidades if u.t_inicio is not None), default=None)
    t_fin = max((u.t_fin for u in unidades if u.t_fin is not None), default=None)
    weights = np.array([max(1, u.n_puntos) for u in unidades], dtype=float)
    vector = (np.exp(1j * np.radians(2 * np.array([u.orientacion for u in unidades]))) * weights).sum() / weights.sum()
    orientacion = float((math.degrees(np.angle(vector)) / 2.0) % 180.0)
    coherencia = float(abs(vector))
    # Gap m?ximo entre puntos consecutivos, por ruta y tiempo.
    # El hueco de muestreo se mide DENTRO de cada unidad; un salto entre días
    # no debe convertir un campo multi-día en trayecto disperso.
    max_gap = max((u.max_gap_m for u in unidades), default=0.0)
    density = n_puntos / metricas['area_ha'] if metricas['area_ha'] > 0 else 0.0
    campos_rutas = sorted({u.ruta_hash for u in unidades})
    principal = max(unidades, key=lambda u: u.n_puntos).ruta_hash
    ancho_m, largo_m, aspecto = calcular_dimensiones_mbb(geom_utm)
    campo = Campo(
        id_estable=_hash('|'.join(sorted(u.id_unidad for u in unidades))),
        campo_id=0, geometry=geom_wgs, geometry_utm=geom_utm, epsg_utm=epsg,
        unidades=unidades, puntos=puntos, tiempos=tiempos, rutas=rutas,
        n_puntos=n_puntos, n_unidades=len(unidades), n_dias=n_dias,
        n_maquinas=n_maquinas, n_sesiones=n_sesiones, horas=round(horas, 2),
        t_inicio=t_inicio.isoformat() if t_inicio is not None else '',
        t_fin=t_fin.isoformat() if t_fin is not None else '',
        area_ha=metricas['area_ha'], perimetro_m=float(geom_utm.length),
        solidez=metricas['solidez'], compacidad=metricas['compacidad'],
        aspect_ratio=aspecto,
        ancho_mbb=ancho_m,
        largo_mbb=largo_m,
        orientacion=orientacion, coherencia=coherencia,
        densidad_puntos_ha=density, max_gap_m=max_gap,
        speed_p50=_pondera(unidades, 'speed_p50'),
        speed_p90=_pondera(unidades, 'speed_p90'),
        state_cobertura=_pondera(unidades, 'state_cobertura'),
        frac_working=_pondera(unidades, 'frac_working'),
        frac_idle=_pondera(unidades, 'frac_idle'),
        frac_transport=_pondera(unidades, 'frac_transport'),
        estado='DUDOSO', confianza=0.0, motivos=[], causa_fragmento='',
        categoria='', requiere_revision=0, cuenta_ha=0.0,
        diagnostico_grande='', parece_campo='DUDOSO',
        rutas_hash=';'.join(campos_rutas), ruta_principal=principal)
    _clasificar_campo(campo, cfg)
    return campo


def _pondera(unidades, campo):
    vals = [(getattr(u, campo), u.n_puntos) for u in unidades
            if getattr(u, campo) is not None]
    if not vals:
        return None if campo in ('speed_p50', 'speed_p90') else 0.0
    return round(float(np.average([v[0] for v in vals],
                                  weights=[v[1] for v in vals])), 3)


def _clasificar_campo(campo: Campo, cfg: dict) -> None:
    campo.diagnostico_grande = ''
    campo.requiere_revision = 0
    campo.cuenta_ha = 0.0
    campo.cuenta_ha_valida = False
    campo.subcategoria = ''
    campo.metrica_detonante = ''
    # Reglas estrictas de caminos, ruido y trabajo agrícola.
    dictamen = clasificar_cobertura_estricta(
        area_ha=campo.area_ha,
        n_puntos=campo.n_puntos,
        n_unidades=campo.n_unidades,
        horas=campo.horas,
        solidez=campo.solidez,
        compacidad=campo.compacidad,
        densidad_puntos_ha=campo.densidad_puntos_ha,
        coherencia_orientacion=campo.coherencia,
        aspect_ratio=campo.aspect_ratio,
        ancho_m=campo.ancho_mbb,
    )
    if dictamen is not None:
        campo.subcategoria = dictamen['subcategoria']
        campo.metrica_detonante = dictamen['metrica_detonante']
        if dictamen['categoria_final'] == 'TRAYECTO_DISPERSO':
            campo.estado = 'TRAYECTO_DISPERSO'
            campo.motivos = [dictamen['motivo']]
            campo.causa_fragmento = dictamen['causa']
            campo.parece_campo = 'NO'
            return
    # Compuerta de ancho estrecho: un trazado de ancho < 25m es un camino.
    ancho_min = float(cfg.get('ancho_min_campo_m', 25.0))
    if campo.ancho_mbb > 0 and campo.ancho_mbb < ancho_min:
        if campo.aspect_ratio > 2.0 or campo.n_unidades <= 2:
            campo.estado = 'TRAYECTO_DISPERSO'
            campo.motivos = [f'ancho estrecho ({campo.ancho_mbb:.1f} m '
                             f'< {ancho_min:.0f} m): posible camino']
            campo.causa_fragmento = 'forma_lineal'
            campo.subcategoria = 'NO_ES_CAMPO'
            campo.metrica_detonante = 'ancho_m'
            campo.parece_campo = 'NO'
            return
    # Compuerta de forma histórica: un trazado alargado y estrecho es un
    # camino, no un campo, aunque tenga densidad suficiente.
    if campo.compacidad < float(cfg['compacidad_min']):
        campo.estado = 'TRAYECTO_DISPERSO'
        campo.motivos = [f'forma lineal (compacidad {campo.compacidad:.3f} '
                         f'< {cfg["compacidad_min"]}): posible camino']
        campo.causa_fragmento = 'forma_lineal'
        campo.subcategoria = 'NO_ES_CAMPO'
        campo.metrica_detonante = 'compacidad'
        campo.parece_campo = 'NO'
        return
    # Y1: compuertas expl?citas (densidad y hueco m?ximo).
    if campo.densidad_puntos_ha < float(cfg['densidad_min_puntos_ha']):
        campo.estado = 'TRAYECTO_DISPERSO'
        campo.motivos = [f'densidad {campo.densidad_puntos_ha:.1f} pts/ha '
                         f'< {cfg["densidad_min_puntos_ha"]}']
        campo.causa_fragmento = 'densidad_baja'
        campo.subcategoria = 'NO_ES_CAMPO'
        campo.metrica_detonante = 'densidad_puntos_ha'
        campo.parece_campo = 'NO'
        return
    if campo.max_gap_m > float(cfg['max_gap_m']):
        campo.estado = 'TRAYECTO_DISPERSO'
        campo.motivos = [f'hueco m?ximo {campo.max_gap_m:.0f} m '
                         f'> {cfg["max_gap_m"]:.0f} m']
        campo.causa_fragmento = 'hueco_muestreo'
        campo.subcategoria = 'NO_ES_CAMPO'
        campo.metrica_detonante = 'max_gap_m'
        campo.parece_campo = 'NO'
        return
    estado, motivos = _clasificar(
        campo.area_ha, campo.n_puntos, campo.solidez, campo.compacidad,
        campo.coherencia, campo.densidad_puntos_ha, 1.0, cfg)
    if (dictamen is not None and dictamen['categoria_final'] == 'CAMPO'
            and estado != 'NO_ES_CAMPO'):
        estado = 'CAMPO_PROBABLE'
        motivos = [dictamen['motivo']]
    # Compuerta adicional para fragmentos muy irregulares: si la compacidad es
    # menor que 0,04, la forma es compatible con camino aunque tenga varias
    # unidades. No se cuenta como superficie agrícola.
    compacidad_min = float(cfg.get('compacidad_fragmento_min', 0.05))
    if estado in ('CAMPO_PROBABLE', 'CAMPO_FRAGMENTO', 'DUDOSO') \
            and campo.compacidad < compacidad_min:
        estado = 'TRAYECTO_DISPERSO'
        motivos = [f'compacidad {campo.compacidad:.3f} < '
                   f'{compacidad_min:.2f}: posible camino']
        campo.causa_fragmento = 'forma_lineal'
        campo.subcategoria = 'NO_ES_CAMPO'
        campo.metrica_detonante = 'compacidad'
    # Base/patio.
    evidencias = []
    if campo.n_sesiones >= int(cfg['base_min_sesiones']):
        evidencias.append(f'{campo.n_sesiones} sesiones')
    if campo.n_dias >= int(cfg['base_min_dias']):
        evidencias.append(f'{campo.n_dias} d?as')
    if campo.horas >= float(cfg['base_min_horas']):
        evidencias.append(f'{campo.horas:.1f} h')
    if campo.speed_p50 is not None and campo.speed_p50 <= float(cfg['base_speed_max']):
        evidencias.append(f'velocidad {campo.speed_p50:.1f} km/h')
    if campo.state_cobertura >= 0.20 and campo.frac_idle >= float(cfg['base_frac_idle_min']):
        evidencias.append(f'{campo.frac_idle:.0%} ralent?')
    sin_pasadas = campo.n_unidades <= 1 or campo.coherencia < cfg['coherencia_min']
    if sin_pasadas:
        evidencias.append('sin estructura de pasadas')
    if sin_pasadas and len(evidencias) >= int(cfg['base_min_evidencias']):
        estado = 'NO_ES_CAMPO'
        motivos = ['posible base/patio: ' + '; '.join(evidencias)]
    campo.estado = estado
    campo.motivos = motivos
    if estado == 'NO_ES_CAMPO':
        campo.subcategoria = 'NO_ES_CAMPO'
    if estado == 'CAMPO_FRAGMENTO':
        if campo.area_ha < float(cfg['area_fragmento_ha']):
            campo.causa_fragmento = 'area_pequena'
        elif campo.n_unidades <= 1:
            campo.causa_fragmento = 'una_sola_unidad'
        elif campo.max_gap_m > float(cfg['max_gap_m']) * 0.7:
            campo.causa_fragmento = 'muestreo_ralo'
        elif campo.solidez < float(cfg['solidez_min']):
            campo.causa_fragmento = 'borde_incompleto'
        else:
            campo.causa_fragmento = 'trabajo_parcial'
    if campo.area_ha > float(cfg['grande_area_ha']):
        campo.categoria = 'CAMPO_GRANDE'
        campo.requiere_revision = 1
        campo.cuenta_ha = 0.0
        campo.diagnostico_grande = 'CAMPO_GRANDE'
        campo.motivos = list(campo.motivos) + [
            f'?rea {campo.area_ha:.0f} ha > {cfg["grande_area_ha"]:.0f} ha: '
            'revisi?n humana antes de contar hect?reas']
    else:
        # Solo los estados de trabajo agrícola cuentan hectáreas. DUDOSO y
        # NO_ES_CAMPO quedan visibles para revisión, pero no suman superficie.
        campo.cuenta_ha = (campo.area_ha
                           if estado in ('CAMPO_PROBABLE', 'CAMPO_FRAGMENTO')
                           else 0.0)
    campo.cuenta_ha_valida = bool(
        campo.cuenta_ha > 0
        and estado in ('CAMPO_PROBABLE', 'CAMPO_FRAGMENTO'))
    consistencia = min(1.0, campo.n_unidades / 2.0)
    working = campo.frac_working if campo.state_cobertura >= 0.20 else 0.5
    campo.confianza = max(0.0, min(1.0,
        0.20 * min(1.0, campo.area_ha / max(cfg['area_fragmento_ha'], 1e-9)) +
        0.15 * campo.solidez + 0.15 * min(1.0, campo.compacidad / 0.10) +
        0.20 * campo.coherencia + 0.10 * min(1.0, campo.densidad_puntos_ha / 100.0) +
        0.10 * consistencia + 0.10 * working))
    if campo.estado == 'CAMPO_PROBABLE':
        campo.parece_campo = 'SI'
    elif campo.categoria == 'CAMPO_GRANDE':
        campo.parece_campo = 'DUDOSO'
    elif campo.estado in ('CAMPO_FRAGMENTO', 'DUDOSO'):
        campo.parece_campo = 'DUDOSO'
    else:
        campo.parece_campo = 'NO'


def resumen_campos(campos: list[Campo]) -> dict:
    return {
        'n_campos': len(campos),
        'por_estado': {e: sum(1 for c in campos if c.estado == e)
                       for e in ESTADOS_CAMPO},
        'area_total_ha': round(sum(c.area_ha for c in campos), 4),
        'area_confirmada_ha': round(sum(c.cuenta_ha for c in campos), 4),
        'n_grandes': sum(1 for c in campos if c.categoria == 'CAMPO_GRANDE'),
        'n_dispersos': sum(1 for c in campos if c.estado == 'TRAYECTO_DISPERSO'),
    }

def fusionar_por_rutas(unidades: list[Unidad], cfg: dict) -> tuple[list[Campo], list[dict]]:
    """Fusi?n por m?quina y luego s?lo entre campos de m?quinas distintas que se solapan.

    Evita el coste cuadr?tico de fusionar decenas de miles de unidades de todo el
    historial a la vez, sin perder la fusi?n entre m?quinas del mismo campo.
    """
    cfg = {**CFG_CAMPOS, **(cfg or {})}
    por_ruta = {}
    for u in unidades:
        por_ruta.setdefault(u.ruta_hash, []).append(u)
    campos, rechazos = [], []
    for grupo in por_ruta.values():
        cs, rej = fusionar_unidades(grupo, cfg)
        campos.extend(cs)
        rechazos.extend(rej)
    if len(por_ruta) < 2 or not campos:
        return campos, rechazos
    arbol = STRtree([c.geometry for c in campos])
    padre = list(range(len(campos)))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for i, campo in enumerate(campos):
        for j in arbol.query(campo.geometry, predicate='intersects'):
            j = int(j)
            if j <= i or campos[j].ruta_principal == campo.ruta_principal:
                continue
            try:
                inter = campo.geometry.intersection(campos[j].geometry)
                if inter.area > 0:
                    ri, rj = raiz(i), raiz(j)
                    if ri != rj:
                        padre[rj] = ri
            except Exception:  # noqa: BLE001
                continue
    grupos = {}
    for i in range(len(campos)):
        grupos.setdefault(raiz(i), []).append(i)
    salida = []
    for indices in grupos.values():
        if len(indices) == 1:
            salida.append(campos[indices[0]])
            continue
        unidades_grupo = [u for i in indices for u in campos[i].unidades]
        cs, rej = fusionar_unidades(unidades_grupo, cfg)
        rechazos.extend(rej)
        salida.extend(cs or [campos[i] for i in indices])
    salida.sort(key=lambda c: (round(c.geometry.centroid.y, 5),
                               round(c.geometry.centroid.x, 5), c.id_estable))
    for i, campo in enumerate(salida, 1):
        campo.campo_id = i
    return salida, rechazos
