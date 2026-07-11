from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go


@dataclass(frozen=True)
class FigureDownloads:
    html: str
    png: bytes | None
    png_error: str | None


def figure_to_downloads(fig: go.Figure) -> FigureDownloads:
    html = fig.to_html(full_html=True, include_plotlyjs="cdn")
    try:
        png = fig.to_image(format="png", scale=2)
        return FigureDownloads(html=html, png=png, png_error=None)
    except Exception as error:
        return FigureDownloads(html=html, png=None, png_error=str(error))
