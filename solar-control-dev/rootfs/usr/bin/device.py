from dataclasses import dataclass
from typing import Optional
import json
import os
import requests
import logging
from datetime import datetime, timezone
from utils import get_sunrise_time, setup_logging

# Configure logging
logger = setup_logging()

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
            'min_daily_power': self.min_daily_power
        }

    @staticmethod
    def _safe_convert(value: any, target_type: type) -> any:
        """Safely convert a value to the target type, handling None and empty strings.
        
        Args:
            value: The value to convert
            target_type: The type to convert to (float, int, etc.)
            
        Returns:
            The converted value, or None if conversion is not possible
        """
        if value in [None, '']:
            return None
        try:
            return target_type(value)
        except (ValueError, TypeError):
            return None

    @classmethod
    def from_dict(cls, data: dict) -> 'Device':
        # Convert numeric values to their correct types
        converted_data = data.copy()
        
        # Define the conversion rules
        conversions = {
            'typical_power_draw': float,
            'min_amperage': float,
            'max_amperage': float,
            'min_on_time': int,
            'min_off_time': int,
            'order': int,
            'energy_delivered_today': float,
            'min_daily_power': float
        }
        
        # Apply conversions
        for field, target_type in conversions.items():
            if field in converted_data:
                converted_data[field] = cls._safe_convert(converted_data[field], target_type)
        
        return cls(**converted_data)

    def update_energy_delivered(self) -> None:
        """Update the energy delivered tracking using Home Assistant history API"""
        if not self.energy_sensor:
            return

        try:
            supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
            if not supervisor_token:
                logger.error("No supervisor token found in environment")
                return

            headers = {
                "Authorization": f"Bearer {supervisor_token}",
                "Content-Type": "application/json",
            }
            
            hass_url = "http://supervisor/core"
            
            # Get sunrise time using existing function
            sunrise_time = get_sunrise_time()
            if not sunrise_time:
                logger.error("Failed to get sunrise time")
                return
                
            # Parse the sunrise time and ensure it's in UTC
            last_rise = datetime.fromisoformat(sunrise_time)
            if last_rise.tzinfo is None:
                # If no timezone info, assume it's in UTC
                last_rise = last_rise.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC if it has timezone info
                last_rise = last_rise.astimezone(timezone.utc)
            
            # Get current energy value and check its unit
            response = requests.get(
                f"{hass_url}/api/states/{self.energy_sensor}",
                headers=headers
            )
            response.raise_for_status()
            current_state = response.json()
            
            # Check the unit of measurement
            unit_of_measurement = current_state.get('attributes', {}).get('unit_of_measurement', '')
            
            # Get energy sensor value at dawn
            dawn_time = last_rise.isoformat()
            response = requests.get(
                f"{hass_url}/api/history/period/{dawn_time}",
                params={
                    'filter_entity_id': self.energy_sensor,
                    'minimal_response': 'true'
                },
                headers=headers
            )
            response.raise_for_status()
            history = response.json()
            
            if not history or not history[0]:
                logger.error(f"No history data found for {self.energy_sensor} after {dawn_time}")
                return
                
            # Get the first reading after dawn
            dawn_energy = None
            for reading in history[0]:
                try:
                    dawn_energy = float(reading.get('state', 0))
                    # Convert to kWh if the sensor is in Wh
                    if unit_of_measurement.lower() in ['wh', 'watt-hour', 'watt-hours']:
                        dawn_energy = dawn_energy / 1000
                    break
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid energy reading at dawn: {reading.get('state')}")
                    continue
            
            if dawn_energy is None:
                logger.error(f"Could not find valid energy reading after dawn for {self.energy_sensor}")
                return
                
            # Get current energy value
            current_energy = float(current_state.get('state', 0))
            # Convert to kWh if the sensor is in Wh
            if unit_of_measurement.lower() in ['wh', 'watt-hour', 'watt-hours']:
                current_energy = current_energy / 1000
            
            # Calculate energy delivered today
            self.energy_delivered_today = current_energy - dawn_energy
            logger.info(f"Updated energy delivered for {self.name}: {self.energy_delivered_today:.2f} kWh")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error while updating energy delivered for {self.name}: {e}")
        except Exception as e:
            logger.error(f"Failed to update energy delivered for {self.name}: {e}", exc_info=True)

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