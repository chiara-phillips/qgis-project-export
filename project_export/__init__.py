"""
Project Export QGIS Plugin

Export project layers to a folder with optional geometry repair,
reprojection, renaming, and a packaged QGIS project file.
"""

from .project_export import ProjectExport


def classFactory(iface):
    """Load the plugin class.

    Parameters
    ----------
    iface
        A QGIS interface instance.

    Returns
    -------
    ProjectExport
        The plugin instance.
    """
    return ProjectExport(iface)
