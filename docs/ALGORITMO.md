# Algoritmo de campos de tractor

## Flujo

```text
CSV contrato
  → cargar_dataframe (timestamp UTC, lat, lon, machine_id)
  → filtrar_mexico
  → detectar_unidades (tiempo primero)
  → fusionar_por_rutas / fusionar_unidades (STRtree + solape + forma)
  → compuertas de densidad, hueco y geometría lineal
  → clasificación estricta y pares contiguos
  → exportar (GeoPackage, CSV, QGZ opcional)
```

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `io.py` | Lee el contrato y construye `X/Y`, rumbo y tiempo. |
| `proyeccion.py` | Inversa equirectangular y origen local. |
| `_pasadas.py` | Segmentación pura de pasadas (sin ancho). |
| `_compat.py` | Configuración y utilidades de pasadas. |
| `estados.py` | Estados por señales geométricas. |
| `unidades.py` | Unidades temporales, huella bufferizada, compuertas y fusión jerárquica. |
| `detector.py` | Fachada única `detectar_campos`. |
| `pares.py` | Pares contiguos y clasificación. |
| `filtro_mexico.py` | Filtro geográfico de respaldo. |
| `exportar.py`, `utils.py` | GeoPackage, QML, CSV y tablas de revisión. |
| `evaluacion.py`, `metricas.py` | IoU, área, Hausdorff y Wilson. |
| `resumen.py`, `resumen_pares.py` | Resumen de etiquetas y pares. |
| `crear_qgz.py` | Proyecto QGIS opcional. |
| `sintetico.py`, `benchmark.py` | Banco sintético reproducible. |
| `cli.py` | Ejecución por línea de comandos. |

## Estados

- `CAMPO_PROBABLE`
- `CAMPO_FRAGMENTO` con causa (`area_pequena`, `una_sola_unidad`,
  `muestreo_ralo`, `borde_incompleto`, `trabajo_parcial`)
- `DUDOSO`
- `NO_ES_CAMPO`
- `TRAYECTO_DISPERSO` (no cuenta hectáreas)

## Compuertas

1. Densidad mínima 20 pts/ha.
2. Hueco máximo entre puntos consecutivos 300 m.
3. Área mínima de descarte 0,10 ha.
4. Compacidad mínima 0,025: una traza alargada y estrecha se trata como
   `TRAYECTO_DISPERSO` (camino), no como campo.
5. `CAMPO_GRANDE` >100 ha requiere revisión; `cuenta_ha=0`.

## Clasificación estricta

`clasificar_cobertura_estricta()` en `estados.py` aplica, en orden:

1. Geometría lineal: camino/acotamiento.
2. Esfuerzo insuficiente: pocos puntos y menos de 9 minutos.
3. Micro-ruido: área mínima con baja solidez.
4. Campo o fragmento con forma aceptable.

El `aspect_ratio` se calcula con el Minimum Bounding Box en `metricas.py` y se
guarda en cada campo. La fusión usa `STRtree` con intersección real y un margen
de 1 m para absorber diferencias de proyección.

## Identificadores

Los ids son hashes deterministas de la ruta y la geometría/tiempo. No se
publican números de serie ni nombres de organización. Las etiquetas de revisión
se invalidan, no se borran, cuando cambia el id.

## Límites

El algoritmo no sustituye una frontera catastral. La validación real requiere
fronteras de referencia y revisión humana.
