"""Tests for MQTT discovery of road trip switches."""

import json
from unittest.mock import MagicMock

import pytest

import mqtt_client
from mqtt_client import (
    slugify,
    sync_road_trip_discovery,
    publish_road_trip_state,
    set_road_trip_command_handler,
    sync_device_switch_discovery,
    sync_global_switch_discovery,
    publish_switch_state,
    set_switch_command_handler,
    on_message,
    SWITCH_KINDS,
    ROAD_TRIP_CONFIG_TOPIC,
    ROAD_TRIP_STATE_TOPIC,
    ROAD_TRIP_COMMAND_TOPIC,
)

AUTO_CONTROL_CONFIG_TOPIC = SWITCH_KINDS["auto_control"]["config_topic"]
AUTO_CONTROL_STATE_TOPIC = SWITCH_KINDS["auto_control"]["state_topic"]
AUTO_CONTROL_COMMAND_TOPIC = SWITCH_KINDS["auto_control"]["command_topic"]
OPTIMIZATION_CONFIG_TOPIC = SWITCH_KINDS["optimization"]["config_topic"]
OPTIMIZATION_STATE_TOPIC = SWITCH_KINDS["optimization"]["state_topic"]
OPTIMIZATION_COMMAND_TOPIC = SWITCH_KINDS["optimization"]["command_topic"]


@pytest.fixture(autouse=True)
def fake_broker(monkeypatch):
    """Replace the paho client with a mock and reset the discovery registry."""
    client = MagicMock()
    client.is_connected.return_value = True
    monkeypatch.setattr(mqtt_client, "mqtt_client", client)
    monkeypatch.setattr(mqtt_client, "_switch_registry", {})
    monkeypatch.setattr(mqtt_client, "_command_handlers", {})
    yield client


def published(client):
    """Return {topic: payload} of everything published to the mock broker."""
    return {call.args[0]: call.args[1] for call in client.publish.call_args_list}


def make_msg(topic, payload):
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload.encode()
    return msg


class TestSlugify:
    def test_lowercases_and_replaces_special_chars(self):
        assert slugify("My Car (EV)") == "my_car_ev"

    def test_plain_name_unchanged(self):
        assert slugify("car") == "car"


class TestSyncDiscovery:
    def test_publishes_config_and_state_for_car(self, fake_broker):
        sync_road_trip_discovery({"My Car": True}, sw_version="1.2.3")

        msgs = published(fake_broker)
        config = json.loads(msgs[ROAD_TRIP_CONFIG_TOPIC.format(slug="my_car")])
        assert config["unique_id"] == "solar_control_my_car_road_trip"
        assert config["command_topic"] == ROAD_TRIP_COMMAND_TOPIC.format(slug="my_car")
        assert config["state_topic"] == ROAD_TRIP_STATE_TOPIC.format(slug="my_car")
        assert config["availability_topic"] == "solar_control/status"
        assert config["device"]["sw_version"] == "1.2.3"
        assert msgs[ROAD_TRIP_STATE_TOPIC.format(slug="my_car")] == "ON"

    def test_config_and_state_are_retained(self, fake_broker):
        sync_road_trip_discovery({"My Car": False})
        for call in fake_broker.publish.call_args_list:
            assert call.kwargs.get("retain") is True

    def test_removed_car_gets_empty_retained_config(self, fake_broker):
        sync_road_trip_discovery({"My Car": False})
        fake_broker.publish.reset_mock()

        sync_road_trip_discovery({})

        msgs = published(fake_broker)
        assert msgs[ROAD_TRIP_CONFIG_TOPIC.format(slug="my_car")] == ""
        assert msgs[ROAD_TRIP_STATE_TOPIC.format(slug="my_car")] == ""
        assert "my_car" not in mqtt_client._switch_registry["road_trip"]


class TestPublishState:
    def test_publishes_on_off(self, fake_broker):
        sync_road_trip_discovery({"Car": False})
        fake_broker.publish.reset_mock()

        publish_road_trip_state("Car", True)
        assert published(fake_broker)[ROAD_TRIP_STATE_TOPIC.format(slug="car")] == "ON"

        publish_road_trip_state("Car", False)
        assert published(fake_broker)[ROAD_TRIP_STATE_TOPIC.format(slug="car")] == "OFF"

    def test_unregistered_device_is_ignored(self, fake_broker):
        publish_road_trip_state("Not A Car", True)
        fake_broker.publish.assert_not_called()

    def test_state_survives_registry_for_republish(self, fake_broker):
        sync_road_trip_discovery({"Car": False})
        publish_road_trip_state("Car", True)
        assert mqtt_client._switch_registry["road_trip"]["car"]["state"] is True


class TestCommandRouting:
    def test_on_command_calls_handler_with_device_name(self, fake_broker):
        sync_road_trip_discovery({"My Car": False})
        handler = MagicMock()
        set_road_trip_command_handler(handler)

        on_message(fake_broker, None,
                   make_msg(ROAD_TRIP_COMMAND_TOPIC.format(slug="my_car"), "ON"))
        handler.assert_called_once_with("My Car", True)

        handler.reset_mock()
        on_message(fake_broker, None,
                   make_msg(ROAD_TRIP_COMMAND_TOPIC.format(slug="my_car"), "OFF"))
        handler.assert_called_once_with("My Car", False)

    def test_unknown_slug_is_ignored(self, fake_broker):
        handler = MagicMock()
        set_road_trip_command_handler(handler)
        on_message(fake_broker, None,
                   make_msg(ROAD_TRIP_COMMAND_TOPIC.format(slug="ghost"), "ON"))
        handler.assert_not_called()

    def test_ha_birth_republishes_discovery(self, fake_broker):
        sync_road_trip_discovery({"Car": True})
        fake_broker.publish.reset_mock()

        on_message(fake_broker, None, make_msg("homeassistant/status", "online"))

        msgs = published(fake_broker)
        assert ROAD_TRIP_CONFIG_TOPIC.format(slug="car") in msgs
        assert msgs[ROAD_TRIP_STATE_TOPIC.format(slug="car")] == "ON"


class TestAutoControlDiscovery:
    def test_publishes_config_and_state_for_every_device(self, fake_broker):
        sync_device_switch_discovery("auto_control", {"HWS": True, "My Car": False})

        msgs = published(fake_broker)
        config = json.loads(msgs[AUTO_CONTROL_CONFIG_TOPIC.format(slug="hws")])
        assert config["unique_id"] == "solar_control_hws_auto_control"
        assert config["name"] == "HWS auto control"
        assert config["command_topic"] == AUTO_CONTROL_COMMAND_TOPIC.format(slug="hws")
        assert msgs[AUTO_CONTROL_STATE_TOPIC.format(slug="hws")] == "ON"
        assert msgs[AUTO_CONTROL_STATE_TOPIC.format(slug="my_car")] == "OFF"

    def test_removed_device_gets_empty_retained_config(self, fake_broker):
        sync_device_switch_discovery("auto_control", {"HWS": True})
        fake_broker.publish.reset_mock()

        sync_device_switch_discovery("auto_control", {})

        msgs = published(fake_broker)
        assert msgs[AUTO_CONTROL_CONFIG_TOPIC.format(slug="hws")] == ""
        assert msgs[AUTO_CONTROL_STATE_TOPIC.format(slug="hws")] == ""

    def test_command_routed_to_handler(self, fake_broker):
        sync_device_switch_discovery("auto_control", {"My Car": True})
        handler = MagicMock()
        set_switch_command_handler("auto_control", handler)

        on_message(fake_broker, None,
                   make_msg(AUTO_CONTROL_COMMAND_TOPIC.format(slug="my_car"), "OFF"))
        handler.assert_called_once_with("My Car", False)

    def test_kinds_are_independent(self, fake_broker):
        """A car has both switches; removing it from one kind keeps the other."""
        sync_device_switch_discovery("road_trip", {"My Car": True})
        sync_device_switch_discovery("auto_control", {"My Car": True})

        sync_device_switch_discovery("road_trip", {})

        assert "my_car" not in mqtt_client._switch_registry["road_trip"]
        assert "my_car" in mqtt_client._switch_registry["auto_control"]


class TestOptimizationDiscovery:
    def test_publishes_global_config_and_state(self, fake_broker):
        sync_global_switch_discovery("optimization", True, sw_version="9.9.9")

        msgs = published(fake_broker)
        config = json.loads(msgs[OPTIMIZATION_CONFIG_TOPIC])
        assert config["unique_id"] == "solar_control_optimization"
        assert config["name"] == "Power optimization"
        assert config["command_topic"] == OPTIMIZATION_COMMAND_TOPIC
        assert config["device"]["sw_version"] == "9.9.9"
        assert msgs[OPTIMIZATION_STATE_TOPIC] == "ON"

    def test_command_routed_with_none_device(self, fake_broker):
        sync_global_switch_discovery("optimization", True)
        handler = MagicMock()
        set_switch_command_handler("optimization", handler)

        on_message(fake_broker, None, make_msg(OPTIMIZATION_COMMAND_TOPIC, "OFF"))
        handler.assert_called_once_with(None, False)

    def test_state_publish(self, fake_broker):
        sync_global_switch_discovery("optimization", True)
        fake_broker.publish.reset_mock()

        publish_switch_state("optimization", None, False)
        assert published(fake_broker)[OPTIMIZATION_STATE_TOPIC] == "OFF"

    def test_republished_on_ha_birth(self, fake_broker):
        sync_global_switch_discovery("optimization", False)
        sync_device_switch_discovery("auto_control", {"HWS": True})
        fake_broker.publish.reset_mock()

        on_message(fake_broker, None, make_msg("homeassistant/status", "online"))

        msgs = published(fake_broker)
        assert OPTIMIZATION_CONFIG_TOPIC in msgs
        assert msgs[OPTIMIZATION_STATE_TOPIC] == "OFF"
        assert AUTO_CONTROL_CONFIG_TOPIC.format(slug="hws") in msgs


class TestAutoClearPublishesState:
    def test_refresh_car_states_clears_and_publishes(self, monkeypatch, fake_broker, tmp_path):
        from tests.test_solar_controller import make_controller, make_car_state

        controller = make_controller(tmp_path)
        device_state = make_car_state(soc=100.0, road_trip=True)
        controller.device_states = {device_state.device.name: device_state}
        monkeypatch.setattr(controller, "get_car_soc", lambda device: 100.0)

        sync_road_trip_discovery({device_state.device.name: True})
        fake_broker.publish.reset_mock()

        controller.refresh_car_states()

        assert device_state.road_trip is False
        slug = slugify(device_state.device.name)
        assert published(fake_broker)[ROAD_TRIP_STATE_TOPIC.format(slug=slug)] == "OFF"
