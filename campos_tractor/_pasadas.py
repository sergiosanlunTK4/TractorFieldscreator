"""Segmentación pura de pasadas de trabajo a partir de la trayectoria.

No estima ancho. Separa el problema en pasos medibles:

  W1. Une tramos contiguos en el tiempo, con rumbo compatible y desplazamiento
      lateral pequeño. Respeta huecos y no cruza giros de cabecera.
  W2. Ajusta rectas por consenso (RANSAC secuencial) sobre los puntos de
      trabajo, en vez de depender de los cambios de rumbo.
  W3. Construye pasadas completas (recta + extensión) y ordena su
      desplazamiento lateral.
  W4. Agrupa pasadas cercanas con criterios geométricos.

Los parámetros viven en ``CFG_PASADAS`` y se pueden sobrescribir con un ``cfg``.
No hay valores ajustados a una sola máquina: los umbrales son geométricos y se
validan con verdad sintética.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

CFG_PASADAS = {
    # Segmentación por rumbo (entrada de W1).
    'tolerancia_rumbo_grados': 12.0,
    'suavizado_rumbo': 5,
    'largo_min_tramo_m': 25.0,
    # W1: fusión de tramos colineales.
    'tolerancia_fusion_grados': 12.0,
    'fusion_lateral_min_m': 1.2,
    'fusion_lateral_max_m': 2.1,
    'hueco_max_m': 15.0,
    'hueco_max_s': 900.0,
    # W2: RANSAC secuencial.
    'ransac_umbral_m': 1.5,
    'ransac_min_puntos': 50,
    'ransac_iteraciones': 200,
    'ransac_max_rectas': 120,
    'ransac_largo_min_m': 30.0,
    'ransac_max_puntos': 20000,
    'ransac_semilla': 20261031,
    'ventana_ransac_puntos': 80,
    # W3: construcción y orden de pasadas.
    'agrupacion_max_m': 3.0,
    'agrupacion_offset_max_m': 2.4,
    'pasada_largo_min_m': 25.0,
    # W4: agrupación y confianza.
    'min_pasadas': 4,
    'pasadas_saturacion': 8.0,
    'radio_cercania': 0.15,
    'radio_cercania_min_m': 0.50,
}


@dataclass
class Recta:
    """Una recta ajustada a puntos de trabajo."""

    centro: np.ndarray
    direccion: np.ndarray
    inicio: float
    fin: float
    n: int
    indices: np.ndarray | None = None
    t0: float = 0.0
    t1: float = 0.0
    n_lineas: int = 1

    @property
    def largo(self) -> float:
        return max(0.0, float(self.fin - self.inicio))

    @property
    def rumbo(self) -> float:
        return math.degrees(math.atan2(self.direccion[1],
                                       self.direccion[0])) % 180.0

    @property
    def normal(self) -> np.ndarray:
        return np.array([-self.direccion[1], self.direccion[0]])


def _cfg(cfg: dict | None) -> dict:
    salida = dict(CFG_PASADAS)
    if cfg:
        salida.update({k: v for k, v in cfg.items() if v is not None})
    return salida


def _direccion(u: np.ndarray) -> np.ndarray:
    """Normaliza y orienta la dirección para que el rumbo quede en [0, 180)."""
    u = np.asarray(u, dtype=float)
    norma = float(np.linalg.norm(u))
    if norma <= 1e-12:
        return np.array([1.0, 0.0])
    u = u / norma
    if u[0] < -1e-12 or (abs(u[0]) <= 1e-12 and u[1] < 0):
        u = -u
    return u


def _recta_desde_puntos(puntos: np.ndarray, indices: np.ndarray,
                        tiempos: np.ndarray | None,
                        largo_min_m: float) -> Recta | None:
    pts = np.asarray(puntos, dtype=float)[indices]
    if len(pts) < 2:
        return None
    centro = pts.mean(axis=0)
    x = pts - centro
    valores, vectores = np.linalg.eigh(x.T @ x)
    u = _direccion(vectores[:, -1])
    proyeccion = (pts - centro) @ u
    largo = float(proyeccion.max() - proyeccion.min())
    if largo < largo_min_m:
        return None
    t0 = t1 = 0.0
    if tiempos is not None:
        t = np.asarray(tiempos, dtype=float)[indices]
        if len(t):
            t0, t1 = float(np.nanmin(t)), float(np.nanmax(t))
    return Recta(centro=centro, direccion=u, inicio=float(proyeccion.min()),
                 fin=float(proyeccion.max()), n=int(len(pts)),
                 indices=np.asarray(indices, dtype=int), t0=t0, t1=t1)


def _suavizar_rumbo(rumbos: np.ndarray, ventana: int) -> np.ndarray:
    r = np.asarray(rumbos, dtype=float)
    validos = np.isfinite(r)
    if validos.sum() < 3:
        return np.full(len(r), np.nan)
    if not validos.all():
        posiciones = np.arange(len(r))
        r = np.interp(posiciones, posiciones[validos], r[validos])
    ventana = max(3, int(ventana) | 1)  # impar
    seno = np.convolve(np.sin(np.radians(r)), np.ones(ventana) / ventana,
                       mode='same')
    coseno = np.convolve(np.cos(np.radians(r)), np.ones(ventana) / ventana,
                         mode='same')
    return np.degrees(np.arctan2(seno, coseno))


def segmentar_por_rumbo(puntos: np.ndarray, rumbos: np.ndarray,
                        tiempos: np.ndarray | None = None,
                        cfg: dict | None = None) -> list[Recta]:
    """W0/W1: parte la traza donde el rumbo cambia de forma sostenida.

    Es la misma entrada que usaba la v1; se conserva para poder medir qué
    aporta la fusión de tramos antes de pasar a RANSAC.
    """
    cfg = _cfg(cfg)
    if len(puntos) < 3:
        return []
    suave = _suavizar_rumbo(rumbos, cfg['suavizado_rumbo'])
    if not np.isfinite(suave).any():
        return []
    tramos: list[tuple[int, int]] = []
    inicio = 0
    for i in range(1, len(suave)):
        if not np.isfinite(suave[i]) or not np.isfinite(suave[i - 1]):
            continue
        if abs((suave[i] - suave[i - 1] + 180.0) % 360.0 - 180.0) > \
                cfg['tolerancia_rumbo_grados']:
            if i - inicio >= 3:
                tramos.append((inicio, i - 1))
            inicio = i
    if len(suave) - inicio >= 3:
        tramos.append((inicio, len(suave) - 1))

    rectas = []
    for a, b in tramos:
        recta = _recta_desde_puntos(puntos, np.arange(a, b + 1), tiempos,
                                    cfg['largo_min_tramo_m'])
        if recta is not None:
            rectas.append(recta)
    return rectas


class _UnionFind:
    def __init__(self, n: int):
        self.padre = list(range(n))

    def find(self, x: int) -> int:
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.padre[rb] = ra


def unir_colineales(rectas: list[Recta], puntos: np.ndarray,
                    tiempos: np.ndarray | None = None,
                    cfg: dict | None = None) -> list[Recta]:
    """W1: fusiona tramos contiguos, casi paralelos y casi alineados.

    No fusiona a través de un giro de cabecera: exige que el hueco longitudinal
    sea pequeño, que el desplazamiento lateral no supere el máximo configurado
    y que el hueco temporal no sea enorme.
    """
    cfg = _cfg(cfg)
    if len(rectas) < 2:
        return list(rectas)
    lateral_max = max(float(cfg['fusion_lateral_min_m']),
                      float(cfg['fusion_lateral_max_m']))
    uf = _UnionFind(len(rectas))
    for i in range(len(rectas)):
        a = rectas[i]
        for j in range(i + 1, len(rectas)):
            b = rectas[j]
            if abs((a.rumbo - b.rumbo + 90.0) % 180.0 - 90.0) > \
                    cfg['tolerancia_fusion_grados']:
                continue
            lateral = abs(float((b.centro - a.centro) @ a.normal))
            if lateral > lateral_max:
                continue
            # Intervalos aproximados sobre la dirección de a.
            b_centro = float((b.centro - a.centro) @ a.direccion)
            b0 = b_centro - b.largo / 2.0
            b1 = b_centro + b.largo / 2.0
            a0, a1 = -a.largo / 2.0, a.largo / 2.0
            solape = min(a1, b1) - max(a0, b0)
            if solape > cfg.get('solape_max_m', 2.0):
                continue
            hueco = max(0.0, max(a0, b0) - min(a1, b1))
            if hueco > cfg['hueco_max_m']:
                continue
            if tiempos is not None and a.t1 and b.t1:
                if a.t0 <= b.t0:
                    dt = b.t0 - a.t1
                else:
                    dt = a.t0 - b.t1
                if dt > cfg['hueco_max_s'] or dt < -5.0:
                    continue
            uf.union(i, j)

    grupos: dict[int, list[int]] = {}
    for i in range(len(rectas)):
        grupos.setdefault(uf.find(i), []).append(i)

    salida: list[Recta] = []
    for indices in grupos.values():
        if len(indices) == 1:
            salida.append(rectas[indices[0]])
            continue
        todos = np.concatenate([rectas[i].indices for i in indices
                                if rectas[i].indices is not None])
        todos = np.unique(todos)
        recta = _recta_desde_puntos(puntos, todos, tiempos,
                                    cfg['largo_min_tramo_m'])
        if recta is None:
            salida.extend(rectas[i] for i in indices)
            continue
        recta.n_lineas = len(indices)
        salida.append(recta)
    return salida


def ajustar_rectas_ransac(puntos: np.ndarray, tiempos: np.ndarray | None = None,
                          cfg: dict | None = None) -> list[Recta]:
    """W2: rectas por consenso secuencial sobre puntos de trabajo.

    Se muestrean dos puntos separados, se cuenta cuántos caen dentro del
    umbral y se acepta la recta con más inliers. Los inliers se retiran y se
    repite. Los parámetros son de configuración; no se ajustan por escenario.
    """
    cfg = _cfg(cfg)
    puntos = np.asarray(puntos, dtype=float)
    if len(puntos) < cfg['ransac_min_puntos']:
        return []
    rng = np.random.default_rng(int(cfg['ransac_semilla']))
    max_puntos = int(cfg['ransac_max_puntos'])
    if len(puntos) > max_puntos:
        muestra = rng.choice(len(puntos), max_puntos, replace=False)
    else:
        muestra = np.arange(len(puntos))
    restantes = np.asarray(muestra, dtype=int)
    rectas: list[Recta] = []
    umbral = float(cfg['ransac_umbral_m'])
    largo_min = float(cfg['ransac_largo_min_m'])
    min_puntos = max(int(cfg['ransac_min_puntos']),
                     int(0.004 * len(restantes)))

    while len(restantes) >= min_puntos and \
            len(rectas) < int(cfg['ransac_max_rectas']):
        mejor: tuple[int, np.ndarray] | None = None
        for _ in range(int(cfg['ransac_iteraciones'])):
            i, j = rng.choice(len(restantes), 2, replace=False)
            p, q = puntos[restantes[i]], puntos[restantes[j]]
            delta = q - p
            largo_muestra = float(np.linalg.norm(delta))
            if largo_muestra < largo_min / 2.0:
                continue
            u = delta / largo_muestra
            n = np.array([-u[1], u[0]])
            distancias = np.abs((puntos[restantes] - p) @ n)
            inliers = distancias <= umbral
            if int(inliers.sum()) < min_puntos:
                continue
            proyeccion = (puntos[restantes[inliers]] - p) @ u
            span = float(proyeccion.max() - proyeccion.min())
            if span < largo_min:
                continue
            score = int(inliers.sum())
            if mejor is None or score > mejor[0]:
                mejor = (score, inliers)
        if mejor is None:
            break
        _, inliers = mejor
        indices = restantes[inliers]
        recta = _recta_desde_puntos(puntos, indices, tiempos, largo_min)
        if recta is None:
            restantes = restantes[~inliers]
            continue
        rectas.append(recta)
        restantes = restantes[~inliers]

    # Refinar cada recta con todos los puntos, no sólo con la muestra.
    refinadas: list[Recta] = []
    for recta in rectas:
        distancias = np.abs((puntos - recta.centro) @ recta.normal)
        inliers = np.where(distancias <= umbral)[0]
        if len(inliers) < min_puntos:
            refinadas.append(recta)
            continue
        refinada = _recta_desde_puntos(puntos, inliers, tiempos, largo_min)
        refinadas.append(refinada if refinada is not None else recta)
    return refinadas


def ajustar_rectas_ransac_ventanas(puntos: np.ndarray,
                                   tiempos: np.ndarray | None = None,
                                   cfg: dict | None = None) -> list[Recta]:
    """RANSAC en ventanas: aproxima surcos curvos sin cambiar rectas.

    Cada ventana ajusta sus propias rectas y luego se fusionan las colineales.
    En un campo recto el resultado debe ser el mismo que RANSAC global; en uno
    curvo las ventanas siguen la tangente local. Se mide como alternativa, no
    se usa por omisión.
    """
    cfg = _cfg(cfg)
    puntos = np.asarray(puntos, dtype=float)
    ventana = int(cfg.get('ventana_ransac_puntos', 80))
    if ventana <= 10 or len(puntos) <= ventana:
        return ajustar_rectas_ransac(puntos, tiempos, cfg)
    rectas: list[Recta] = []
    for inicio in range(0, len(puntos), ventana):
        fin = min(len(puntos), inicio + ventana)
        if fin - inicio < cfg['ransac_min_puntos']:
            continue
        sub = puntos[inicio:fin]
        t_sub = None if tiempos is None else np.asarray(tiempos)[inicio:fin]
        for recta in ajustar_rectas_ransac(sub, t_sub, cfg):
            if recta.indices is not None:
                recta.indices = recta.indices + inicio
            rectas.append(recta)
    if not rectas:
        return []
    return unir_colineales(rectas, puntos, tiempos, cfg)


def _familias_orientacion(rectas: list[Recta],
                          tolerancia: float) -> list[list[Recta]]:
    familias: list[list[Recta]] = []
    for recta in rectas:
        for familia in familias:
            if abs((recta.rumbo - familia[0].rumbo + 90.0) % 180.0 - 90.0) <= \
                    tolerancia:
                familia.append(recta)
                break
        else:
            familias.append([recta])
    return familias


def _familia_dominante(rectas: list[Recta],
                       cfg: dict) -> tuple[list[Recta], np.ndarray]:
    familias = _familias_orientacion(rectas, cfg['tolerancia_fusion_grados'])
    if not familias:
        return [], np.array([1.0, 0.0])
    familia = max(familias, key=lambda f: sum(r.n for r in f))
    angulos = np.radians(2.0 * np.array([r.rumbo for r in familia]))
    pesos = np.array([r.n for r in familia], dtype=float)
    z = np.sum(pesos * np.exp(1j * angulos))
    direccion = np.array([math.cos(np.angle(z) / 2.0),
                          math.sin(np.angle(z) / 2.0)])
    return familia, _direccion(direccion)


def pasadas_desde_rectas(rectas: list[Recta], cfg: dict | None = None) -> list[dict]:
    """W3: convierte rectas en pasadas completas y ordenadas lateralmente."""
    cfg = _cfg(cfg)
    if len(rectas) < 2:
        return []
    familia, direccion = _familia_dominante(rectas, cfg)
    if len(familia) < 2:
        return []
    normal = np.array([-direccion[1], direccion[0]])
    agrupacion = max(float(cfg['fusion_lateral_min_m']),
                     min(float(cfg['agrupacion_max_m']),
                         float(cfg['agrupacion_offset_max_m'])))
    ordenadas = sorted(familia, key=lambda r: float(r.centro @ normal))
    grupos: list[list[Recta]] = []
    for recta in ordenadas:
        offset = float(recta.centro @ normal)
        if grupos and offset - float(grupos[-1][-1].centro @ normal) <= agrupacion:
            grupos[-1].append(recta)
        else:
            grupos.append([recta])

    pasadas = []
    for grupo in grupos:
        pesos = np.array([r.n for r in grupo], dtype=float)
        offset = float(np.average([float(r.centro @ normal) for r in grupo],
                                  weights=pesos))
        indices = [r.indices for r in grupo if r.indices is not None]
        unidos = np.unique(np.concatenate(indices)) if indices else np.array([], dtype=int)
        angulos = np.radians(2.0 * np.array([r.rumbo for r in grupo]))
        z = np.sum(pesos * np.exp(1j * angulos))
        rumbo = float((np.degrees(np.angle(z) / 2.0)) % 180.0)
        pasadas.append({
            'offset': offset,
            'n': int(sum(r.n for r in grupo)),
            'n_rectas': len(grupo),
            'largo': float(max(r.largo for r in grupo)),
            'indices': unidos,
            'rumbo': rumbo,
            't0': float(min(r.t0 for r in grupo)),
            't1': float(max(r.t1 for r in grupo)),
            'centro': np.average([r.centro for r in grupo], axis=0,
                                 weights=pesos),
        })
    pasadas.sort(key=lambda p: p['offset'])
    return pasadas


