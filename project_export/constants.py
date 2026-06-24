"""Shared constants for the Project Export plugin."""

from __future__ import annotations

PLUGIN_NAME = "Project Export"

DEFAULT_OUTPUT_CRS = "EPSG:4326"

DEFAULT_OUTPUT_FORMAT = "GeoJSON"

OUTPUT_FORMATS: dict[str, str] = {
    "GeoPackage": ".gpkg",
    "GeoJSON": ".geojson",
    "ESRI Shapefile": ".shp",
}

RASTER_OUTPUT_FORMAT = "GeoTIFF"
RASTER_OUTPUT_EXTENSION = ".tif"

DEFAULT_PROJECT_BASENAME = "exported"

DEFAULT_NAME_SUFFIX = "_export"

NAMING_MODE_IGNORE = "ignore"
NAMING_MODE_PREFIX = "prefix"
NAMING_MODE_SUFFIX = "suffix"

NAMING_MODE_LABELS: dict[str, str] = {
    NAMING_MODE_IGNORE: "Keep original names",
    NAMING_MODE_PREFIX: "Add prefix",
    NAMING_MODE_SUFFIX: "Add suffix",
}

SETTINGS_PREFIX = "ProjectExport/"


def format_label_for_suffix(suffix: str) -> str:
    """Return the format label for a file suffix.

    Parameters
    ----------
    suffix
        File suffix including the leading dot (e.g. ``".gpkg"``).

    Returns
    -------
    str
        Matching key from ``OUTPUT_FORMATS``.

    Raises
    ------
    ValueError
        If ``suffix`` does not match a supported format.
    """
    normalized = suffix.lower()
    if normalized == RASTER_OUTPUT_EXTENSION:
        return RASTER_OUTPUT_FORMAT

    for label, extension in OUTPUT_FORMATS.items():
        if extension == normalized:
            return label
    raise ValueError(f"Unsupported file extension: {suffix}")
