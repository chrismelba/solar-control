import json
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class Battery:
    def __init__(self, 
                 size_kwh: float,
                 battery_percent_entity: str,
                 max_charging_speed_kw: Optional[float] = None,
                 expected_kwh_per_hour: Optional[float] = None,
                 bring_forward_mode: bool = False):
        """
        Initialize a Battery object.
        
        Args:
            size_kwh (float): Battery size in kWh
            battery_percent_entity (str): Home Assistant entity ID for battery percentage
            max_charging_speed_kw (float, optional): Maximum charging speed in kW
            expected_kwh_per_hour (float, optional): Expected kWh used per hour, subtracted from solar forecast
            bring_forward_mode (bool): Experimental mode to shift load forward in the day if battery is sufficiently charged
        """
        self.size_kwh = size_kwh
        self.battery_percent_entity = battery_percent_entity
        self.max_charging_speed_kw = max_charging_speed_kw
        self.expected_kwh_per_hour = expected_kwh_per_hour
        self.bring_forward_mode = bring_forward_mode

    def to_dict(self) -> dict:
        """Convert battery object to dictionary."""
        return {
            'size_kwh': self.size_kwh,
            'battery_percent_entity': self.battery_percent_entity,
            'max_charging_speed_kw': self.max_charging_speed_kw,
            'expected_kwh_per_hour': self.expected_kwh_per_hour,
            'bring_forward_mode': self.bring_forward_mode
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Battery':
        """Create a Battery object from a dictionary."""
        return cls(
            size_kwh=data['size_kwh'],
            battery_percent_entity=data['battery_percent_entity'],
            max_charging_speed_kw=data.get('max_charging_speed_kw'),
            expected_kwh_per_hour=data.get('expected_kwh_per_hour'),
            bring_forward_mode=data.get('bring_forward_mode', False)  # Default to False for backward compatibility
        )

    @classmethod
    def load(cls, file_path: str) -> Optional['Battery']:
        """Load battery configuration from file."""
        try:
            if not os.path.exists(file_path):
                return None
                
            with open(file_path, 'r') as f:
                data = json.load(f)
                return cls.from_dict(data)
        except Exception as e:
            logger.error(f"Error loading battery configuration: {e}")
            return None

    def save(self, file_path: str) -> bool:
        """Save battery configuration to file."""
        try:
            logger.debug(f"Saving battery configuration to {file_path}")
            logger.debug(f"Battery data to save: {self.to_dict()}")
            
            # Ensure the directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w') as f:
                json.dump(self.to_dict(), f, indent=4)
            
            logger.info(f"Successfully saved battery configuration to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving battery configuration to {file_path}: {e}")
            return False 