from __future__ import annotations

from pathlib import Path
import base64
import html
import sys

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ecosensor.charts import build_geo_comparison_chart, build_location_map, build_time_chart
from ecosensor.data import load_measurements
from ecosensor.export import figure_to_downloads
from ecosensor.geo import DEFAULT_RADIUS_KM, LOCALITY_COLUMN
from ecosensor.recommendations import build_recommendations, load_reference_limits
from ecosensor.stats import build_numeric_summary

DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "raw"
REFERENCE_LIMITS = PROJECT_ROOT / "config" / "reference_limits.yaml"
LOCALITIES_FILE = PROJECT_ROOT / "config" / "localities.csv"
LOGO_FILE = PROJECT_ROOT / "LOGO_blanco.png"
TIME_INTERVALS = {
    "5 min": "5min",
    "15 min": "15min",
    "30 min": "30min",
    "1 hora": "1h",
    "2 horas": "2h",
    "4 horas": "4h",
}
EXCLUDED_LOCALITIES = {"sin localidad", "sin ubicacion"}

st.set_page_config(
    page_title="EcoSensor - Analitica",
    page_icon="EcoSensor",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    .ecosensor-header {display:flex; align-items:center; gap:1.25rem; background:#0f3d3e; padding:1rem 1.25rem; border-radius:8px; margin-bottom:1rem;}
    .ecosensor-logo {height:77px; width:auto; flex:0 0 auto;}
    .ecosensor-title {color:white; margin:0; font-size:2.25rem; line-height:1.1;}
    .ecosensor-subtitle {color:#d7f3ef; margin:0.35rem 0 0 0;}
    .status-grid {display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:.75rem; margin:.5rem 0 1rem;}
    .status-card {border-left:6px solid; border-radius:8px; padding:.8rem 1rem; background:#111827; box-shadow:0 1px 3px rgba(0,0,0,.25);}
    .status-card h4 {margin:0 0 .35rem; color:#f9fafb;}
    .status-card p {margin:.2rem 0; color:#d1d5db; font-size:.9rem;}
    .status-normal {border-color:#22c55e;}
    .status-alerta {border-color:#f59e0b;}
    .status-critico {border-color:#ef4444;}
    @media (max-width: 640px) {
        .block-container {padding-left:.75rem; padding-right:.75rem; padding-top:.6rem;}
        .ecosensor-header {gap:.75rem; padding:.75rem; align-items:flex-start;}
        .ecosensor-logo {height:48px;}
        .ecosensor-title {font-size:1.35rem !important;}
        .ecosensor-subtitle {font-size:.82rem;}
        div[data-testid="stMetric"] {padding:.45rem;}
        div[data-testid="stMetricValue"] {font-size:1.25rem;}
        .status-grid {grid-template-columns:1fr;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if LOGO_FILE.exists():
    logo_base64 = base64.b64encode(LOGO_FILE.read_bytes()).decode("ascii")
    st.markdown(
        f"""
        <div class="ecosensor-header">
            <img class="ecosensor-logo" src="data:image/png;base64,{logo_base64}" />
            <div>
                <h1 class="ecosensor-title">EcoSensor - Analitica</h1>
                <p class="ecosensor-subtitle">Dashboard interactivo para mediciones ambientales en CSV.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.title("EcoSensor - Analitica")
    st.caption("Dashboard interactivo para mediciones ambientales en CSV.")


def _available_csv_files() -> list[Path]:
    return sorted(DEFAULT_DATA_DIR.glob("*.csv"), key=lambda path: path.stat().st_mtime)


def _select_time_range(df: pd.DataFrame, timestamp_column: str) -> tuple[object, object] | None:
    min_date = df[timestamp_column].min().date()
    max_date = df[timestamp_column].max().date()
    selected_range = st.sidebar.date_input(
        "Intervalo de fechas",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    if isinstance(selected_range, tuple) and len(selected_range) == 2:
        return selected_range
    return None


def _apply_time_filter(
    df: pd.DataFrame,
    timestamp_column: str,
    selected_range: tuple[object, object] | None,
) -> pd.DataFrame:
    if selected_range is None:
        return df.copy()
    start_date, end_date = selected_range
    mask = (df[timestamp_column].dt.date >= start_date) & (df[timestamp_column].dt.date <= end_date)
    return df.loc[mask].copy()


def _aggregate_time_series(
    df: pd.DataFrame,
    timestamp_column: str,
    metrics: list[str],
    frequency: str,
) -> pd.DataFrame:
    if df.empty or not metrics:
        return df[[timestamp_column, *metrics]].copy()

    aggregated = (
        df[[timestamp_column, *metrics]]
        .dropna(subset=[timestamp_column])
        .set_index(timestamp_column)
        .resample(frequency)[metrics]
        .mean()
        .dropna(how="all")
        .reset_index()
    )
    return aggregated


def _valid_localities(df: pd.DataFrame, locality_column: str) -> list[str]:
    values = sorted(str(value) for value in df[locality_column].dropna().unique().tolist())
    return [value for value in values if value.lower() not in EXCLUDED_LOCALITIES]


st.sidebar.header("Filtros")
uploaded_file = st.sidebar.file_uploader("Subir CSV de EcoSensor", type=["csv"])
local_csv_files = _available_csv_files()
selected_local_csv = None
if uploaded_file is None and local_csv_files:
    selected_name = st.sidebar.selectbox("CSV local", [path.name for path in local_csv_files], index=len(local_csv_files) - 1)
    selected_local_csv = next(path for path in local_csv_files if path.name == selected_name)

source = uploaded_file if uploaded_file is not None else selected_local_csv
if source is None:
    st.info("Coloca un CSV en data/raw o sube un archivo desde la barra lateral.")
    st.stop()

try:
    preview_df, preview_profile = load_measurements(source, LOCALITIES_FILE, DEFAULT_RADIUS_KM, False)
except Exception as error:
    st.error(f"No se pudo cargar el CSV: {error}")
    st.stop()

selected_date_range = _select_time_range(preview_df, preview_profile.timestamp_column)
metrics = st.sidebar.multiselect(
    "Parametros a graficar",
    options=preview_profile.numeric_columns,
    default=preview_profile.numeric_columns[: min(3, len(preview_profile.numeric_columns))],
)
chart_type = st.sidebar.selectbox("Tipo de grafica", ["Linea", "Area", "Dispersion", "Barras"])
time_interval_label = st.sidebar.select_slider(
    "Agrupar mediciones cada",
    options=list(TIME_INTERVALS.keys()),
    value="5 min",
)
locality_radius_km = st.sidebar.slider(
    "Radio por localidad (km)",
    min_value=0.5,
    max_value=10.0,
    value=DEFAULT_RADIUS_KM,
    step=0.5,
)
use_reverse_geocoding = st.sidebar.checkbox(
    "Usar API para nombres de localidad",
    value=True,
    help="Convierte el centro de cada grupo GPS a nombre de localidad mediante geocodificacion inversa.",
)

try:
    df, profile = load_measurements(source, LOCALITIES_FILE, locality_radius_km, use_reverse_geocoding)
except Exception as error:
    st.error(f"No se pudo cargar el CSV: {error}")
    st.stop()

if use_reverse_geocoding:
    st.caption("Modo territorial: nombres de localidad por API cuando hay internet; fallback automatico si la API no responde.")
else:
    st.caption("Modo territorial: catalogo local o agrupacion automatica por radio.")

filtered_df = _apply_time_filter(df, profile.timestamp_column, selected_date_range)

metric_cards = st.columns(5, gap="small")
metric_cards[0].metric("Registros", f"{len(filtered_df):,}")
metric_cards[1].metric("Parametros", len(profile.numeric_columns))
metric_cards[2].metric("GPS valido", f"{profile.gps_row_count:,}")
metric_cards[3].metric("Inicio", profile.start_time.strftime("%Y-%m-%d %H:%M") if profile.start_time else "N/D")
metric_cards[4].metric("Fin", profile.end_time.strftime("%Y-%m-%d %H:%M") if profile.end_time else "N/D")

with st.expander("Calidad y validacion del archivo", expanded=False):
    quality = profile.quality
    if quality:
        quality_columns = st.columns(4)
        quality_columns[0].metric("Filas originales", f"{quality.original_rows:,}")
        quality_columns[1].metric("Filas aceptadas", f"{quality.accepted_rows:,}")
        quality_columns[2].metric("Fechas invalidas", f"{quality.invalid_timestamp_rows:,}")
        quality_columns[3].metric("GPS valido", f"{profile.gps_row_count:,}")
        issues = []
        if quality.empty_rows:
            issues.append(f"{quality.empty_rows:,} filas completamente vacias")
        if quality.invalid_timestamp_rows:
            issues.append(f"{quality.invalid_timestamp_rows:,} filas descartadas por fecha/hora invalida")
        if quality.incomplete_gps_rows:
            issues.append(f"{quality.incomplete_gps_rows:,} filas con solo una coordenada GPS")
        if quality.out_of_range_gps_rows:
            issues.append(f"{quality.out_of_range_gps_rows:,} filas con coordenadas fuera de rango")
        for column, count in quality.numeric_parse_failures.items():
            issues.append(f"{count:,} valores no numericos en {column}")
        if issues:
            st.warning("Se detectaron observaciones de calidad:\n\n- " + "\n- ".join(issues))
        else:
            st.success("El archivo supero las validaciones basicas de estructura, fecha, valores numericos y GPS.")
        st.caption("Las filas sin fecha valida se excluyen del analisis. Las coordenadas incompletas o fuera de rango no se usan en el mapa.")

if not metrics:
    st.warning("Selecciona al menos un parametro numerico.")
    st.stop()

st.subheader("Grafica contra tiempo")
time_chart_df = _aggregate_time_series(filtered_df, profile.timestamp_column, metrics, TIME_INTERVALS[time_interval_label])
st.caption(f"Intervalo de agrupacion: {time_interval_label}. Puntos graficados: {len(time_chart_df):,}.")
time_fig = build_time_chart(time_chart_df, profile.timestamp_column, metrics, chart_type)
st.plotly_chart(time_fig, width="stretch", key="time_series_chart")

downloads = figure_to_downloads(time_fig)
st.download_button(
    "Descargar grafica HTML",
    data=downloads.html,
    file_name="ecosensor_grafica_tiempo.html",
    mime="text/html",
)
if downloads.png is not None:
    st.download_button(
        "Descargar grafica PNG",
        data=downloads.png,
        file_name="ecosensor_grafica_tiempo.png",
        mime="image/png",
    )
else:
    st.caption("La descarga PNG requiere Kaleido disponible en el entorno de ejecucion.")

st.subheader("Mapa GPS")
if profile.latitude_column and profile.longitude_column and profile.gps_row_count > 0:
    map_metric = st.selectbox("Parametro para mapa", profile.numeric_columns, index=0)
    map_fig = build_location_map(filtered_df, profile.latitude_column, profile.longitude_column, map_metric)
    st.plotly_chart(map_fig, width="stretch", key="gps_map_chart")
else:
    st.warning("Este CSV no contiene pares validos de latitud y longitud para generar el mapa.")

st.subheader("Estadistica descriptiva")
summary = build_numeric_summary(filtered_df, metrics)
st.dataframe(summary, width="stretch", hide_index=True)
st.download_button(
    "Descargar estadistica CSV",
    data=summary.to_csv(index=False).encode("utf-8-sig"),
    file_name="ecosensor_estadistica.csv",
    mime="text/csv",
)

st.subheader("Comparativa territorial")
locality_column = profile.locality_column or (LOCALITY_COLUMN if LOCALITY_COLUMN in filtered_df.columns else None)
if locality_column:
    locality_options = _valid_localities(filtered_df, locality_column)
    if locality_options:
        selected_localities = st.multiselect(
            "Localidades a incluir",
            options=locality_options,
            default=locality_options[: min(6, len(locality_options))],
        )
        selected_geo_metrics = st.multiselect(
            "Variables medidas para comparar",
            options=profile.numeric_columns,
            default=profile.numeric_columns[: min(3, len(profile.numeric_columns))],
        )
        aggregation = st.selectbox("Agregacion", ["Promedio", "Maximo", "Minimo", "Mediana"])
        if selected_localities and selected_geo_metrics:
            geo_fig = build_geo_comparison_chart(
                filtered_df,
                locality_column,
                selected_localities,
                selected_geo_metrics,
                aggregation,
            )
            st.plotly_chart(geo_fig, width="stretch", key="territorial_comparison_chart")
            geo_downloads = figure_to_downloads(geo_fig)
            st.download_button(
                "Descargar comparativa territorial HTML",
                data=geo_downloads.html,
                file_name="ecosensor_comparativa_territorial.html",
                mime="text/html",
            )
        else:
            st.warning("Selecciona al menos una localidad y una variable medida.")
    else:
        st.warning("No hay localidades validas para comparar en el intervalo seleccionado.")
else:
    st.warning(
        "Este CSV no incluye columnas de geolocalizacion o territorio. "
        "Cuando el archivo incluya columnas como territorio, estado, municipio, ciudad, latitud o longitud, "
        "esta seccion activara la grafica comparativa de barras."
    )

st.subheader("Evaluacion y recomendaciones")
reference_limits = load_reference_limits(REFERENCE_LIMITS)
recommendations = build_recommendations(summary, reference_limits)
if recommendations:
    cards = []
    for recommendation in recommendations:
        status = str(recommendation["Estado"])
        status_class = "status-" + status.lower()
        cards.append(
            f'<div class="status-card {status_class}">'
            f'<h4>{html.escape(str(recommendation["Parametro"]))} · {html.escape(status)}</h4>'
            f'<p>Promedio: {html.escape(str(recommendation["Promedio"]))} · Maximo: {html.escape(str(recommendation["Maximo"]))}</p>'
            f'<p>{html.escape(str(recommendation["Recomendacion"]))}</p>'
            "</div>"
        )
    st.markdown('<div class="status-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)
    st.caption("Semaforos calculados con los limites configurables del proyecto; no sustituyen normas regulatorias ni criterios medicos.")
    st.dataframe(pd.DataFrame(recommendations), width="stretch", hide_index=True)
else:
    st.info("No hay limites de referencia configurados para los parametros seleccionados.")

with st.expander("Vista previa de datos"):
    st.dataframe(filtered_df.head(200), width="stretch")
