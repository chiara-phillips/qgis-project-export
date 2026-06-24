# Project Export

QGIS plugin that exports all vector and raster layers from the current project
to a folder, with optional geometry repair, reprojection, file renaming, and a
packaged `.qgz` project file.

Compatible with QGIS 3.28+ and QGIS 4.x.

## Features

- Export every project layer to a chosen output folder
- Optional fix geometries (buffer by 0), reproject, and rename files
- Optional `.qgz` project referencing the exported layers
- Defaults for CRS, format, and output folder are remembered between sessions

## Project structure

```
project_export/
├── __init__.py              # Plugin entry point
├── project_export.py        # Main plugin class
├── metadata.txt             # QGIS plugin metadata
├── constants.py             # Shared constants
├── core/
│   └── export.py            # Export processing logic
├── dialogs/
│   └── export_dock.py       # Export dock panel
└── icons/
```

## Install

```bash
git clone https://github.com/chiara-phillips/qgis-project-export
cd qgis-project-export
python install.py
```

Then enable **Project Export** in the QGIS Plugin Manager.

To remove:

```bash
python install.py --remove
```

## Development

Run import smoke tests (requires PyQt6):

```bash
pip install PyQt6 pytest
pytest tests -v
```

Package for upload to plugins.qgis.org:

```bash
python package_plugin.py
```

## License

MIT
