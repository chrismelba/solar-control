import logging
import requests
import os
from datetime import datetime

logger = logging.getLogger(__name__)

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
