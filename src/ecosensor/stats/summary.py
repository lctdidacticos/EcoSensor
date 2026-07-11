from __future__ import annotations

import pandas as pd


def build_numeric_summary(df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    if not metrics:
        return pd.DataFrame()

    summary = df[metrics].describe(percentiles=[0.25, 0.5, 0.75]).T
    summary = summary.rename(
        columns={
            "count": "Registros",
            "mean": "Promedio",
            "std": "Desv_est",
            "min": "Minimo",
            "25%": "P25",
            "50%": "Mediana",
            "75%": "P75",
            "max": "Maximo",
        }
    )
    return summary.reset_index(names="Parametro").round(3)
