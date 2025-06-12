import logging
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

# Global variables
mqtt_client: mqtt.Client = None
subscribed_topics = []
device_states = {}
last_data_update = None

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
        client = mqtt.Client(client_id)

        # Set will message for availability
        client.will_set(AVAILABILITY_TOPIC, "offline", 0, False)

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