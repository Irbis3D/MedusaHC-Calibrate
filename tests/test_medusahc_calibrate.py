import importlib.util
import math
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1] / "klippy" / "extras" / "medusahc_calibrate.py"
)
SPEC = importlib.util.spec_from_file_location("medusahc_calibrate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def circular_contacts(center=(100.0, 200.0), radius=4.0):
    result = {}
    for name, vx, vy in MODULE._DIRECTIONS:
        result[name] = (center[0] + vx * radius, center[1] + vy * radius)
    return result


class CenterEvaluationTests(unittest.TestCase):
    def test_eight_axes_generate_sixteen_circular_contacts(self):
        directions, pairs = MODULE.circle_directions(8)
        self.assertEqual(len(directions), 16)
        self.assertEqual(len(pairs), 8)
        for first, second, unused_name in pairs:
            self.assertAlmostEqual(directions[first][2] + directions[second][2], 0.0)
            self.assertAlmostEqual(directions[first][3] + directions[second][3], 0.0)

    def test_eight_axes_keep_at_least_five_for_center(self):
        directions, pairs = MODULE.circle_directions(8)
        contacts = {}
        for key, unused_name, vx, vy in directions:
            contacts[key] = (100.0 + vx * 4.0, 200.0 + vy * 4.0)
        for key in (0, 1, 2, 3):
            point = contacts[key]
            contacts[key] = (point[0] + 0.5 * (key + 1), point[1] - 0.4 * key)

        result = MODULE.evaluate_contact_centers(
            contacts, 0.02, pairs
        )

        accepted = [pair for pair in result["pairs"] if pair["accepted"]]
        self.assertGreaterEqual(len(accepted), 5)

    def test_eight_contacts_recover_center(self):
        result = MODULE.evaluate_contact_centers(
            circular_contacts(), center_tolerance=0.03
        )
        self.assertAlmostEqual(result["center"][0], 100.0)
        self.assertAlmostEqual(result["center"][1], 200.0)
        self.assertEqual(result["rejected_axes"], [])

    def test_one_bad_axis_is_rejected(self):
        contacts = circular_contacts()
        contacts["N"] = (contacts["N"][0] + 0.30, contacts["N"][1])
        result = MODULE.evaluate_contact_centers(
            contacts, center_tolerance=0.03
        )
        self.assertEqual(result["rejected_axes"], ["N-S"])
        self.assertAlmostEqual(result["center"][0], 100.0, places=6)
        self.assertAlmostEqual(result["center"][1], 200.0, places=6)

    def test_two_bad_axes_continue_with_warning(self):
        contacts = circular_contacts()
        contacts["N"] = (contacts["N"][0] + 0.30, contacts["N"][1])
        contacts["E"] = (contacts["E"][0], contacts["E"][1] + 0.30)
        result = MODULE.evaluate_contact_centers(
            contacts, center_tolerance=0.03
        )
        self.assertTrue(result["degraded_quality"])
        self.assertEqual(len(result["rejected_axes"]), 1)

    def test_different_pair_diameter_does_not_affect_center_selection(self):
        contacts = circular_contacts()
        contacts["NE"] = (
            contacts["NE"][0] + math.sqrt(0.5) * 0.4,
            contacts["NE"][1] + math.sqrt(0.5) * 0.4,
        )
        result = MODULE.evaluate_contact_centers(
            contacts, center_tolerance=0.25
        )
        self.assertEqual(result["rejected_axes"], [])


class OffsetCalculationTests(unittest.TestCase):
    def test_hidden_macro_name_is_preferred_with_legacy_fallback(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)

        class Printer:
            objects = {"gcode_macro _DROP": object()}

            def lookup_object(self, name, default=None):
                return self.objects.get(name, default)

        instance.printer = Printer()
        self.assertEqual(instance._macro_name("DROP"), "_DROP")
        self.assertEqual(instance._macro_name("CLEAN"), "CLEAN")

    def test_first_repeated_xy_contact_is_discarded(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        instance.samples = 4
        instance.samples_result = "median"
        instance.samples_tolerance = 10.0
        instance.samples_tolerance_retries = 0
        instance.sample_retract_dist = 2.0
        instance.spread = 7.0
        instance.speed = 4.0
        instance.retract_speed = 50.0
        instance.verbose = False
        instance.current_tool = 0
        instance.current_direction = "0.0deg"
        points = iter(((10.0, 0.0, 5.0), (11.0, 0.0, 5.0),
                       (12.0, 0.0, 5.0), (13.0, 0.0, 5.0)))
        calls = []
        instance.endstops = type("Endstops", (), {"xy": object()})()
        instance._probe_to = lambda *args, **kwargs: (calls.append(1), next(points))[1]
        instance._move = lambda *args: None
        instance._wait_moves = lambda: None
        instance._contact_triggered = lambda: False

        result = instance._sample_contact(
            "0.0deg", 1.0, 0.0, (0.0, 0.0), 5.0,
            sample_count=4, position_start=False,
        )

        self.assertEqual(len(calls), 4)
        self.assertEqual(result, (12.0, 0.0))

    def test_single_rough_contact_is_not_discarded(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        instance.samples_result = "median"
        instance.samples_tolerance = 0.02
        instance.samples_tolerance_retries = 0
        instance.sample_retract_dist = 2.0
        instance.spread = 7.0
        instance.speed = 4.0
        instance.retract_speed = 50.0
        instance.verbose = False
        instance.current_tool = 0
        instance.current_direction = "rough_E"
        instance.endstops = type("Endstops", (), {"xy": object()})()
        instance._probe_to = lambda *args, **kwargs: (10.0, 0.0, 5.0)
        instance._move = lambda *args: None
        instance._wait_moves = lambda: None
        instance._contact_triggered = lambda: False

        result = instance._sample_contact(
            "E", 1.0, 0.0, (0.0, 0.0), 5.0,
            sample_count=1, position_start=False,
        )

        self.assertEqual(result, (10.0, 0.0))

    def test_circular_probe_uses_one_initial_lift_and_no_direction_lifts(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        instance.directions = 8
        instance.spread = 7.0
        instance.final_lift_z = 4.0
        instance.sample_retract_dist = 2.0
        instance.lift_speed = 4.0
        instance.transition_speed = 150.0
        instance.retract_speed = 50.0
        instance.center_tolerance = 0.02
        instance.current_tool = 0
        safe_calls = []
        moves = []
        instance._safe_above = lambda *args: safe_calls.append(args)
        instance._move = lambda position, speed: moves.append((position, speed))
        instance._wait_moves = lambda: None
        instance._contact_triggered = lambda: False

        def sample(name, vx, vy, center, side_z, sample_count=None,
                   position_start=True):
            self.assertFalse(position_start)
            return (center[0] + vx * 2.5, center[1] + vy * 2.5)

        instance._sample_contact = sample
        result = instance._probe_xy((100.0, 200.0), 10.0)

        self.assertEqual(len(safe_calls), 1)
        self.assertEqual(len(moves), 16)
        self.assertAlmostEqual(result["center"][0], 100.0)
        self.assertAlmostEqual(result["center"][1], 200.0)

    def test_preheat_starts_all_tools_before_waiting_for_t0(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        instance.calibration_temperature = 150.0
        instance.gcode = type("GCode", (), {"respond_info": lambda self, message: None})()
        commands = []
        instance._run = commands.append

        instance._preheat_tools([0, 1, 2], wait_tool=0)

        self.assertEqual(commands, [
            "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=150.000",
            "SET_HEATER_TEMPERATURE HEATER=extruder1 TARGET=150.000",
            "SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=150.000",
            "TEMPERATURE_WAIT SENSOR=extruder MINIMUM=150.000",
        ])

    def test_preheat_supports_selected_tools_and_wait_target(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        instance.calibration_temperature = 150.0
        instance.gcode = type("GCode", (), {"respond_info": lambda self, message: None})()
        commands = []
        instance._run = commands.append

        instance._preheat_tools([2, 4], wait_tool=2)

        self.assertEqual(commands, [
            "SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=150.000",
            "SET_HEATER_TEMPERATURE HEATER=extruder4 TARGET=150.000",
            "TEMPERATURE_WAIT SENSOR=extruder2 MINIMUM=150.000",
        ])

    def test_cooldown_disables_only_participating_tools(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        instance.gcode = type("GCode", (), {"respond_info": lambda self, message: None})()
        commands = []
        instance._run = commands.append

        instance._cooldown_tools([2, 4])

        self.assertEqual(commands, [
            "SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0",
            "SET_HEATER_TEMPERATURE HEATER=extruder4 TARGET=0",
        ])

    def test_offsets_are_relative_to_t0(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        measured = {
            0: {"position": [10.0, 20.0, 30.0]},
            1: {"position": [10.2, 19.9, 30.05]},
        }
        offsets = instance._offsets_from_measurements(measured)
        self.assertEqual(offsets[0], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(offsets[1][0], 0.2)
        self.assertAlmostEqual(offsets[1][1], -0.1)
        self.assertAlmostEqual(offsets[1][2], 0.05)

    def test_rough_center_uses_four_single_contacts(self):
        instance = object.__new__(MODULE.MedusaHCCalibrate)
        calls = []
        positions = {
            "E": (104.0, 200.0),
            "W": (96.0, 200.0),
            "N": (100.0, 204.0),
            "S": (100.0, 196.0),
        }

        def sample(name, vx, vy, center, side_z, sample_count=None):
            calls.append((name, sample_count))
            return positions[name]

        instance._sample_contact = sample
        center = instance._probe_xy_rough((99.0, 201.0), 10.0)
        self.assertEqual(center, (100.0, 200.0))
        self.assertEqual(
            calls, [("E", 1), ("W", 1), ("N", 1), ("S", 1)]
        )


if __name__ == "__main__":
    unittest.main()
