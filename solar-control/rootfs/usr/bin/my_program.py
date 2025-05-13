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
    response = requests.get('http://supervisor/addons/self/options')
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

@app.route('/')
def index():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving index page with ingress path: {ingress_path}")
    return make_response(render_template('index.html', ingress_path=ingress_path, basename=ingress_path))

@app.route('/debug')
def debug():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving debug page with ingress path: {ingress_path}")
    
    # Get Nginx logs
    nginx_error_log = ""
    nginx_access_log = ""
    try:
        with open('/data/nginx/logs/error.log', 'r') as f:
            nginx_error_log = f.read()
    except Exception as e:
        nginx_error_log = f"Error reading Nginx error log: {str(e)}"
    
    try:
        with open('/data/nginx/logs/access.log', 'r') as f:
            nginx_access_log = f.read()
    except Exception as e:
        nginx_access_log = f"Error reading Nginx access log: {str(e)}"

    # Get current configuration
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}

    # Get current environment
    env = {
        'PORT': os.environ.get('PORT', 'Not set'),
        'INGRESS_PATH': os.environ.get('INGRESS_PATH', 'Not set'),
        'HASS_URL': os.environ.get('HASS_URL', 'Not set'),
    }

    # Get request headers for debugging
    headers = dict(request.headers)

    return make_response(render_template('debug.html',
                         config=config,
                         env=env,
                         headers=headers,
                         nginx_error_log=nginx_error_log,
                         nginx_access_log=nginx_access_log,
                         ingress_path=ingress_path,
                         basename=ingress_path))

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
            'tariff_rate': request.form.get('tariff_rate')
        }
        
        # Save configuration
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        
        # Update controller configuration
        controller.update_config(config)
        
        return redirect(url_for('index'))
    
    # Load current configuration
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}
    
    # Get entities from Home Assistant
    try:
        response = requests.get('http://supervisor/core/api/states')
        entities = response.json()
    except Exception as e:
        logger.error(f"Error fetching entities: {e}")
        entities = []
    
    # Get sensor values
    sensor_values = {}
    for entity_id in ['solar_generation', 'grid_power', 'solar_forecast']:
        if entity_id in config and config[entity_id]:
            try:
                response = requests.get(f'http://supervisor/core/api/states/{config[entity_id]}')
                sensor_values[entity_id] = response.json()
            except Exception as e:
                logger.error(f"Error fetching {entity_id} value: {e}")
    
    return make_response(render_template('configure_grid.html', 
                         config=config, 
                         entities=entities,
                         sensor_values=sensor_values,
                         ingress_path=ingress_path,
                         basename=ingress_path))

@app.route('/configure/battery')
def configure_battery():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving configure battery page with ingress path: {ingress_path}")
    return make_response(render_template('configure_battery.html',
                         ingress_path=ingress_path,
                         basename=ingress_path))

@app.route('/configure/devices')
def configure_devices():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    logger.info(f"Serving configure devices page with ingress path: {ingress_path}")
    
    # Get entities from Home Assistant
    try:
        response = requests.get('http://supervisor/core/api/states')
        entities = response.json()
    except Exception as e:
        logger.error(f"Error fetching entities: {e}")
        entities = []
    
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
 