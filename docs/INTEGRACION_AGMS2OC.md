# Integración con AGMS2OC

Este paquete expone el detector como una función estable y tres salidas de
consumo directo:

| Salida | Estado interno | Uso |
|---|---|---|
| `campos` | `CAMPO_PROBABLE` | parcelas con mejor evidencia |
| `campos_fragmento` | `CAMPO_FRAGMENTO` | trabajo agrícola parcial o fragmentado |
| `campos_dudosos` | `DUDOSO` | revisión humana; no cuenta hectáreas |

Los caminos y trayectos quedan en `trayectos_dispersos`; los descartes sin
campo quedan en `no_campo`.

## Uso desde Python

```python
from campos_tractor import cargar_dataframe, detectar_campos_por_estado

frame = cargar_dataframe(df)  # timestamp UTC, lat, lon, machine_id
resultado = detectar_campos_por_estado(frame, ruta_hash='ruta_001')

for campo in resultado['campos']:
    print(campo.id_estable, campo.area_ha, campo.to_dict())

for campo in resultado['campos_fragmento']:
    ...

for campo in resultado['campos_dudosos']:
    ...
```

Cada elemento es un `Campo` con:

- `id_estable`
- `geometry` en WGS84
- `geometry_utm`
- `epsg_utm`
- `area_ha`
- `cuenta_ha`
- `estado`
- `subcategoria`
- `metrica_detonante`
- `motivo`
- `aspect_ratio`
- `ancho_mbb`
- `confianza`
- `unidades`

`resultado['resumen']` devuelve conteos y hectáreas por grupo.

## Uso desde GeoPackage

El GeoPackage de salida contiene capas separadas:

```text
campos
campos_probables
campos_fragmentos
campos_dudosos
campos_descartados
trayectos_dispersos
unidades
pares_contiguos
```

Y archivos CSV equivalentes:

```text
campos_v0.4.0.csv
campos_probables_v0.4.0.csv
campos_fragmentos_v0.4.0.csv
campos_dudosos_v0.4.0.csv
campos_descartados_v0.4.0.csv
trayectos_dispersos_v0.4.0.csv
```

## Regla de hectáreas

- `CAMPO_PROBABLE` y `CAMPO_FRAGMENTO`: `cuenta_ha > 0` y
  `cuenta_ha_valida == 1`.
- `DUDOSO`: visible para revisión, pero `cuenta_ha = 0`.
- `NO_ES_CAMPO` y `TRAYECTO_DISPERSO`: no cuentan hectáreas.

## Identificadores

Los `id_estable` son hashes deterministas. AGMS2OC puede usarlos como clave
para revisión, etiquetas o actualizaciones sin depender de coordenadas ni de
números de serie.
