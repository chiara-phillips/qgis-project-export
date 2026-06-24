"""
Project Export dock widget.

Export all project layers to a folder with optional geometry repair,
reprojection, renaming, and a packaged QGIS project file.
"""

from __future__ import annotations

from pathlib import Path

from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer
from qgis.PyQt.QtCore import Qt, QSettings, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.gui import QgsProjectionSelectionWidget

from ..constants import (
    DEFAULT_NAME_SUFFIX,
    DEFAULT_OUTPUT_CRS,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_PROJECT_BASENAME,
    NAMING_MODE_IGNORE,
    NAMING_MODE_LABELS,
    OUTPUT_FORMATS,
    PLUGIN_NAME,
    SETTINGS_PREFIX,
)
from ..core.export import (
    ExportedLayer,
    build_output_filename,
    export_project_layers,
    iter_project_layers,
    safe_basename,
    save_export_project,
)


class ExportWorker(QThread):
    """Background worker for project layer export."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        output_dir: Path,
        target_crs: str,
        format_label: str,
        fix_geometries: bool,
        reproject: bool,
        naming_mode: str,
        naming_text: str,
    ) -> None:
        super().__init__()
        self.output_dir = output_dir
        self.target_crs = target_crs
        self.format_label = format_label
        self.fix_geometries = fix_geometries
        self.reproject = reproject
        self.naming_mode = naming_mode
        self.naming_text = naming_text

    def run(self) -> None:
        """Run export in a background thread."""
        try:
            results = export_project_layers(
                output_dir=self.output_dir,
                target_crs=self.target_crs,
                format_label=self.format_label,
                fix_geometries=self.fix_geometries,
                reproject=self.reproject,
                naming_mode=self.naming_mode,
                naming_text=self.naming_text,
                progress_callback=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished.emit(
                [
                    {
                        "path": str(exported.path),
                        "source_layer_id": exported.source_layer_id,
                    }
                    for exported in results
                ]
            )
        except Exception as exc:
            self.error.emit(str(exc))


class ExportDockWidget(QDockWidget):
    """Dock panel for exporting project layers."""

    def __init__(self, iface, parent=None) -> None:
        """Initialize the dock widget.

        Parameters
        ----------
        iface
            QGIS interface instance.
        parent
            Parent widget.
        """
        super().__init__(PLUGIN_NAME, parent)
        self.iface = iface
        self.settings = QSettings()
        self._worker: ExportWorker | None = None
        self._output_package_dir: Path | None = None

        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._setup_ui()
        self._load_defaults()
        self._on_reproject_toggled()
        self._on_naming_mode_changed()
        self._on_save_project_toggled()

    def _setup_ui(self) -> None:
        """Set up the dock widget UI."""
        main_widget = QWidget()
        self.setWidget(main_widget)

        layout = QVBoxLayout(main_widget)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()
        form.setSpacing(6)

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(OUTPUT_FORMATS.keys()))
        self.format_combo.setToolTip(
            "Format for vector layers. Rasters are always saved as GeoTIFF."
        )
        form.addRow("Vector format", self.format_combo)

        naming_layout = QHBoxLayout()
        self.naming_mode_combo = QComboBox()
        for mode, label in NAMING_MODE_LABELS.items():
            self.naming_mode_combo.addItem(label, mode)
        ignore_index = self.naming_mode_combo.findData(NAMING_MODE_IGNORE)
        if ignore_index >= 0:
            self.naming_mode_combo.setCurrentIndex(ignore_index)
        self.naming_mode_combo.currentIndexChanged.connect(self._on_naming_mode_changed)
        naming_layout.addWidget(self.naming_mode_combo)

        self.naming_text_input = QLineEdit()
        self.naming_text_input.setPlaceholderText(f"e.g. {DEFAULT_NAME_SUFFIX}")
        naming_layout.addWidget(self.naming_text_input)
        form.addRow("File name", naming_layout)

        options_layout = QHBoxLayout()
        self.fix_geometries_check = QCheckBox("Fix geometries")
        self.fix_geometries_check.setToolTip(
            "Buffer by 0 on vector layers. Rasters are unchanged."
        )
        options_layout.addWidget(self.fix_geometries_check)

        self.reproject_check = QCheckBox("Reproject")
        self.reproject_check.toggled.connect(self._on_reproject_toggled)
        options_layout.addWidget(self.reproject_check)
        options_layout.addStretch()
        form.addRow("", options_layout)

        self.crs_widget = QgsProjectionSelectionWidget()
        form.addRow("CRS", self.crs_widget)
        self._crs_form_label = form.labelForField(self.crs_widget)

        self.save_project_check = QCheckBox("Save .qgz project in output folder")
        self.save_project_check.setChecked(True)
        self.save_project_check.toggled.connect(self._on_save_project_toggled)
        form.addRow("", self.save_project_check)

        self.project_name_input = QLineEdit()
        self.project_name_input.setPlaceholderText(DEFAULT_PROJECT_BASENAME)
        form.addRow("Project file name", self.project_name_input)
        self._project_name_form_label = form.labelForField(self.project_name_input)

        output_dir_layout = QHBoxLayout()
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Choose a folder...")
        output_dir_layout.addWidget(self.output_dir_input)
        self.output_dir_btn = QPushButton("Browse")
        self.output_dir_btn.clicked.connect(self._browse_output_dir)
        output_dir_layout.addWidget(self.output_dir_btn)
        form.addRow("Output folder", output_dir_layout)

        layout.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(72)
        self.log_text.setPlaceholderText("Log...")
        layout.addWidget(self.log_text)

        self.export_btn = QPushButton("Export project layers")
        self.export_btn.clicked.connect(self._run_export)
        layout.addWidget(self.export_btn)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.status_label)

        layout.addStretch()

    def _load_defaults(self) -> None:
        """Load default CRS, format, and output directory from settings."""
        crs_authid = self.settings.value(
            f"{SETTINGS_PREFIX}output_crs",
            DEFAULT_OUTPUT_CRS,
            type=str,
        )
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem(crs_authid))

        settings_key = f"{SETTINGS_PREFIX}output_format"
        if self.settings.contains(settings_key):
            format_index = self.settings.value(settings_key, type=int)
        else:
            format_index = self.format_combo.findText(DEFAULT_OUTPUT_FORMAT)
        if 0 <= format_index < self.format_combo.count():
            self.format_combo.setCurrentIndex(format_index)

        self.output_dir_input.setText(
            self.settings.value(f"{SETTINGS_PREFIX}output_dir", "", type=str)
        )

    def _save_defaults(self) -> None:
        """Persist export defaults to QSettings."""
        self.settings.setValue(
            f"{SETTINGS_PREFIX}output_crs",
            self.crs_widget.crs().authid(),
        )
        self.settings.setValue(
            f"{SETTINGS_PREFIX}output_format",
            self.format_combo.currentIndex(),
        )
        self.settings.setValue(
            f"{SETTINGS_PREFIX}output_dir",
            self.output_dir_input.text().strip(),
        )
        self.settings.sync()

    def _naming_mode(self) -> str:
        """Return the selected file naming mode."""
        mode = self.naming_mode_combo.currentData()
        if mode:
            return str(mode)
        return NAMING_MODE_IGNORE

    def _on_naming_mode_changed(self) -> None:
        """Show the text field only for prefix and suffix modes."""
        use_text = self._naming_mode() != NAMING_MODE_IGNORE
        self.naming_text_input.setVisible(use_text)
        self.naming_text_input.setEnabled(use_text)

    def _on_save_project_toggled(self) -> None:
        """Show project file options only when saving a project file."""
        save_project = self.save_project_check.isChecked()
        self.project_name_input.setVisible(save_project)
        if self._project_name_form_label is not None:
            self._project_name_form_label.setVisible(save_project)

    def _on_reproject_toggled(self) -> None:
        """Show the CRS picker only when reprojection is requested."""
        show_crs = self.reproject_check.isChecked()
        self.crs_widget.setVisible(show_crs)
        if self._crs_form_label is not None:
            self._crs_form_label.setVisible(show_crs)

    def _browse_output_dir(self) -> None:
        """Open a directory dialog for the output folder."""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            self.output_dir_input.text() or "",
        )
        if dir_path:
            self.output_dir_input.setText(dir_path)

    def _resolve_output_dir(self) -> Path | None:
        """Return the output directory for export."""
        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            QMessageBox.warning(
                self,
                PLUGIN_NAME,
                "Please choose an output folder.",
            )
            return None
        return Path(output_dir)

    def _confirm_overwrite(self, paths: list[Path]) -> bool:
        """Ask the user before overwriting existing files."""
        existing = [path for path in paths if path.exists()]
        if not existing:
            return True

        if len(existing) == 1:
            message = f"{existing[0]} already exists.\n\nOverwrite?"
        else:
            preview = "\n".join(str(path) for path in existing[:5])
            if len(existing) > 5:
                preview = f"{preview}\n..."
            message = (
                f"{len(existing)} file(s) already exist in the output folder.\n\n"
                f"{preview}\n\nOverwrite?"
            )

        reply = QMessageBox.question(
            self,
            "Overwrite Files?",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _run_export(self) -> None:
        """Validate inputs and start export."""
        reproject = self.reproject_check.isChecked()
        target_crs = self.crs_widget.crs().authid()

        if reproject and not target_crs:
            QMessageBox.warning(
                self,
                PLUGIN_NAME,
                "Please select a valid CRS.",
            )
            return

        if not reproject:
            target_crs = target_crs or DEFAULT_OUTPUT_CRS

        format_label = self.format_combo.currentText()

        try:
            layers = iter_project_layers()
            if not layers:
                raise ValueError("No vector or raster layers found in the project.")
            output_dir = self._resolve_output_dir()
            if output_dir is None:
                return
            if not self._confirm_overwrite(
                [
                    output_dir
                    / build_output_filename(
                        layer.name(),
                        isinstance(layer, QgsRasterLayer),
                        format_label,
                        naming_mode=self._naming_mode(),
                        naming_text=self.naming_text_input.text(),
                    )
                    for layer in layers
                ]
            ):
                return
        except ValueError as exc:
            QMessageBox.warning(self, PLUGIN_NAME, str(exc))
            return

        self._output_package_dir = output_dir
        self.log_text.clear()
        self._save_defaults()

        self.export_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Exporting...")
        self.status_label.setStyleSheet("color: blue; font-size: 10px;")

        self._worker = ExportWorker(
            output_dir=output_dir,
            target_crs=target_crs,
            format_label=format_label,
            fix_geometries=self.fix_geometries_check.isChecked(),
            reproject=reproject,
            naming_mode=self._naming_mode(),
            naming_text=self.naming_text_input.text(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, percent: int, message: str) -> None:
        """Update progress UI."""
        self.progress_bar.setValue(percent)
        self._append_log(message)

    def _on_finished(self, results: list) -> None:
        """Handle successful export."""
        exported_layers = [
            ExportedLayer(
                path=Path(item["path"]),
                source_layer_id=str(item["source_layer_id"]),
            )
            for item in results
        ]

        self.progress_bar.setValue(100)
        self.progress_bar.setVisible(False)
        self.export_btn.setEnabled(True)
        self.status_label.setText(f"Exported {len(exported_layers)} file(s)")
        self.status_label.setStyleSheet("color: green; font-size: 10px;")

        project_path: Path | None = None
        if (
            self.save_project_check.isChecked()
            and self._output_package_dir is not None
            and exported_layers
        ):
            project_basename = self.project_name_input.text().strip()
            if not project_basename:
                project_basename = DEFAULT_PROJECT_BASENAME
            else:
                project_basename = safe_basename(project_basename)
            try:
                project_path = save_export_project(
                    output_dir=self._output_package_dir.resolve(),
                    exported_layers=exported_layers,
                    project_basename=project_basename,
                )
                self._append_log(f"Project saved: {project_path.name}")
            except ValueError as exc:
                self._append_log(f"Project not saved: {exc}")

        if project_path is not None:
            message = f"Exported {len(exported_layers)} file(s) and {project_path.name}"
        else:
            message = f"Exported {len(exported_layers)} file(s) to folder."

        self.iface.messageBar().pushSuccess(PLUGIN_NAME, message)
        self._worker = None

    def _on_error(self, message: str) -> None:
        """Handle export failure."""
        self.progress_bar.setVisible(False)
        self.export_btn.setEnabled(True)
        self.status_label.setText("Export failed")
        self.status_label.setStyleSheet("color: red; font-size: 10px;")
        self._append_log(message)
        QMessageBox.critical(
            self,
            PLUGIN_NAME,
            f"Export failed:\n\n{message}",
        )
        self._worker = None

    def _append_log(self, message: str) -> None:
        """Append a line to the log text area."""
        self.log_text.append(message)
