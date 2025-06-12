import logging
import requests
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
import json

def setup_logging():
    """Centralized logging configuration for the application"""
    try:
        # Read debug level directly from options.json
        options_file = '/data/options.json'
        if os.path.exists(options_file):
            with open(options_file, 'r') as f:
                config = json.load(f)
            print(f"Retrieved config from options.json: {config}")
            debug_level = config.get('debug_level', 'info').upper()
            print(f"Debug level from config: {debug_level}")
        else:
            print(f"Options file not found at {options_file}")
            debug_level = 'INFO'
    except Exception as e:
        print(f"Error reading options file: {str(e)}")
        debug_level = 'INFO'  # Default to INFO level

    # Create logs directory if it doesn't exist
    log_dir = '/data/logs'
    os.makedirs(log_dir, exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, debug_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),  # Log to console
            RotatingFileHandler(
                filename=os.path.join(log_dir, 'solar-control.log'),
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
        ]
    )

    # Create logger
    logger = logging.getLogger(__name__)
    logger.info(f"Logging level set to: {debug_level}")
    return logger

def set_mqtt_settings():
    """Configure MQTT settings from environment variables if running as HA add-on"""
    try:
        if os.environ.get("IS_HA_ADDON"):
            # Read current settings
            options_file = '/data/options.json'
            if not os.path.exists(options_file):
                logger.error("Options file not found")
                return None
                
            with open(options_file, 'r') as f:
                settings = json.load(f)
            
            # Check if MQTT settings are set to auto
            if settings.get('mqtt', {}).get('broker') != "auto_broker" \
                    or settings.get('mqtt', {}).get('port') != "auto_port" \
                    or settings.get('mqtt', {}).get('username') != "auto_user" \
                    or settings.get('mqtt', {}).get('password') != "auto_password":
                # If settings were manually set, use the manually set settings
                return settings.get('mqtt')

            # Get MQTT settings from environment
            broker_host = os.getenv("MQTTHOST", None)
            broker_port = os.getenv("MQTTPORT", None)
            broker_user = os.getenv("MQTTUSER", None)
            broker_pass = os.getenv("MQTTPASS", None)

            if not broker_host or not broker_port:
                logger.error("MQTT connection could not be established. Please check if your MQTT Add-On is running!")
                return None

            logger.debug(f"MQTT Credentials - Host: {broker_host} Port: {broker_port} User: {broker_user} Pass: {'*' * len(broker_pass) if broker_pass else 'None'}")

            # Update settings
            if 'mqtt' not in settings:
                settings['mqtt'] = {}
                
            settings['mqtt'].update({
                'broker': broker_host,
                'port': broker_port,
                'username': broker_user,
                'password': broker_pass
            })

            # Save updated settings
            with open(options_file, 'w') as f:
                json.dump(settings, f, indent=4)

            return settings['mqtt']
            
        return None
    except Exception as e:
        logger.error(f"Error setting MQTT settings: {e}")
        return None

def get_sunrise_time():
    try:
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if not supervisor_token:
            logger.error("No supervisor token found in environment")
            return None

        headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        }

        # Get history for the past 24 hours
        response = requests.get(
            'http://supervisor/core/api/history/period',
            params={
                'filter_entity_id': 'sun.sun',
                'minimal_response': 'true'
            },
            headers=headers
        )
        response.raise_for_status()
        
        history = response.json()
        if not history or not history[0]:
            return None

        # Find the most recent transition from below_horizon to above_horizon
        for state in reversed(history[0]):
            if state.get('state') == 'above_horizon':
                # Parse the UTC time string
                utc_time = datetime.fromisoformat(state.get('last_changed').replace('Z', '+00:00'))
                # Convert to local time
                local_time = utc_time.astimezone()
                return local_time.isoformat()
        
        return None
    except Exception as e:
        logger.error(f"Error fetching sunrise time: {e}")
        return None
