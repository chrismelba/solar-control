"""Tests for device.py"""

import json
import os

import pytest

from device import Device


def make_device(**overrides):
    """Create a minimal valid Device, optionally overriding fields."""
    defaults = {
        "name": "Test Device",
        "switch_entity": "switch.test",
        "typical_power_draw": 1000.0,
    }
    defaults.update(overrides)
    return Device(**defaults)


def make_device_dict(**overrides):
    """Return a minimal device dict, optionally overriding fields."""
    defaults = {
        "name": "Test Device",
        "switch_entity": "switch.test",
        "typical_power_draw": 1000.0,
        "current_power_sensor": None,
        "energy_sensor": None,
        "power_delivery_sensor": None,
        "has_variable_amperage": False,
        "min_amperage": None,
        "max_amperage": None,
        "variable_amperage_control": None,
        "min_on_time": 60,
        "min_off_time": 60,
        "run_once": False,
        "completion_sensor": None,
        "order": 0,
        "energy_delivered_today": 0.0,
        "min_daily_power": None,
    }
    defaults.update(overrides)
    return defaults


class TestDeviceSafeConvert:
    def test_converts_float(self):
        assert Device._safe_convert("3.14", float) == 3.14

    def test_converts_int(self):
        assert Device._safe_convert("42", int) == 42

    def test_none_returns_none(self):
        assert Device._safe_convert(None, float) is None

    def test_empty_string_returns_none(self):
        assert Device._safe_convert("", float) is None

    def test_invalid_string_returns_none(self):
        assert Device._safe_convert("abc", float) is None

    def test_zero_is_valid(self):
        assert Device._safe_convert("0", float) == 0.0
        assert Device._safe_convert(0, int) == 0


class TestDeviceInit:
    def test_required_fields(self):
        d = make_device()
        assert d.name == "Test Device"
        assert d.switch_entity == "switch.test"
        assert d.typical_power_draw == 1000.0

    def test_defaults(self):
        d = make_device()
        assert d.has_variable_amperage is False
        assert d.min_amperage is None
        assert d.max_amperage is None
        assert d.min_on_time == 60
        assert d.min_off_time == 60
        assert d.run_once is False
        assert d.order == 0
        assert d.energy_delivered_today == 0.0
        assert d.min_daily_power is None

    def test_variable_amperage_device(self):
        d = make_device(
            has_variable_amperage=True,
            min_amperage=6.0,
            max_amperage=32.0,
            variable_amperage_control="number.ev_charger_amps",
        )
        assert d.has_variable_amperage is True
        assert d.min_amperage == 6.0
        assert d.max_amperage == 32.0


class TestDeviceToDict:
    def test_contains_all_fields(self):
        d = make_device()
        result = d.to_dict()
        expected_keys = {
            "name", "switch_entity", "typical_power_draw", "current_power_sensor",
            "energy_sensor", "power_delivery_sensor", "has_variable_amperage",
            "min_amperage", "max_amperage", "variable_amperage_control",
            "min_on_time", "min_off_time", "run_once", "completion_sensor",
            "order", "energy_delivered_today", "min_daily_power",
        }
        assert set(result.keys()) == expected_keys

    def test_values_match(self):
        d = make_device(typical_power_draw=500.0, min_on_time=120, order=3)
        result = d.to_dict()
        assert result["typical_power_draw"] == 500.0
        assert result["min_on_time"] == 120
        assert result["order"] == 3


class TestDeviceFromDict:
    def test_basic_round_trip(self):
        data = make_device_dict()
        device = Device.from_dict(data)
        assert device.name == "Test Device"
        assert device.typical_power_draw == 1000.0

    def test_numeric_conversion_from_strings(self):
        data = make_device_dict(
            typical_power_draw="2000",
            min_amperage="6",
            max_amperage="32.5",
            min_on_time="90",
            min_off_time="30",
            order="2",
            energy_delivered_today="1.5",
            min_daily_power="500",
        )
        device = Device.from_dict(data)
        assert device.typical_power_draw == 2000.0
        assert device.min_amperage == 6.0
        assert device.max_amperage == 32.5
        assert device.min_on_time == 90
        assert device.min_off_time == 30
        assert device.order == 2
        assert device.energy_delivered_today == 1.5
        assert device.min_daily_power == 500.0

    def test_legacy_fields_are_stripped(self):
        data = make_device_dict()
        data["last_power_update"] = "2024-01-01T00:00:00"
        data["last_dawn_reset"] = "2024-01-01T06:00:00"
        # Should not raise; legacy fields are silently removed
        device = Device.from_dict(data)
        assert device.name == "Test Device"

    def test_none_numeric_fields_remain_none(self):
        data = make_device_dict(min_amperage=None, min_daily_power=None)
        device = Device.from_dict(data)
        assert device.min_amperage is None
        assert device.min_daily_power is None

    def test_full_round_trip_via_to_dict(self):
        original = Device(
            name="My Device",
            switch_entity="switch.my_device",
            typical_power_draw=1500.0,
            has_variable_amperage=True,
            min_amperage=6.0,
            max_amperage=16.0,
            variable_amperage_control="number.charger",
            min_on_time=300,
            min_off_time=60,
            run_once=True,
            completion_sensor="binary_sensor.done",
            order=2,
            energy_delivered_today=3.5,
            min_daily_power=1000.0,
        )
        restored = Device.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.typical_power_draw == original.typical_power_draw
        assert restored.has_variable_amperage == original.has_variable_amperage
        assert restored.min_amperage == original.min_amperage
        assert restored.max_amperage == original.max_amperage
        assert restored.min_on_time == original.min_on_time
        assert restored.run_once == original.run_once
        assert restored.energy_delivered_today == original.energy_delivered_today
        assert restored.min_daily_power == original.min_daily_power


class TestDeviceFileOperations:
    def _devices_file(self, tmp_path):
        return str(tmp_path / "data" / "devices.json")

    def test_save_all_and_load_all(self, tmp_path):
        devices_file = self._devices_file(tmp_path)
        devices = [
            make_device(name="Device A", typical_power_draw=500.0),
            make_device(name="Device B", typical_power_draw=1500.0),
        ]
        Device.save_all(devices, devices_file)

        loaded = Device.load_all(devices_file)
        assert len(loaded) == 2
        names = {d.name for d in loaded}
        assert names == {"Device A", "Device B"}

    def test_load_all_returns_empty_when_file_missing(self, tmp_path):
        result = Device.load_all(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_save_adds_new_device(self, tmp_path):
        devices_file = self._devices_file(tmp_path)
        d = make_device(name="New Device")
        d.save(devices_file)

        loaded = Device.load_all(devices_file)
        assert len(loaded) == 1
        assert loaded[0].name == "New Device"

    def test_save_updates_existing_device(self, tmp_path):
        devices_file = self._devices_file(tmp_path)
        d = make_device(name="My Device", typical_power_draw=1000.0)
        d.save(devices_file)

        d.typical_power_draw = 2000.0
        d.save(devices_file)

        loaded = Device.load_all(devices_file)
        assert len(loaded) == 1
        assert loaded[0].typical_power_draw == 2000.0

    def test_delete_removes_device(self, tmp_path):
        devices_file = self._devices_file(tmp_path)
        devices = [
            make_device(name="Keep Me"),
            make_device(name="Delete Me"),
        ]
        Device.save_all(devices, devices_file)

        Device.delete("Delete Me", devices_file)

        loaded = Device.load_all(devices_file)
        assert len(loaded) == 1
        assert loaded[0].name == "Keep Me"

    def test_delete_nonexistent_device_is_noop(self, tmp_path):
        devices_file = self._devices_file(tmp_path)
        Device.save_all([make_device(name="Only Device")], devices_file)

        Device.delete("Ghost Device", devices_file)

        loaded = Device.load_all(devices_file)
        assert len(loaded) == 1
