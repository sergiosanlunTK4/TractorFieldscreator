# Algoritmo de campos de tractor

## Flujo

```text
CSV contrato
  → cargar_dataframe (timestamp UTC, lat, lon, machine_id)
  → filtrar_mexico
  → detectar_unidades (tiempo primero)
  → fusionar_por_rutas / fusionar_unidades (solape + forma)
  → compuertas de densidad y hueco
  → estados y pares contiguos
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

## Identificadores

Los ids son hashes deterministas de la ruta y la geometría/tiempo. No se
publican números de serie ni nombres de organización. Las etiquetas de revisión
se invalidan, no se borran, cuando cambia el id.

## Límites

El algoritmo no sustituye una frontera catastral. La validación real requiere
fronteras de referencia y revisión humana.
