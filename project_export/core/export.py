"""Layer export: fix geometries, reproject, rename, and write project layers."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Callable, NamedTuple

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsLayerTree,
    QgsLayerTreeGroup,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from ..constants import (
    NAMING_MODE_IGNORE,
    NAMING_MODE_PREFIX,
    NAMING_MODE_SUFFIX,
    OUTPUT_FORMATS,
    RASTER_OUTPUT_EXTENSION,
)

ProgressCallback = Callable[[int, str], None]


class ExportedLayer(NamedTuple):
    """An exported file and the source project layer it was created from."""

    path: Path
    source_layer_id: str


def _named_style_export_succeeded(result: object) -> bool:
    """Return whether ``exportNamedStyle`` reported success."""
    if isinstance(result, tuple):
        return bool(result[0])
    if isinstance(result, str):
        return result == ""
    return True


def _named_style_import_succeeded(result: object) -> bool:
    """Return whether ``importNamedStyle`` reported success."""
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


def _copy_renderer_symbology(source: QgsMapLayer, destination: QgsMapLayer) -> bool:
    """Copy renderer, opacity, and blend mode from ``source`` to ``destination``."""
    renderer = source.renderer()
    if renderer is None:
        return False

    destination.setRenderer(renderer.clone())
    destination.setOpacity(source.opacity())
    destination.setBlendMode(source.blendMode())

    if isinstance(source, QgsVectorLayer) and isinstance(destination, QgsVectorLayer):
        destination.setLabelsEnabled(source.labelsEnabled())
        if source.labelsEnabled():
            labeling = source.labeling()
            if labeling is not None:
                destination.setLabeling(labeling.clone())

    destination.triggerRepaint()
    return True


def copy_layer_symbology(source: QgsMapLayer, destination: QgsMapLayer) -> bool:
    """Copy symbology and related style from ``source`` to ``destination``.

    Uses ``exportNamedStyle`` / ``importNamedStyle`` so the active renderer
    (colors, line width, labels, etc.) is copied, not only named style slots.

    Parameters
    ----------
    source
        Layer currently loaded in the project.
    destination
        Newly exported layer to style.

    Returns
    -------
    bool
        ``True`` if style was copied successfully.
    """
    if isinstance(source, QgsVectorLayer) != isinstance(destination, QgsVectorLayer):
        return False
    if isinstance(source, QgsRasterLayer) != isinstance(destination, QgsRasterLayer):
        return False

    document = QDomDocument("qgis")
    export_result = source.exportNamedStyle(document)
    if not _named_style_export_succeeded(export_result):
        return _copy_renderer_symbology(source, destination)

    categories = QgsMapLayer.StyleCategory.AllStyleCategories
    try:
        import_result = destination.importNamedStyle(document, categories)
    except TypeError:
        import_result = destination.importNamedStyle(document)

    if not _named_style_import_succeeded(import_result):
        return _copy_renderer_symbology(source, destination)

    destination.triggerRepaint()
    return True


def _unique_temp_path(target: Path) -> Path:
    """Return a temporary path alongside ``target`` for safe in-place replacement.

    Parameters
    ----------
    target
        Final output path that must not be written directly.

    Returns
    -------
    Path
        Writable temporary path with the same suffix as ``target``.
    """
    return target.parent / f".{target.stem}_{uuid.uuid4().hex[:8]}{target.suffix}"


def _vector_source_path(layer: QgsVectorLayer) -> Path | None:
    """Return the on-disk path for an OGR-backed vector layer, if available.

    Parameters
    ----------
    layer
        Vector layer to inspect.

    Returns
    -------
    Path or None
        Source file path when the layer is file-backed.
    """
    if layer.providerType() != "ogr":
        return None

    source = layer.source().split("|", maxsplit=1)[0]
    source_path = Path(source)
    if source_path.is_file():
        return source_path.resolve()
    return None


def _resolve_export_path(
    output_path: Path, source_path: Path | None
) -> tuple[Path, bool]:
    """Choose a safe write path when export would overwrite the input file.

    Parameters
    ----------
    output_path
        Requested output file path.
    source_path
        On-disk path of the input layer, if known.

    Returns
    -------
    tuple[Path, bool]
        Write path and whether the result must replace ``output_path`` afterward.
    """
    output_path = output_path.resolve()
    if source_path is not None and source_path.resolve() == output_path:
        return _unique_temp_path(output_path), True
    return output_path, False


def _coerce_processing_output_path(output: object, fallback: Path) -> Path:
    """Normalize a processing ``OUTPUT`` value to a filesystem path.

    Parameters
    ----------
    output
        Value returned by a processing algorithm.
    fallback
        Path to use when ``output`` does not reference a file directly.

    Returns
    -------
    Path
        Resolved output file path.
    """
    if isinstance(output, QgsMapLayer):
        source = output.source().split("|", maxsplit=1)[0]
        return Path(source)

    text = str(output)
    if text.startswith("file://"):
        text = text[7:]

    path = Path(text)
    if path.is_file():
        return path
    return fallback


def _finalize_export_path(
    written_path: Path,
    output_path: Path,
    replace_output: bool,
) -> Path:
    """Move a temporary export to its final destination when needed.

    Parameters
    ----------
    written_path
        Path written by a processing algorithm.
    output_path
        Final output path requested by the caller.
    replace_output
        Whether ``written_path`` must replace ``output_path``.

    Returns
    -------
    Path
        Resolved final output path.

    Raises
    ------
    ValueError
        If the written file is missing or empty.
    """
    written_path = _coerce_processing_output_path(written_path, written_path)
    written_path = Path(written_path).resolve()
    output_path = output_path.resolve()

    if not written_path.is_file():
        raise ValueError(f"Export failed: {output_path}")
    if written_path.stat().st_size == 0:
        raise ValueError(f"Export produced an empty file: {written_path}")

    if not replace_output:
        return written_path

    if written_path == output_path:
        return output_path

    if output_path.exists():
        output_path.unlink()
    written_path.replace(output_path)
    return output_path


def _validate_exported_layer(result_path: Path, is_raster: bool) -> None:
    """Verify that an exported file can be opened as a QGIS layer.

    Parameters
    ----------
    result_path
        Exported file path.
    is_raster
        Whether the file should be opened as a raster layer.

    Raises
    ------
    ValueError
        If the exported file cannot be loaded.
    """
    result_path = result_path.resolve()
    layer_name = result_path.stem

    if is_raster:
        layer: QgsMapLayer = QgsRasterLayer(str(result_path), layer_name)
    else:
        layer = QgsVectorLayer(str(result_path), layer_name, "ogr")

    if layer.isValid():
        return

    error_detail = layer.error().message() if layer.error() else "unknown error"
    raise ValueError(f"Export produced unreadable file: {result_path} ({error_detail})")


def _load_layer_for_project(result_path: Path) -> QgsMapLayer:
    """Open an exported file as a layer for inclusion in a new project.

    Parameters
    ----------
    result_path
        Exported file path.

    Returns
    -------
    QgsMapLayer
        Valid raster or vector layer.

    Raises
    ------
    ValueError
        If the file cannot be loaded.
    """
    result_path = Path(result_path).resolve()
    if not result_path.is_file():
        raise ValueError(f"Output file not found: {result_path}")
    if result_path.stat().st_size == 0:
        raise ValueError(f"Output file is empty: {result_path}")

    layer_name = result_path.stem
    if result_path.suffix.lower() in {".tif", ".tiff"}:
        layer: QgsMapLayer = QgsRasterLayer(str(result_path), layer_name)
    else:
        layer = QgsVectorLayer(str(result_path), layer_name, "ogr")

    if layer.isValid():
        return layer

    error_detail = layer.error().message() if layer.error() else "unknown error"
    raise ValueError(
        f"Could not load layer for project: {result_path} ({error_detail})"
    )


def resolve_output_path(output_path: Path, format_label: str) -> Path:
    """Ensure ``output_path`` uses the extension for ``format_label``.

    Parameters
    ----------
    output_path
        User-provided output path or basename.
    format_label
        Key from ``OUTPUT_FORMATS`` (e.g. ``"GeoPackage"``).

    Returns
    -------
    Path
        Output path with the correct extension.

    Raises
    ------
    ValueError
        If ``format_label`` is not a supported format.
    """
    if format_label not in OUTPUT_FORMATS:
        raise ValueError(f"Unsupported output format: {format_label}")

    extension = OUTPUT_FORMATS[format_label]
    if output_path.suffix.lower() != extension:
        return output_path.with_suffix(extension)
    return output_path


def safe_basename(name: str) -> str:
    """Return a filesystem-safe basename derived from ``name``.

    Parameters
    ----------
    name
        Raw layer or file name.

    Returns
    -------
    str
        Sanitized basename.
    """
    cleaned = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return cleaned or "exported"


def build_output_filename(
    layer_name: str,
    is_raster: bool,
    format_label: str,
    naming_mode: str,
    naming_text: str = "",
) -> Path:
    """Build an output filename for a layer.

    Parameters
    ----------
    layer_name
        Source layer name.
    is_raster
        Whether the layer is a raster.
    format_label
        Vector format label from ``OUTPUT_FORMATS`` (ignored for rasters).
    naming_mode
        One of ``NAMING_MODE_IGNORE``, ``NAMING_MODE_PREFIX``, or
        ``NAMING_MODE_SUFFIX``.
    naming_text
        Text applied according to ``naming_mode``. Ignored when the mode is
        ``NAMING_MODE_IGNORE`` or when this value is empty.

    Returns
    -------
    Path
        Filename (no parent directory).
    """
    basename = safe_basename(layer_name)
    text = safe_basename(naming_text.strip()) if naming_text.strip() else ""

    if naming_mode == NAMING_MODE_PREFIX and text:
        basename = f"{text}{basename}"
    elif naming_mode == NAMING_MODE_SUFFIX and text:
        basename = f"{basename}{text}"
    elif naming_mode not in {
        NAMING_MODE_IGNORE,
        NAMING_MODE_PREFIX,
        NAMING_MODE_SUFFIX,
    }:
        raise ValueError(f"Unsupported naming mode: {naming_mode}")

    if is_raster:
        return Path(f"{basename}{RASTER_OUTPUT_EXTENSION}")
    return resolve_output_path(Path(basename), format_label)


def _write_vector_layer(
    layer: QgsVectorLayer,
    output_path: Path,
    target_crs: QgsCoordinateReferenceSystem,
    report: Callable[[int, str], None],
) -> Path:
    """Write a vector layer to ``output_path`` using the native reproject tool.

    When ``target_crs`` matches the layer CRS, this performs a format export
    without changing coordinates.

    Parameters
    ----------
    layer
        Vector layer to write.
    output_path
        Destination file path.
    target_crs
        CRS for the output layer.
    report
        Progress reporting callback.

    Returns
    -------
    Path
        Path to the written file.
    """
    from qgis import processing

    output_path = Path(output_path).resolve()
    write_path, replace_output = _resolve_export_path(
        output_path,
        _vector_source_path(layer),
    )

    layer_crs = layer.crs()
    if layer_crs.isValid() and layer_crs == target_crs:
        report(65, f"Exporting vector to {output_path.name}...")
    else:
        report(65, f"Reprojecting vector to {target_crs.authid()}...")

    result = processing.run(
        "native:reprojectlayer",
        {
            "INPUT": layer,
            "TARGET_CRS": target_crs,
            "OUTPUT": str(write_path),
        },
    )
    result_path = _finalize_export_path(
        Path(result["OUTPUT"]),
        output_path,
        replace_output,
    )
    _validate_exported_layer(result_path, is_raster=False)
    return result_path


def _raster_source_path(layer: QgsRasterLayer) -> Path | None:
    """Return the on-disk path for a GDAL-backed raster layer, if available.

    Parameters
    ----------
    layer
        Raster layer to inspect.

    Returns
    -------
    Path or None
        Source file path when the layer is file-backed.
    """
    if layer.providerType() != "gdal":
        return None

    source = layer.source().split("|", maxsplit=1)[0]
    source_path = Path(source)
    if source_path.is_file():
        return source_path
    return None


def _write_raster_layer(
    layer: QgsRasterLayer,
    output_path: Path,
    target_crs: QgsCoordinateReferenceSystem,
    report: Callable[[int, str], None],
) -> Path:
    """Write a raster layer to ``output_path``.

    File-backed rasters with unchanged CRS are copied directly when possible.
    Otherwise the GDAL warp reproject algorithm is used.

    Parameters
    ----------
    layer
        Raster layer to write.
    output_path
        Destination file path.
    target_crs
        CRS for the output layer.
    report
        Progress reporting callback.

    Returns
    -------
    Path
        Path to the written file.
    """
    from qgis import processing

    output_path = Path(output_path).resolve()
    source_path = _raster_source_path(layer)
    layer_crs = layer.crs()
    same_crs = (
        not layer_crs.isValid()
        or not target_crs.isValid()
        or layer_crs == target_crs
        or layer_crs.authid() == target_crs.authid()
    )

    if same_crs and source_path is not None:
        if source_path.resolve() == output_path:
            _validate_exported_layer(output_path, is_raster=True)
            return output_path

        report(65, f"Exporting raster to {output_path.name}...")
        write_path, replace_output = _resolve_export_path(output_path, source_path)
        shutil.copy2(source_path, write_path)
        result_path = _finalize_export_path(write_path, output_path, replace_output)
        _validate_exported_layer(result_path, is_raster=True)
        return result_path

    write_path, replace_output = _resolve_export_path(output_path, source_path)
    if same_crs:
        report(65, f"Exporting raster to {output_path.name}...")
    else:
        report(65, f"Reprojecting raster to {target_crs.authid()}...")

    result = processing.run(
        "gdal:warpreproject",
        {
            "INPUT": layer,
            "SOURCE_CRS": None,
            "TARGET_CRS": target_crs,
            "RESAMPLING": 0,
            "NODATA": None,
            "TARGET_RESOLUTION": None,
            "OPTIONS": "",
            "DATA_TYPE": 0,
            "TARGET_EXTENT": None,
            "CRS": None,
            "OUTPUT": str(write_path),
        },
    )
    result_path = _finalize_export_path(
        Path(result["OUTPUT"]),
        output_path,
        replace_output,
    )
    _validate_exported_layer(result_path, is_raster=True)
    return result_path


def export_layer(
    layer: QgsMapLayer,
    output_path: Path,
    format_label: str,
    target_crs: str,
    fix_geometries: bool = False,
    reproject: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Export a map layer: optional geometry repair, reproject, and write to disk.

    Parameters
    ----------
    layer
        Vector or raster layer to process.
    output_path
        Destination file path (extension may be adjusted for vectors).
    format_label
        Vector format label from ``OUTPUT_FORMATS`` (rasters use GeoTIFF).
    target_crs
        Target CRS auth id when ``reproject`` is ``True``.
    fix_geometries
        If ``True``, run a zero-distance buffer on vector layers only.
    reproject
        If ``True``, reproject to ``target_crs`` before writing.
    progress_callback
        Optional callback receiving ``(percent, message)`` updates.

    Returns
    -------
    Path
        Path to the written output file.

    Raises
    ------
    ValueError
        If processing fails.
    """
    from qgis import processing

    def report(percent: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(percent, message)

    if not layer.isValid():
        raise ValueError("The input layer is not valid.")

    is_raster = isinstance(layer, QgsRasterLayer)
    if is_raster:
        output_path = Path(output_path)
        if output_path.suffix.lower() != RASTER_OUTPUT_EXTENSION:
            output_path = output_path.with_suffix(RASTER_OUTPUT_EXTENSION)
    else:
        output_path = resolve_output_path(Path(output_path), format_label)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    write_crs = QgsCoordinateReferenceSystem(target_crs)
    if reproject:
        if not write_crs.isValid():
            raise ValueError(f"Invalid target CRS: {target_crs}")
    else:
        source_crs = layer.crs()
        if source_crs.isValid():
            write_crs = source_crs
        elif not write_crs.isValid():
            raise ValueError(
                "Layer has no CRS and reprojection is disabled. "
                "Enable reproject or assign a CRS to the layer."
            )

    processed_layer: QgsMapLayer = layer

    if not is_raster and fix_geometries:
        report(35, "Fixing geometries (buffer by 0)...")
        fixed_result = processing.run(
            "native:buffer",
            {
                "INPUT": layer,
                "DISTANCE": 0,
                "SEGMENTS": 5,
                "END_CAP_STYLE": 0,
                "JOIN_STYLE": 0,
                "MITER_LIMIT": 2,
                "DISSOLVE": False,
                "SEPARATE_DISJOINT": False,
                "OUTPUT": "memory:fixed",
            },
        )
        processed_layer = fixed_result["OUTPUT"]
        if processed_layer is None or not processed_layer.isValid():
            raise ValueError("Geometry repair failed.")
    elif not is_raster:
        report(35, "Skipping geometry repair.")
    else:
        report(35, "Raster layer: skipping geometry repair.")

    if is_raster:
        raster_layer = processed_layer  # type: ignore[assignment]
        result_path = _write_raster_layer(raster_layer, output_path, write_crs, report)
    else:
        vector_layer = processed_layer  # type: ignore[assignment]
        result_path = _write_vector_layer(vector_layer, output_path, write_crs, report)

    report(100, f"Export complete: {result_path.name}")
    return result_path


def _is_exportable_layer(layer: QgsMapLayer | None) -> bool:
    """Return whether ``layer`` is a valid vector or raster layer."""
    if layer is None:
        return False
    if not isinstance(layer, (QgsVectorLayer, QgsRasterLayer)):
        return False
    return layer.isValid()


def _collect_layers_in_tree_order(
    tree_node: QgsLayerTreeGroup,
    layers: list[QgsMapLayer],
) -> None:
    """Append exportable layers from ``tree_node`` in legend order."""
    for child in tree_node.children():
        if QgsLayerTree.isLayer(child):
            layer = child.layer()
            if _is_exportable_layer(layer):
                layers.append(layer)
        elif QgsLayerTree.isGroup(child):
            _collect_layers_in_tree_order(child, layers)


def _clone_layer_tree_for_export(
    source_node: QgsLayerTreeGroup,
    target_parent: QgsLayerTreeGroup,
    exported_by_source_id: dict[str, QgsMapLayer],
) -> None:
    """Mirror ``source_node`` structure on ``target_parent`` for exported layers."""
    for child in source_node.children():
        if QgsLayerTree.isGroup(child):
            new_group = target_parent.addGroup(child.name())
            new_group.setItemVisibilityChecked(child.itemVisibilityChecked())
            _clone_layer_tree_for_export(child, new_group, exported_by_source_id)
            if not new_group.children():
                target_parent.removeChildNode(new_group)
        elif QgsLayerTree.isLayer(child):
            source_id = child.layerId()
            destination_layer = exported_by_source_id.get(source_id)
            if destination_layer is None:
                continue
            layer_node = target_parent.addLayer(destination_layer)
            if layer_node is not None:
                layer_node.setItemVisibilityChecked(child.itemVisibilityChecked())


def iter_project_layers() -> list[QgsMapLayer]:
    """Return valid vector and raster layers from the active QGIS project.

    Layers are returned in the same order as the project layer tree
    (top to bottom in the Layers panel), including nested groups.

    Returns
    -------
    list[QgsMapLayer]
        Project layers suitable for export.
    """
    layers: list[QgsMapLayer] = []
    _collect_layers_in_tree_order(QgsProject.instance().layerTreeRoot(), layers)
    return layers


def export_project_layers(
    output_dir: Path,
    target_crs: str,
    format_label: str,
    fix_geometries: bool = False,
    reproject: bool = False,
    naming_mode: str = NAMING_MODE_IGNORE,
    naming_text: str = "",
    progress_callback: ProgressCallback | None = None,
) -> list[ExportedLayer]:
    """Export all vector and raster layers in the project to ``output_dir``.

    Parameters
    ----------
    output_dir
        Folder that will receive exported files.
    target_crs
        Target CRS auth id when ``reproject`` is ``True``.
    format_label
        Vector format label from ``OUTPUT_FORMATS``.
    fix_geometries
        If ``True``, repair vector geometries before export.
    reproject
        If ``True``, reproject layers to ``target_crs``.
    naming_mode
        Output naming mode (see ``build_output_filename``).
    naming_text
        Text applied according to ``naming_mode``.
    progress_callback
        Optional progress callback.

    Returns
    -------
    list[ExportedLayer]
        Exported files and their source layer ids.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    layers = iter_project_layers()
    if not layers:
        raise ValueError("No vector or raster layers found in the project.")

    results: list[ExportedLayer] = []
    total = len(layers)

    for index, layer in enumerate(layers):
        base_percent = int((index / total) * 100)
        next_percent = int(((index + 1) / total) * 100)

        def layer_progress(percent: int, message: str) -> None:
            if progress_callback is None:
                return
            scaled = base_percent + int((percent / 100) * (next_percent - base_percent))
            progress_callback(scaled, f"[{index + 1}/{total}] {message}")

        is_raster = isinstance(layer, QgsRasterLayer)
        output_name = build_output_filename(
            layer.name(),
            is_raster,
            format_label,
            naming_mode=naming_mode,
            naming_text=naming_text,
        )
        output_path = output_dir / output_name

        layer_progress(0, f"Processing {layer.name()}...")
        result_path = export_layer(
            layer=layer,
            output_path=output_path,
            format_label=format_label,
            target_crs=target_crs,
            fix_geometries=fix_geometries,
            reproject=reproject,
            progress_callback=layer_progress,
        )
        results.append(ExportedLayer(result_path, layer.id()))

    if progress_callback is not None:
        progress_callback(100, f"Finished exporting {len(results)} layer(s).")

    return results


def save_export_project(
    output_dir: Path,
    exported_layers: list[ExportedLayer],
    project_basename: str | None = None,
) -> Path:
    """Write a QGIS project that references exported layers in ``output_dir``.

    Symbology and layer-tree order from the active project are applied to the
    exported layers in the saved project file.

    Parameters
    ----------
    output_dir
        Folder containing the exported layer files.
    exported_layers
        Exported files and the source project layer for each one.
    project_basename
        Base name for the ``.qgz`` file (default from ``DEFAULT_PROJECT_BASENAME``).

    Returns
    -------
    Path
        Path to the written project file.

    Raises
    ------
    ValueError
        If no valid layers can be added or the project cannot be written.
    """
    from ..constants import DEFAULT_PROJECT_BASENAME

    output_dir = Path(output_dir).resolve()
    if project_basename is None:
        project_basename = DEFAULT_PROJECT_BASENAME

    project_path = output_dir / f"{project_basename}.qgz"
    project = QgsProject()
    project.setFileName(str(project_path))
    project.setPresetHomePath(str(output_dir))

    project_instance = QgsProject.instance()
    exported_by_source_id: dict[str, QgsMapLayer] = {}

    for exported in exported_layers:
        layer = _load_layer_for_project(exported.path)
        project.addMapLayer(layer, False)
        source_layer = project_instance.mapLayer(exported.source_layer_id)
        if source_layer is not None:
            copy_layer_symbology(source_layer, layer)
        exported_by_source_id[exported.source_layer_id] = layer

    if not exported_by_source_id:
        raise ValueError("No valid layers available to save in the project file.")

    _clone_layer_tree_for_export(
        project_instance.layerTreeRoot(),
        project.layerTreeRoot(),
        exported_by_source_id,
    )

    if not project.mapLayers():
        raise ValueError("No valid layers available to save in the project file.")

    if not project.write():
        raise ValueError(f"Could not write project file: {project_path}")

    return project_path
