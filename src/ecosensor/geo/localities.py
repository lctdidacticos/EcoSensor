from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

import pandas as pd

LOCALITY_COLUMN = "Localidad"
DEFAULT_RADIUS_KM = 3.0
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "EcoSensor-Analitica/0.1"


@dataclass(frozen=True)
class Locality:
    name: str
    latitude: float
    longitude: float
    radius_km: float = DEFAULT_RADIUS_KM


@dataclass
class LocalityCluster:
    label: str
    latitude: float
    longitude: float
    count: int = 0


def haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    earth_radius_km = 6371.0088
    delta_lat = radians(lat_b - lat_a)
    delta_lon = radians(lon_b - lon_a)
    origin_lat = radians(lat_a)
    target_lat = radians(lat_b)
    value = sin(delta_lat / 2) ** 2 + cos(origin_lat) * cos(target_lat) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(value))


def load_localities(path: Path) -> list[Locality]:
    if not path.exists():
        return []

    df = pd.read_csv(path)
    required_columns = {"nombre", "latitud", "longitud"}
    if not required_columns.issubset({column.lower().strip() for column in df.columns}):
        return []

    normalized_columns = {column.lower().strip(): column for column in df.columns}
    name_column = normalized_columns["nombre"]
    latitude_column = normalized_columns["latitud"]
    longitude_column = normalized_columns["longitud"]
    radius_column = normalized_columns.get("radio_km")

    localities: list[Locality] = []
    for row in df.to_dict("records"):
        name = str(row.get(name_column, "")).strip()
        latitude = pd.to_numeric(row.get(latitude_column), errors="coerce")
        longitude = pd.to_numeric(row.get(longitude_column), errors="coerce")
        radius = pd.to_numeric(row.get(radius_column), errors="coerce") if radius_column else DEFAULT_RADIUS_KM
        if name and pd.notna(latitude) and pd.notna(longitude):
            localities.append(
                Locality(
                    name=name,
                    latitude=float(latitude),
                    longitude=float(longitude),
                    radius_km=float(radius) if pd.notna(radius) else DEFAULT_RADIUS_KM,
                )
            )
    return localities


@lru_cache(maxsize=512)
def reverse_geocode_locality(latitude: float, longitude: float) -> str | None:
    query = urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "zoom": 10,
            "addressdetails": 1,
            "accept-language": "es",
        }
    )
    request = Request(
        f"{NOMINATIM_REVERSE_URL}?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return None

    address = payload.get("address") or {}
    for key in (
        "city",
        "town",
        "village",
        "municipality",
        "county",
        "suburb",
        "neighbourhood",
        "state_district",
        "state",
    ):
        value = str(address.get(key, "")).strip()
        if value:
            return value

    display_name = str(payload.get("display_name", "")).strip()
    return display_name.split(",", 1)[0] if display_name else None


def _assign_from_catalog(
    df: pd.DataFrame,
    latitude_column: str,
    longitude_column: str,
    localities: list[Locality],
) -> pd.Series:
    labels = pd.Series("Sin localidad", index=df.index, dtype="string")
    valid_gps = df[latitude_column].notna() & df[longitude_column].notna()

    for index, row in df.loc[valid_gps, [latitude_column, longitude_column]].iterrows():
        latitude = float(row[latitude_column])
        longitude = float(row[longitude_column])
        matches = [
            (haversine_km(latitude, longitude, locality.latitude, locality.longitude), locality)
            for locality in localities
        ]
        if not matches:
            continue
        distance_km, locality = min(matches, key=lambda item: item[0])
        if distance_km <= locality.radius_km:
            labels.at[index] = locality.name

    return labels


def _build_auto_clusters(
    df: pd.DataFrame,
    latitude_column: str,
    longitude_column: str,
    radius_km: float,
) -> tuple[pd.Series, list[LocalityCluster]]:
    labels = pd.Series("Sin localidad", index=df.index, dtype="string")
    valid_points = df.loc[df[latitude_column].notna() & df[longitude_column].notna(), [latitude_column, longitude_column]]
    clusters: list[LocalityCluster] = []

    for index, row in valid_points.iterrows():
        latitude = float(row[latitude_column])
        longitude = float(row[longitude_column])
        best_cluster: LocalityCluster | None = None
        best_distance: float | None = None

        for cluster in clusters:
            distance = haversine_km(latitude, longitude, cluster.latitude, cluster.longitude)
            if distance <= radius_km and (best_distance is None or distance < best_distance):
                best_cluster = cluster
                best_distance = distance

        if best_cluster is None:
            best_cluster = LocalityCluster(label=f"Localidad {len(clusters) + 1}", latitude=latitude, longitude=longitude)
            clusters.append(best_cluster)

        best_cluster.latitude = (best_cluster.latitude * best_cluster.count + latitude) / (best_cluster.count + 1)
        best_cluster.longitude = (best_cluster.longitude * best_cluster.count + longitude) / (best_cluster.count + 1)
        best_cluster.count += 1
        labels.at[index] = best_cluster.label

    return labels, clusters


def _replace_cluster_labels_with_api_names(labels: pd.Series, clusters: list[LocalityCluster]) -> pd.Series:
    replacements: dict[str, str] = {}
    seen_names: dict[str, int] = {}

    for cluster in clusters:
        locality_name = reverse_geocode_locality(round(cluster.latitude, 6), round(cluster.longitude, 6))
        if not locality_name:
            locality_name = cluster.label

        seen_names[locality_name] = seen_names.get(locality_name, 0) + 1
        if seen_names[locality_name] > 1:
            locality_name = f"{locality_name} ({seen_names[locality_name]})"
        replacements[cluster.label] = locality_name

    return labels.replace(replacements)


def add_locality_labels(
    df: pd.DataFrame,
    latitude_column: str | None,
    longitude_column: str | None,
    localities_path: Path | None = None,
    default_radius_km: float = DEFAULT_RADIUS_KM,
    use_reverse_geocoding: bool = False,
) -> pd.DataFrame:
    if not latitude_column or not longitude_column:
        return df
    if latitude_column not in df.columns or longitude_column not in df.columns:
        return df

    if use_reverse_geocoding:
        labels, clusters = _build_auto_clusters(df, latitude_column, longitude_column, default_radius_km)
        df[LOCALITY_COLUMN] = _replace_cluster_labels_with_api_names(labels, clusters)
        return df

    localities = load_localities(localities_path) if localities_path else []
    if localities:
        df[LOCALITY_COLUMN] = _assign_from_catalog(df, latitude_column, longitude_column, localities)
    else:
        labels, _clusters = _build_auto_clusters(df, latitude_column, longitude_column, default_radius_km)
        df[LOCALITY_COLUMN] = labels
    return df