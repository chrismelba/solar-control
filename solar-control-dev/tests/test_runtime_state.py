"""Tests for runtime state (de)serialization."""

from device import Device
from solar_controller import DeviceState
from runtime_state import serialize_runtime_state, apply_runtime_state


def make_state(**kwargs):
    device = Device(name=kwargs.pop("name", "Dev"), switch_entity="switch.dev",
                    typical_power_draw=1000.0)
    return DeviceState(device=device, **kwargs)


class TestSerialize:
    def test_defaults_produce_empty_state(self):
        states = {"Dev": make_state()}
        assert serialize_runtime_state(states) == {}

    def test_non_defaults_are_stored(self):
        states = {
            "Car": make_state(name="Car", road_trip=True,
                              one_off_charge_target=10.0,
                              one_off_charge_start_energy=2.5),
            "HWS": make_state(name="HWS", auto_control=False),
        }
        result = serialize_runtime_state(states)
        assert result == {
            "Car": {"one_off_charge_target": 10.0,
                    "one_off_charge_start_energy": 2.5,
                    "road_trip": True},
            "HWS": {"auto_control": False},
        }

    def test_auto_control_true_is_omitted(self):
        states = {"Dev": make_state(auto_control=True, road_trip=True)}
        assert "auto_control" not in serialize_runtime_state(states)["Dev"]


class TestApply:
    def test_round_trip(self):
        source = {
            "Car": make_state(name="Car", road_trip=True, auto_control=False,
                              one_off_charge_target=8.0,
                              one_off_charge_start_energy=1.0),
        }
        target = {"Car": make_state(name="Car")}
        apply_runtime_state(target, serialize_runtime_state(source))

        restored = target["Car"]
        assert restored.road_trip is True
        assert restored.auto_control is False
        assert restored.one_off_charge_target == 8.0
        assert restored.one_off_charge_start_energy == 1.0

    def test_unknown_devices_ignored(self):
        target = {"Dev": make_state()}
        apply_runtime_state(target, {"Ghost": {"road_trip": True}})
        assert target["Dev"].road_trip is False

    def test_missing_keys_leave_defaults(self):
        target = {"Dev": make_state()}
        apply_runtime_state(target, {"Dev": {}})
        assert target["Dev"].auto_control is True
        assert target["Dev"].road_trip is False
        assert target["Dev"].one_off_charge_target is None
