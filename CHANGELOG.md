# Changelog

## 0.4.0 — detector actual

- Unidades temporales: `trabajo_gap_s=300`, velocidad 1–15 km/h,
  `paso_max_m=350`, `unidad_min_puntos=10`.
- Huella: buffer `0,20 * mediana`, mínimo 3 m, tope 5 m, cierre 2 m.
- Fusión: solape mínimo 0,08; orientación 30°; `union_dist_m=0` (no fusiona por
  cercanía sin solape); solidez 0,30; compacidad 0,02; extensión máxima 10 km;
  área máxima 2.000 ha.
- Compuertas: densidad mínima 20 pts/ha; hueco máximo 300 m; forma lineal
  (compacidad <0,025) se marca `TRAYECTO_DISPERSO` para no contar caminos;
  campo grande 100 ha (revisión humana, no cuenta hectáreas); descarte 0,10 ha.
- Pares contiguos: |gap| ≤ 600 s y distancia entre inicios ≤ 150 m.
- Filtro México de respaldo: caja 14,5–32,8 N / -118,5 a -86,5 O, colchón 10 km.

## 0.3.0 — histórico

- Visitas por sesión y DBSCAN espacial.
- Fusión por solape y orientación.
- Pares candidatos y revisión persistente.

## 0.2.0 — histórico

- Detección por DBSCAN de puntos, estados y filtro de área.

## 0.1.0 — histórico

- Proyección equirectangular inversa y exportación GeoPackage.
