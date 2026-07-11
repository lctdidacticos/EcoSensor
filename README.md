# EcoSensor Dashboard

Web App para explorar mediciones ambientales generadas por EcoSensor desde archivos CSV.

## Objetivo

- Cargar archivos CSV de mediciones ambientales.
- Generar graficas interactivas contra tiempo.
- Comparar parametros por territorio cuando el CSV incluya columnas de geolocalizacion o territorio.
- Calcular estadisticas descriptivas.
- Emitir recomendaciones configurables con base en limites de referencia editables.
- Preparar el proyecto para despliegue en Render.

## Estructura

- `app/main.py`: entrada Streamlit del dashboard.
- `src/ecosensor/data`: carga, limpieza y deteccion de columnas.
- `src/ecosensor/charts`: fabricas de graficas Plotly.
- `src/ecosensor/stats`: estadisticas descriptivas.
- `src/ecosensor/recommendations`: reglas configurables.
- `config/reference_limits.yaml`: limites iniciales editables.
- `data/raw`: CSV originales.
- `exports`: archivos generados por el usuario.

## Ejecucion local

```powershell
cd C:\CODEX\EcoSensor
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app/main.py
```

## Datos actuales

El primer CSV de referencia esta en `data/raw/EcoSensor_02.csv`. Este archivo contiene fecha, hora y parametros ambientales, pero no contiene columnas visibles de geolocalizacion. El dashboard queda preparado para activar comparativas territoriales cuando se cargue un CSV con columnas como `territorio`, `estado`, `municipio`, `ciudad`, `latitud` o `longitud`.

## Localidades GPS

La comparativa territorial usa `config/localities.csv` para convertir coordenadas en nombres de localidad. Cada fila define `nombre`, `latitud`, `longitud` y `radio_km`. Si el archivo no existe o no contiene localidades validas, la app crea grupos automaticos con el radio elegido en la barra lateral.
## Geocodificacion inversa

La app puede usar una API de geocodificacion inversa para convertir el centro de cada grupo GPS en un nombre de localidad. El radio elegido en la barra lateral recalcula dinamicamente los grupos y, por tanto, la comparativa territorial. Si no hay internet o la API no responde, se conserva un fallback local para no bloquear el analisis.
## Agrupacion temporal y exportacion

La grafica contra tiempo permite agrupar mediciones en intervalos de 5, 15 y 30 minutos, o 1, 2 y 4 horas. La comparativa territorial tambien puede descargarse como HTML interactivo para compartir resultados academicos.
## Comparativa territorial multiple

La comparativa territorial permite seleccionar varias localidades y varias variables medidas para construir un grafico comparativo agrupado. La barra lateral mantiene el selector de CSV local para pruebas y ordena los filtros principales segun el flujo de analisis: archivo, fechas, parametros, tipo de grafica, intervalo temporal, radio de localidad y API de nombres.