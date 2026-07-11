from __future__ import annotations


def has_geo_support(geo_columns: list[str]) -> bool:
    return len(geo_columns) > 0
