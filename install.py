#!/usr/bin/env python3
"""
Cross-platform installation script for Project Export.

Usage:
    python install.py          # Install the plugin
    python install.py --remove # Remove the plugin
"""

import argparse
import configparser
import os
import shutil
import sys
from pathlib import Path


def get_qgis_base_dir() -> Path:
    """Return the QGIS application support directory for this platform.

    Returns
    -------
    Path
        Base directory containing ``QGIS3``, ``QGIS4``, etc.

    Raises
    ------
    RuntimeError
        If the platform is unsupported.
    """
    home = Path.home()

    if sys.platform in ("linux", "linux2"):
        return home / ".local/share/QGIS"
    if sys.platform == "darwin":
        return home / "Library/Application Support/QGIS"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "QGIS"
        return home / "AppData/Roaming/QGIS"

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _legacy_default_plugin_dir() -> Path:
    """Return the historical default-profile plugin directory."""
    base = get_qgis_base_dir()
    return base / "QGIS3/profiles/default/python/plugins"


def discover_qgis_plugin_dirs(default_only: bool = False) -> list[Path]:
    """Discover QGIS plugin directories on this machine.

    Parameters
    ----------
    default_only
        If ``True``, only return the legacy ``default`` profile path.

    Returns
    -------
    list[Path]
        Plugin directories to install into.
    """
    if default_only:
        return [_legacy_default_plugin_dir()]

    base = get_qgis_base_dir()
    if not base.is_dir():
        return [_legacy_default_plugin_dir()]

    plugin_dirs = sorted(
        {path for path in base.glob("QGIS*/profiles/*/python/plugins") if path.is_dir()}
    )
    if plugin_dirs:
        return plugin_dirs

    return [_legacy_default_plugin_dir()]


def read_default_profile_name(qgis_version_dir: Path) -> str | None:
    """Read the default profile name from ``profiles.ini``.

    Parameters
    ----------
    qgis_version_dir
        Path such as ``.../QGIS/QGIS4``.

    Returns
    -------
    str or None
        Default profile name when present.
    """
    profiles_ini = qgis_version_dir / "profiles/profiles.ini"
    if not profiles_ini.is_file():
        return None

    parser = configparser.ConfigParser()
    parser.read(profiles_ini)
    if parser.has_option("core", "defaultProfile"):
        return parser.get("core", "defaultProfile")
    return None


def install_plugin(
    source_dir: Path, plugin_dir: Path, plugin_name: str = "project_export"
) -> bool:
    """Install the plugin to the QGIS plugins directory.

    Parameters
    ----------
    source_dir
        Path to the plugin source directory.
    plugin_dir
        Path to the QGIS plugins directory.
    plugin_name
        Name of the plugin folder in QGIS plugins directory.

    Returns
    -------
    bool
        ``True`` if installation was successful.
    """
    target_dir = plugin_dir / plugin_name

    plugin_dir.mkdir(parents=True, exist_ok=True)

    if target_dir.exists():
        print(f"Removing existing installation: {target_dir}")
        shutil.rmtree(target_dir)

    print(f"Installing plugin to: {target_dir}")
    shutil.copytree(source_dir, target_dir)

    return True


def remove_plugin(plugin_dir: Path, plugin_name: str = "project_export") -> bool:
    """Remove the plugin from the QGIS plugins directory.

    Parameters
    ----------
    plugin_dir
        Path to the QGIS plugins directory.
    plugin_name
        Name of the plugin folder in QGIS plugins directory.

    Returns
    -------
    bool
        ``True`` if removal was successful.
    """
    target_dir = plugin_dir / plugin_name

    if target_dir.exists():
        print(f"Removing plugin: {target_dir}")
        shutil.rmtree(target_dir)
        return True

    print(f"Plugin not found: {target_dir}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Install or remove Project Export")
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove the plugin instead of installing",
    )
    parser.add_argument(
        "--plugin-dir",
        type=str,
        default=None,
        help="Install to a single custom QGIS plugin directory",
    )
    parser.add_argument(
        "--default-only",
        action="store_true",
        help="Install only to the legacy default profile directory",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="project_export",
        help="Plugin folder name in QGIS plugins directory (default: project_export)",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    source_dir = script_dir / "project_export"

    if not source_dir.exists():
        print(f"Error: Plugin source directory not found: {source_dir}")
        sys.exit(1)

    if args.plugin_dir:
        plugin_dirs = [Path(args.plugin_dir)]
    else:
        plugin_dirs = discover_qgis_plugin_dirs(default_only=args.default_only)

    print(f"Platform: {sys.platform}")
    print(f"Plugin name: {args.name}")
    print(f"Target directories ({len(plugin_dirs)}):")
    for plugin_dir in plugin_dirs:
        print(f"  - {plugin_dir}")
    print()

    base = get_qgis_base_dir()
    for qgis_dir in sorted(base.glob("QGIS*")) if base.is_dir() else []:
        profile = read_default_profile_name(qgis_dir)
        if profile is not None:
            print(f"Active profile for {qgis_dir.name}: {profile}")
    print()

    if args.remove:
        results = [remove_plugin(plugin_dir, args.name) for plugin_dir in plugin_dirs]
        success = any(results)
        if success:
            print("Plugin removed successfully.")
    else:
        results = [
            install_plugin(source_dir, plugin_dir, args.name)
            for plugin_dir in plugin_dirs
        ]
        success = all(results)

        if success:
            print()
            print("=" * 60)
            print("Installation complete!")
            print("=" * 60)
            print()
            print("To use the plugin:")
            print("  1. Restart QGIS")
            print("  2. Go to Plugins -> Manage and Install Plugins...")
            print("  3. Open the Installed tab and search for 'Project Export'")
            print("  4. Enable the plugin")
            print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
