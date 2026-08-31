# MedusaHC-Calibrate

> [!IMPORTANT]
> **[Installation, updates, removal, and manual setup](INSTALLATION.md)**

Experimental independent tool-offset calibration module for
[MedusaHC](https://github.com/Irbis3D/MedusaHC).

It supports the current MedusaHC Python controller and the frozen
`legacy-macros` controller. It does **not** require `klipper-toolchanger`.

## Calibration methods

| Command | Method | Result |
| --- | --- | --- |
| `CALIBRATE_XYZ_TOUCH` | Contact sensor | X/Y/Z |
| `CALIBRATE_Z_EDDY` | Native Klipper Eddy Tap on the bed | Z only |
| `CALIBRATE_XYZ_EDDY` | Eddy Tap for Z plus stationary EddySeek for XY | X/Y/Z |

All methods use T0 as the zero reference. Each successfully completed tool is
saved immediately to the existing `TOOL_OFFSET` variables and
`saved_vars.cfg`; a later failure does not discard earlier completed tools.

## Safety

This is experimental motion-control software. Before the first automatic run:

- make a complete printer configuration backup;
- verify every sensor pin and coordinate manually;
- confirm that all tools can reach the bed Tap point and calibration sensor;
- check Z clearance, XY travel limits, docks, cables, and heater operation;
- keep the printer idle and remain next to it with emergency stop available.

The module refuses to start while Klipper reports `printing` or `paused`.
Heaters are disabled after completion or failure, but that is not a substitute
for supervising the first runs.

## Requirements

- A working MedusaHC installation.
- `pin_watch.py` and the stable MedusaHC command interface: `SET`, `DROP`,
  `CLEAN`, and `TOOL_OFFSET_T`. Internal compatibility commands do not need to
  appear in the Mainsail macro panel.
- `[save_variables]` configured by MedusaHC.
- A working MedusaHC `HOME_REQUEST` command. Both Eddy calibration commands
  also require a working `Z_TILT_ADJUST` command.
- Additional hardware/software required by the selected method, described
  below.

## Installation

The installer copies one Klipper extra and one editable configuration file. It
does not install packages, modify Moonraker, restart services, or reboot the
printer.

Install directly from GitHub:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)"
```

The installer keeps a clean checkout in `~/medusahc-calibrate`, verifies that
MedusaHC Core (`medusahc.py`, `pin_watch.py`, and `MHC_variables.cfg`) is
present, and links the Klipper module from that checkout. With the current Core
layout it stores the editable configuration in `config/MedusaHC/` and asks
before adding its include to `MHC_config.cfg`. Legacy root-level configurations
remain supported.

The installer separately asks whether it may add a marked
`[update_manager medusahc-calibrate]` block directly to `moonraker.conf`. If
approved, MedusaHC-Calibrate appears in the normal Mainsail/Fluidd Update
Manager. Moonraker updates the clean checkout and restarts Klipper; the linked
module immediately uses the new code. The editable calibration config is
outside the repository and is never overwritten by an update. No extra
Moonraker include file is created.

If Calibrate was installed by the earlier archive-based installer, run the
normal install command once more. It creates the persistent checkout, replaces
the old copied Klipper module with the managed link, and preserves the existing
calibration configuration.

Update, status, and removal use the same entry point:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)" -- update
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)" -- status
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Calibrate/main/install-online.sh)" -- uninstall
```

For local testing from a checkout:

```bash
cd MedusaHC-Calibrate
bash install.sh
```

The local script provides install/update, removal, and status. With the current
Core layout the default locations are:

```text
~/klipper/klippy/extras/medusahc_calibrate.py
~/printer_data/config/MedusaHC/medusahc_calibrate.cfg
```

For another layout, supply paths explicitly:

```bash
KLIPPER_DIR=/path/to/klipper \
PRINTER_CONFIG_DIR=/path/to/printer_data/config \
bash install.sh
```

With the current Core layout, the installer asks before adding the following
relative include to the include block at the top of
`MedusaHC/MHC_config.cfg`:

```ini
[include medusahc_calibrate.cfg]
```

For a legacy root-level Core layout, the same line is added to `printer.cfg`
instead. An older incorrect
`[include MedusaHC/medusahc_calibrate.cfg]` entry in `MHC_config.cfg` is replaced
during an approved install or update.

Existing calibration configuration is preserved during updates and is removed
only after a separate confirmation during uninstall. Nothing is
restarted automatically by the command-line installer. Review the file and
restart Klipper or Moonraker yourself only when the printer is idle. Updates
started later through Moonraker may restart the managed Klipper service.

## Configuration overview

All MedusaHC-Calibrate settings and Mainsail/Fluidd macro entry points are in:

```text
~/printer_data/config/MedusaHC/medusahc_calibrate.cfg
```

The configuration is divided into Common, Contact sensor, Eddy Tap, and
EddySeek blocks. Only enable methods whose hardware has been verified.

### Common integration

The defaults call the public MedusaHC macros and work with both controllers:

```ini
set_command: SET
drop_command: DROP
clean_command: CLEAN
offset_command: TOOL_OFFSET_T
tool_state_object: pin_watch io
```

`calibration_temperature` defaults to 150°C. During Eddy calibration the
module heats only the current tool, keeps it at temperature during Tap and
EddySeek, switches it off after its measurement, then starts the next tool.

## SexBall-style contact calibration

The contact sensor must provide one normally stable digital signal when the
nozzle pushes it from above or from any XY direction.

Uncomment and set these values:

```ini
pin: ^PA1
probe_x: 0
probe_y: 0
probe_z: 15
```

- `pin` is the real contact input, including the correct pull-up and inversion.
- `probe_x` / `probe_y` are an approximate center of the sensor.
- `probe_z` is a safe machine Z above the sensor, not its trigger height.

Verify the pin with Klipper diagnostics before allowing motion. Verify the
approximate XYZ manually at low speed and ensure `max_probe_travel` cannot move
the nozzle into the machine.

The process first finds a rough center from the four cardinal sides, probes Z,
then measures a circle around the sensor. `directions` is the number of
diametrically opposed axes; the physical circle contains twice that many
points. For example:

```ini
directions: 12
samples: 5
```

means 24 circular positions and five physical contacts at each position. The
first contact is discarded as settling. Opposite pairs produce independent
center estimates; inconsistent axes are rejected and reported. If several
axes look questionable, calibration continues with a warning and preserves
the diagnostic summary.

The current contact workflow performs `HOME_REQUEST`, then heats all
participating tools and waits for T0 before measurement. It does not currently
run `Z_TILT_ADJUST`. Per-tool heater sequencing and Z tilt for this method are
planned follow-up work; the Eddy workflows already use both.

Important contact settings:

- `spread` — starting radial distance from the approximate center;
- `lower_z` — how far below the top contact point the side probes run;
- `sample_retract_dist` — radial release distance between contacts;
- `samples_tolerance` — allowed spread for repeated contacts;
- `center_tolerance` — allowed disagreement between opposing-axis centers.

Start with conservative speeds and generous safe clearance. Run:

```gcode
CALIBRATE_XYZ_TOUCH
```

## Native Eddy Tap Z calibration

This method requires a toolhead-mounted Eddy probe already configured for
Klipper's native `PROBE METHOD=tap` operation.

Set a safe bed point reachable by every tool:

```ini
tap_probe: probe_eddy_current eddy
tap_x: 165
tap_y: 190
tap_samples: 3
```

The median of the Tap samples is used. T0 becomes Z zero; existing X/Y offsets
are preserved. Run:

```gcode
CALIBRATE_Z_EDDY
```

## Eddy Tap + EddySeek XYZ calibration

This method uses two sensors:

1. the toolhead-mounted Eddy probe performs native Tap on the bed for Z;
2. a stationary Eddy Coil locates the metal nozzle in XY without touching it.

Install EddySeek from its own project and follow its current installation
instructions:

https://github.com/charliemayall/EddySeek

Configure its `[eddy_seek]` section for the actual LDC1612 connection, tool
count, search strategy, and safe travel limits. Hardware I2C is recommended
when available.

### Find the stationary sensor coordinates

1. Install T0 and clean the nozzle.
2. Move T0 above the stationary coil at the intended measurement height.
3. Enter approximate `sensor_x`, `sensor_y`, and `sensor_z` in `[eddy_seek]`.
4. Run EddySeek's accuracy command:

```gcode
EDDY_SEEK_ACCURACY TOOL=0 REPEATS=10
```

5. Add the reported mean X/Y correction to `sensor_x`/`sensor_y` and repeat
   until the mean is close to zero and repeatability is acceptable.

Do this at the final measurement height: a tilted coil or asymmetric magnetic
field can move the apparent XY center when Z changes. Keep enough physical
clearance for a small filament string.

Set MedusaHC-Calibrate to the same machine height:

```ini
eddy_seek_z: 5.0
eddy_seek_repeats: 3
```

If EddySeek uses `sensor_z`, its allowed Z band must include
`eddy_seek_z + the current tool's measured Z offset`.

The module calls the main EddySeek operation as:

```gcode
EDDY_SEEK_TOOL TOOL=<n> LOAD=0 REPEATS=<eddy_seek_repeats>
```

MedusaHC owns pickup, cleaning, Tap, heater sequencing, parking, offset saving,
and tool progression. Run:

```gcode
CALIBRATE_XYZ_EDDY
```

## Status

During or after a run:

```gcode
CALIBRATION_STATUS
```

The Klipper object `medusahc_calibrate` also exposes operation, current tool,
direction, sample number, progress, reference, results, and last error.

## Removal

Run:

```bash
bash install.sh uninstall
```

The installer asks before editing `printer.cfg` and before deleting the user
configuration. It does not remove MedusaHC, EddySeek, Klipper, saved offsets,
or any unrelated file.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
