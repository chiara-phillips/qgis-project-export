"""
Project Export - Main Plugin Class

Manages QGIS menu integration, toolbar buttons, and dockable panels.
"""

import os
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from .constants import PLUGIN_NAME


class ProjectExport:
    """Project Export plugin implementation for QGIS."""

    MENU_NAME = f"&{PLUGIN_NAME}"

    def __init__(self, iface):
        """Constructor.

        Args:
            iface: An interface instance that provides the hook to QGIS.
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.toolbar_actions = []
        self._export_dock = None

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        checkable=False,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        Args:
            icon_path: Path to the icon for this action.
            text: Text that appears in the menu for this action.
            callback: Function to be called when the action is triggered.
            enabled_flag: A flag indicating if the action should be enabled.
            add_to_menu: Flag indicating whether action should be added to menu.
            add_to_toolbar: Flag indicating whether action should be added to toolbar.
            status_tip: Optional text to show in status bar when mouse hovers over action.
            checkable: Whether the action is checkable (toggle).
            parent: Parent widget for the new action.

        Returns
        -------
        QAction
            The action that was created.
        """
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)
        action.setCheckable(checkable)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if add_to_toolbar:
            self._register_toolbar_icon(action)
            self.toolbar_actions.append(action)

        if add_to_menu:
            self.iface.addPluginToMenu(self.MENU_NAME, action)

        self.actions.append(action)

        return action

    def _register_toolbar_icon(self, action) -> None:
        """Add an action to the QGIS plugin toolbar."""
        if hasattr(self.iface, "addToolBarIcon"):
            self.iface.addToolBarIcon(action)
        else:
            self.iface.addPluginToToolbar(action)

    def _unregister_toolbar_icon(self, action) -> None:
        """Remove an action from the QGIS plugin toolbar."""
        if hasattr(self.iface, "removeToolBarIcon"):
            self.iface.removeToolBarIcon(action)
        else:
            self.iface.removePluginToolbarIcon(action)

    def _add_menu_separator(self) -> None:
        """Add a separator to the plugin menu."""
        separator = QAction(self.iface.mainWindow())
        separator.setSeparator(True)
        self.iface.addPluginToMenu(self.MENU_NAME, separator)
        self.actions.append(separator)

    @staticmethod
    def _destroy_dock_widget(iface, dock) -> None:
        """Remove a dock widget synchronously so reloaders do not see orphans.

        Parameters
        ----------
        iface
            QGIS interface instance.
        dock
            Dock widget to destroy.
        """
        iface.removeDockWidget(dock)
        dock.setParent(None)
        dock.hide()
        try:
            from qgis.PyQt import sip

            sip.delete(dock)
        except Exception:
            dock.deleteLater()

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_base = os.path.join(self.plugin_dir, "icons")

        main_icon = os.path.join(icon_base, "icon.png")
        if not os.path.exists(main_icon):
            main_icon = ":/images/themes/default/mActionAddRasterLayer.svg"

        about_icon = os.path.join(icon_base, "about.svg")
        if not os.path.exists(about_icon):
            about_icon = ":/images/themes/default/mActionHelpContents.svg"

        self.export_action = self.add_action(
            main_icon,
            PLUGIN_NAME,
            self.toggle_export_dock,
            status_tip=f"Toggle {PLUGIN_NAME} panel",
            checkable=True,
            parent=self.iface.mainWindow(),
        )

        self._add_menu_separator()

        self.add_action(
            about_icon,
            f"About {PLUGIN_NAME}",
            self.show_about,
            add_to_toolbar=False,
            status_tip=f"About {PLUGIN_NAME}",
            parent=self.iface.mainWindow(),
        )

    def unload(self):
        """Remove the plugin menu item and icon from QGIS GUI."""
        if self._export_dock:
            try:
                self._export_dock.visibilityChanged.disconnect(
                    self._on_export_visibility_changed
                )
            except (RuntimeError, TypeError):
                pass
            self._destroy_dock_widget(self.iface, self._export_dock)
            self._export_dock = None

        for action in self.actions:
            self.iface.removePluginMenu(self.MENU_NAME, action)

        for action in self.toolbar_actions:
            self._unregister_toolbar_icon(action)

        self.actions.clear()
        self.toolbar_actions.clear()

    def toggle_export_dock(self):
        """Toggle the Project Export dock widget visibility."""
        if self._export_dock is None:
            try:
                from .dialogs.export_dock import ExportDockWidget

                self._export_dock = ExportDockWidget(
                    self.iface, self.iface.mainWindow()
                )
                self._export_dock.setObjectName("ProjectExportDock")
                self._export_dock.visibilityChanged.connect(
                    self._on_export_visibility_changed
                )
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self._export_dock
                )
                self._export_dock.show()
                self._export_dock.raise_()
                return

            except Exception as e:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Error",
                    f"Failed to create {PLUGIN_NAME} panel:\n{str(e)}",
                )
                self.export_action.setChecked(False)
                return

        if self._export_dock.isVisible():
            self._export_dock.hide()
        else:
            self._export_dock.show()
            self._export_dock.raise_()

    def _on_export_visibility_changed(self, visible):
        """Handle Project Export dock visibility change."""
        self.export_action.setChecked(visible)

    def show_about(self):
        """Display the about dialog."""
        version = "Unknown"
        try:
            metadata_path = os.path.join(self.plugin_dir, "metadata.txt")
            with open(metadata_path, "r", encoding="utf-8") as f:
                content = f.read()
                version_match = re.search(r"^version=(.+)$", content, re.MULTILINE)
                if version_match:
                    version = version_match.group(1).strip()
        except Exception as e:
            QMessageBox.warning(
                self.iface.mainWindow(),
                PLUGIN_NAME,
                f"Could not read version from metadata.txt:\n{str(e)}",
            )

        about_text = f"""
<h2>{PLUGIN_NAME} for QGIS</h2>
<p>Version: {version}</p>
<p>Author: Chiara Phillips</p>

<h3>Features:</h3>
<ul>
<li><b>Project layer export:</b> Save all vector and raster layers from the
current project to a folder</li>
<li><b>Optional processing:</b> Fix geometries, reproject, and rename files</li>
<li><b>Project package:</b> Optionally write a <code>.qgz</code> that references
the exported layers</li>
</ul>

<p>Licensed under MIT License</p>
"""
        QMessageBox.about(
            self.iface.mainWindow(),
            f"About {PLUGIN_NAME}",
            about_text,
        )
