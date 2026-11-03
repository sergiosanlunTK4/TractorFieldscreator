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
- Clasificación estricta: `aspect_ratio` del Minimum Bounding Box, reglas de
  camino (`solidez <0,25` o `compacidad <0,08`), esfuerzo insuficiente,
  micro-ruido y campo/fragmento. Nuevas columnas `aspect_ratio`,
  `subcategoria`, `metrica_detonante` y `cuenta_ha_valida`.
- Fusión: consulta `STRtree` con intersección real y buffer de 1 m en lugar de
  un buffer fijo de ~22 m; se eliminan decenas de miles de pares falsos.
- CLI: omite archivos sin puntos dentro de México y los reporta en
  `archivos_omitidos`.
- Solo `CAMPO_PROBABLE` y `CAMPO_FRAGMENTO` cuentan hectáreas. `DUDOSO` se
  conserva para revisión con `cuenta_ha=0`, evitando sumar superficie incierta.
- Clasificación por dimensiones del MBB: `ancho_mbb` y `largo_mbb` en metros.
  Trazas con ancho <25 m, elongación extrema o moderada se envían a
  `TRAYECTO_DISPERSO`.
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
