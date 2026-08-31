#!/bin/sh
set -eu

PROJECT_NAME="MedusaHC-Calibrate"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
KLIPPER_DIR=${KLIPPER_DIR:-"$HOME/klipper"}
CONFIG_DIR=${PRINTER_CONFIG_DIR:-"$HOME/printer_data/config"}
PRINTER_CFG=${PRINTER_CFG:-"$CONFIG_DIR/printer.cfg"}

if [ -f "$CONFIG_DIR/MedusaHC/MHC_variables.cfg" ]; then
    CORE_CONFIG_DIR="$CONFIG_DIR/MedusaHC"
    INCLUDE_FILE="$CORE_CONFIG_DIR/MHC_config.cfg"
    INCLUDE_LINE="[include MedusaHC/medusahc_calibrate.cfg]"
else
    CORE_CONFIG_DIR="$CONFIG_DIR"
    INCLUDE_FILE="$PRINTER_CFG"
    INCLUDE_LINE="[include medusahc_calibrate.cfg]"
fi

SOURCE_MODULE="$SCRIPT_DIR/klippy/extras/medusahc_calibrate.py"
SOURCE_CONFIG="$SCRIPT_DIR/config/medusahc_calibrate.cfg"
TARGET_MODULE="$KLIPPER_DIR/klippy/extras/medusahc_calibrate.py"
TARGET_CONFIG="$CORE_CONFIG_DIR/medusahc_calibrate.cfg"

say() {
    printf '%s\n' "[$PROJECT_NAME] $*"
}

confirm() {
    printf '%s [y/N]: ' "$1"
    read -r answer
    case "$answer" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

require_layout() {
    if [ ! -d "$KLIPPER_DIR/klippy/extras" ]; then
        say "Klipper extras directory not found: $KLIPPER_DIR/klippy/extras"
        say "Set KLIPPER_DIR to the correct Klipper checkout and try again."
        exit 1
    fi
    if [ ! -d "$CONFIG_DIR" ] || [ ! -f "$PRINTER_CFG" ]; then
        say "Printer configuration not found under: $CONFIG_DIR"
        say "Set PRINTER_CONFIG_DIR or PRINTER_CFG and try again."
        exit 1
    fi
}

require_core() {
    missing=""
    [ -f "$KLIPPER_DIR/klippy/extras/pin_watch.py" ] || missing="$missing pin_watch.py"
    [ -f "$CORE_CONFIG_DIR/MHC_variables.cfg" ] || missing="$missing MHC_variables.cfg"
    if [ ! -f "$KLIPPER_DIR/klippy/extras/medusahc.py" ] \
        && [ ! -f "$CORE_CONFIG_DIR/MHC_macros.cfg" ]; then
        missing="$missing medusahc.py-or-MHC_macros.cfg"
    fi
    if [ -n "$missing" ]; then
        say "MedusaHC Core dependency is incomplete. Missing:$missing"
        say "Install and configure MedusaHC Core before MedusaHC-Calibrate."
        exit 1
    fi
}

add_include() {
    if [ ! -f "$INCLUDE_FILE" ]; then
        say "Include target not found: $INCLUDE_FILE"
        say "Add $INCLUDE_LINE manually after preparing the Core configuration."
        return
    fi
    if grep -Fqx "$INCLUDE_LINE" "$INCLUDE_FILE"; then
        say "$INCLUDE_FILE already includes medusahc_calibrate.cfg"
        return
    fi
    if ! confirm "Add $INCLUDE_LINE to $INCLUDE_FILE?"; then
        say "Include was not added. Add it manually before restarting Klipper."
        return
    fi
    tmp=$(mktemp "$CORE_CONFIG_DIR/.medusahc-calibrate-include.XXXXXX")
    {
        cat "$INCLUDE_FILE"
        printf '\n%s\n' "$INCLUDE_LINE"
    } > "$tmp"
    chmod --reference="$INCLUDE_FILE" "$tmp" 2>/dev/null || true
    mv "$tmp" "$INCLUDE_FILE"
    say "Added include to $INCLUDE_FILE"
}

remove_include() {
    if [ ! -f "$INCLUDE_FILE" ] || ! grep -Fqx "$INCLUDE_LINE" "$INCLUDE_FILE"; then
        return
    fi
    if ! confirm "Remove $INCLUDE_LINE from $INCLUDE_FILE?"; then
        say "Include was kept. Do not restart Klipper after deleting the config file."
        return
    fi
    tmp=$(mktemp "$CORE_CONFIG_DIR/.medusahc-calibrate-include.XXXXXX")
    awk -v line="$INCLUDE_LINE" '$0 != line { print }' "$INCLUDE_FILE" > "$tmp"
    chmod --reference="$INCLUDE_FILE" "$tmp" 2>/dev/null || true
    mv "$tmp" "$INCLUDE_FILE"
    say "Removed include from $INCLUDE_FILE"
}

install_module() {
    require_layout
    require_core
    [ -f "$SOURCE_MODULE" ] || { say "Missing $SOURCE_MODULE"; exit 1; }
    [ -f "$SOURCE_CONFIG" ] || { say "Missing $SOURCE_CONFIG"; exit 1; }

    say "No services will be restarted automatically. Do not install during a print."
    if [ -f "$TARGET_MODULE" ] && ! cmp -s "$SOURCE_MODULE" "$TARGET_MODULE"; then
        confirm "Replace the existing $TARGET_MODULE?" || {
            say "Installation cancelled before changing files."
            return
        }
    fi
    install -m 0644 "$SOURCE_MODULE" "$TARGET_MODULE"
    say "Installed Klipper module: $TARGET_MODULE"

    if [ -e "$TARGET_CONFIG" ]; then
        say "Existing user configuration preserved: $TARGET_CONFIG"
        say "Compare it with $SOURCE_CONFIG when updating."
    else
        install -m 0644 "$SOURCE_CONFIG" "$TARGET_CONFIG"
        say "Installed editable configuration: $TARGET_CONFIG"
    fi
    add_include
    say "Installation complete. Review every coordinate and pin before restarting Klipper."
}

uninstall_module() {
    require_layout
    say "No services will be restarted automatically."
    remove_include
    if [ -f "$TARGET_MODULE" ]; then
        rm -f -- "$TARGET_MODULE"
        say "Removed Klipper module: $TARGET_MODULE"
    fi
    if [ -f "$TARGET_CONFIG" ]; then
        if confirm "Delete the user calibration config $TARGET_CONFIG?"; then
            rm -f -- "$TARGET_CONFIG"
            say "Removed calibration configuration"
        else
            say "User calibration configuration was kept"
        fi
    fi
    say "Removal complete. Restart Klipper only when the printer is idle."
}

show_status() {
    [ -f "$TARGET_MODULE" ] && module_state="installed" || module_state="not installed"
    [ -f "$TARGET_CONFIG" ] && config_state="installed" || config_state="not installed"
    if [ -f "$INCLUDE_FILE" ] && grep -Fqx "$INCLUDE_LINE" "$INCLUDE_FILE"; then
        include_state="present"
    else
        include_state="absent"
    fi
    say "Klipper module: $module_state"
    say "Calibration config: $config_state"
    say "configuration include: $include_state ($INCLUDE_FILE)"
}

menu() {
    printf '\n%s\n' "$PROJECT_NAME Manager"
    printf '%s\n' '1) Install or update'
    printf '%s\n' '2) Remove'
    printf '%s\n' '3) Status'
    printf '%s\n' '4) Exit'
    printf 'Select: '
    read -r choice
    case "$choice" in
        1) install_module ;;
        2) uninstall_module ;;
        3) show_status ;;
        4) exit 0 ;;
        *) say "Unknown selection"; exit 1 ;;
    esac
}

case "${1:-menu}" in
    install|update) install_module ;;
    uninstall|remove) uninstall_module ;;
    status) show_status ;;
    menu) menu ;;
    *) say "Usage: $0 [install|update|uninstall|status]"; exit 1 ;;
esac
