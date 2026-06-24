#!/bin/bash
# Installation script for Project Export
#
# Usage:
#   ./install.sh              # Install the plugin
#   ./install.sh --remove     # Remove the plugin
#   ./install.sh --name foo   # Install with custom name

set -e

PLUGIN_NAME="project_export"
REMOVE=false
DEFAULT_ONLY=false
CUSTOM_PLUGIN_DIR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --remove|-r)
            REMOVE=true
            shift
            ;;
        --name|-n)
            PLUGIN_NAME="$2"
            shift 2
            ;;
        --default-only)
            DEFAULT_ONLY=true
            shift
            ;;
        --plugin-dir)
            CUSTOM_PLUGIN_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --remove, -r         Remove the plugin instead of installing"
            echo "  --name, -n NAME      Plugin folder name (default: project_export)"
            echo "  --default-only       Install only to the legacy default profile"
            echo "  --plugin-dir PATH    Install to a single custom plugin directory"
            echo "  --help, -h           Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

discover_plugin_dirs() {
    if [[ -n "$CUSTOM_PLUGIN_DIR" ]]; then
        echo "$CUSTOM_PLUGIN_DIR"
        return
    fi

    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        BASE_DIR="$HOME/.local/share/QGIS"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        BASE_DIR="$HOME/Library/Application Support/QGIS"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        BASE_DIR="$APPDATA/QGIS"
    else
        echo "Unknown OS type: $OSTYPE" >&2
        exit 1
    fi

    if [[ "$DEFAULT_ONLY" == true ]]; then
        echo "${BASE_DIR}/QGIS3/profiles/default/python/plugins"
        return
    fi

    if [[ -d "$BASE_DIR" ]]; then
        find "$BASE_DIR" -path "*/profiles/*/python/plugins" -type d 2>/dev/null | sort -u
    fi

    if [[ ! -d "$BASE_DIR" ]]; then
        echo "${BASE_DIR}/QGIS3/profiles/default/python/plugins"
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/project_export"

echo "Platform: $OSTYPE"
echo "Plugin name: $PLUGIN_NAME"
echo ""

if [[ ! -d "$SOURCE_DIR" && "$REMOVE" != true ]]; then
    echo "Error: Source directory not found: $SOURCE_DIR"
    exit 1
fi

mapfile -t PLUGIN_DIRS < <(discover_plugin_dirs)

if [[ ${#PLUGIN_DIRS[@]} -eq 0 ]]; then
    echo "Error: No QGIS plugin directories found."
    exit 1
fi

echo "Target directories (${#PLUGIN_DIRS[@]}):"
for dir in "${PLUGIN_DIRS[@]}"; do
    echo "  - $dir"
done
echo ""

if [[ "$REMOVE" == true ]]; then
    removed=false
    for PLUGIN_DIR in "${PLUGIN_DIRS[@]}"; do
        TARGET_DIR="${PLUGIN_DIR}/${PLUGIN_NAME}"
        if [[ -d "$TARGET_DIR" ]]; then
            echo "Removing plugin: $TARGET_DIR"
            rm -rf "$TARGET_DIR"
            removed=true
        fi
    done

    if [[ "$removed" == true ]]; then
        echo "Plugin removed successfully."
    else
        echo "Plugin not found. Nothing to remove."
    fi
else
    for PLUGIN_DIR in "${PLUGIN_DIRS[@]}"; do
        mkdir -p "$PLUGIN_DIR"
        TARGET_DIR="${PLUGIN_DIR}/${PLUGIN_NAME}"

        if [[ -d "$TARGET_DIR" ]]; then
            echo "Removing existing installation: $TARGET_DIR"
            rm -rf "$TARGET_DIR"
        fi

        echo "Installing plugin to: $TARGET_DIR"
        cp -r "$SOURCE_DIR" "$TARGET_DIR"
    done

    echo ""
    echo "============================================================"
    echo "Installation complete!"
    echo "============================================================"
    echo ""
    echo "To use the plugin:"
    echo "  1. Restart QGIS"
    echo "  2. Go to Plugins -> Manage and Install Plugins..."
    echo "  3. Open the Installed tab and search for 'Project Export'"
    echo "  4. Enable the plugin"
    echo ""
fi
