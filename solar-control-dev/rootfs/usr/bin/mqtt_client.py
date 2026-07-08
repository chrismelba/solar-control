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
ROAD_TRIP_CONFIG_TOPIC = DISCOVERY_PREFIX + "/switch/solar_control/{slug}_road_trip/config"
ROAD_TRIP_STATE_TOPIC = "solar_control/devices/{slug}/road_trip/state"
ROAD_TRIP_COMMAND_TOPIC = "solar_control/devices/{slug}/road_trip/set"

# Global variables
mqtt_client: mqtt.Client = None
subscribed_topics = []
device_states = {}
last_data_update = None

# Discovery registry: slug -> {"name": device name, "state": bool}
# Kept so discovery can be republished on reconnect / HA restart, and so
# command topics (which carry the slug) can be mapped back to device names.
_road_trip_registry = {}
_road_trip_command_handler = None  # callable(device_name: str, enabled: bool)
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
        client.subscribe(ROAD_TRIP_COMMAND_TOPIC.format(slug="+"))
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
        elif topic.endswith("/road_trip/set"):
            handle_road_trip_command(topic.split("/")[2], payload)
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

def handle_road_trip_command(slug, payload):
    """Handle an ON/OFF command from a discovered road trip switch."""
    entry = _road_trip_registry.get(slug)
    if not entry:
        logging.warning(f"Road trip command for unknown device slug: {slug}")
        return
    if _road_trip_command_handler is None:
        logging.warning("Road trip command received but no handler registered")
        return
    try:
        _road_trip_command_handler(entry["name"], payload.strip().upper() == "ON")
    except Exception as e:
        logging.error(f"Error handling road trip command for {entry['name']}: {e}")


def set_road_trip_command_handler(handler):
    """Register the callback invoked as handler(device_name, enabled) when a
    road trip switch is flipped from Home Assistant."""
    global _road_trip_command_handler
    _road_trip_command_handler = handler


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


def _publish_road_trip_config(slug, device_name):
    config = {
        "name": f"{device_name} road trip",
        "unique_id": f"solar_control_{slug}_road_trip",
        "state_topic": ROAD_TRIP_STATE_TOPIC.format(slug=slug),
        "command_topic": ROAD_TRIP_COMMAND_TOPIC.format(slug=slug),
        "icon": "mdi:bag-suitcase",
        "availability_topic": AVAILABILITY_TOPIC,
        "device": _device_info(),
    }
    publish_message(ROAD_TRIP_CONFIG_TOPIC.format(slug=slug), config, retain=True)


def _publish_all_discovery():
    """(Re)publish discovery configs and current states for all registered cars."""
    for slug, entry in _road_trip_registry.items():
        _publish_road_trip_config(slug, entry["name"])
        publish_message(ROAD_TRIP_STATE_TOPIC.format(slug=slug),
                        "ON" if entry["state"] else "OFF", retain=True)


def publish_road_trip_state(device_name, enabled):
    """Publish a car's current road trip state to its discovered switch."""
    slug = slugify(device_name)
    entry = _road_trip_registry.get(slug)
    if entry is None:
        return  # not a registered car (e.g. discovery not synced yet)
    entry["state"] = bool(enabled)
    publish_message(ROAD_TRIP_STATE_TOPIC.format(slug=slug),
                    "ON" if enabled else "OFF", retain=True)


def sync_road_trip_discovery(cars, sw_version=None):
    """Reconcile discovered road trip switches with the current device list.

    cars: {device_name: road_trip_enabled} for every device that is a car.
    Publishes discovery + state for new/updated cars and removes the retained
    discovery config for devices that are no longer cars.
    """
    global _sw_version
    if sw_version:
        _sw_version = sw_version

    desired = {slugify(name): name for name in cars}

    # Remove switches for devices that are gone / no longer cars
    for slug in list(_road_trip_registry):
        if slug not in desired:
            del _road_trip_registry[slug]
            # Empty retained payload deletes the entity from HA
            publish_message(ROAD_TRIP_CONFIG_TOPIC.format(slug=slug), "", retain=True)
            publish_message(ROAD_TRIP_STATE_TOPIC.format(slug=slug), "", retain=True)

    for slug, name in desired.items():
        _road_trip_registry[slug] = {"name": name, "state": bool(cars[name])}

    _publish_all_discovery()


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