from dataclasses import dataclass
from typing import Optional
import json
import os

@dataclass
class Device:
    name: str
    switch_entity: str
    typical_power_draw: float  # in watts
    current_power_sensor: Optional[str] = None  # Home Assistant entity ID
    has_variable_amperage: bool = False
    min_amperage: Optional[float] = None  # in amps
    max_amperage: Optional[float] = None  # in amps
    min_on_time: int = 60  # in seconds
    min_off_time: int = 60  # in seconds
    run_once: bool = False
    completion_sensor: Optional[str] = None  # Home Assistant entity ID for completion status
    order: int = 0  # For drag-and-drop ordering

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'switch_entity': self.switch_entity,
            'typical_power_draw': self.typical_power_draw,
            'current_power_sensor': self.current_power_sensor,
            'has_variable_amperage': self.has_variable_amperage,
            'min_amperage': self.min_amperage,
            'max_amperage': self.max_amperage,
            'min_on_time': self.min_on_time,
            'min_off_time': self.min_off_time,
            'run_once': self.run_once,
            'completion_sensor': self.completion_sensor,
            'order': self.order
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Device':
        return cls(**data)

    def save(self, devices_file: str):
        """Save this device to the devices configuration file"""
        try:
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