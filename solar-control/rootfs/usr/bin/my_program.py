from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash, abort, json
import os
import logging
import json
import requests
from device import Device
from datetime import datetime, timezone
import pytz
from solar_controller import SolarController

# Set up logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create static directory if it doesn't exist
static_dir = '/usr/bin/static'
if not os.path.exists(static_dir):
    logger.info(f"Creating static directory: {static_dir}")
    os.makedirs(static_dir)

app = Flask(__name__, 
           static_folder=static_dir,
           template_folder='templates')

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

# ... existing code ...
 