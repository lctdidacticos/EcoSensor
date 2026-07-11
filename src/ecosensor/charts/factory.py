from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

TEMPLATE = "plotly_white"
COLOR_SEQUENCE = ["#0F766E", "#2563EB", "#D97706", "#7C3AED", "#DC2626", "#0891B2"]
EXCLUDED_GEO_LABELS = {"sin localidad", "sin ubicacion"}


def build_time_chart(
    df: pd.DataFrame,
    timestamp_column: str,
    metrics: list[str],
    chart_type: str,
) -> go.Figure:
    if not metrics:
        return go.Figure()

    plot_df = df[[timestamp_column, *metrics]].copy()
    plot_df = plot_df.melt(
        id_vars=timestamp_column,
        value_vars=metrics,
        var_name="Parametro",
        value_name="Valor",
    )

    chart_type = chart_type.lower()
    if chart_type == "area":
        fig = px.area(
            plot_df,
            x=timestamp_column,
            y="Valor",
            color="Parametro",
            template=TEMPLATE,
            color_discrete_sequence=COLOR_SEQUENCE,
        )
    elif chart_type == "dispersion":
        fig = px.scatter(
            plot_df,
            x=timestamp_column,
            y="Valor",
            color="Parametro",
            template=TEMPLATE,
            color_discrete_sequence=COLOR_SEQUENCE,
        )
    elif chart_type == "barras":
        fig = px.bar(
            plot_df,
            x=timestamp_column,
            y="Valor",
            color="Parametro",
            template=TEMPLATE,
            color_discrete_sequence=COLOR_SEQUENCE,
        )
    else:
        fig = px.line(
            plot_df,
            x=timestamp_column,
            y="Valor",
            color="Parametro",
            markers=True,
            template=TEMPLATE,
            color_discrete_sequence=COLOR_SEQUENCE,
        )

    fig.update_layout(
        title="Mediciones ambientales contra tiempo",
        xaxis_title="Tiempo",
        yaxis_title="Valor medido",
        legend_title="Parametro",
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


def _aggregate_geo(df: pd.DataFrame, geo_column: str, metrics: list[str], aggregation: str) -> pd.DataFrame:
    chart_df = df.dropna(subset=[geo_column, *metrics]).copy()
    chart_df = chart_df[~chart_df[geo_column].astype(str).str.lower().isin(EXCLUDED_GEO_LABELS)]
    if chart_df.empty:
        return pd.DataFrame(columns=[geo_column, *metrics])

    grouped = chart_df.groupby(geo_column, dropna=False)[metrics]
    if aggregation == "Maximo":
        return grouped.max().reset_index()
    if aggregation == "Minimo":
        return grouped.min().reset_index()
    if aggregation == "Mediana":
        return grouped.median().reset_index()
    return grouped.mean().reset_index()


def build_geo_bar_chart(
    df: pd.DataFrame,
    geo_column: str,
    metric: str,
    aggregation: str,
) -> go.Figure:
    grouped = _aggregate_geo(df, geo_column, [metric], aggregation)
    if grouped.empty:
        return go.Figure()

    grouped = grouped.sort_values(metric, ascending=False).head(30)
    fig = px.bar(
        grouped,
        x=geo_column,
        y=metric,
        template=TEMPLATE,
        color=metric,
        color_continuous_scale="Tealgrn",
    )
    fig.update_layout(
        title=f"Comparativa territorial: {metric}",
        xaxis_title=geo_column,
        yaxis_title=f"{aggregation} de {metric}",
        margin=dict(l=20, r=20, t=60, b=80),
    )
    fig.update_xaxes(tickangle=-35)
    return fig


def build_geo_comparison_chart(
    df: pd.DataFrame,
    geo_column: str,
    localities: list[str],
    metrics: list[str],
    aggregation: str,
) -> go.Figure:
    if not localities or not metrics:
        return go.Figure()

    chart_df = df[df[geo_column].isin(localities)].copy()
    grouped = _aggregate_geo(chart_df, geo_column, metrics, aggregation)
    if grouped.empty:
        return go.Figure()

    grouped[geo_column] = pd.Categorical(grouped[geo_column], categories=localities, ordered=True)
    grouped = grouped.sort_values(geo_column)
    plot_df = grouped.melt(
        id_vars=geo_column,
        value_vars=metrics,
        var_name="Parametro",
        value_name="Valor",
    )

    fig = go.Figure()
    bar_width = max(0.12, min(0.26, 0.75 / max(len(metrics), 1)))
    for index, metric in enumerate(metrics):
        fig.add_trace(
            go.Bar(
                name=metric,
                x=grouped[geo_column].astype(str).tolist(),
                y=grouped[metric].tolist(),
                width=bar_width,
                marker_color=COLOR_SEQUENCE[index % len(COLOR_SEQUENCE)],
                text=[f"{value:.2f}" if pd.notna(value) else "" for value in grouped[metric].tolist()],
                textposition="outside",
                offsetgroup=metric,
                showlegend=True,
            )
        )

    fig.update_layout(
        title="Comparativa territorial por localidad",
        template=TEMPLATE,
        barmode="group",
        bargap=0.28,
        bargroupgap=0.08,
        xaxis_title="Localidad",
        yaxis_title=f"{aggregation} de mediciones",
        legend_title="Parametro",
        margin=dict(l=20, r=20, t=70, b=95),
        uniformtext_minsize=9,
        uniformtext_mode="hide",
    )
    fig.update_xaxes(tickangle=-35, categoryorder="array", categoryarray=localities)
    return fig


def build_location_map(
    df: pd.DataFrame,
    latitude_column: str,
    longitude_column: str,
    metric: str,
) -> go.Figure:
    map_df = df.dropna(subset=[latitude_column, longitude_column, metric]).copy()
    if map_df.empty:
        return go.Figure()

    hover_data = [column for column in ("device_id", "Localidad", "Ubicacion GPS") if column in map_df.columns]
    fig = px.scatter_mapbox(
        map_df,
        lat=latitude_column,
        lon=longitude_column,
        color=metric,
        size=metric,
        size_max=18,
        zoom=11,
        height=520,
        template=TEMPLATE,
        color_continuous_scale="Viridis",
        hover_data=hover_data,
    )
    fig.update_layout(
        title=f"Mapa de mediciones GPS: {metric}",
        mapbox_style="open-street-map",
        margin=dict(l=0, r=0, t=55, b=0),
    )
    return fig