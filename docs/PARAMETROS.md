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

## Pares de revisión

| Parámetro | Defecto | Uso |
|---|---:|---|
| `max_gap_s` | 600 | Pares consecutivos ≤10 min. |
| `max_dist_m` | 150 | Distancia entre inicios. |

## Seguridad

No hay credenciales, IPs, series de máquina ni rutas de datos en este repositorio.
Las coordenadas reales viven fuera, en archivos ignorados.
