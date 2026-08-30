"""Independent contact, Eddy Tap, and EddySeek calibration for MedusaHC.

The module owns probing and full-tool calibration orchestration.  It does not
depend on a generic toolchanger object. Tool changes use the public MedusaHC
SET/DROP/CLEAN macros, and each successfully measured tool is saved before the
next tool begins.
"""

import logging
import math
import statistics


_ROUGH_DIRECTIONS = (
    ("E", 1.0, 0.0),
    ("NE", math.sqrt(0.5), math.sqrt(0.5)),
    ("N", 0.0, 1.0),
    ("NW", -math.sqrt(0.5), math.sqrt(0.5)),
    ("W", -1.0, 0.0),
    ("SW", -math.sqrt(0.5), -math.sqrt(0.5)),
    ("S", 0.0, -1.0),
    ("SE", math.sqrt(0.5), -math.sqrt(0.5)),
)
_DIRECTIONS = _ROUGH_DIRECTIONS

_OPPOSITE_PAIRS = (("E", "W"), ("NE", "SW"), ("N", "S"), ("NW", "SE"))


def circle_directions(axis_count):
    """Return 2*N contact directions and N diametrically opposed pairs."""
    point_count = axis_count * 2
    directions = []
    for index in range(point_count):
        angle = 2.0 * math.pi * index / float(point_count)
        degrees = 360.0 * index / float(point_count)
        directions.append((index, "%.1fdeg" % degrees, math.cos(angle), math.sin(angle)))
    pairs = []
    for index in range(axis_count):
        opposite = index + axis_count
        pairs.append((
            index,
            opposite,
            "%.1f-%.1fdeg" % (
                360.0 * index / float(point_count),
                360.0 * opposite / float(point_count),
            ),
        ))
    return directions, pairs


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _mean_point(points):
    count = float(len(points))
    return (
        sum(point[0] for point in points) / count,
        sum(point[1] for point in points) / count,
    )


def _middle(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def evaluate_contact_centers(contacts, center_tolerance, opposite_pairs=None):
    """Return a robust center from three or more opposing contact pairs."""
    opposite_pairs = _OPPOSITE_PAIRS if opposite_pairs is None else opposite_pairs
    pair_data = []
    for pair in opposite_pairs:
        first, second = pair[:2]
        name = pair[2] if len(pair) > 2 else "%s-%s" % (first, second)
        a, b = contacts[first], contacts[second]
        pair_data.append({
            "name": name,
            "center": _middle(a, b),
        })

    if len(pair_data) < 3:
        raise ValueError("at least three opposite calibration directions are required")

    def subset_score(indices):
        indices = tuple(indices)
        center = _mean_point([pair_data[index]["center"] for index in indices])
        deviations = [
            _distance(pair_data[index]["center"], center) for index in indices
        ]
        return {
            "indices": tuple(indices),
            "center": center,
            "max_center_deviation": max(deviations),
            "score": math.sqrt(sum(value * value for value in deviations) / len(deviations)),
        }

    all_axes = subset_score(range(len(pair_data)))
    accepted = list(range(len(pair_data)))
    minimum_accepted = max(3, len(pair_data) // 2 + 1)
    rejected_indices = []
    while len(accepted) > minimum_accepted:
        centers = [pair_data[index]["center"] for index in accepted]
        robust_center = (
            statistics.median(point[0] for point in centers),
            statistics.median(point[1] for point in centers),
        )
        ranked = []
        for index in accepted:
            center_error = _distance(pair_data[index]["center"], robust_center)
            score = center_error / center_tolerance
            ranked.append((score, center_error, index))
        ranked.sort(reverse=True)
        if ranked[0][0] <= 1.0:
            break
        rejected_indices.append(ranked[0][2])
        accepted.remove(ranked[0][2])

    selected = subset_score(accepted)
    within_tolerance = selected["max_center_deviation"] <= center_tolerance
    rejected = [pair_data[index]["name"] for index in rejected_indices]

    accepted_set = set(selected["indices"])
    for index, item in enumerate(pair_data):
        item["accepted"] = index in accepted_set
        item["center_deviation"] = _distance(item["center"], selected["center"])

    return {
        "center": selected["center"],
        "pairs": pair_data,
        "rejected_axes": rejected,
        "max_center_deviation": selected["max_center_deviation"],
        "degraded_quality": not within_tolerance,
        "all_axes_center_deviation": all_axes["max_center_deviation"],
    }


class _ContactEndstops:
    """Expose one physical contact input to XY-vector and Z probing moves."""

    def __init__(self, config, pin):
        self.printer = config.get_printer()
        pins = self.printer.lookup_object("pins")
        bare_pin = pin.replace("^", "").replace("!", "")
        pins.allow_multi_use_pin(bare_pin)
        self.xy = self._make_endstop(pins, pin)
        self.z = self._make_endstop(pins, pin)
        self.printer.register_event_handler("klippy:mcu_identify", self._attach_steppers)

    @staticmethod
    def _make_endstop(pins, pin):
        params = pins.lookup_pin(pin, can_invert=True, can_pullup=True)
        return params["chip"].setup_pin("endstop", params)

    def _attach_steppers(self):
        kinematics = self.printer.lookup_object("toolhead").get_kinematics()
        for stepper in kinematics.get_steppers():
            if stepper.is_active_axis("x") or stepper.is_active_axis("y"):
                self.xy.add_stepper(stepper)
            if stepper.is_active_axis("z"):
                self.z.add_stepper(stepper)

    def query(self, endstop, print_time):
        return bool(endstop.query_endstop(print_time))


class MedusaHCCalibrate:
    """Measure and store offsets for all configured MedusaHC tools."""

    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        contact_pin = config.get("pin", None)
        self.endstops = (
            _ContactEndstops(config, contact_pin) if contact_pin else None
        )

        # Public macro names are shared by the classic macro controller and
        # MedusaHC Python Controller. They may be overridden for custom setups.
        self.set_command = config.get("set_command", "SET")
        self.drop_command = config.get("drop_command", "DROP")
        self.clean_command = config.get("clean_command", "CLEAN")
        self.offset_command = config.get("offset_command", "TOOL_OFFSET_T")
        self.tool_state_object = config.get("tool_state_object", "pin_watch io")

        # Contact coordinates are required only when a contact pin is enabled.
        self.probe_x = config.getfloat("probe_x") if contact_pin else 0.0
        self.probe_y = config.getfloat("probe_y") if contact_pin else 0.0
        self.probe_z_position = config.getfloat("probe_z") if contact_pin else 0.0
        self.spread = config.getfloat("spread", 7.0, above=0.0)
        self.lower_z = config.getfloat("lower_z", 0.3, minval=0.0)
        self.travel_speed = config.getfloat("travel_speed", 250.0, above=0.0)
        self.positioning_speed = config.getfloat(
            "positioning_speed", 250.0, above=0.0
        )
        self.transition_speed = config.getfloat(
            "transition_speed", 250.0, above=0.0
        )
        self.speed = config.getfloat("speed", 4.0, above=0.0)
        self.z_speed = config.getfloat("z_speed", 6.0, above=0.0)
        self.lift_speed = config.getfloat("lift_speed", 4.0, above=0.0)
        self.retract_speed = config.getfloat("retract_speed", 150.0, above=0.0)
        self.final_lift_z = config.getfloat("final_lift_z", 6.0, above=0.0)
        self.max_probe_travel = config.getfloat("max_probe_travel", 12.0, above=0.0)

        self.sample_retract_dist = config.getfloat(
            "sample_retract_dist", 2.0, above=0.0
        )
        self.z_sample_retract_dist = config.getfloat(
            "z_sample_retract_dist", 3.0, above=0.0
        )
        self.samples = config.getint("samples", 5, minval=1)
        self.directions = config.getint("directions", 12, minval=3, maxval=32)
        self.samples_result = config.getchoice(
            "samples_result", {"median": "median", "average": "average"}, "median"
        )
        self.samples_tolerance = config.getfloat(
            "samples_tolerance", 0.03, minval=0.0
        )
        self.samples_tolerance_retries = config.getint(
            "samples_tolerance_retries", 10, minval=0
        )
        self.center_tolerance = config.getfloat("center_tolerance", 0.03, above=0.0)
        self.calibration_temperature = config.getfloat(
            "calibration_temperature", 150.0, minval=0.0
        )
        self.tap_probe_name = config.get("tap_probe", "probe_eddy_current eddy")
        self.tap_x = config.getfloat("tap_x", 165.0)
        self.tap_y = config.getfloat("tap_y", 190.0)
        self.tap_samples = config.getint("tap_samples", 3, minval=1, maxval=20)
        self.eddy_seek_z = config.getfloat("eddy_seek_z", 5.0)
        self.eddy_seek_repeats = config.getint(
            "eddy_seek_repeats", 3, minval=1, maxval=20
        )
        self.verbose = config.getboolean("verbose", True)

        self.operation = "idle"
        self.current_tool = -1
        self.current_direction = ""
        self.current_sample = 0
        self.progress = 0.0
        self.last_error = ""
        self.results = {}
        self.reference = None
        self.gcode.register_command(
            "MHC_CALIBRATE_ALL",
            self.cmd_MHC_CALIBRATE_ALL,
            desc="Calibrate every configured MedusaHC tool",
        )
        self.gcode.register_command(
            "MHC_CALIBRATE_QUERY",
            self.cmd_MHC_CALIBRATE_QUERY,
            desc="Report MedusaHC calibration state",
        )
        self.gcode.register_command(
            "MHC_CALIBRATE_EDDY_ALL", self.cmd_MHC_CALIBRATE_EDDY_ALL,
            desc="Calibrate XYZ using Eddy Tap and EddySeek",
        )
        self.gcode.register_command(
            "MHC_CALIBRATE_TAP_Z", self.cmd_MHC_CALIBRATE_TAP_Z,
            desc="Calibrate tool Z offsets using Eddy Tap",
        )

    def get_status(self, eventtime):
        return {
            "operation": self.operation,
            "current_tool": self.current_tool,
            "current_direction": self.current_direction,
            "current_sample": self.current_sample,
            "progress": self.progress,
            "last_error": self.last_error,
            "reference": self.reference,
            "results": self.results,
        }

    def _run(self, script):
        self.gcode.run_script_from_command(script)

    def _macro_name(self, name):
        """Prefer a hidden macro while remaining compatible with legacy names."""
        candidates = (name,) if name.startswith("_") else ("_" + name, name)
        for candidate in candidates:
            if self.printer.lookup_object("gcode_macro %s" % candidate, None) is not None:
                return candidate
        return name

    def _tool_count(self):
        state_name = self._macro_name("GLOBAL_STATE")
        state = self.printer.lookup_object("gcode_macro %s" % state_name, None)
        if state is None:
            raise self.printer.command_error(
                "MedusaHC calibration requires GLOBAL_STATE configuration"
            )
        return int(state.variables.get("max_tool", 0))

    def _preflight_common(self):
        stats = self.printer.lookup_object("print_stats", None)
        if getattr(stats, "state", "") in ("printing", "paused"):
            raise self.printer.command_error("Calibration is unavailable during a print")
        toolhead = self.printer.lookup_object("toolhead")
        status = toolhead.get_status(self.reactor.monotonic())
        if not all(axis in status.get("homed_axes", "") for axis in "xyz"):
            raise self.printer.command_error("Home XYZ before calibration")
        if self._tool_count() < 1:
            raise self.printer.command_error("No MedusaHC tools are configured")

    def _preflight(self):
        self._preflight_common()
        if self.endstops is None:
            raise self.printer.command_error(
                "Contact calibration requires pin in [medusahc_calibrate]"
            )
        toolhead = self.printer.lookup_object("toolhead")
        print_time = toolhead.get_last_move_time()
        if self.endstops.query(self.endstops.z, print_time):
            raise self.printer.command_error(
                "Calibration contact sensor is triggered before movement"
            )

    def _emergency_lift(self):
        """Best-effort vertical retreat without attempting another tool change."""
        try:
            toolhead = self.printer.lookup_object("toolhead")
            status = toolhead.get_status(self.reactor.monotonic())
            if "z" not in status.get("homed_axes", ""):
                return
            position = toolhead.get_position()
            target_z = min(
                position[2] + self.final_lift_z,
                status["axis_maximum"][2],
            )
            self._move([None, None, target_z], self.lift_speed)
        except Exception:
            logging.exception("MedusaHC calibration emergency lift failed")

    def _move(self, position, speed):
        self.printer.lookup_object("toolhead").manual_move(position, speed)

    def _wait_moves(self):
        self.printer.lookup_object("toolhead").wait_moves()

    def _contact_triggered(self, endstop=None):
        toolhead = self.printer.lookup_object("toolhead")
        return self.endstops.query(
            self.endstops.xy if endstop is None else endstop,
            toolhead.get_last_move_time(),
        )

    def _probe_to(self, endstop, target, speed, check_movement=True):
        # manual_move queues positioning.  Ensure the preceding release move
        # has physically completed and its endstop state reached the host
        # before homing checks the initial contact state.
        self._wait_moves()
        homing = self.printer.lookup_object("homing")
        try:
            return homing.probing_move(
                endstop, target, speed, check_movement=check_movement
            )[:3]
        except self.printer.command_error as exc:
            raise self.printer.command_error(
                "Calibration contact was not detected: %s" % exc
            )

    def _safe_above(self, x=None, y=None, z=None):
        target_z = self.probe_z_position if z is None else z
        self._move([None, None, target_z], self.lift_speed)
        self._move(
            [self.probe_x if x is None else x, self.probe_y if y is None else y, None],
            self.transition_speed,
        )

    def _reduce_samples(self, values):
        if self.samples_result == "median":
            return statistics.median(values)
        return sum(values) / float(len(values))

    def _sample_contact(
            self, name, vx, vy, center, side_z, sample_count=None,
            position_start=True):
        sample_count = self.samples if sample_count is None else sample_count
        discard_settling_contact = sample_count > 1
        measurement_count = sample_count - 1 if discard_settling_contact else 1
        settling_done = not discard_settling_contact
        values = []
        contacts = []
        retries = 0
        start = [
            center[0] + vx * self.spread,
            center[1] + vy * self.spread,
            side_z,
        ]
        if position_start:
            self._safe_above(start[0], start[1], side_z + self.final_lift_z)
            self._move(start, self.lift_speed)
        while len(values) < measurement_count:
            physical_sample = len(values) + (2 if settling_done else 1)
            self.current_sample = physical_sample
            if self._contact_triggered():
                raise self.printer.command_error(
                    "%s contact sensor is triggered before probing"
                    % self.current_direction
                )
            target = [
                center[0] - vx * self.spread,
                center[1] - vy * self.spread,
                side_z,
            ]
            # On CoreXY a 45-degree Cartesian move may leave one belt motor
            # stationary. Klipper's generic post-probe check interprets that
            # one stationary motor as a pre-trigger, even though the other
            # motor moved and the contact occurred. We already verify the
            # sensor is open above, so skip only that motor-motion check for
            # true diagonal vectors.
            diagonal = abs(vx) > 1.0e-9 and abs(vy) > 1.0e-9
            contact = self._probe_to(
                self.endstops.xy,
                target,
                self.speed,
                check_movement=not diagonal,
            )
            projection = contact[0] * vx + contact[1] * vy
            if not settling_done:
                settling_done = True
                if self.verbose:
                    self.gcode.respond_info(
                        "MHC calibration T%d %s settling contact 1/%d discarded: "
                        "X=%.6f Y=%.6f Z=%.6f"
                        % (
                            self.current_tool, self.current_direction, sample_count,
                            contact[0], contact[1], contact[2],
                        )
                    )
            else:
                values.append(projection)
                contacts.append(contact)
            if self.verbose and settling_done and contacts:
                self.gcode.respond_info(
                    "MHC calibration T%d %s sample %d/%d: X=%.6f Y=%.6f Z=%.6f"
                    % (
                        self.current_tool,
                        self.current_direction,
                        len(values) + 1,
                        sample_count,
                        contact[0],
                        contact[1],
                        contact[2],
                    )
                )
            # Always release the sensor after a contact, including the final
            # sample. Subsequent samples immediately probe from this short
            # radial retreat.
            retract = [
                contact[0] + vx * self.sample_retract_dist,
                contact[1] + vy * self.sample_retract_dist,
                side_z,
            ]
            self._move(retract, self.retract_speed)
            self._wait_moves()
            if self._contact_triggered():
                retract[0] += vx
                retract[1] += vy
                self._move(retract, self.retract_speed)
                self._wait_moves()
                if self._contact_triggered():
                    raise self.printer.command_error(
                        "%s contact sensor did not release after 3 mm retreat"
                        % self.current_direction
                    )
            if len(values) > 1 and max(values) - min(values) > self.samples_tolerance:
                if retries >= self.samples_tolerance_retries:
                    raise self.printer.command_error(
                        "%s samples exceed tolerance %.6f mm" % (
                            name, self.samples_tolerance
                        )
                    )
                retries += 1
                if self.verbose:
                    self.gcode.respond_info(
                        "MHC calibration T%d %s: sample spread too large, retry %d/%d"
                        % (
                            self.current_tool,
                            self.current_direction,
                            retries,
                            self.samples_tolerance_retries,
                        )
                    )
                values = []
                contacts = []
                continue

        selected = self._reduce_samples(values)
        best = min(
            contacts,
            key=lambda point: abs((point[0] * vx + point[1] * vy) - selected),
        )
        return (best[0], best[1])

    def _probe_z(self, center, samples=None):
        count = self.samples if samples is None else samples
        values = []
        retries = 0
        self._safe_above(center[0], center[1])
        while len(values) < count:
            self.current_direction = "Z"
            self.current_sample = len(values) + 1
            target = [
                center[0], center[1],
                self.probe_z_position - self.max_probe_travel,
            ]
            contact = self._probe_to(self.endstops.z, target, self.z_speed)
            values.append(contact[2])
            if self.verbose:
                self.gcode.respond_info(
                    "MHC calibration T%d Z sample %d/%d: Z=%.6f"
                    % (self.current_tool, len(values), count, contact[2])
                )
            retract_z = contact[2] + self.z_sample_retract_dist
            self._move([center[0], center[1], retract_z], self.retract_speed)
            self._wait_moves()
            if self._contact_triggered(self.endstops.z):
                retract_z += 1.0
                self._move([center[0], center[1], retract_z], self.retract_speed)
                self._wait_moves()
                if self._contact_triggered(self.endstops.z):
                    raise self.printer.command_error(
                        "Z contact sensor did not release after %.1f mm retreat"
                        % (self.z_sample_retract_dist + 1.0)
                    )
            if max(values) - min(values) > self.samples_tolerance:
                if retries >= self.samples_tolerance_retries:
                    raise self.printer.command_error(
                        "Z samples exceed tolerance %.6f mm" % self.samples_tolerance
                    )
                retries += 1
                values = []
                continue
        return self._reduce_samples(values)

    def _probe_xy(self, center, side_z):
        directions, opposite_pairs = circle_directions(self.directions)
        contacts = {}
        first = directions[0]
        self._safe_above(
            center[0] + first[2] * self.spread,
            center[1] + first[3] * self.spread,
            side_z + self.final_lift_z,
        )
        self._move([
            center[0] + first[2] * self.spread,
            center[1] + first[3] * self.spread,
            side_z,
        ], self.lift_speed)
        for position, (key, name, vx, vy) in enumerate(directions):
            self.current_direction = name
            contact = self._sample_contact(
                name, vx, vy, center, side_z, position_start=False
            )
            contacts[key] = contact
            if position + 1 < len(directions):
                next_direction = directions[position + 1]
                next_vx, next_vy = next_direction[2], next_direction[3]
                contact_radius = (
                    (contact[0] - center[0]) * vx
                    + (contact[1] - center[1]) * vy
                )
                orbit_radius = max(
                    contact_radius + self.sample_retract_dist,
                    self.sample_retract_dist + 1.0,
                )
                self._move([
                    center[0] + next_vx * orbit_radius,
                    center[1] + next_vy * orbit_radius,
                    side_z,
                ], self.transition_speed)
                self._wait_moves()
                if self._contact_triggered():
                    self._move([
                        center[0] + next_vx * (orbit_radius + 1.0),
                        center[1] + next_vy * (orbit_radius + 1.0),
                        side_z,
                    ], self.retract_speed)
                    self._wait_moves()
                    if self._contact_triggered():
                        raise self.printer.command_error(
                            "%s contact sensor did not release before next direction"
                            % name
                        )
        return evaluate_contact_centers(
            contacts,
            self.center_tolerance,
            opposite_pairs,
        )

    def _probe_xy_rough(self, center, side_z):
        """Locate an approximate center with one E/W/N/S contact each."""
        contacts = {}
        for name, vx, vy in (
            ("E", 1.0, 0.0),
            ("W", -1.0, 0.0),
            ("N", 0.0, 1.0),
            ("S", 0.0, -1.0),
        ):
            self.current_direction = "rough_%s" % name
            contacts[name] = self._sample_contact(
                name, vx, vy, center, side_z, sample_count=1
            )
        return (
            (contacts["E"][0] + contacts["W"][0]) * 0.5,
            (contacts["N"][1] + contacts["S"][1]) * 0.5,
        )

    def _position_over_probe(self):
        self._move([None, None, self.probe_z_position], self.positioning_speed)
        self._move(
            [self.probe_x, self.probe_y, None], self.positioning_speed
        )

    def _measure_tool(self, tool):
        self.current_tool = tool
        self._run("%s T=%d" % (self._macro_name(self.set_command), tool))
        self._run(self._macro_name(self.clean_command))
        # SET applies the tool's previously stored correction. Calibration
        # must measure every nozzle in the same uncorrected coordinate system.
        self._run("SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0")
        self._position_over_probe()
        initial = (self.probe_x, self.probe_y)
        rough_z = self._probe_z(initial, samples=1)
        center = self._probe_xy_rough(initial, rough_z - self.lower_z)
        final_z = self._probe_z(center)
        final = self._probe_xy(center, final_z - self.lower_z)
        self._safe_above(final["center"][0], final["center"][1])
        result = {
            "position": [final["center"][0], final["center"][1], final_z],
            "rejected_axes": final["rejected_axes"],
            "max_center_deviation": final["max_center_deviation"],
            "degraded_quality": final["degraded_quality"],
            "all_axes_center_deviation": final["all_axes_center_deviation"],
            "pairs": final["pairs"],
        }
        self._report_tool(tool, result)
        return result

    def _report_tool(self, tool, result):
        self.gcode.respond_info(
            "MedusaHC T%d center X=%.6f Y=%.6f Z=%.6f; rejected=%s; "
            "center spread=%.6f"
            % (
                tool,
                result["position"][0],
                result["position"][1],
                result["position"][2],
                ",".join(result["rejected_axes"]) or "none",
                result["max_center_deviation"],
            )
        )
        if result["degraded_quality"]:
            self.gcode.respond_info(
                "WARNING: MedusaHC T%d calibration quality is outside tolerance; "
                "axes %s rejected; calibration continued "
                "(all-axis center spread=%.6f)"
                % (
                    tool,
                    ",".join(result["rejected_axes"]) or "none",
                    result["all_axes_center_deviation"],
                )
            )
        if self.verbose:
            for pair in result["pairs"]:
                self.gcode.respond_info(
                    "MHC calibration T%d axis %s: center X=%.6f Y=%.6f "
                    "deviation=%.6f %s"
                    % (
                        tool,
                        pair["name"],
                        pair["center"][0],
                        pair["center"][1],
                        pair["center_deviation"],
                        "accepted" if pair["accepted"] else "REJECTED",
                    )
                )

    def _offsets_from_measurements(self, measured):
        reference = measured[0]["position"]
        offsets = {}
        for tool, result in measured.items():
            position = result["position"]
            offsets[tool] = [position[index] - reference[index] for index in range(3)]
        return offsets

    def _commit_offsets(self, offsets):
        offset_macro = self._macro_name("TOOL_OFFSET")
        for tool in sorted(offsets):
            for axis, value in zip(("x", "y", "z"), offsets[tool]):
                self._run(
                    "SET_GCODE_VARIABLE MACRO=%s VARIABLE=t%d_off_%s VALUE=%.9f"
                    % (offset_macro, tool, axis, value)
                )
                self._run(
                    "SAVE_VARIABLE VARIABLE=t%d_gcode_%s_offset VALUE=%.9f"
                    % (tool, axis, value)
                )

    def _commit_z_offset(self, tool, value):
        offset_macro = self._macro_name("TOOL_OFFSET")
        self._run(
            "SET_GCODE_VARIABLE MACRO=%s VARIABLE=t%d_off_z VALUE=%.9f"
            % (offset_macro, tool, value)
        )
        self._run(
            "SAVE_VARIABLE VARIABLE=t%d_gcode_z_offset VALUE=%.9f"
            % (tool, value)
        )

    def _installed_tool(self):
        source = self.printer.lookup_object("medusahc", None)
        if source is None:
            source = self.printer.lookup_object(self.tool_state_object, None)
        if source is None:
            raise self.printer.command_error(
                "Neither [medusahc] nor [%s] is configured"
                % self.tool_state_object
            )
        if hasattr(source, "get_status"):
            status = source.get_status(self.reactor.monotonic())
            return int(status.get("current_tool", -1))
        return int(getattr(source, "current_tool", -1))

    def _prepare_eddy_calibration(self):
        self._run(self._macro_name("HOME_REQUEST"))
        self._preflight_common()
        if self._installed_tool() >= 0:
            self._run(self._macro_name(self.drop_command))
        self._run("Z_TILT_ADJUST")

    def _tap_z(self, tool):
        self.current_tool = tool
        self.current_direction = "TAP_Z"
        self._run("%s T=%d" % (self._macro_name(self.set_command), tool))
        self._run(self._macro_name(self.clean_command))
        self._run("SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0")
        self._move([None, None, self.final_lift_z], self.positioning_speed)
        self._move([self.tap_x, self.tap_y, None], self.positioning_speed)
        probe = self.printer.lookup_object(self.tap_probe_name, None)
        if probe is None:
            raise self.printer.command_error(
                "Tap probe object '%s' was not found" % self.tap_probe_name
            )
        values = []
        for sample in range(self.tap_samples):
            self._run("PROBE METHOD=tap")
            value = probe.get_status(
                self.reactor.monotonic()
            ).get("last_z_result", None)
            if value is None:
                raise self.printer.command_error("Eddy Tap returned no Z result")
            values.append(float(value))
            self.gcode.respond_info(
                "MedusaHC T%d Eddy Tap sample %d/%d: Z=%.6f"
                % (tool, sample + 1, self.tap_samples, values[-1])
            )
        value = statistics.median(values)
        self.gcode.respond_info(
            "MedusaHC T%d Eddy Tap median Z=%.6f" % (tool, value)
        )
        return value

    def _eddy_seek_xy(self, tool, z_delta):
        self.current_direction = "EDDY_XY"
        self._move([None, None, self.eddy_seek_z + z_delta], self.positioning_speed)
        # EddySeek owns sensor_x/sensor_y, moves to the sensor itself and keeps
        # its T0 reference for subsequent tools.  LOAD=0 leaves tool changing
        # entirely under MedusaHC control.
        eddy = self.printer.lookup_object("eddy_seek", None)
        if eddy is None:
            raise self.printer.command_error("[eddy_seek] is not configured")
        previous = eddy._tools.get_tool(tool)
        self._run(
            "EDDY_SEEK_TOOL TOOL=%d LOAD=0 REPEATS=%d"
            % (tool, self.eddy_seek_repeats)
        )
        self._wait_moves()
        measured = eddy._tools.get_tool(tool)
        # EDDY_SEEK_TOOL reports a failed search without raising a G-code
        # error.  It only replaces its tool record after a successful seek.
        if measured is previous:
            raise self.printer.command_error(
                "EddySeek failed to measure T%d" % tool
            )
        result = (float(measured.offset.x), float(measured.offset.y))
        self.gcode.respond_info(
            "MedusaHC T%d EddySeek offset X=%.6f Y=%.6f (%d run%s)"
            % (tool, result[0], result[1], self.eddy_seek_repeats,
               "" if self.eddy_seek_repeats == 1 else "s")
        )
        return result

    def _restore_active_offset(self):
        try:
            tool = self._installed_tool()
        except Exception:
            return
        if tool >= 0:
            self._run(
                "%s T=%d MOVE=0"
                % (self._macro_name(self.offset_command), tool)
            )

    @staticmethod
    def _heater_name(tool):
        return "extruder" if tool == 0 else "extruder%d" % tool

    def _preheat_tools(self, tools, wait_tool):
        tools = tuple(tools)
        if not tools:
            return
        self._start_heaters(tools)
        self.gcode.respond_info(
            "MedusaHC calibration heating %s to %.1f C; waiting for T%d"
            % (
                ",".join("T%d" % tool for tool in tools),
                self.calibration_temperature,
                wait_tool,
            )
        )
        self._wait_heater(wait_tool)

    def _start_heaters(self, tools):
        for tool in tools:
            self._run(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.3f"
                % (self._heater_name(tool), self.calibration_temperature)
            )

    def _wait_heater(self, tool):
        self._run(
            "TEMPERATURE_WAIT SENSOR=%s MINIMUM=%.3f"
            % (self._heater_name(tool), self.calibration_temperature)
        )

    def _cooldown_tools(self, tools):
        for tool in tools:
            self._run(
                "SET_HEATER_TEMPERATURE HEATER=%s TARGET=0"
                % self._heater_name(tool)
            )
        if tools:
            self.gcode.respond_info(
                "MedusaHC calibration heaters disabled: %s"
                % ",".join("T%d" % tool for tool in tools)
            )

    def cmd_MHC_CALIBRATE_ALL(self, gcmd):
        if self.operation != "idle":
            raise gcmd.error("MedusaHC calibration is already running")
        self.operation = "calibrating_all"
        self.last_error = ""
        self.results = {}
        self.reference = None
        tools = ()
        try:
            self._run(self._macro_name("HOME_REQUEST"))
            self._preflight()
            count = self._tool_count()
            tools = tuple(range(count))
            self._preheat_tools(tools, wait_tool=0)
            measured = {}
            offsets = {}
            for tool in tools:
                measured[tool] = self._measure_tool(tool)
                if tool == 0:
                    self.reference = measured[0]["position"]
                position = measured[tool]["position"]
                offsets[tool] = [
                    position[index] - self.reference[index] for index in range(3)
                ]
                self._commit_offsets({tool: offsets[tool]})
                self.results[str(tool)] = {
                    "offset": offsets[tool],
                    "position": position,
                    "rejected_axes": measured[tool]["rejected_axes"],
                }
                self.progress = float(tool + 1) / float(count)
                self.gcode.respond_info(
                    "MedusaHC T%d offsets saved: X=%.6f Y=%.6f Z=%.6f"
                    % (tool, offsets[tool][0], offsets[tool][1], offsets[tool][2])
                )
            self._run(self._macro_name(self.drop_command))
            self.gcode.respond_info(
                "MedusaHC calibration completed: %d tools measured and saved" % count
            )
        except Exception as exc:
            self.last_error = str(exc)
            logging.exception("MedusaHC calibration failed")
            self._emergency_lift()
            try:
                self._restore_active_offset()
            except Exception:
                logging.exception("MedusaHC calibration offset restore failed")
            raise
        finally:
            try:
                self._cooldown_tools(tools)
            except Exception:
                logging.exception("MedusaHC calibration heater shutdown failed")
            self.operation = "idle"
            self.current_direction = ""
            self.current_sample = 0
            self.current_tool = -1

    def _run_eddy_calibration(self, gcmd, xy_enabled):
        if self.operation != "idle":
            raise gcmd.error("MedusaHC calibration is already running")
        self.operation = "calibrating_eddy" if xy_enabled else "calibrating_tap_z"
        self.last_error = ""
        self.results = {}
        self.reference = None
        self.progress = 0.0
        tools = ()
        try:
            stats = self.printer.lookup_object("print_stats", None)
            if getattr(stats, "state", "") in ("printing", "paused"):
                raise gcmd.error("Calibration is unavailable during a print")
            count = self._tool_count()
            tools = tuple(range(count))
            # Start only T0 before homing and Z tilt.  EddySeek runs with the
            # measured tool held at temperature, but never with a second
            # heater active on the same calibration pass.
            self._start_heaters(tools[:1])
            self.gcode.respond_info(
                "MedusaHC calibration preheating %s during home and Z tilt"
                % ",".join("T%d" % tool for tool in tools[:1])
            )
            self._prepare_eddy_calibration()
            reference_z = None
            reference_xy = None
            for tool in tools:
                # The current tool was started after the preceding seek (T0
                # was started before preparation).  Wait before pickup and
                # keep it at temperature through both Tap and EddySeek.
                self._preheat_tools((tool,), wait_tool=tool)
                tap_z = self._tap_z(tool)
                if reference_z is None:
                    reference_z = tap_z
                    self.reference = [None, None, tap_z]
                z_offset = tap_z - reference_z
                xy = None
                if xy_enabled:
                    xy = self._eddy_seek_xy(tool, z_offset)
                # Measurement is complete.  Stop this heater, start the next
                # one immediately, and park the current tool while the next
                # tool warms up.
                self._cooldown_tools((tool,))
                if tool + 1 < count:
                    self._start_heaters((tool + 1,))
                self._run(self._macro_name(self.drop_command))
                if xy_enabled:
                    if reference_xy is None:
                        reference_xy = xy
                        self.reference[0], self.reference[1] = xy
                    offset = [xy[0] - reference_xy[0],
                              xy[1] - reference_xy[1], z_offset]
                    self._commit_offsets({tool: offset})
                else:
                    offset = [None, None, z_offset]
                    self._commit_z_offset(tool, z_offset)
                self.results[str(tool)] = {
                    "offset": offset, "tap_z": tap_z,
                    "position": ([xy[0], xy[1], tap_z]
                                 if xy_enabled else [None, None, tap_z]),
                }
                self.progress = float(tool + 1) / float(count)
                if xy_enabled:
                    self.gcode.respond_info(
                        "MedusaHC T%d Eddy offsets saved: X=%.6f Y=%.6f Z=%.6f"
                        % (tool, offset[0], offset[1], offset[2]))
                else:
                    self.gcode.respond_info(
                        "MedusaHC T%d Tap Z offset saved: Z=%.6f" % (tool, z_offset))
            self.gcode.respond_info(
                "MedusaHC %s calibration completed: %d tools measured and saved"
                % ("Eddy XYZ" if xy_enabled else "Tap Z", count))
        except Exception as exc:
            self.last_error = str(exc)
            logging.exception("MedusaHC Eddy calibration failed")
            self._emergency_lift()
            try:
                self._restore_active_offset()
            except Exception:
                logging.exception("MedusaHC calibration offset restore failed")
            raise
        finally:
            try:
                self._cooldown_tools(tools)
            except Exception:
                logging.exception("MedusaHC calibration heater shutdown failed")
            self.operation = "idle"
            self.current_direction = ""
            self.current_sample = 0
            self.current_tool = -1

    def cmd_MHC_CALIBRATE_EDDY_ALL(self, gcmd):
        self._run_eddy_calibration(gcmd, xy_enabled=True)

    def cmd_MHC_CALIBRATE_TAP_Z(self, gcmd):
        self._run_eddy_calibration(gcmd, xy_enabled=False)

    def cmd_MHC_CALIBRATE_QUERY(self, gcmd):
        gcmd.respond_info(
            "MedusaHC calibration: operation=%s progress=%.1f%% error=%s"
            % (self.operation, self.progress * 100.0, self.last_error or "none")
        )


def load_config(config):
    return MedusaHCCalibrate(config)
