import logging
import requests
import os
from datetime import datetime

logger = logging.getLogger(__name__)

def get_sunrise_time() -> str:
    """Get the sunrise time from Home Assistant"""
    try:
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if not supervisor_token:
            logger.error("No supervisor token found in environment")
            return None

        headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        }
        
        hass_url = "http://supervisor/core"
        
        # Get sunrise time from sun.sun entity
        response = requests.get(
            f"{hass_url}/api/states/sun.sun",
            headers=headers
        )
        response.raise_for_status()
        sun_data = response.json()
        
        # Get the next sunrise time
        next_rising = sun_data.get('attributes', {}).get('next_rising')
        if next_rising:
            return next_rising
            
        logger.error("Could not get sunrise time from sun.sun entity")
        return None
        
    except Exception as e:
        logger.error(f"Failed to get sunrise time: {e}")
        return None 