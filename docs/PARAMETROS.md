# Parámetros del detector

Los valores viven en `config_campos.yaml` y en `CFG_CAMPOS`. No se ajustan con
etiquetas de retención.

## Tiempo

| Parámetro | Defecto | Uso |
|---|---:|---|
| `trabajo_gap_s` | 300 | Hueco máximo para unir puntos de una unidad. |
| `vel_min_kmh` | 1,0 | Velocidad mínima de trabajo. |
| `vel_max_kmh` | 15,0 | Velocidad máxima de trabajo; por encima se corta. |
| `paso_max_m` | 350 | Paso máximo entre puntos de una unidad. |
| `giro_ventana` | 3 | Ventana de giro sostenido. |
| `giro_sostenido_deg` | 220 | Giro acumulado que corta la unidad. |
| `unidad_min_puntos` | 10 | Mínimo de puntos de una unidad. |

## Forma

| Parámetro | Defecto | Uso |
|---|---:|---|
| `buffer_factor` | 0,20 | Radio = factor × mediana de espaciado. |
| `buffer_min_m` | 3 | Radio mínimo. |
| `buffer_max_m` | 5 | Tope de radio. |
| `closing_m` | 2 | Cierre morfológico. |

## Fusión

| Parámetro | Defecto | Uso |
|---|---:|---|
| `union_overlap_min` | 0,08 | Solape mínimo de huellas de puntos. |
| `union_dist_m` | 0 | Sin solape no se fusiona por cercanía. |
| `union_query_buffer_m` | 0 | Margen extra de la consulta `STRtree`; 0 usa intersección exacta. |
| `union_gap_s` | 300 | Continuidad temporal para contigüidad. |
| `union_orient_deg` | 30 | Diferencia máxima de orientación. |
| `union_solidez_min` | 0,30 | Solidez mínima al unir. |
| `union_compacidad_min` | 0,020 | Compacidad mínima al unir. |
| `union_max_extension_m` | 10.000 | Extensión máxima del campo. |
| `union_max_area_ha` | 2.000 | Área máxima de una unión. |

## Compuertas

| Parámetro | Defecto | Uso |
|---|---:|---|
| `densidad_min_puntos_ha` | 20 | Por debajo: `TRAYECTO_DISPERSO`. |
| `max_gap_m` | 300 | Hueco máximo dentro de una unidad. |
| `compacidad_min` | 0,025 | Por debajo: forma lineal (camino), no cuenta hectáreas. |
| `grande_area_ha` | 100 | `CAMPO_GRANDE` con revisión pendiente. |
| `area_descarte_ha` | 0,10 | Descarte de polígonos pequeños. |

### Reglas estrictas de clasificación

| Regla | Condición | Resultado |
|---|---|---|
| Ancho estrecho | `0 < ancho_mbb < 25` y (`aspect_ratio > 2` o `n_unidades <= 2`) | `TRAYECTO_DISPERSO` / `NO_ES_CAMPO` |
| Elongación extrema | `aspect_ratio >= 8`, salvo `area_ha >= 2` + 10 unidades + `ancho_mbb >= 50` | `TRAYECTO_DISPERSO` / `NO_ES_CAMPO` |
| Elongación moderada | `aspect_ratio >= 5` y (`ancho_mbb < 35` o `n_unidades <= 3` o `horas < 0,50`) | `TRAYECTO_DISPERSO` / `NO_ES_CAMPO` |
| Trazado poco sólido | (`solidez < 0,25` o `compacidad < 0,08`) y (`n_unidades <= 2` o `coherencia >= 0,95` o `aspect_ratio > 4`) | `TRAYECTO_DISPERSO` / `NO_ES_CAMPO` |
| Esfuerzo insuficiente | `n_puntos < 40`, `horas < 0,15` y `densidad < 70` o `n_unidades == 1` | `TRAYECTO_DISPERSO` / `NO_ES_CAMPO` |
| Micro-ruido | `cuenta_ha < 0,10` y `solidez < 0,40` | `TRAYECTO_DISPERSO` / `RUIDO_COBERTURA` |
| Campo | `solidez >= 0,25`, `compacidad >= 0,08` y (`cuenta_ha >= 0,60` o 3 unidades + 40 puntos) | `CAMPO` / `TRABAJO_AGRICOLA` |
| Fragmento | Resto con forma aceptable | `CAMPO_FRAGMENTO` / `TRABAJO_AGRICOLA` |

## Pares de revisión

| Parámetro | Defecto | Uso |
|---|---:|---|
| `max_gap_s` | 600 | Pares consecutivos ≤10 min. |
| `max_dist_m` | 150 | Distancia entre inicios. |

## Seguridad

No hay credenciales, IPs, series de máquina ni rutas de datos en este repositorio.
Las coordenadas reales viven fuera, en archivos ignorados.
