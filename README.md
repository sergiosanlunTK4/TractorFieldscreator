# campos-tractor

Repositorio: <https://github.com/sergiosanlunTK4/TractorFieldscreator>

Detección y agrupación de **campos de tractor** a partir de trayectorias con
tiempo real. No incluye clientes de API, base de datos, Angular, FastAPI ni datos
reales.

## Qué hace

1. Reconstruye la trayectoria en orden temporal.
2. Corta sesiones y unidades de trabajo; separa traslados.
3. Construye huellas con buffer adaptativo y cierre morfológico.
4. Fusiona por solape validando forma, densidad y extensión (sin cadenas ciegas).
5. Aplica compuertas de densidad y hueco máximo; lo descartado va a capas aparte.
6. Clasifica estados y genera pares contiguos para revisión.
7. Exporta GeoPackage 4326/UTM, CSV y, si hay QGIS, un `.qgz`.

## Contrato de entrada

Un CSV por máquina (o una tabla con `machine_id`) con estas columnas:

| Columna | Obligatoria | Tipo | Descripción |
|---|---|---|---|
| `timestamp` | sí | ISO 8601 UTC | Instante del punto. |
| `lat` | sí | float | Latitud WGS84. |
| `lon` | sí | float | Longitud WGS84. |
| `machine_id` | sí | texto | Identificador de la máquina; se hashea en la salida. |
| `speed_kmh` | no | float | Señal blanda, nunca compuerta. |
| `state` | no | texto | Señal blanda (`Working`, `Idle`, `Transport`). |

La ruta de los datos se pasa por `--datos` o `CAMPOS_DATA_DIR`; nunca está dentro
del repositorio. Ejemplo de CSV sintético:

```csv
timestamp,lat,lon,machine_id,speed_kmh,state
2026-06-01T08:00:00Z,18.6,-95.5,maquina_sintetica,6.0,Working
2026-06-01T08:01:00Z,18.6,-95.5,maquina_sintetica,6.2,Working
```

## Instalación y ejecución

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
campos-tractor --datos C:\ruta\a\csv --salida C:\ruta\a\salida
```

Salida principal:

```text
salida/0.4.0/campos_v0.4.0_4326.gpkg
salida/0.4.0/campos_v0.4.0_utm<zona>.gpkg
salida/revision_campos.gpkg
```

## QGIS (opcional)

El proyecto `.qgz` se crea en una segunda ejecución, para que QGIS no abra el
GeoPackage mientras el detector todavía lo tiene bloqueado en Windows:

```powershell
& "C:\Program Files\QGIS 3.40.13\bin\python-qgis-ltr.bat" `
  -m campos_tractor.crear_qgz `
  --gpkg salida\0.4.0\campos_v0.4.0_4326.gpkg `
  --revision salida\revision_campos.gpkg `
  --qml salida\0.4.0\campos_v0.4.0.qml `
  --salida salida\0.4.0\campos_v0.4.0.qgz
```

El comando también se imprime al final de `campos-tractor` cuando existe
`QGIS_PYTHON`.

## Capas

- `campos`: campos no dispersos; `cuenta_ha=0` para `DUDOSO`, no-campo y
  `CAMPO_GRANDE`.
- `campos_descartados`: área <0,10 ha.
- `trayectos_dispersos`: densidad <20 pts/ha, hueco >300 m, forma lineal
  (caminos) o micro-ruido; no suman hectáreas.
- `unidades`: bloques temporales de trabajo.
- `trazas`: una línea por unidad, sin cruzar huecos >T.
- `trazas_puntos`: puntos submuestreados con timestamp.
- `pares_contiguos`: pares consecutivos para revisión.
- `puntos_fuera_mexico`: filtro geográfico de respaldo.
- `revision` y `revision_pares`: tablas persistentes fuera de `campos`.

## Clasificación estricta

Cada cobertura se evalúa con estas señales, en orden:

1. **Camino / acotamiento por ancho:** `ancho_mbb < 25 m` y
   `aspect_ratio > 2` o `n_unidades <= 2`.
2. **Elongación extrema:** `aspect_ratio >= 8`, salvo campos grandes
   (`area_ha >= 2`, al menos 10 unidades y `ancho_mbb >= 50 m`).
3. **Elongación moderada:** `aspect_ratio >= 5` con `ancho_mbb < 35 m`,
   `n_unidades <= 3` o `horas < 0,50`.
4. **Trazado poco sólido:** `solidez < 0,25` o `compacidad < 0,08` con
   `n_unidades <= 2`, `coherencia >= 0,95` o `aspect_ratio > 4`.
5. **Esfuerzo insuficiente:** `n_puntos < 40` y `horas < 0,15`, con
   `densidad < 70 pts/ha` o una sola unidad.
6. **Micro-ruido:** `cuenta_ha < 0,10` y `solidez < 0,40`.
7. **Campo / fragmento:** con `solidez >= 0,25` y `compacidad >= 0,08`; es
   `CAMPO` si `cuenta_ha >= 0,60` o hay al menos 3 unidades y 40 puntos.
8. **Fragmento irregular:** si la compacidad final es `< 0,05`, se envía a
   `TRAYECTO_DISPERSO` aunque tenga varias unidades.

Las salidas incorporan:

- `aspect_ratio`: largo/ancho del Minimum Bounding Box.
- `ancho_mbb`: ancho del MBB en metros; señal para separar trazas lineales.
- `subcategoria`: `TRABAJO_AGRICOLA`, `NO_ES_CAMPO` o `RUIDO_COBERTURA`.
- `metrica_detonante`: señal que decidió el filtro.
- `cuenta_ha_valida`: si la cobertura cuenta hectáreas. Solo
  `CAMPO_PROBABLE` y `CAMPO_FRAGMENTO` cuentan; `DUDOSO` queda para revisión
  con `cuenta_ha = 0`.

## Parámetros

`config_campos.yaml` contiene tiempo, forma, fusión, compuertas y base. Los
valores por defecto están congelados en `campos_tractor/unidades.py:CFG_CAMPOS`.
No se estima el ancho de trabajo de la máquina; `ancho_mbb` es solo una señal
geométrica del polígono para distinguir trazas lineales.

## Pruebas

```powershell
pytest -q
```

Todas las pruebas usan datos sintéticos generados por código. No leen archivos
reales ni GeoPackages externos.

## Límites

- Sin fronteras de referencia no se puede afirmar exactitud geométrica real.
- La compuerta de 20 pts/ha puede descartar campos ralos reales.
- El buffer no supera al casco cóncavo en todos los escenarios sintéticos.
- La caja de México es un respaldo, no una frontera exacta.
