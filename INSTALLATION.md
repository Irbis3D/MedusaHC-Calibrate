# MedusaHC-Calibrate installation

MedusaHC-Calibrate is an optional module. Install and configure MedusaHC Core
before installing it.

> [!WARNING]
> Do not install, update, remove, or restart Klipper or Moonraker during a
> print.

## Install

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)"
```

The installer:

1. Creates a clean Git checkout at `~/medusahc-calibrate`.
2. Verifies the MedusaHC Core dependency.
3. Links `medusahc_calibrate.py` into Klipper's `klippy/extras` directory.
4. Creates `MedusaHC/medusahc_calibrate.cfg` only if it does not already exist.
5. Asks before adding `[include medusahc_calibrate.cfg]` to the include block in
   `MedusaHC/MHC_config.cfg`.
6. Separately asks before adding a marked Update Manager block directly to
   `moonraker.conf`.

No service is restarted automatically. Review all calibration pins,
coordinates, movement limits, temperatures, and method-specific settings
before restarting Klipper.

For an older root-level MedusaHC layout, the calibration config and include
remain at the root of `printer_data/config`. Existing configuration is always
preserved.

## Moonraker updates

When approved during installation, Moonraker manages the clean
`~/medusahc-calibrate` checkout and displays MedusaHC-Calibrate in the normal
Mainsail/Fluidd Update Manager. After an update it restarts Klipper so the
linked module uses the new code. The editable calibration config is outside the
repository and is not overwritten.

An installation made by the older archive installer can be migrated by running
the normal install command once more.

## Status

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)" -- status
```

## Command-line update

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)" -- update
```

The command refuses to update a checkout containing local changes.

## Uninstall

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)" -- uninstall
```

The uninstaller separately asks before removing:

- the calibration include from `MHC_config.cfg`;
- the managed Update Manager block from `moonraker.conf`;
- the editable `medusahc_calibrate.cfg` file.

It removes the Klipper module link and the managed Git checkout. Answer `n` to
the configuration-file question to preserve all calibration settings. It does
not remove MedusaHC Core, EddySeek, Klipper, saved offsets, or any other
printer configuration.

If permission to remove an active include or updater entry is declined, removal
is cancelled before deleting the module or checkout, preventing broken links.

## Local/manual installation

From a clean clone, run:

```bash
git clone https://github.com/Irbis3D/MedusaHC-Calibrate.git ~/medusahc-calibrate
cd ~/medusahc-calibrate
bash install.sh install
```

For non-standard layouts, set `KLIPPER_DIR`, `PRINTER_CONFIG_DIR`,
`PRINTER_CFG`, or `MOONRAKER_CFG` before running `install.sh`.
