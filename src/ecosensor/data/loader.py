from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from ecosensor.geo import LOCALITY_COLUMN, add_locality_labels

DATE_CANDIDATES = ("fecha", "date")
TIME_CANDIDATES = ("hora", "time")
LATITUDE_CANDIDATES = ("latitud", "latitude", "lat")
LONGITUDE_CANDIDATES = ("longitud", "longitude", "lng", "lon")
GEO_KEYWORDS = (
    "territorio",
    "region",
    "estado",
    "municipio",
    "ciudad",
    "localidad",
    "zona",
    "sitio",
    "pais",
    "ubicacion",
    "location",
    "device_id",
)
IDENTIFIER_COLUMNS = ("id", "record_id", "registro_id", "measurement_id")
ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin1")
GPS_ZONE_COLUMN = "Ubicacion GPS"


@dataclass(frozen=True)
class DataQualityReport:
    original_rows: int
    accepted_rows: int
    empty_rows: int
    invalid_timestamp_rows: int
    incomplete_gps_rows: int
    out_of_range_gps_rows: int
    numeric_parse_failures: dict[str, int]


@dataclass(frozen=True)
class DataProfile:
    timestamp_column: str
    numeric_columns: list[str]
    categorical_columns: list[str]
    geo_columns: list[str]
    row_count: int
    start_time: pd.Timestamp | None
    end_time: pd.Timestamp | None
    latitude_column: str | None = None
    longitude_column: str | None = None
    locality_column: str | None = None
    gps_row_count: int = 0
    quality: DataQualityReport | None = None


def _read_csv(source: str | Path | BinaryIO) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            return pd.read_csv(source, encoding=encoding)
        except UnicodeDecodeError as error:
            last_error = error
    raise ValueError(f"No se pudo leer el CSV con codificaciones conocidas: {last_error}")


def _normalize_column_name(column: object) -> str:
    return str(column).strip().replace("Ãƒâ€š", "")


def _find_first_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {column.lower().strip(): column for column in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    for column in columns:
        normalized = column.lower().strip()
        if any(candidate == normalized or candidate in normalized for candidate in candidates):
            return column
    return None


def _add_timestamp(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    date_column = _find_first_column(df.columns.tolist(), DATE_CANDIDATES)
    time_column = _find_first_column(df.columns.tolist(), TIME_CANDIDATES)

    if date_column and time_column:
        raw_datetime = df[date_column].astype(str).str.strip() + " " + df[time_column].astype(str).str.strip()
        df["timestamp"] = pd.to_datetime(raw_datetime, dayfirst=True, errors="coerce")
        return df, "timestamp"

    if date_column:
        df["timestamp"] = pd.to_datetime(df[date_column], dayfirst=True, errors="coerce")
        return df, "timestamp"

    for column in df.columns:
        parsed = pd.to_datetime(df[column], dayfirst=True, errors="coerce")
        if parsed.notna().mean() >= 0.8:
            df["timestamp"] = parsed
            return df, "timestamp"

    raise ValueError("No se encontro una columna de fecha/hora interpretable en el CSV.")


def _coerce_numeric_columns(df: pd.DataFrame, timestamp_column: str) -> tuple[pd.DataFrame, dict[str, int]]:
    failures: dict[str, int] = {}
    for column in df.columns:
        if column == timestamp_column:
            continue
        if pd.api.types.is_numeric_dtype(df[column]):
            continue
        cleaned = df[column].astype(str).str.replace(",", ".", regex=False).str.strip()
        numeric = pd.to_numeric(cleaned, errors="coerce")
        if numeric.notna().mean() >= 0.75:
            failed = int((cleaned.ne("") & cleaned.ne("nan") & numeric.isna()).sum())
            if failed:
                failures[column] = failed
            df[column] = numeric
    return df, failures


def _coerce_coordinates(
    df: pd.DataFrame,
    latitude_column: str | None,
    longitude_column: str | None,
) -> pd.DataFrame:
    for column in (latitude_column, longitude_column):
        if column:
            cleaned = df[column].astype(str).str.replace(",", ".", regex=False).str.strip()
            df[column] = pd.to_numeric(cleaned, errors="coerce")
    return df


def _detect_coordinate_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    columns = df.columns.tolist()
    latitude_column = _find_first_column(columns, LATITUDE_CANDIDATES)
    longitude_column = _find_first_column(columns, LONGITUDE_CANDIDATES)
    return latitude_column, longitude_column


def _add_gps_zone(df: pd.DataFrame, latitude_column: str | None, longitude_column: str | None) -> pd.DataFrame:
    if not latitude_column or not longitude_column:
        return df

    valid_gps = df[latitude_column].notna() & df[longitude_column].notna()
    if not valid_gps.any():
        return df

    latitude = df[latitude_column].round(4).astype("string")
    longitude = df[longitude_column].round(4).astype("string")
    df[GPS_ZONE_COLUMN] = "Sin ubicacion"
    df.loc[valid_gps, GPS_ZONE_COLUMN] = latitude[valid_gps] + ", " + longitude[valid_gps]
    return df


def _is_identifier_column(column: str) -> bool:
    normalized = column.lower().strip()
    return normalized in IDENTIFIER_COLUMNS or normalized.endswith("_id")


def _detect_geo_columns(df: pd.DataFrame, latitude_column: str | None, longitude_column: str | None) -> list[str]:
    detected: list[str] = []
    coordinate_columns = {column for column in (latitude_column, longitude_column) if column}
    for column in df.columns:
        if column in coordinate_columns:
            continue
        normalized = column.lower().strip()
        if any(keyword in normalized for keyword in GEO_KEYWORDS):
            detected.append(column)
    for derived_column in (LOCALITY_COLUMN, GPS_ZONE_COLUMN):
        if derived_column in df.columns and derived_column not in detected:
            detected.append(derived_column)
    return detected


def load_measurements(
    source: str | Path | BinaryIO,
    localities_path: Path | None = None,
    locality_radius_km: float = 3.0,
    use_reverse_geocoding: bool = False,
) -> tuple[pd.DataFrame, DataProfile]:
    df = _read_csv(source)
    if df.empty:
        raise ValueError("El CSV no contiene registros.")

    original_rows = len(df)
    df.columns = [_normalize_column_name(column) for column in df.columns]
    empty_rows = int(df.isna().all(axis=1).sum())
    df = df.dropna(how="all").copy()
    df, timestamp_column = _add_timestamp(df)
    invalid_timestamp_rows = int(df[timestamp_column].isna().sum())
    df, numeric_parse_failures = _coerce_numeric_columns(df, timestamp_column)
    df = df.dropna(subset=[timestamp_column]).sort_values(timestamp_column)

    latitude_column, longitude_column = _detect_coordinate_columns(df)
    df = _coerce_coordinates(df, latitude_column, longitude_column)
    incomplete_gps_rows = 0
    out_of_range_gps_rows = 0
    if latitude_column and longitude_column:
        latitude_present = df[latitude_column].notna()
        longitude_present = df[longitude_column].notna()
        incomplete_gps_rows = int((latitude_present ^ longitude_present).sum())
        complete_gps = latitude_present & longitude_present
        valid_range = df[latitude_column].between(-90, 90) & df[longitude_column].between(-180, 180)
        out_of_range_gps_rows = int((complete_gps & ~valid_range).sum())
        df.loc[complete_gps & ~valid_range, [latitude_column, longitude_column]] = pd.NA
    df = _add_gps_zone(df, latitude_column, longitude_column)
    df = add_locality_labels(
        df,
        latitude_column,
        longitude_column,
        localities_path,
        locality_radius_km,
        use_reverse_geocoding,
    )
    coordinate_columns = {column for column in (latitude_column, longitude_column) if column}

    numeric_columns = [
        column
        for column in df.select_dtypes(include="number").columns.tolist()
        if column != timestamp_column and column not in coordinate_columns and not _is_identifier_column(column)
    ]
    categorical_columns = [
        column
        for column in df.columns.tolist()
        if column not in numeric_columns and column != timestamp_column
    ]
    geo_columns = _detect_geo_columns(df, latitude_column, longitude_column)
    gps_row_count = 0
    locality_column = LOCALITY_COLUMN if LOCALITY_COLUMN in df.columns else None
    if latitude_column and longitude_column:
        gps_row_count = int((df[latitude_column].notna() & df[longitude_column].notna()).sum())

    profile = DataProfile(
        timestamp_column=timestamp_column,
        numeric_columns=numeric_columns,
        categorical_columns=categorical_columns,
        geo_columns=geo_columns,
        row_count=len(df),
        start_time=df[timestamp_column].min() if not df.empty else None,
        end_time=df[timestamp_column].max() if not df.empty else None,
        latitude_column=latitude_column,
        longitude_column=longitude_column,
        locality_column=locality_column,
        gps_row_count=gps_row_count,
        quality=DataQualityReport(
            original_rows=original_rows,
            accepted_rows=len(df),
            empty_rows=empty_rows,
            invalid_timestamp_rows=invalid_timestamp_rows,
            incomplete_gps_rows=incomplete_gps_rows,
            out_of_range_gps_rows=out_of_range_gps_rows,
            numeric_parse_failures=numeric_parse_failures,
        ),
    )
    return df, profile
