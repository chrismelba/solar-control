import logging
import re
import time
import paho.mqtt.client as mqtt
import json
import os
from threading import Thread, Timer
from datetime import datetime
from utils import set_mqtt_settings

# MQTT Topics
AVAILABILITY_TOPIC = "solar_control/status"
CONTROL_TOPIC = "solar_control/control"
STATE_TOPIC = "solar_control/state"
DEVICE_STATE_TOPIC = "solar_control/devices/{device_name}/state"
DEVICE_CONTROL_TOPIC = "solar_control/devices/{device_name}/control"

# Home Assistant MQTT discovery
DISCOVERY_PREFIX = "homeassistant"
HA_STATUS_TOPIC = "homeassistant/status"  # HA publishes online/offline here

# Discoverable switch kinds. per_device kinds get one switch per registered
# device (topics contain the device slug); global kinds get exactly one switch.
SWITCH_KINDS = {
    "road_trip": {
        "config_topic": DISCOVERY_PREFIX + "/switch/solar_control/{slug}_road_trip/config",
        "state_topic": "solar_control/devices/{slug}/road_trip/state",
        "command_topic": "solar_control/devices/{slug}/road_trip/set",
        "name": "{name} road trip",
        "icon": "mdi:bag-suitcase",
        "per_device": True,
    },
    "auto_control": {
        "config_topic": DISCOVERY_PREFIX + "/switch/solar_control/{slug}_auto_control/config",
        "state_topic": "solar_control/devices/{slug}/auto_control/state",
        "command_topic": "solar_control/devices/{slug}/auto_control/set",
        "name": "{name} auto control",
        "icon": "mdi:robot",
        "per_device": True,
    },
    "optimization": {
        "config_topic": DISCOVERY_PREFIX + "/switch/solar_control/optimization/config",
        "state_topic": "solar_control/optimization/state",
        "command_topic": "solar_control/optimization/set",
        "name": "Power optimization",
        "icon": "mdi:lightning-bolt",
        "per_device": False,
    },
}

# Back-compat aliases (older callers/tests import these directly)
ROAD_TRIP_CONFIG_TOPIC = SWITCH_KINDS["road_trip"]["config_topic"]
ROAD_TRIP_STATE_TOPIC = SWITCH_KINDS["road_trip"]["state_topic"]
ROAD_TRIP_COMMAND_TOPIC = SWITCH_KINDS["road_trip"]["command_topic"]

# Global variables
mqtt_client: mqtt.Client = None
subscribed_topics = []
device_states = {}
last_data_update = None

# Discovery registry: kind -> {slug: {"name": device name, "state": bool}}
# (global kinds use a single None slug). Kept so discovery can be republished
# on reconnect / HA restart, and so command topics (which carry the slug) can
# be mapped back to device names.
_switch_registry = {}
_command_handlers = {}  # kind -> callable(device_name_or_None, enabled: bool)
_sw_version = None


def slugify(name):
    """Turn a device name into a topic/unique_id-safe slug."""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')

def connect():
    """Establish MQTT connection with the broker"""
    global mqtt_client
    
    try:
        # Get MQTT settings
        mqtt_settings = set_mqtt_settings()
        if not mqtt_settings:
            logging.error("Failed to get MQTT settings")
            return False

        # Create client with unique ID
        client_id = "solar_control" if os.environ.get("IS_HA_ADDON") else f"solar_control_{os.getpid()}"
        if hasattr(mqtt, "CallbackAPIVersion"):
            # paho-mqtt >= 2.0 requires an explicit callback API version;
            # VERSION1 keeps the pre-2.0 callback signatures working
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id)
        else:
            client = mqtt.Client(client_id)

        # Set will message for availability (retained, so HA sees the correct
        # availability even if it restarts after this add-on died)
        client.will_set(AVAILABILITY_TOPIC, "offline", 0, True)

        # Set credentials if provided
        if mqtt_settings.get("username") and mqtt_settings.get("password"):
            client.username_pw_set(mqtt_settings["username"], mqtt_settings["password"])

        # Set port
        port = 1883
        if mqtt_settings.get("port"):
            try:
                conf_port = int(mqtt_settings["port"])
                if conf_port > 0:
                    port = conf_port
            except ValueError:
                logging.warning(f"Invalid port number: {mqtt_settings['port']}, using default 1883")

        # Connect to broker
        client.connect(mqtt_settings["broker"], port)
        
        # Set up callbacks
        client.on_message = on_message
        client.on_disconnect = on_disconnect
        client.on_connect = on_connect

        # Start the client loop
        client.loop_start()
        
        # Store client globally
        mqtt_client = client
        
        logging.info("MQTT client connected successfully")
        return True

    except Exception as e:
        logging.error(f"Failed to connect to MQTT broker: {e}")
        return False

def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the broker"""
    if rc == 0:
        logging.info("Connected to MQTT broker")
        # Publish online status
        publish_message(AVAILABILITY_TOPIC, "online", retain=True)
        
        # Subscribe to control topics
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(DEVICE_CONTROL_TOPIC.format(device_name="+"))
        for spec in SWITCH_KINDS.values():
            client.subscribe(spec["command_topic"].format(slug="+"))
        # HA publishes its birth message here; discovery must be republished
        # when HA restarts or it forgets our entities
        client.subscribe(HA_STATUS_TOPIC)

        # Republish discovery + states after a reconnect
        _publish_all_discovery()
    else:
        logging.error(f"Failed to connect to MQTT broker with code: {rc}")

def on_disconnect(client, userdata, rc):
    """Callback for when the client disconnects from the broker"""
    logging.warning(f"Disconnected from MQTT broker with code: {rc}")
    if rc != 0:
        logging.info("Attempting to reconnect...")
        try:
            client.reconnect()
        except Exception as e:
            logging.error(f"Failed to reconnect: {e}")

def on_message(client, userdata, msg):
    """Callback for when a message is received"""
    try:
        topic = msg.topic
        payload = msg.payload.decode()
        logging.debug(f"Received message on topic {topic}: {payload}")

        # Handle control messages
        if topic == CONTROL_TOPIC:
            handle_control_message(payload)
        elif topic == HA_STATUS_TOPIC:
            if payload == "online":
                logging.info("Home Assistant came online - republishing MQTT discovery")
                _publish_all_discovery()
        elif topic == SWITCH_KINDS["optimization"]["command_topic"]:
            _handle_switch_command("optimization", None, payload)
        elif topic.endswith("/road_trip/set"):
            _handle_switch_command("road_trip", topic.split("/")[2], payload)
        elif topic.endswith("/auto_control/set"):
            _handle_switch_command("auto_control", topic.split("/")[2], payload)
        elif topic.startswith("solar_control/devices/"):
            device_name = topic.split("/")[2]
            handle_device_control(device_name, payload)

    except Exception as e:
        logging.error(f"Error processing MQTT message: {e}")

def handle_control_message(payload):
    """Handle control messages for the main system"""
    try:
        data = json.loads(payload)
        command = data.get("command")
        
        if command == "run_control_loop":
            # Trigger control loop
            pass
        elif command == "update_status":
            # Force status update
            publish_status()
        else:
            logging.warning(f"Unknown control command: {command}")
            
    except json.JSONDecodeError:
        logging.error("Invalid JSON in control message")
    except Exception as e:
        logging.error(f"Error handling control message: {e}")

def handle_device_control(device_name, payload):
    """Handle control messages for specific devices"""
    try:
        data = json.loads(payload)
        command = data.get("command")
        
        if command == "turn_on":
            # Turn device on
            pass
        elif command == "turn_off":
            # Turn device off
            pass
        else:
            logging.warning(f"Unknown device command for {device_name}: {command}")
            
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON in device control message for {device_name}")
    except Exception as e:
        logging.error(f"Error handling device control for {device_name}: {e}")

def _handle_switch_command(kind, slug, payload):
    """Handle an ON/OFF command from a discovered switch."""
    entry = _switch_registry.get(kind, {}).get(slug)
    if entry is None:
        logging.warning(f"{kind} command for unknown device slug: {slug}")
        return
    handler = _command_handlers.get(kind)
    if handler is None:
        logging.warning(f"{kind} command received but no handler registered")
        return
    try:
        handler(entry["name"], payload.strip().upper() == "ON")
    except Exception as e:
        logging.error(f"Error handling {kind} command for {entry['name']}: {e}")


def set_switch_command_handler(kind, handler):
    """Register the callback invoked as handler(device_name_or_None, enabled)
    when a switch of this kind is flipped from Home Assistant."""
    _command_handlers[kind] = handler


def _device_info():
    info = {
        "identifiers": ["solar_control"],
        "name": "Solar Control",
        "manufacturer": "chrismelba",
        "model": "Solar Control Add-on",
    }
    if _sw_version:
        info["sw_version"] = _sw_version
    return info


def _publish_switch_config(kind, slug, device_name):
    spec = SWITCH_KINDS[kind]
    config = {
        "name": spec["name"].format(name=device_name),
        "unique_id": "solar_control_" + (f"{slug}_" if slug else "") + kind,
        "state_topic": spec["state_topic"].format(slug=slug),
        "command_topic": spec["command_topic"].format(slug=slug),
        "icon": spec["icon"],
        "availability_topic": AVAILABILITY_TOPIC,
        "device": _device_info(),
    }
    publish_message(spec["config_topic"].format(slug=slug), config, retain=True)


def _publish_switch_state_raw(kind, slug, enabled):
    publish_message(SWITCH_KINDS[kind]["state_topic"].format(slug=slug),
                    "ON" if enabled else "OFF", retain=True)


def _publish_all_discovery():
    """(Re)publish discovery configs and current states for every registered switch."""
    for kind, entries in _switch_registry.items():
        for slug, entry in entries.items():
            _publish_switch_config(kind, slug, entry["name"])
            _publish_switch_state_raw(kind, slug, entry["state"])


def publish_switch_state(kind, device_name, enabled):
    """Publish the current state of a discovered switch.

    device_name is None for global kinds. No-op if the switch isn't
    registered (e.g. discovery not synced yet)."""
    slug = slugify(device_name) if device_name else None
    entry = _switch_registry.get(kind, {}).get(slug)
    if entry is None:
        return
    entry["state"] = bool(enabled)
    _publish_switch_state_raw(kind, slug, enabled)


def sync_device_switch_discovery(kind, states, sw_version=None):
    """Reconcile discovered per-device switches of one kind with the device list.

    states: {device_name: enabled} for every device that should have this
    switch. Publishes discovery + state for new/updated devices and removes
    the retained discovery config for devices no longer in the dict.
    """
    global _sw_version
    if sw_version:
        _sw_version = sw_version

    spec = SWITCH_KINDS[kind]
    registry = _switch_registry.setdefault(kind, {})
    desired = {slugify(name): name for name in states}

    for slug in list(registry):
        if slug not in desired:
            del registry[slug]
            # Empty retained payload deletes the entity from HA
            publish_message(spec["config_topic"].format(slug=slug), "", retain=True)
            publish_message(spec["state_topic"].format(slug=slug), "", retain=True)

    for slug, name in desired.items():
        registry[slug] = {"name": name, "state": bool(states[name])}
        _publish_switch_config(kind, slug, name)
        _publish_switch_state_raw(kind, slug, registry[slug]["state"])


def sync_global_switch_discovery(kind, enabled, sw_version=None):
    """Register + publish a single global (non-per-device) switch."""
    global _sw_version
    if sw_version:
        _sw_version = sw_version
    _switch_registry.setdefault(kind, {})[None] = {"name": None, "state": bool(enabled)}
    _publish_switch_config(kind, None, None)
    _publish_switch_state_raw(kind, None, enabled)


# --- Back-compat wrappers (older callers/tests use the road-trip names) ---

def sync_road_trip_discovery(cars, sw_version=None):
    sync_device_switch_discovery("road_trip", cars, sw_version)


def publish_road_trip_state(device_name, enabled):
    publish_switch_state("road_trip", device_name, enabled)


def set_road_trip_command_handler(handler):
    set_switch_command_handler("road_trip", handler)


def publish_message(topic, payload, retain=False):
    """Publish a message to the MQTT broker"""
    if mqtt_client and mqtt_client.is_connected():
        try:
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            mqtt_client.publish(topic, payload, retain=retain)
            return True
        except Exception as e:
            logging.error(f"Error publishing message to {topic}: {e}")
    return False

def publish_status():
    """Publish current system status"""
    try:
        status = {
            "timestamp": datetime.now().isoformat(),
            "devices": device_states,
            "last_update": last_data_update.isoformat() if last_data_update else None
        }
        publish_message(STATE_TOPIC, status, retain=True)
    except Exception as e:
        logging.error(f"Error publishing status: {e}")

def update_device_state(device_name, state):
    """Update and publish device state"""
    try:
        device_states[device_name] = state
        topic = DEVICE_STATE_TOPIC.format(device_name=device_name)
        publish_message(topic, state, retain=True)
    except Exception as e:
        logging.error(f"Error updating device state for {device_name}: {e}")

def disconnect():
    """Disconnect from the MQTT broker"""
    global mqtt_client
    if mqtt_client:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            logging.info("Disconnected from MQTT broker")
        except Exception as e:
            logging.error(f"Error disconnecting from MQTT broker: {e}")
        finally:
            mqtt_client = None 