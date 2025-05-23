from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash, abort, json, make_response
import os
import logging
import json
import requests
from device import Device
from datetime import datetime, timezone
import pytz
from solar_controller import SolarController

# Get debug level from configuration
try:
    supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
    headers = {"Authorization": f"Bearer {supervisor_token}", "Content-Type": "application/json"} if supervisor_token else {}
    response = requests.get('http://supervisor/addons/self/options', headers=headers)
    config = response.json()
    debug_level = config.get('debug_level', 'info').upper()
except Exception as e:
    debug_level = 'DEBUG'

# Set up logging with configuration-based level
logging.basicConfig(
    level=getattr(logging, debug_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log the current debug level
logger.info(f"Logging level set to: {debug_level}")

# Create static directory if it doesn't exist
static_dir = '/usr/bin/static'
if not os.path.exists(static_dir):
    logger.info(f"Creating static directory: {static_dir}")
    os.makedirs(static_dir)

app = Flask(__name__, 
           static_folder=static_dir,
           template_folder='templates')

# Add a context processor to make the ingress path available in templates
@app.context_processor
def inject_ingress_path():
    # Get ingress path from header
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Using ingress path from header: {ingress_path}")
    logger.info(f"All request headers: {dict(request.headers)}")
    return dict(ingress_path=ingress_path, basename=ingress_path)

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

# Create controller instance
controller = SolarController(
    config_file="/data/solar_config.json",
    devices_file="/data/devices.json"
)

# Start the control loop
logger.info("Starting solar controller control loop...")
controller.start_control_loop()

# Log static file configuration
logger.info('Static folder: %s', app.static_folder)
logger.info('Static URL path: %s', app.static_url_path)
logger.info('Static files available:')
for root, dirs, files in os.walk(static_dir):
    for file in files:
        logger.info('  %s', os.path.join(root, file))

# Configuration file paths
CONFIG_FILE = '/data/solar_config.json'
DEVICES_FILE = '/data/devices.json'
SETTINGS_FILE = '/data/settings.json'

# Debug: Log data directory state
logger.info("Checking data directory state...")
logger.info(f"Data directory exists: {os.path.exists('/data')}")
logger.info(f"Data directory permissions: {oct(os.stat('/data').st_mode)[-3:]}")
logger.info(f"Data directory owner: {os.stat('/data').st_uid}")

# Ensure data directory exists
logger.info("Ensuring data directory exists...")
os.makedirs('/data', exist_ok=True)

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
                'power_optimization_enabled': False
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
    devices = Device.load_all(DEVICES_FILE)  # Load devices using the constant
    # Sort devices by their order property
    devices.sort(key=lambda x: x.order)
    sensor_values = get_sensor_values()  # Get sensor values
    return make_response(render_template('index.html', 
                         devices=devices,
                         sensor_values=sensor_values,
                         ingress_path=ingress_path,
                         basename=ingress_path))

@app.route('/<path:page>')
def static_page(page):
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving static page {page} with ingress path: {ingress_path}")
    
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
            'data': lambda: {}
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
    for entity_id in ['solar_generation', 'grid_power', 'solar_forecast']:
        if entity_id in config and config[entity_id]:
            try:
                response = requests.get(
                    f'http://supervisor/core/api/states/{config[entity_id]}',
                    headers=headers
                )
                response.raise_for_status()  # Raise exception for non-200 status codes
                sensor_values[entity_id] = response.json()
            except Exception as e:
                logger.error(f"Error fetching {entity_id} value: {e}")
    
    return sensor_values

def get_entities():
    try:
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        headers = {"Authorization": f"Bearer {supervisor_token}", "Content-Type": "application/json"} if supervisor_token else {}
        logger.info("Attempting to fetch entities from supervisor API")
        response = requests.get('http://supervisor/core/api/states', headers=headers)
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
        with open(f'/data/nginx/logs/{log_type}.log', 'r') as f:
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
            'site_export_limit': request.form.get('site_export_limit')
        }
        
        # Convert site_export_limit to float if provided
        if config['site_export_limit']:
            try:
                config['site_export_limit'] = float(config['site_export_limit'])
            except ValueError:
                config['site_export_limit'] = None
        else:
            config['site_export_limit'] = None
        
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
    
    # Load current configuration
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}
    
    return make_response(render_template('configure_battery.html',
                         config=config,
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
        devices = Device.load_all(DEVICES_FILE)
        device = next((d for d in devices if d.name == name), None)
        if device is None:
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        return jsonify(device.to_dict())
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices', methods=['GET'])
def get_devices():
    try:
        if not os.path.exists(DEVICES_FILE):
            return jsonify([])
        devices = Device.load_all(DEVICES_FILE)
        # Sort devices by their order property
        devices.sort(key=lambda x: x.order)
        return jsonify([device.to_dict() for device in devices])
    except Exception as e:
        logger.error(f"Error loading devices: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices', methods=['POST'])
def add_device():
    try:
        device_data = request.json
        devices = Device.load_all(DEVICES_FILE)
        
        # Check if device with same name exists
        if any(d.name == device_data['name'] for d in devices):
            return jsonify({'status': 'error', 'message': 'Device with this name already exists'}), 400
        
        # Set order to be the next available index
        device_data['order'] = len(devices)
        
        # Create new device
        device = Device(**device_data)
        devices.append(device)
        Device.save_all(devices, DEVICES_FILE)
        
        return jsonify(device.to_dict())
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>', methods=['PUT'])
def update_device(name):
    try:
        device_data = request.json
        devices = Device.load_all(DEVICES_FILE)
        
        # Find device
        device_index = next((i for i, d in enumerate(devices) if d.name == name), None)
        if device_index is None:
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        
        # Preserve the existing order if not provided in the update
        if 'order' not in device_data:
            device_data['order'] = devices[device_index].order
        
        # Update device
        devices[device_index] = Device(**device_data)
        Device.save_all(devices, DEVICES_FILE)
        
        return jsonify(devices[device_index].to_dict())
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>', methods=['DELETE'])
def delete_device(name):
    try:
        devices = Device.load_all(DEVICES_FILE)
        
        # Find and remove device
        devices = [d for d in devices if d.name != name]
        Device.save_all(devices, DEVICES_FILE)
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/reorder', methods=['POST'])
def reorder_devices():
    try:
        order_data = request.get_json()
        if not order_data or not isinstance(order_data, list):
            return jsonify({'status': 'error', 'message': 'Invalid order data format'}), 400
            
        devices = Device.load_all(DEVICES_FILE)
        device_dict = {d.name: d for d in devices}
        
        # Update order for each device
        for item in order_data:
            if not isinstance(item, dict) or 'name' not in item or 'order' not in item:
                return jsonify({'status': 'error', 'message': 'Invalid device order item format'}), 400
                
            device = device_dict.get(item['name'])
            if device:
                device.order = int(item['order'])
        
        # Save updated devices
        Device.save_all(list(device_dict.values()), DEVICES_FILE)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error reordering devices: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/status', methods=['GET'])
def get_status():
    try:
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
        
        return jsonify({
            'status': 'running',
            'version': '1.0.0',  # TODO: Get actual version
            'power_optimization_enabled': settings.get('power_optimization_enabled', False)
        })
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/settings/power_optimization', methods=['POST'])
def update_power_optimization():
    try:
        data = request.json
        enabled = data.get('enabled', False)
        
        # Load current settings
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            settings = {}
        
        # Update settings
        settings['power_optimization_enabled'] = enabled
        
        # Save settings
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>/state', methods=['GET'])
def get_device_state(name):
    try:
        logger.debug(f"Getting state for device: {name}")
        devices = Device.load_all(DEVICES_FILE)
        logger.debug(f"Loaded {len(devices)} devices from file")
        
        device = next((d for d in devices if d.name == name), None)
        if device is None:
            logger.error(f"Device not found: {name}")
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404

        logger.debug(f"Found device: {device.name}, switch_entity: {device.switch_entity}")

        # Get the current state from Home Assistant
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if not supervisor_token:
            logger.error("No supervisor token available in environment")
            return jsonify({'status': 'error', 'message': 'No supervisor token available'}), 500

        headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        }

        logger.debug(f"Making request to Home Assistant API for entity: {device.switch_entity}")
        response = requests.get(
            f"http://supervisor/core/api/states/{device.switch_entity}",
            headers=headers
        )
        logger.debug(f"Home Assistant API response status: {response.status_code}")
        
        response.raise_for_status()
        state = response.json().get('state', 'off')
        logger.debug(f"Retrieved state for device {name}: {state}")
        
        return jsonify({'state': state})
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error getting device state for {name}: {e}")
        return jsonify({'status': 'error', 'message': f'Network error: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error getting device state for {name}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices/<name>/set_state', methods=['POST'])
def set_device_state(name):
    try:
        logger.debug(f"Received set_state request for device: {name}")
        data = request.get_json()
        logger.debug(f"Request data: {data}")
        
        if not data or 'state' not in data:
            logger.error(f"Invalid request data: {data}")
            return jsonify({'status': 'error', 'message': 'Invalid request data'}), 400

        devices = Device.load_all(DEVICES_FILE)
        logger.debug(f"Loaded {len(devices)} devices from file")
        device = next((d for d in devices if d.name == name), None)
        
        if device is None:
            logger.error(f"Device not found: {name}")
            return jsonify({'status': 'error', 'message': 'Device not found'}), 404

        logger.debug(f"Found device: {device.name}, switch_entity: {device.switch_entity}")
        logger.debug(f"Attempting to set state to: {data['state']}")
        
        # Set the device state using the explicit set_state method
        success = device.set_state(data['state'])
        if not success:
            logger.error(f"Failed to set state for device {name}")
            return jsonify({'status': 'error', 'message': 'Failed to set device state'}), 500

        logger.debug(f"Successfully set state for device {name}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error setting device state for {name}: {e}")
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
 