from __future__ import annotations

from pathlib import Path
from typing import Any
import re

import pandas as pd
import yaml


def _normalize_metric_name(value: str) -> str:
    base_name = str(value).split("(", 1)[0]
    normalized = (
        base_name.replace("µ", "u")
        .replace("³", "3")
        .replace("°", "")
        .replace("Â", "")
        .lower()
    )
    return re.sub(r"[^a-z0-9.]+", "", normalized)


def load_reference_limits(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    return {_normalize_metric_name(key): value for key, value in loaded.items()}


def build_recommendations(summary: pd.DataFrame, reference_limits: dict[str, Any]) -> list[dict[str, str]]:
    if summary.empty:
        return []

    recommendations: list[dict[str, str]] = []
    for row in summary.to_dict("records"):
        metric = str(row["Parametro"])
        normalized_metric = _normalize_metric_name(metric)
        limits = reference_limits.get(normalized_metric)
        if not limits:
            continue

        maximum = row.get("Maximo")
        minimum = row.get("Minimo")
        average = row.get("Promedio")
        status = "Normal"
        message = "Sin excedencias contra los limites configurados."

        if "critical" in limits and pd.notna(maximum) and maximum >= limits["critical"]:
            status = "Critico"
            message = limits.get("high_message", "Valor maximo por encima del limite critico configurado.")
        elif "warning" in limits and pd.notna(maximum) and maximum >= limits["warning"]:
            status = "Alerta"
            message = limits.get("high_message", "Valor maximo por encima del limite de alerta configurado.")
        elif "warning_low" in limits and pd.notna(minimum) and minimum < limits["warning_low"]:
            status = "Alerta"
            message = limits.get("high_message", "Valor minimo por debajo del rango operativo configurado.")
        elif "warning_high" in limits and pd.notna(maximum) and maximum > limits["warning_high"]:
            status = "Alerta"
            message = limits.get("high_message", "Valor maximo por encima del rango operativo configurado.")

        recommendations.append(
            {
                "Parametro": metric,
                "Estado": status,
                "Promedio": f"{average:.3f}" if pd.notna(average) else "N/D",
                "Maximo": f"{maximum:.3f}" if pd.notna(maximum) else "N/D",
                "Recomendacion": message,
            }
        )

    return recommendations
