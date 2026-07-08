from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash, abort, json, make_response
import atexit
import os
import logging
import json
import requests
import threading
import time
from datetime import datetime, timezone
from device import Device
from battery import Battery
from solar_controller import SolarController
from utils import get_sunrise_time, setup_logging, entity_state_to_is_on
from runtime_state import serialize_runtime_state, apply_runtime_state
from mqtt_client import (connect as mqtt_connect, disconnect as mqtt_disconnect,
                         publish_message, update_device_state, publish_status,
                         sync_device_switch_discovery, sync_global_switch_discovery,
                         publish_switch_state, set_switch_command_handler)

HASS_URL = os.environ.get('HASS_URL', 'http://supervisor/core')

# Set up logging using the centralized configuration
logger = setup_logging()

# Create static directory if it doesn't exist
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
if not os.path.exists(static_dir):
    logger.info(f"Creating static directory: {static_dir}")
    os.makedirs(static_dir)

_base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
           static_folder=static_dir,
           template_folder=os.path.join(_base_dir, 'templates'))

# Add a context processor to make the ingress path available in templates
@app.context_processor
def inject_ingress_path():
    # Get ingress path from header
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.debug(f"Using ingress path from header: {ingress_path}")
    logger.debug(f"All request headers: {dict(request.headers)}")
    return dict(ingress_path=ingress_path, basename=ingress_path, app_version=APP_VERSION)

# Override url_for to include ingress path for all URLs
@app.template_global()
def url_for(endpoint, **values):
    if endpoint == 'static':
        ingress_path = request.headers.get('X-Ingress-Path', '')
        return ingress_path + app.url_for(endpoint, **values)
    elif endpoint.startswith('/'):
        ingress_path = request.headers.get('X-Ingress-Path', '')
        return ingress_path + endpoint
    return app.url_for(endpoint, **values)

# Add a before_request handler to set the static URL path for each request
@app.before_request
def before_request():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    app.static_url_path = f'{ingress_path}/static'
    logger.debug(f"Set static URL path to: {app.static_url_path}")

DATA_DIR = os.environ.get('DATA_DIR', '/data')

# Read add-on version for cache-busting static assets
def _read_addon_version():
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'config.yaml')
        with open(config_path) as f:
            for line in f:
                if line.startswith('version:'):
                    return line.split(':', 1)[1].strip().strip('"')
    except Exception:
        pass
    return 'dev'

APP_VERSION = _read_addon_version()

# Configuration file paths (defined here so they're available from startup)
CONFIG_FILE = f'{DATA_DIR}/solar_config.json'
DEVICES_FILE = f'{DATA_DIR}/devices.json'
SETTINGS_FILE = f'{DATA_DIR}/settings.json'
BATTERY_FILE = f'{DATA_DIR}/battery.json'
STATE_FILE = f'{DATA_DIR}/state.json'

# Create controller instance
controller = SolarController(
    config_file=CONFIG_FILE,
    devices_file=DEVICES_FILE
)

# Initialize MQTT connection
logger.info("Initializing MQTT connection...")
if mqtt_connect():
    logger.info("MQTT connection established successfully")
    # Publish optimization toggle state
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
        optimization_enabled = settings.get('power_optimization_enabled', False)
        publish_message('solar_control/optimization_enabled', str(optimization_enabled).lower(), retain=True)
    except Exception as e:
        logger.error(f"Error publishing initial optimization state: {e}")
else:
    logger.warning("Failed to establish MQTT connection")

# Initialise device states synchronously so load_one_off_state() can restore them
logger.info("Initialising device states...")
try:
    controller.initialize_device_states()
except Exception as e:
    logger.warning(f"Could not initialise device states at startup: {e}")

# Start the control loop
logger.info("Starting solar controller control loop...")
controller.start_control_loop()

# --- Runtime state persistence (one-off charges, road trip mode) ---

def save_runtime_state():
    """Save per-device runtime state (one-off charges, road trip, auto control) to disk."""
    try:
        state = serialize_runtime_state(controller.device_states)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        logger.error(f"Error saving runtime state: {e}")

def load_runtime_state():
    """Restore per-device runtime state from disk after a restart."""
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
        apply_runtime_state(controller.device_states, state)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"Error loading runtime state: {e}")

def _state_save_loop():
    while True:
        time.sleep(60)
        save_runtime_state()

load_runtime_state()
_state_thread = threading.Thread(target=_state_save_loop, daemon=True, name='state-saver')
_state_thread.start()

# --- MQTT discovery: expose switches as HA entities ---

def _load_power_optimization():
    """Read the current power optimization setting from disk."""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return bool(json.load(f).get('power_optimization_enabled', False))
    except Exception:
        return False

def _set_power_optimization(enabled):
    """Persist the power optimization setting and publish it everywhere.

    Shared by the REST API route and the MQTT switch command handler."""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {}
    settings['power_optimization_enabled'] = enabled
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
    # Legacy plain topic (kept for existing user automations) + discovered switch
    publish_message('solar_control/optimization_enabled', str(enabled).lower(), retain=True)
    publish_switch_state('optimization', None, enabled)
    logger.info(f"Power optimization set to: {enabled}")

def sync_mqtt_discovery():
    """Publish/refresh all discovered HA entities:
    road trip switch per car, auto-control switch per device, and the
    global power optimization switch."""
    try:
        cars = {name: ds.road_trip for name, ds in controller.device_states.items()
                if ds.device.is_car}
        sync_device_switch_discovery('road_trip', cars, sw_version=APP_VERSION)
        all_devices = {name: ds.auto_control
                       for name, ds in controller.device_states.items()}
        sync_device_switch_discovery('auto_control', all_devices, sw_version=APP_VERSION)
        sync_global_switch_discovery('optimization', _load_power_optimization(),
                                     sw_version=APP_VERSION)
    except Exception as e:
        logger.error(f"Error syncing MQTT discovery: {e}")

def _handle_road_trip_command(device_name, enabled):
    """A road trip switch was flipped from Home Assistant."""
    device_state = controller.device_states.get(device_name)
    if not device_state or not device_state.device.is_car:
        logger.warning(f"MQTT road trip command for unknown car: {device_name}")
        return
    device_state.road_trip = enabled
    logger.info(f"Road trip mode for {device_name} set to {enabled} via MQTT")
    save_runtime_state()
    publish_switch_state('road_trip', device_name, enabled)

def _handle_auto_control_command(device_name, enabled):
    """An auto-control switch was flipped from Home Assistant."""
    device_state = controller.device_states.get(device_name)
    if not device_state:
        logger.warning(f"MQTT auto control command for unknown device: {device_name}")
        return
    device_state.auto_control = enabled
    logger.info(f"Auto control for {device_name} set to {enabled} via MQTT")
    save_runtime_state()
    publish_switch_state('auto_control', device_name, enabled)

def _handle_optimization_command(_device_name, enabled):
    """The power optimization switch was flipped from Home Assistant."""
    try:
        _set_power_optimization(enabled)
    except Exception as e:
        logger.error(f"Error handling optimization command: {e}")

set_switch_command_handler('road_trip', _handle_road_trip_command)
set_switch_command_handler('auto_control', _handle_auto_control_command)
set_switch_command_handler('optimization', _handle_optimization_command)
sync_mqtt_discovery()

# Modify the device state endpoints to publish MQTT updates
@app.route('/api/devices/<name>/state', methods=['GET'])
def get_device_state(name):
    try:
        logger.debug(f"Getting state for device: {name}")
        devices = Device.load_all(DEVICES_FILE)
        
        device = next((d for d in devices if d.name == name), None)
        if device is None:
            logger.info(f"Device not found: {name}")
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404

        # Get the current state from Home Assistant
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if not supervisor_token:
            logger.error("No supervisor token available in environment")
            return jsonify({'status': 'error', 'message': 'No supervisor token available'}), 500

        headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        }

        response = requests.get(
            f"{HASS_URL}/api/states/{device.switch_entity}",
            headers=headers
        )
        response.raise_for_status()
        state = response.json().get('state', 'off')
        logger.debug(f"Retrieved state for device {name}: {state}")

        # Publish state to MQTT
        update_device_state(name, {'state': state})

        # is_on normalizes non-switch domains (climate reports 'heat'/'cool'/... when on)
        return jsonify({'state': state, 'is_on': entity_state_to_is_on(state)})
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error getting device state for {name}: {e}")
        return jsonify({'status': 'error', 'message': f'Network error: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error getting device state for {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>/set_state', methods=['POST'])
def set_device_state(name):
    try:
        data = request.get_json()
        logger.debug(f"Setting state for device {name}: {data}")
        
        if not data or 'state' not in data:
            logger.info(f"Invalid request data: {data}")
            return jsonify({'status': 'error', 'message': 'Invalid request data'}), 400

        devices = Device.load_all(DEVICES_FILE)
        device = next((d for d in devices if d.name == name), None)
        
        if device is None:
            logger.info(f"Device not found: {name}")
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404

        # Set the device state using the explicit set_state method
        success = device.set_state(data['state'])
        if not success:
            logger.error(f"Failed to set state for device {name}")
            return jsonify({'status': 'error', 'message': 'Failed to set device state'}), 500

        # Publish state to MQTT
        update_device_state(name, {'state': data['state']})
        
        logger.info(f"Successfully set state for device {name} to {data['state']}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error setting device state for {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

# Disconnect MQTT cleanly on interpreter shutdown. (Must NOT be a Flask
# teardown_appcontext handler — those run after every request, which was
# silently killing the MQTT connection on the first page load.)
atexit.register(mqtt_disconnect)

# Log static file configuration
logger.info('Static folder: %s', app.static_folder)
logger.info('Static URL path: %s', app.static_url_path)
logger.info('Static files available:')
for root, dirs, files in os.walk(static_dir):
    for file in files:
        logger.info('  %s', os.path.join(root, file))

# Debug: Log data directory state
logger.info("Checking data directory state...")
logger.info(f"Data directory exists: {os.path.exists(DATA_DIR)}")
logger.info(f"Data directory permissions: {oct(os.stat(DATA_DIR).st_mode)[-3:]}")
logger.info(f"Data directory owner: {os.stat(DATA_DIR).st_uid}")

# Ensure data directory exists
logger.info("Ensuring data directory exists...")
os.makedirs(DATA_DIR, exist_ok=True)

# Initialize files if they don't exist
def initialize_files():
    # Initialize devices file
    if not os.path.exists(DEVICES_FILE):
        logger.info(f"Creating devices file: {DEVICES_FILE}")
        with open(DEVICES_FILE, 'w') as f:
            json.dump([], f)
    
    # Initialize settings file
    if not os.path.exists(SETTINGS_FILE):
        logger.info(f"Creating settings file: {SETTINGS_FILE}")
        with open(SETTINGS_FILE, 'w') as f:
            json.dump({
                'power_optimization_enabled': True
            }, f)
    
    # Initialize config file
    if not os.path.exists(CONFIG_FILE):
        logger.info(f"Creating config file: {CONFIG_FILE}")
        with open(CONFIG_FILE, 'w') as f:
            json.dump({}, f)

# Initialize files
initialize_files()

# Static page handler
@app.route('/')
def root():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving root page with ingress path: {ingress_path}")
    devices = Device.load_all(DEVICES_FILE)
    devices.sort(key=lambda x: x.order)
    sensor_values = get_sensor_values()
    sunrise_time = get_sunrise_time()
    entities = get_entities()
    try:
        with open(CONFIG_FILE, 'r') as f:
            grid_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        grid_config = {}
    battery_obj = Battery.load(BATTERY_FILE)
    battery_config = {
        'size_kwh': battery_obj.size_kwh,
        'battery_percent_entity': battery_obj.battery_percent_entity,
        'max_charging_speed_kw': battery_obj.max_charging_speed_kw,
        'expected_kwh_per_hour': battery_obj.expected_kwh_per_hour,
        'bring_forward_mode': battery_obj.bring_forward_mode,
    } if battery_obj else {}
    return make_response(render_template('index.html',
                         devices=devices,
                         sensor_values=sensor_values,
                         sunrise_time=sunrise_time,
                         entities=entities,
                         grid_config=grid_config,
                         battery_config=battery_config,
                         ingress_path=ingress_path,
                         basename=ingress_path))

@app.route('/<path:page>')
def static_page(page):
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.debug(f"Serving static page {page} with ingress path: {ingress_path}")
    
    # Map page names to templates and required data
    page_config = {
        '': {
            'template': 'index.html',
            'data': lambda: {
                'sensor_values': get_sensor_values()
            }
        },
        'debug': {
            'template': 'debug.html',
            'data': lambda: {
                'config': load_config(),
                'env': {
                    'PORT': os.environ.get('PORT', 'Not set'),
                    'INGRESS_PATH': os.environ.get('INGRESS_PATH', 'Not set'),
                    'HASS_URL': os.environ.get('HASS_URL', 'Not set'),
                },
                'headers': dict(request.headers),
                'nginx_error_log': get_nginx_log('error'),
                'nginx_access_log': get_nginx_log('access')
            }
        },
        'configure/battery': {
            'template': 'configure_battery.html',
            'data': lambda: {
                'entities': get_entities()
            }
        },
        'configure/devices': {
            'template': 'configure_devices.html',
            'data': lambda: {
                'entities': get_entities()
            }
        }
    }
    
    # Check if page exists in config
    if page not in page_config:
        abort(404)
    
    # Get page configuration
    config = page_config[page]
    
    # Get template and data
    template = config['template']
    data = config['data']()
    
    # Add common data
    data.update({
        'ingress_path': ingress_path,
        'basename': ingress_path
    })
    
    return make_response(render_template(template, **data))

# Helper functions for static page data
def get_sensor_values():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}
    
    # Get supervisor token from environment
    supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
    if not supervisor_token:
        logger.error("No supervisor token found in environment")
        return {}
    
    headers = {
        "Authorization": f"Bearer {supervisor_token}",
        "Content-Type": "application/json",
    }
    
    sensor_values = {}
    for entity_id in ['solar_generation', 'grid_power', 'solar_forecast', 'tariff_rate']:
        if entity_id in config and config[entity_id]:
            try:
                response = requests.get(
                    f'{HASS_URL}/api/states/{config[entity_id]}',
                    headers=headers
                )
                response.raise_for_status()  # Raise exception for non-200 status codes
                sensor_values[entity_id] = response.json()
            except Exception as e:
                logger.error(f"Error fetching {entity_id} value: {e}")
    
    # Add tariff mode if tariff rate is configured
    if 'tariff_rate' in sensor_values:
        try:
            sensor_values['tariff_mode'] = controller.get_current_tariff_mode()
        except Exception as e:
            logger.error(f"Error determining tariff mode: {e}")
            sensor_values['tariff_mode'] = 'error'
    
    # Add bring forward power and battery configuration
    try:
        # Get debug state to access bring forward power
        debug_state = controller.get_debug_state()
        if debug_state and debug_state.bring_forward_power is not None:
            sensor_values['bring_forward_power'] = {
                'state': f"{debug_state.bring_forward_power:.0f}",
                'unit': 'W',
                'friendly_name': 'Bring Forward Power'
            }
        
        # Get battery configuration to check bring forward mode
        battery = Battery.load(BATTERY_FILE)
        if battery:
            sensor_values['bring_forward_mode'] = {
                'state': 'enabled' if battery.bring_forward_mode else 'disabled',
                'friendly_name': 'Bring Forward Mode'
            }
            # Fetch battery percentage entity state if configured
            if battery.battery_percent_entity:
                try:
                    response = requests.get(
                        f'{HASS_URL}/api/states/{battery.battery_percent_entity}',
                        headers=headers
                    )
                    response.raise_for_status()
                    sensor_values['battery_percent'] = response.json()
                except Exception as e:
                    logger.error(f"Error fetching battery_percent value: {e}")
    except Exception as e:
        logger.error(f"Error getting bring forward information: {e}")
    
    return sensor_values


def get_entities():
    try:
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        headers = {"Authorization": f"Bearer {supervisor_token}", "Content-Type": "application/json"} if supervisor_token else {}
        logger.info("Attempting to fetch entities from supervisor API")
        response = requests.get(f'{HASS_URL}/api/states', headers=headers)
        logger.info(f"Supervisor API response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Supervisor API returned non-200 status code: {response.status_code}")
            return []
            
        entities = response.json()
        
        # Validate entities structure
        if not isinstance(entities, list):
            logger.error(f"Expected list of entities, got {type(entities)}")
            return []
            
        # Log some sample entities for debugging
        if entities:
            logger.info(f"Sample entity structure: {entities[0]}")
            
        logger.info(f"Successfully fetched {len(entities)} entities")
        return entities
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching entities: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON response: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching entities: {e}")
        return []

def get_nginx_log(log_type):
    try:
        with open(f'{DATA_DIR}/nginx/logs/{log_type}.log', 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading Nginx {log_type} log: {str(e)}"

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Keep the dynamic routes
@app.route('/configure/grid', methods=['GET', 'POST'])
def configure_grid():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving configure grid page with ingress path: {ingress_path}")
    
    if request.method == 'POST':
        config = {
            'solar_generation': request.form.get('solar_generation'),
            'grid_power': request.form.get('grid_power'),
            'solar_forecast': request.form.get('solar_forecast'),
            'grid_voltage': request.form.get('grid_voltage'),
            'grid_voltage_fixed': request.form.get('grid_voltage_fixed'),
            'tariff_rate': request.form.get('tariff_rate'),
            'site_export_limit': request.form.get('site_export_limit'),
            'tariff_modes': request.form.get('tariff_modes')
        }
        
        # Convert site_export_limit to float if provided
        if config['site_export_limit']:
            try:
                config['site_export_limit'] = float(config['site_export_limit'])
            except ValueError:
                config['site_export_limit'] = None
        else:
            config['site_export_limit'] = None
            
        # Parse tariff_modes JSON if provided
        if config['tariff_modes']:
            try:
                config['tariff_modes'] = json.loads(config['tariff_modes'])
            except json.JSONDecodeError:
                config['tariff_modes'] = {}
        else:
            config['tariff_modes'] = {}
        
        # Save configuration
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        
        # Update controller configuration
        controller.update_config(config)
        
        ingress_path = request.headers.get('X-Ingress-Path', '')
        return redirect(ingress_path + '/')    
    # Load current configuration
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}
    
    # Get entities and sensor values
    entities = get_entities()
    sensor_values = get_sensor_values()
    
    return make_response(render_template('configure_grid.html', 
                         config=config, 
                         entities=entities,
                         sensor_values=sensor_values,
                         ingress_path=ingress_path,
                         basename=ingress_path))

@app.route('/configure/battery', methods=['GET', 'POST'])
def configure_battery():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving configure battery page with ingress path: {ingress_path}")
    
    # Load battery configuration
    battery = Battery.load(BATTERY_FILE)
    config = battery.to_dict() if battery else {}

    # Get entities for the searchable selects
    entities = get_entities()

    return make_response(render_template('configure_battery.html',
                         config=config,
                         entities=entities,
                         ingress_path=ingress_path,
                         basename=ingress_path))

@app.route('/configure/devices', methods=['GET'])
def configure_devices():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving configure devices page with ingress path: {ingress_path}")
    
    # Get entities for the device configuration form
    logger.info("Fetching entities for device configuration form")
    entities = get_entities()
    logger.info(f"Retrieved {len(entities)} entities for device configuration")
    
    return make_response(render_template('configure_devices.html',
                         entities=entities,
                         ingress_path=ingress_path,
                         basename=ingress_path))

@app.route('/api/devices/<name>', methods=['GET'])
def get_device(name):
    try:
        logger.debug(f"Getting state for device: {name}")
        # Get device from controller's live state
        device_state = controller.device_states.get(name)
        if device_state is None:
            logger.info(f"Device not found: {name}")
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        
        # Get the device object and update its energy delivered value
        device = device_state.device
        device.update_energy_delivered()
        
        # Get the device data and add runtime state
        device_data = device.to_dict()
        device_data.update({
            'is_on': device_state.is_on,
            'last_state_change': device_state.last_state_change.isoformat() if device_state.last_state_change else None,
            'current_amperage': device_state.current_amperage,
            'has_completed': device_state.has_completed
        })
        
        logger.debug(f"Retrieved device state for {name}: {device_data}")
        return jsonify(device_data)
    except Exception as e:
        logger.error(f"Error getting device state for {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices', methods=['GET'])
def get_devices():
    try:
        logger.debug("Getting state for all devices")
        # Get all devices from controller's live state
        devices_data = []
        for device_state in controller.device_states.values():
            device = device_state.device
            # Update energy delivered value
            device.update_energy_delivered()
            
            # Get device data and add runtime state
            device_data = device.to_dict()
            device_data.update({
                'is_on': device_state.is_on,
                'last_state_change': device_state.last_state_change.isoformat() if device_state.last_state_change else None,
                'current_amperage': device_state.current_amperage,
                'has_completed': device_state.has_completed,
                'current_power': controller.get_device_power(device_state),
                'car_soc': device_state.car_soc,
                'road_trip': device_state.road_trip,
                'auto_control': device_state.auto_control,
                'one_off_charge_target': device_state.one_off_charge_target,
                'one_off_charge_delivered': (
                    max(0, device.energy_delivered_today - (device_state.one_off_charge_start_energy or 0))
                    if device_state.one_off_charge_target is not None else None
                ),
            })
            devices_data.append(device_data)
        
        # Sort devices by their order property
        devices_data.sort(key=lambda x: x['order'])
        logger.debug(f"Retrieved state for {len(devices_data)} devices")
        return jsonify(devices_data)
    except Exception as e:
        logger.error(f"Error loading devices: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>/one_off_charge', methods=['POST'])
def set_one_off_charge(name):
    try:
        data = request.json
        device_state = controller.device_states.get(name)
        if not device_state:
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        target_kwh = data.get('target_kwh')  # None = cancel
        if target_kwh is None:
            device_state.one_off_charge_target = None
            device_state.one_off_charge_start_energy = None
        else:
            device_state.one_off_charge_target = float(target_kwh)
            device_state.one_off_charge_start_energy = device_state.device.energy_delivered_today
        save_runtime_state()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error setting one-off charge for {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>/road_trip', methods=['POST'])
def set_road_trip(name):
    try:
        data = request.json
        device_state = controller.device_states.get(name)
        if not device_state:
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        device_state.road_trip = bool(data.get('enabled'))
        logger.info(f"Road trip mode for {name} set to {device_state.road_trip}")
        save_runtime_state()
        publish_switch_state('road_trip', name, device_state.road_trip)
        return jsonify({'status': 'success', 'road_trip': device_state.road_trip})
    except Exception as e:
        logger.error(f"Error setting road trip mode for {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>/auto_control', methods=['POST'])
def set_auto_control(name):
    try:
        data = request.json
        device_state = controller.device_states.get(name)
        if not device_state:
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        device_state.auto_control = bool(data.get('enabled'))
        logger.info(f"Auto control for {name} set to {device_state.auto_control}")
        save_runtime_state()
        publish_switch_state('auto_control', name, device_state.auto_control)
        return jsonify({'status': 'success', 'auto_control': device_state.auto_control})
    except Exception as e:
        logger.error(f"Error setting auto control for {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices', methods=['POST'])
def add_device():
    try:
        device_data = request.json
        logger.debug(f"Adding new device: {device_data}")
        devices = Device.load_all(DEVICES_FILE)
        
        # Check if device with same name exists
        if any(d.name == device_data['name'] for d in devices):
            logger.info(f"Device with name {device_data['name']} already exists")
            return jsonify({'status': 'error', 'message': 'Device with this name already exists'}), 400
        
        # Set order to be the next available index
        device_data['order'] = len(devices)

        # Create new device (from_dict applies numeric conversions and cleanup)
        device = Device.from_dict(device_data)
        devices.append(device)
        Device.save_all(devices, DEVICES_FILE)
        controller.initialize_device_states()
        sync_mqtt_discovery()

        logger.info(f"Successfully added device: {device.name}")
        return jsonify(device.to_dict())
    except Exception as e:
        logger.error(f"Error adding device: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>', methods=['PUT'])
def update_device(name):
    try:
        device_data = request.json
        logger.debug(f"Updating device {name}: {device_data}")
        devices = Device.load_all(DEVICES_FILE)
        
        # Find device
        device_index = next((i for i, d in enumerate(devices) if d.name == name), None)
        if device_index is None:
            logger.info(f"Device not found: {name}")
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        
        # Preserve the existing order if not provided in the update
        if 'order' not in device_data:
            device_data['order'] = devices[device_index].order
        
        # Update device (from_dict applies numeric conversions and cleanup)
        devices[device_index] = Device.from_dict(device_data)
        Device.save_all(devices, DEVICES_FILE)
        controller.initialize_device_states()
        sync_mqtt_discovery()

        logger.info(f"Successfully updated device: {name}")
        return jsonify(devices[device_index].to_dict())
    except Exception as e:
        logger.error(f"Error updating device {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>', methods=['DELETE'])
def delete_device(name):
    try:
        logger.debug(f"Deleting device: {name}")
        devices = Device.load_all(DEVICES_FILE)
        
        # Find and remove device
        devices = [d for d in devices if d.name != name]
        Device.save_all(devices, DEVICES_FILE)
        controller.initialize_device_states()
        sync_mqtt_discovery()

        logger.info(f"Successfully deleted device: {name}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error deleting device {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/reorder', methods=['POST'])
def reorder_devices():
    try:
        order_data = request.get_json()
        logger.debug(f"Reordering devices: {order_data}")
        if not order_data or not isinstance(order_data, list):
            logger.info("Invalid order data format")
            return jsonify({'status': 'error', 'message': 'Invalid order data format'}), 400
            
        devices = Device.load_all(DEVICES_FILE)
        device_dict = {d.name: d for d in devices}
        
        # Update order for each device
        for item in order_data:
            if not isinstance(item, dict) or 'name' not in item or 'order' not in item:
                logger.info("Invalid device order item format")
                return jsonify({'status': 'error', 'message': 'Invalid device order item format'}), 400
                
            device = device_dict.get(item['name'])
            if device:
                device.order = int(item['order'])
        
        # Save updated devices
        Device.save_all(list(device_dict.values()), DEVICES_FILE)
        controller.initialize_device_states()
        logger.info("Successfully reordered devices")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error reordering devices: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
        logger.debug("Getting system status")
        # Load settings
        if not os.path.exists(SETTINGS_FILE):
            settings = {'power_optimization_enabled': False}
        else:
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
            except json.JSONDecodeError:
                logger.error("Error decoding settings file, using defaults")
                settings = {'power_optimization_enabled': False}
        
        status = {
            'status': 'running',
            'version': APP_VERSION,
            'power_optimization_enabled': settings.get('power_optimization_enabled', False)
        }
        
        # Add debug state information if available
        debug_state = controller.get_debug_state()
        if debug_state:
            status['debug_state'] = debug_state.to_dict()
        
        logger.debug(f"System status: {status}")
        return jsonify(status)
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/control/run', methods=['POST'])
def run_control_loop():
    try:
        logger.debug("Manually running control loop")
        controller.run_control_loop()
        logger.info("Control loop completed successfully")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error running control loop: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/settings/power_optimization', methods=['POST'])
def update_power_optimization():
    try:
        data = request.json
        enabled = data.get('enabled', False)
        _set_power_optimization(enabled)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error updating power optimization setting: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/states/<entity_id>', methods=['GET'])
def get_entity_state(entity_id):
    try:
        logger.debug(f"Getting state for entity: {entity_id}")
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if not supervisor_token:
            logger.error("No supervisor token available in environment")
            return jsonify({'status': 'error', 'message': 'No supervisor token available'}), 500

        headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        }

        response = requests.get(
            f"{HASS_URL}/api/states/{entity_id}",
            headers=headers
        )
        response.raise_for_status()
        state = response.json()
        logger.debug(f"Retrieved state for entity {entity_id}: {state}")
        return jsonify(state)
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error getting entity state for {entity_id}: {e}")
        return jsonify({'status': 'error', 'message': f'Network error: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error getting entity state for {entity_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/tariff_modes', methods=['GET'])
def get_tariff_modes():
    try:
        logger.debug("Getting tariff modes")
        # Get the tariff rate entity from config
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            config = {}
        
        tariff_rate_entity = config.get('tariff_rate')
        if not tariff_rate_entity:
            logger.info("No tariff rate entity configured")
            return jsonify({
                'status': 'success',
                'modes': ['normal', 'cheap', 'free'],
                'current_modes': {},
                'options': []
            })

        # Get the options from Home Assistant
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if not supervisor_token:
            logger.error("No supervisor token available in environment")
            return jsonify({'status': 'error', 'message': 'No supervisor token available'}), 500

        headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        }

        response = requests.get(
            f"{HASS_URL}/api/states/{tariff_rate_entity}",
            headers=headers
        )
        response.raise_for_status()
        state_data = response.json()
        
        # Get the options from the entity's attributes
        options = state_data.get('attributes', {}).get('options', [])
        
        # Get the current mode assignments from config
        current_modes = config.get('tariff_modes', {})
        
        result = {
            'status': 'success',
            'modes': ['normal', 'cheap', 'free'],  # The available modes we support
            'current_modes': current_modes,  # The current mode assignments
            'options': options  # The tariff rate options from Home Assistant
        }
        logger.debug(f"Retrieved tariff modes: {result}")
        return jsonify(result)
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error getting tariff modes: {e}")
        return jsonify({'status': 'error', 'message': f'Network error: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error getting tariff modes: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/config/grid', methods=['POST'])
def api_config_grid():
    try:
        data = request.json
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        config = {
            'solar_generation': data.get('solar_generation') or None,
            'grid_power': data.get('grid_power') or None,
            'solar_forecast': data.get('solar_forecast') or None,
            'grid_voltage': data.get('grid_voltage') or None,
            'grid_voltage_fixed': data.get('grid_voltage_fixed') or None,
            'tariff_rate': data.get('tariff_rate') or None,
            'site_export_limit': None,
            'tariff_modes': data.get('tariff_modes', {}),
        }

        if data.get('site_export_limit'):
            try:
                config['site_export_limit'] = float(data['site_export_limit'])
            except (ValueError, TypeError):
                config['site_export_limit'] = None

        if isinstance(config['tariff_modes'], str):
            try:
                config['tariff_modes'] = json.loads(config['tariff_modes'])
            except json.JSONDecodeError:
                config['tariff_modes'] = {}

        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)

        controller.update_config(config)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error saving grid config via API: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400


@app.route('/api/battery', methods=['GET'])
def get_battery():
    try:
        logger.debug("Getting battery configuration")
        battery = Battery.load(BATTERY_FILE)
        if battery is None:
            logger.info("No battery configuration found")
            return jsonify({
                'status': 'success',
                'config': {}
            })
        
        result = {
            'status': 'success',
            'config': battery.to_dict()
        }
        logger.debug(f"Retrieved battery configuration: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting battery configuration: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/battery', methods=['POST'])
def update_battery():
    try:
        # Log the raw request data
        logger.debug(f"Raw request data: {request.get_data()}")
        logger.debug(f"Request content type: {request.content_type}")
        logger.debug(f"Request headers: {dict(request.headers)}")
        
        data = request.json
        logger.debug(f"Parsed JSON data: {data}")
        if not data:
            logger.info("No data provided for battery update")
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        # Validate required fields
        if 'size_kwh' not in data or 'battery_percent_entity' not in data:
            logger.info("Missing required fields for battery update")
            logger.info(f"Received fields: {list(data.keys()) if data else 'None'}")
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        # Validate data types
        try:
            size_kwh = float(data['size_kwh'])
            battery_percent_entity = str(data['battery_percent_entity'])
            max_charging_speed_kw = float(data['max_charging_speed_kw']) if data.get('max_charging_speed_kw') else None
            expected_kwh_per_hour = float(data['expected_kwh_per_hour']) if data.get('expected_kwh_per_hour') else None
            bring_forward_mode = bool(data.get('bring_forward_mode', False))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid data type in battery configuration: {e}")
            return jsonify({'status': 'error', 'message': f'Invalid data type: {str(e)}'}), 400

        logger.debug(f"Validated data: size_kwh={size_kwh}, battery_percent_entity={battery_percent_entity}, max_charging_speed_kw={max_charging_speed_kw}, expected_kwh_per_hour={expected_kwh_per_hour}, bring_forward_mode={bring_forward_mode}")

        # Create battery object
        battery = Battery(
            size_kwh=size_kwh,
            battery_percent_entity=battery_percent_entity,
            max_charging_speed_kw=max_charging_speed_kw,
            expected_kwh_per_hour=expected_kwh_per_hour,
            bring_forward_mode=bring_forward_mode
        )

        # Save configuration
        if battery.save(BATTERY_FILE):
            logger.info("Successfully updated battery configuration")
            return jsonify({'status': 'success'})
        else:
            logger.error("Failed to save battery configuration")
            return jsonify({'status': 'error', 'message': 'Failed to save battery configuration'}), 500
    except Exception as e:
        logger.error(f"Error updating battery configuration: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

def _get_ha_headers():
    token = os.environ.get('SUPERVISOR_TOKEN', '')
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _integrate_power_history(entity_id, start_dt):
    """Fetch HA history for a power sensor (W) from start_dt to now and integrate to kWh."""
    try:
        start_str = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
        resp = requests.get(
            f"{HASS_URL}/api/history/period/{start_str}",
            params={'filter_entity_id': entity_id, 'minimal_response': 'true', 'no_attributes': 'true'},
            headers=_get_ha_headers(),
            timeout=15
        )
        states = resp.json()[0] if resp.ok and resp.json() else []
    except Exception as e:
        logger.warning(f"Failed to fetch history for {entity_id}: {e}")
        return 0.0

    energy_wh = 0.0
    prev_power = 0.0
    prev_time = start_dt.replace(tzinfo=timezone.utc)

    for s in states:
        try:
            power = float(s['state'])
        except (ValueError, KeyError, TypeError):
            power = prev_power
        try:
            ts = datetime.fromisoformat(s['last_changed'].replace('Z', '+00:00'))
        except (KeyError, ValueError):
            continue
        dt_h = (ts - prev_time).total_seconds() / 3600
        if dt_h > 0:
            energy_wh += prev_power * dt_h
        prev_power, prev_time = power, ts

    # Final segment from last reading to now
    now_utc = datetime.now(timezone.utc)
    dt_h = (now_utc - prev_time).total_seconds() / 3600
    if dt_h > 0:
        energy_wh += prev_power * dt_h

    return round(max(0.0, energy_wh / 1000), 2)


def _integrate_grid_history(entity_id, start_dt):
    """Like _integrate_power_history but splits import (positive) and export (negative) kWh."""
    try:
        start_str = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
        resp = requests.get(
            f"{HASS_URL}/api/history/period/{start_str}",
            params={'filter_entity_id': entity_id, 'minimal_response': 'true', 'no_attributes': 'true'},
            headers=_get_ha_headers(),
            timeout=15
        )
        states = resp.json()[0] if resp.ok and resp.json() else []
    except Exception as e:
        logger.warning(f"Failed to fetch grid history for {entity_id}: {e}")
        return 0.0, 0.0

    import_wh = 0.0
    export_wh = 0.0
    prev_power = 0.0
    prev_time = start_dt.replace(tzinfo=timezone.utc)

    for s in states:
        try:
            power = float(s['state'])
        except (ValueError, KeyError, TypeError):
            power = prev_power
        try:
            ts = datetime.fromisoformat(s['last_changed'].replace('Z', '+00:00'))
        except (KeyError, ValueError):
            continue
        dt_h = (ts - prev_time).total_seconds() / 3600
        if dt_h > 0:
            wh = prev_power * dt_h
            if wh >= 0:
                import_wh += wh
            else:
                export_wh += abs(wh)
        prev_power, prev_time = power, ts

    now_utc = datetime.now(timezone.utc)
    dt_h = (now_utc - prev_time).total_seconds() / 3600
    if dt_h > 0:
        wh = prev_power * dt_h
        if wh >= 0:
            import_wh += wh
        else:
            export_wh += abs(wh)

    return round(import_wh / 1000, 2), round(export_wh / 1000, 2)


@app.route('/api/energy/today')
def energy_today():
    try:
        now_local = datetime.now()
        midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        except Exception:
            config = {}

        solar_kwh = 0.0
        if config.get('solar_generation'):
            solar_kwh = _integrate_power_history(config['solar_generation'], midnight)

        grid_import_kwh = 0.0
        grid_export_kwh = 0.0
        if config.get('grid_power'):
            grid_import_kwh, grid_export_kwh = _integrate_grid_history(config['grid_power'], midnight)

        devices_out = []
        for device_state in controller.device_states.values():
            device = device_state.device
            if device.energy_sensor and device.energy_delivered_today is not None:
                kwh = round(max(0.0, device.energy_delivered_today), 2)
                if kwh > 0:
                    devices_out.append({'name': device.name, 'kwh': kwh})

        total_in = solar_kwh + grid_import_kwh
        known_out = sum(d['kwh'] for d in devices_out)
        other_kwh = round(max(0.0, total_in - known_out - grid_export_kwh), 2)

        return jsonify({
            'solar_kwh': solar_kwh,
            'grid_import_kwh': grid_import_kwh,
            'grid_export_kwh': grid_export_kwh,
            'devices': devices_out,
            'other_kwh': other_kwh,
            'as_of': now_local.strftime('%H:%M')
        })
    except Exception as e:
        logger.error(f"Error computing energy today: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400


# Get port from environment
port = int(os.environ.get('PORT', 5000))
logger.info(f"Starting Flask application on port {port}")

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    logger.info(f"Static folder: {app.static_folder}")
    logger.info(f"Static URL path: {app.static_url_path}")
    logger.info(f"Template folder: {app.template_folder}")
    logger.info(f"Debug mode: {app.debug}")
    app.run(host='0.0.0.0', port=port)
 