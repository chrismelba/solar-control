from dataclasses import dataclass
from typing import Optional
import json
import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class Device:
    name: str
    switch_entity: str
    typical_power_draw: float  # in watts
    current_power_sensor: Optional[str] = None  # Home Assistant entity ID
    energy_sensor: Optional[str] = None  # Home Assistant entity ID for energy consumption
    power_delivery_sensor: Optional[str] = None  # Home Assistant entity ID for power delivery
    has_variable_amperage: bool = False
    min_amperage: Optional[float] = None  # in amps
    max_amperage: Optional[float] = None  # in amps
    variable_amperage_control: Optional[str] = None  # Home Assistant entity ID for controlling amperage
    min_on_time: int = 60  # in seconds
    min_off_time: int = 60  # in seconds
    run_once: bool = False
    completion_sensor: Optional[str] = None  # Home Assistant entity ID for completion status
    order: int = 0  # For drag-and-drop ordering
    energy_delivered_today: float = 0.0  # in watt-hours
    last_power_update: Optional[datetime] = None
    last_dawn_reset: Optional[datetime] = None
    min_daily_power: Optional[float] = None  # Minimum power required per day in watt-hours

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'switch_entity': self.switch_entity,
            'typical_power_draw': self.typical_power_draw,
            'current_power_sensor': self.current_power_sensor,
            'energy_sensor': self.energy_sensor,
            'power_delivery_sensor': self.power_delivery_sensor,
            'has_variable_amperage': self.has_variable_amperage,
            'min_amperage': self.min_amperage,
            'max_amperage': self.max_amperage,
            'variable_amperage_control': self.variable_amperage_control,
            'min_on_time': self.min_on_time,
            'min_off_time': self.min_off_time,
            'run_once': self.run_once,
            'completion_sensor': self.completion_sensor,
            'order': self.order,
            'energy_delivered_today': self.energy_delivered_today,
            'last_power_update': self.last_power_update.isoformat() if self.last_power_update else None,
            'last_dawn_reset': self.last_dawn_reset.isoformat() if self.last_dawn_reset else None,
            'min_daily_power': self.min_daily_power
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Device':
        # Convert the ISO format strings back to datetime if they exist
        if 'last_power_update' in data and data['last_power_update']:
            data['last_power_update'] = datetime.fromisoformat(data['last_power_update'])
        if 'last_dawn_reset' in data and data['last_dawn_reset']:
            data['last_dawn_reset'] = datetime.fromisoformat(data['last_dawn_reset'])
        return cls(**data)

    def update_power_delivered(self, current_power: float) -> None:
        """Update the energy delivered tracking"""
        now = datetime.now()
        
        # Check if we need to reset (dawn condition)
        if self.should_reset_power_tracking():
            self.energy_delivered_today = 0.0
            self.last_power_update = now
            self.last_dawn_reset = now
            return

        # Calculate energy delivered since last update
        if self.last_power_update:
            time_diff = (now - self.last_power_update).total_seconds() / 3600  # Convert to hours
            self.energy_delivered_today += current_power * time_diff

        self.last_power_update = now

    def should_reset_power_tracking(self) -> bool:
        """Check if power tracking should be reset based on dawn condition"""
        try:
            supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
            if not supervisor_token:
                return False

            headers = {
                "Authorization": f"Bearer {supervisor_token}",
                "Content-Type": "application/json",
            }
            
            hass_url = "http://supervisor/core"
            
            # Get the sun.sun entity state
            response = requests.get(
                f"{hass_url}/api/states/sun.sun",
                headers=headers
            )
            response.raise_for_status()
            sun_state = response.json()
            
            # Check if the sun has risen since our last reset
            if sun_state['state'] == 'above_horizon':
                if not self.last_dawn_reset:
                    return True
                
                # Get the last time the sun rose
                last_rise = datetime.fromisoformat(sun_state['attributes'].get('next_rising', '').replace('Z', '+00:00'))
                if last_rise > self.last_dawn_reset:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check dawn condition: {e}")
            return False

    def save(self, devices_file: str):
        """Save this device to the devices configuration file"""
        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(devices_file), exist_ok=True)
            
            # Load existing devices
            devices = []
            if os.path.exists(devices_file):
                with open(devices_file, 'r') as f:
                    devices = json.load(f)
            
            # Find and update or append this device
            found = False
            for i, device in enumerate(devices):
                if device['name'] == self.name:
                    devices[i] = self.to_dict()
                    found = True
                    break
            
            if not found:
                devices.append(self.to_dict())
            
            # Save back to file
            with open(devices_file, 'w') as f:
                json.dump(devices, f, indent=2)
                
        except Exception as e:
            raise Exception(f"Failed to save device: {str(e)}")

    @classmethod
    def load_all(cls, devices_file: str) -> list['Device']:
        """Load all devices from the configuration file"""
        if not os.path.exists(devices_file):
            return []
            
        with open(devices_file, 'r') as f:
            devices_data = json.load(f)
            
        return [cls.from_dict(device_data) for device_data in devices_data]

    @classmethod
    def delete(cls, name: str, devices_file: str):
        """Delete a device from the configuration file"""
        try:
            devices = cls.load_all(devices_file)
            devices = [d for d in devices if d.name != name]
            
            with open(devices_file, 'w') as f:
                json.dump([d.to_dict() for d in devices], f, indent=2)
                
        except Exception as e:
            raise Exception(f"Failed to delete device: {str(e)}")

    def set_state(self, state: bool) -> bool:
        """Set the state of the device in Home Assistant"""
        if not self.switch_entity:
            logger.debug(f"No switch entity defined for {self.name}")
            return False
            
        supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        if not supervisor_token:
            logger.debug("No supervisor token found in environment")
            return False
            
        try:
            headers = {
                "Authorization": f"Bearer {supervisor_token}",
                "Content-Type": "application/json",
            }
            
            hass_url = "http://supervisor/core"
            
            # First, get the entity state to determine its type
            logger.debug(f"Fetching entity state for {self.switch_entity}")
            response = requests.get(
                f"{hass_url}/api/states/{self.switch_entity}",
                headers=headers
            )
            response.raise_for_status()
            entity_data = response.json()
            logger.debug(f"Entity state response: {entity_data}")
            
            # Determine the domain and service based on entity type
            domain = entity_data['entity_id'].split('.')[0]
            service = "turn_on" if state else "turn_off"
            logger.debug(f"Detected domain: {domain}, using service: {service}")
            
            # Use the appropriate service based on the domain

            service_data = {"entity_id": self.switch_entity}
            
            logger.debug(f"Sending service call to {domain}.{service} with data: {service_data}")
            response = requests.post(
                f"{hass_url}/api/services/{domain}/{service}",
                headers=headers,
                json=service_data
            )
            
            response.raise_for_status()
            logger.debug(f"Service call response: {response.status_code} - {response.text}")
            return True
        except Exception as e:
            logger.error(f"Failed to set state for {self.name}: {e}")
            return False

    @staticmethod
    def save_all(devices: list, devices_file: str):
        """Save all devices to the configuration file"""
        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(devices_file), exist_ok=True)
            # Convert devices to list of dicts
            devices_data = [d.to_dict() for d in devices]
            with open(devices_file, 'w') as f:
                json.dump(devices_data, f, indent=2)
        except Exception as e:
            raise Exception(f"Failed to save all devices: {str(e)}") 