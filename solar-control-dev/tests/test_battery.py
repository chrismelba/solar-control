"""Tests for battery.py"""

import json
import os

import pytest

from battery import Battery


class TestBatteryInit:
    def test_required_fields(self):
        b = Battery(size_kwh=10.0, battery_percent_entity="sensor.battery")
        assert b.size_kwh == 10.0
        assert b.battery_percent_entity == "sensor.battery"

    def test_optional_fields_default_to_none_or_false(self):
        b = Battery(size_kwh=5.0, battery_percent_entity="sensor.batt")
        assert b.max_charging_speed_kw is None
        assert b.expected_kwh_per_hour is None
        assert b.bring_forward_mode is False

    def test_all_fields(self):
        b = Battery(
            size_kwh=13.5,
            battery_percent_entity="sensor.batt_pct",
            max_charging_speed_kw=5.0,
            expected_kwh_per_hour=0.5,
            bring_forward_mode=True,
        )
        assert b.size_kwh == 13.5
        assert b.max_charging_speed_kw == 5.0
        assert b.expected_kwh_per_hour == 0.5
        assert b.bring_forward_mode is True


class TestBatteryToDict:
    def test_round_trip(self):
        b = Battery(
            size_kwh=13.5,
            battery_percent_entity="sensor.batt_pct",
            max_charging_speed_kw=5.0,
            expected_kwh_per_hour=0.4,
            bring_forward_mode=True,
        )
        d = b.to_dict()
        assert d == {
            "size_kwh": 13.5,
            "battery_percent_entity": "sensor.batt_pct",
            "max_charging_speed_kw": 5.0,
            "expected_kwh_per_hour": 0.4,
            "bring_forward_mode": True,
        }

    def test_none_values_preserved(self):
        b = Battery(size_kwh=5.0, battery_percent_entity="sensor.b")
        d = b.to_dict()
        assert d["max_charging_speed_kw"] is None
        assert d["expected_kwh_per_hour"] is None


class TestBatteryFromDict:
    def test_full_dict(self):
        data = {
            "size_kwh": 10.0,
            "battery_percent_entity": "sensor.b",
            "max_charging_speed_kw": 3.0,
            "expected_kwh_per_hour": 0.3,
            "bring_forward_mode": True,
        }
        b = Battery.from_dict(data)
        assert b.size_kwh == 10.0
        assert b.battery_percent_entity == "sensor.b"
        assert b.max_charging_speed_kw == 3.0
        assert b.expected_kwh_per_hour == 0.3
        assert b.bring_forward_mode is True

    def test_missing_optional_fields_use_defaults(self):
        data = {
            "size_kwh": 10.0,
            "battery_percent_entity": "sensor.b",
        }
        b = Battery.from_dict(data)
        assert b.max_charging_speed_kw is None
        assert b.expected_kwh_per_hour is None
        assert b.bring_forward_mode is False

    def test_serialization_round_trip(self):
        original = Battery(
            size_kwh=7.2,
            battery_percent_entity="sensor.bat",
            max_charging_speed_kw=2.5,
            expected_kwh_per_hour=0.6,
            bring_forward_mode=False,
        )
        restored = Battery.from_dict(original.to_dict())
        assert restored.size_kwh == original.size_kwh
        assert restored.battery_percent_entity == original.battery_percent_entity
        assert restored.max_charging_speed_kw == original.max_charging_speed_kw
        assert restored.expected_kwh_per_hour == original.expected_kwh_per_hour
        assert restored.bring_forward_mode == original.bring_forward_mode


class TestBatteryLoadSave:
    def test_save_creates_file(self, tmp_path):
        b = Battery(size_kwh=10.0, battery_percent_entity="sensor.b")
        file_path = str(tmp_path / "battery.json")
        result = b.save(file_path)
        assert result is True
        assert os.path.exists(file_path)

    def test_save_and_load_round_trip(self, tmp_path):
        b = Battery(
            size_kwh=13.5,
            battery_percent_entity="sensor.batt_pct",
            max_charging_speed_kw=5.0,
            expected_kwh_per_hour=0.4,
            bring_forward_mode=True,
        )
        file_path = str(tmp_path / "battery.json")
        b.save(file_path)

        loaded = Battery.load(file_path)
        assert loaded is not None
        assert loaded.size_kwh == b.size_kwh
        assert loaded.battery_percent_entity == b.battery_percent_entity
        assert loaded.max_charging_speed_kw == b.max_charging_speed_kw
        assert loaded.expected_kwh_per_hour == b.expected_kwh_per_hour
        assert loaded.bring_forward_mode == b.bring_forward_mode

    def test_load_returns_none_when_file_missing(self, tmp_path):
        result = Battery.load(str(tmp_path / "does_not_exist.json"))
        assert result is None

    def test_load_returns_none_on_invalid_json(self, tmp_path):
        bad_file = tmp_path / "battery.json"
        bad_file.write_text("not valid json {{{")
        result = Battery.load(str(bad_file))
        assert result is None

    def test_save_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "a" / "b" / "battery.json"
        b = Battery(size_kwh=5.0, battery_percent_entity="sensor.b")
        result = b.save(str(nested))
        assert result is True
        assert nested.exists()
