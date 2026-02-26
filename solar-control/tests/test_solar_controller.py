"""Tests for solar_controller.py"""

import json
import os
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from solar_controller import SolarController, DeviceState, DebugState
from device import Device
from battery import Battery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_controller(tmp_path, config=None, devices=None):
    """Return a SolarController backed by temp config/devices files."""
    config_file = str(tmp_path / "solar_config.json")
    devices_file = str(tmp_path / "devices.json")

    with open(config_file, "w") as f:
        json.dump(config or {}, f)

    with open(devices_file, "w") as f:
        json.dump(devices or [], f)

    return SolarController(config_file=config_file, devices_file=devices_file)


def make_device(
    name="Test Device",
    switch_entity="switch.test",
    typical_power_draw=1000.0,
    **kwargs,
):
    return Device(
        name=name,
        switch_entity=switch_entity,
        typical_power_draw=typical_power_draw,
        **kwargs,
    )


def make_mock_response(state, attributes=None, status_code=200):
    """Create a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {"state": state, "attributes": attributes or {}}
    mock.raise_for_status = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# DebugState
# ---------------------------------------------------------------------------

class TestDebugState:
    def test_to_dict_contains_expected_keys(self):
        now = datetime.now(timezone.utc)
        ds = DebugState(
            timestamp=now,
            available_power=500.0,
            grid_voltage=230.0,
            grid_power=-200.0,
        )
        d = ds.to_dict()
        assert d["available_power"] == 500.0
        assert d["grid_voltage"] == 230.0
        assert d["grid_power"] == -200.0
        assert d["timestamp"] == now.isoformat()
        assert d["mandatory_devices"] == []
        assert d["optional_devices"] == []
        assert d["power_optimization_enabled"] is True
        assert d["manual_power_override"] is None

    def test_to_dict_with_optional_fields(self):
        now = datetime.now(timezone.utc)
        ds = DebugState(
            timestamp=now,
            available_power=1000.0,
            grid_voltage=230.0,
            grid_power=0.0,
            solar_forecast_remaining=5.0,
            expected_energy_remaining=3.0,
            hours_until_sunset=4.5,
            bring_forward_power=800.0,
        )
        d = ds.to_dict()
        assert d["solar_forecast_remaining"] == 5.0
        assert d["expected_energy_remaining"] == 3.0
        assert d["hours_until_sunset"] == 4.5
        assert d["bring_forward_power"] == 800.0


# ---------------------------------------------------------------------------
# SolarController.calculate_optimal_amperage
# ---------------------------------------------------------------------------

class TestCalculateOptimalAmperage:
    def test_returns_none_for_non_variable_device(self, tmp_path):
        ctrl = make_controller(tmp_path)
        device = make_device(has_variable_amperage=False)
        assert ctrl.calculate_optimal_amperage(device, 5000.0) is None

    def test_clamps_to_min_amperage(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch.object(ctrl, "get_grid_voltage", return_value=230.0):
            device = make_device(
                has_variable_amperage=True,
                min_amperage=6.0,
                max_amperage=32.0,
            )
            # Available power only supports 3A but min is 6A → result is 6A
            result = ctrl.calculate_optimal_amperage(device, 230.0 * 3)
            assert result == 6

    def test_clamps_to_max_amperage(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch.object(ctrl, "get_grid_voltage", return_value=230.0):
            device = make_device(
                has_variable_amperage=True,
                min_amperage=6.0,
                max_amperage=16.0,
            )
            # Available power would support 40A but max is 16A → result is 16A
            result = ctrl.calculate_optimal_amperage(device, 230.0 * 40)
            assert result == 16

    def test_floors_to_whole_number(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch.object(ctrl, "get_grid_voltage", return_value=230.0):
            device = make_device(
                has_variable_amperage=True,
                min_amperage=6.0,
                max_amperage=32.0,
            )
            # 2990W / 230V = 13.0 → floor → 13A
            result = ctrl.calculate_optimal_amperage(device, 2990.0)
            assert result == 13

    def test_mid_range_amperage(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch.object(ctrl, "get_grid_voltage", return_value=230.0):
            device = make_device(
                has_variable_amperage=True,
                min_amperage=6.0,
                max_amperage=32.0,
            )
            # 2300W / 230V = 10A exactly
            result = ctrl.calculate_optimal_amperage(device, 2300.0)
            assert result == 10


# ---------------------------------------------------------------------------
# SolarController.get_device_power
# ---------------------------------------------------------------------------

class TestGetDevicePower:
    def test_returns_zero_when_device_is_off(self, tmp_path):
        ctrl = make_controller(tmp_path)
        device = make_device()
        ds = DeviceState(device=device, is_on=False)
        assert ctrl.get_device_power(ds) == 0.0

    def test_uses_typical_power_draw_as_fallback(self, tmp_path):
        ctrl = make_controller(tmp_path)
        device = make_device(typical_power_draw=800.0)
        ds = DeviceState(device=device, is_on=True)
        assert ctrl.get_device_power(ds) == 800.0

    def test_reads_from_power_sensor(self, tmp_path):
        ctrl = make_controller(tmp_path)
        device = make_device(
            typical_power_draw=1000.0,
            current_power_sensor="sensor.power",
        )
        ds = DeviceState(device=device, is_on=True)
        mock_resp = make_mock_response("650", {"unit_of_measurement": "W"})
        with patch("requests.get", return_value=mock_resp):
            power = ctrl.get_device_power(ds)
        assert power == 650.0

    def test_converts_kw_sensor_to_watts(self, tmp_path):
        ctrl = make_controller(tmp_path)
        device = make_device(
            typical_power_draw=1000.0,
            current_power_sensor="sensor.power_kw",
        )
        ds = DeviceState(device=device, is_on=True)
        mock_resp = make_mock_response("1.5", {"unit_of_measurement": "kW"})
        with patch("requests.get", return_value=mock_resp):
            power = ctrl.get_device_power(ds)
        assert power == 1500.0

    def test_uses_amperage_when_variable_and_no_sensor(self, tmp_path):
        ctrl = make_controller(tmp_path)
        device = make_device(
            has_variable_amperage=True,
            min_amperage=6.0,
            max_amperage=32.0,
        )
        ds = DeviceState(device=device, is_on=True, current_amperage=10.0)
        with patch.object(ctrl, "get_grid_voltage", return_value=230.0):
            power = ctrl.get_device_power(ds)
        assert power == pytest.approx(2300.0)

    def test_falls_back_to_typical_power_when_sensor_fails(self, tmp_path):
        ctrl = make_controller(tmp_path)
        device = make_device(
            typical_power_draw=750.0,
            current_power_sensor="sensor.broken",
        )
        ds = DeviceState(device=device, is_on=True)
        with patch("requests.get", side_effect=Exception("network error")):
            power = ctrl.get_device_power(ds)
        assert power == 750.0


# ---------------------------------------------------------------------------
# SolarController.get_available_power
# ---------------------------------------------------------------------------

class TestGetAvailablePower:
    def test_returns_manual_override_when_set(self, tmp_path):
        ctrl = make_controller(tmp_path, config={"grid_power": "sensor.grid"})
        ctrl.set_manual_power_override(999.0)
        power = ctrl.get_available_power()
        assert power == 999.0

    def test_returns_zero_when_no_grid_power_configured(self, tmp_path):
        ctrl = make_controller(tmp_path, config={})
        assert ctrl.get_available_power() == 0.0

    def test_returns_infinity_in_free_tariff_mode(self, tmp_path):
        ctrl = make_controller(tmp_path, config={"grid_power": "sensor.grid"})
        with patch.object(ctrl, "get_current_tariff_mode", return_value="free"):
            power = ctrl.get_available_power()
        assert power == float("inf")

    def test_exporting_to_grid_gives_positive_available_power(self, tmp_path):
        """When grid_power is negative (exporting), available_power should be positive."""
        ctrl = make_controller(tmp_path, config={"grid_power": "sensor.grid"})
        # Grid power = -1000W (exporting 1000W)
        mock_resp = make_mock_response("-1000", {"unit_of_measurement": "W"})
        with patch("requests.get", return_value=mock_resp):
            with patch.object(ctrl, "get_current_tariff_mode", return_value="normal"):
                power = ctrl.get_available_power()
        assert power == pytest.approx(1000.0)

    def test_importing_from_grid_gives_zero_available_power(self, tmp_path):
        """When grid_power is positive (importing), available_power should clamp to 0."""
        ctrl = make_controller(tmp_path, config={"grid_power": "sensor.grid"})
        mock_resp = make_mock_response("500", {"unit_of_measurement": "W"})
        with patch("requests.get", return_value=mock_resp):
            with patch.object(ctrl, "get_current_tariff_mode", return_value="normal"):
                power = ctrl.get_available_power()
        assert power == 0.0

    def test_converts_kw_to_watts(self, tmp_path):
        ctrl = make_controller(tmp_path, config={"grid_power": "sensor.grid_kw"})
        mock_resp = make_mock_response("-2.0", {"unit_of_measurement": "kW"})
        with patch("requests.get", return_value=mock_resp):
            with patch.object(ctrl, "get_current_tariff_mode", return_value="normal"):
                power = ctrl.get_available_power()
        assert power == pytest.approx(2000.0)

    def test_returns_zero_on_request_exception(self, tmp_path):
        ctrl = make_controller(tmp_path, config={"grid_power": "sensor.grid"})
        with patch("requests.get", side_effect=Exception("timeout")):
            with patch.object(ctrl, "get_current_tariff_mode", return_value="normal"):
                power = ctrl.get_available_power()
        assert power == 0.0

    def test_controlled_device_power_adds_back(self, tmp_path):
        """Power consumed by a controlled device is added back to available power."""
        ctrl = make_controller(tmp_path, config={"grid_power": "sensor.grid"})
        # Simulate a device consuming 500W - grid reads -500W (net export)
        # but we're actually importing 0W since our device is using the solar
        device = make_device(typical_power_draw=500.0)
        ds = DeviceState(device=device, is_on=True)
        ctrl.device_states["Test Device"] = ds

        # Grid reports 0W (balanced), but device is on consuming 500W of solar
        mock_resp = make_mock_response("0", {"unit_of_measurement": "W"})
        with patch("requests.get", return_value=mock_resp):
            with patch.object(ctrl, "get_current_tariff_mode", return_value="normal"):
                power = ctrl.get_available_power()
        # available = -grid_power + controlled_power = 0 + 500 = 500
        assert power == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# SolarController.get_hours_until_sunset
# ---------------------------------------------------------------------------

class TestGetHoursUntilSunset:
    def test_returns_none_when_sunset_unavailable(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch.object(ctrl, "get_sunset_time", return_value=None):
            assert ctrl.get_hours_until_sunset() is None

    def test_returns_positive_hours(self, tmp_path):
        ctrl = make_controller(tmp_path)
        future_sunset = datetime.now(timezone.utc) + timedelta(hours=3)
        with patch.object(ctrl, "get_sunset_time", return_value=future_sunset):
            hours = ctrl.get_hours_until_sunset()
        assert hours == pytest.approx(3.0, abs=0.1)

    def test_clamps_to_zero_after_sunset(self, tmp_path):
        ctrl = make_controller(tmp_path)
        past_sunset = datetime.now(timezone.utc) - timedelta(hours=1)
        with patch.object(ctrl, "get_sunset_time", return_value=past_sunset):
            hours = ctrl.get_hours_until_sunset()
        assert hours == 0.0


# ---------------------------------------------------------------------------
# SolarController.get_battery_charging_requirement
# ---------------------------------------------------------------------------

class TestGetBatteryChargingRequirement:
    def test_returns_none_when_no_battery(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch("battery.Battery.load", return_value=None):
            result = ctrl.get_battery_charging_requirement()
        assert result is None

    def test_calculates_energy_needed(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(
            size_kwh=10.0,
            battery_percent_entity="sensor.batt_pct",
        )
        mock_resp = make_mock_response("80")  # 80% charged
        with patch("requests.get", return_value=mock_resp):
            result = ctrl.get_battery_charging_requirement(battery=battery)
        # 10kWh * (100 - 80) / 100 = 2kWh needed
        assert result == pytest.approx(2.0)

    def test_zero_needed_when_fully_charged(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(size_kwh=10.0, battery_percent_entity="sensor.batt_pct")
        mock_resp = make_mock_response("100")
        with patch("requests.get", return_value=mock_resp):
            result = ctrl.get_battery_charging_requirement(battery=battery)
        assert result == pytest.approx(0.0)

    def test_returns_none_on_request_error(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(size_kwh=10.0, battery_percent_entity="sensor.batt_pct")
        with patch("requests.get", side_effect=Exception("timeout")):
            result = ctrl.get_battery_charging_requirement(battery=battery)
        assert result is None


# ---------------------------------------------------------------------------
# SolarController.is_battery_full_enough
# ---------------------------------------------------------------------------

class TestIsBatteryFullEnough:
    def test_returns_true_when_no_battery(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch("battery.Battery.load", return_value=None):
            assert ctrl.is_battery_full_enough() is True

    def test_above_95_percent_is_full_enough(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(size_kwh=10.0, battery_percent_entity="sensor.batt_pct")
        mock_resp = make_mock_response("96")
        with patch("requests.get", return_value=mock_resp):
            assert ctrl.is_battery_full_enough(battery=battery) is True

    def test_below_95_percent_is_not_full_enough(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(size_kwh=10.0, battery_percent_entity="sensor.batt_pct")
        mock_resp = make_mock_response("90")
        with patch("requests.get", return_value=mock_resp):
            assert ctrl.is_battery_full_enough(battery=battery) is False

    def test_exactly_95_is_not_full_enough(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(size_kwh=10.0, battery_percent_entity="sensor.batt_pct")
        mock_resp = make_mock_response("95")
        with patch("requests.get", return_value=mock_resp):
            # > 95 required, so exactly 95 should be False
            assert ctrl.is_battery_full_enough(battery=battery) is False

    def test_returns_true_on_request_error(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(size_kwh=10.0, battery_percent_entity="sensor.batt_pct")
        with patch("requests.get", side_effect=Exception("network error")):
            assert ctrl.is_battery_full_enough(battery=battery) is True


# ---------------------------------------------------------------------------
# SolarController.get_expected_energy_remaining
# ---------------------------------------------------------------------------

class TestGetExpectedEnergyRemaining:
    def test_returns_none_when_no_forecast(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch.object(ctrl, "get_solar_forecast_remaining", return_value=None):
            result = ctrl.get_expected_energy_remaining()
        assert result is None

    def test_returns_full_forecast_when_no_battery(self, tmp_path):
        ctrl = make_controller(tmp_path)
        with patch.object(ctrl, "get_solar_forecast_remaining", return_value=8.0):
            with patch("battery.Battery.load", return_value=None):
                result = ctrl.get_expected_energy_remaining()
        assert result == pytest.approx(8.0)

    def test_returns_full_forecast_when_battery_has_no_kwh_per_hour(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(
            size_kwh=10.0,
            battery_percent_entity="sensor.batt_pct",
            expected_kwh_per_hour=None,
        )
        with patch.object(ctrl, "get_solar_forecast_remaining", return_value=6.0):
            result = ctrl.get_expected_energy_remaining(battery=battery)
        assert result == pytest.approx(6.0)

    def test_subtracts_house_and_battery_load(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(
            size_kwh=10.0,
            battery_percent_entity="sensor.batt_pct",
            expected_kwh_per_hour=1.0,
        )
        with patch.object(ctrl, "get_solar_forecast_remaining", return_value=10.0):
            with patch.object(ctrl, "get_hours_until_sunset", return_value=4.0):
                with patch.object(ctrl, "get_battery_charging_requirement", return_value=2.0):
                    result = ctrl.get_expected_energy_remaining(battery=battery)
        # house = 1.0 * 4 = 4kWh, battery = 2kWh, total = 6kWh
        # net = 10 - 6 = 4kWh
        assert result == pytest.approx(4.0)

    def test_clamps_to_zero_when_energy_deficit(self, tmp_path):
        ctrl = make_controller(tmp_path)
        battery = Battery(
            size_kwh=20.0,
            battery_percent_entity="sensor.batt_pct",
            expected_kwh_per_hour=2.0,
        )
        with patch.object(ctrl, "get_solar_forecast_remaining", return_value=3.0):
            with patch.object(ctrl, "get_hours_until_sunset", return_value=10.0):
                with patch.object(ctrl, "get_battery_charging_requirement", return_value=5.0):
                    result = ctrl.get_expected_energy_remaining(battery=battery)
        # house = 2.0 * 10 = 20kWh, battery = 5kWh → deficit of 22kWh vs 3kWh forecast
        assert result == 0.0


# ---------------------------------------------------------------------------
# SolarController.get_current_tariff_mode
# ---------------------------------------------------------------------------

class TestGetCurrentTariffMode:
    def test_defaults_to_normal_when_not_configured(self, tmp_path):
        ctrl = make_controller(tmp_path, config={})
        result = ctrl.get_current_tariff_mode()
        assert result == "normal"

    def test_maps_tariff_value_to_mode(self, tmp_path):
        config = {
            "tariff_rate": "sensor.tariff",
            "tariff_modes": {"peak": "normal", "offpeak": "cheap", "free": "free"},
        }
        ctrl = make_controller(tmp_path, config=config)
        mock_resp = make_mock_response("offpeak")
        with patch("requests.get", return_value=mock_resp):
            result = ctrl.get_current_tariff_mode()
        assert result == "cheap"

    def test_defaults_to_normal_for_unknown_tariff(self, tmp_path):
        config = {
            "tariff_rate": "sensor.tariff",
            "tariff_modes": {"peak": "normal"},
        }
        ctrl = make_controller(tmp_path, config=config)
        mock_resp = make_mock_response("unknown_tariff")
        with patch("requests.get", return_value=mock_resp):
            result = ctrl.get_current_tariff_mode()
        assert result == "normal"

    def test_defaults_to_normal_on_request_error(self, tmp_path):
        config = {"tariff_rate": "sensor.tariff"}
        ctrl = make_controller(tmp_path, config=config)
        with patch("requests.get", side_effect=Exception("timeout")):
            result = ctrl.get_current_tariff_mode()
        assert result == "normal"
