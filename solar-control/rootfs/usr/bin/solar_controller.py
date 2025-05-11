#!/usr/bin/python3

import logging
import time
from datetime import datetime, timezone
import requests
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from device import Device
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class DeviceState:
    """Tracks the current state of a device"""
    device: Device
    is_on: bool = False
    last_state_change: datetime = None
    current_amperage: Optional[float] = None
    has_completed: bool = False

class SolarController:
    def __init__(self, config_file: str, devices_file: str):
        self.config_file = config_file
        self.devices_file = devices_file
        self.settings_file = '/data/settings.json'
        self.device_states: Dict[str, DeviceState] = {}
        self.supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        self.hass_url = "http://supervisor/core"
        
    def get_headers(self) -> dict:
        """Get headers for Home Assistant API requests"""
        return {
            "Authorization": f"Bearer {self.supervisor_token}",
            "Content-Type": "application/json",
        }
        
    def get_grid_voltage(self) -> float:
        """Get the current grid voltage"""
        config = self.load_config()
        if config.get('grid_voltage_fixed'):
            return float(config['grid_voltage_fixed'])
            
        if not config.get('grid_voltage'):
            logger.error("No grid voltage configured")
            return 230.0  # Default to 230V if not configured
            
        try:
            response = requests.get(
                f"{self.hass_url}/api/states/{config['grid_voltage']}", 
                headers=self.get_headers()
            )
            response.raise_for_status()
            return float(response.json().get('state', 230.0))
        except Exception as e:
            logger.error(f"Failed to get grid voltage: {e}")
            return 230.0  # Default to 230V on error
            
    def get_available_power(self) -> float:
        """Calculate available power by subtracting non-controllable loads from grid power"""
        config = self.load_config()
        if not config.get('grid_power'):
            logger.error("No grid power sensor configured")
            return 0.0
            
        try:
            response = requests.get(
                f"{self.hass_url}/api/states/{config['grid_power']}", 
                headers=self.get_headers()
            )
            response.raise_for_status()
            grid_power = float(response.json().get('state', 0))
            
            # Convert to watts if needed
            unit = response.json().get('attributes', {}).get('unit_of_measurement', 'W')
            if unit.lower() == 'kw':
                grid_power *= 1000
                
            return max(0, grid_power)  # Don't return negative power
        except Exception as e:
            logger.error(f"Failed to get available power: {e}")
            return 0.0
            
    def load_config(self) -> dict:
        """Load configuration from file"""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}
            
    def load_settings(self) -> dict:
        """Load settings from file"""
        try:
            with open(self.settings_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            return {'power_optimization_enabled': True}  # Default to enabled
            
    def initialize_device_states(self):
        """Initialize or update device states"""
        devices = Device.load_all(self.devices_file)
        current_time = datetime.now(timezone.utc)
        
        # Update existing states
        for device in devices:
            if device.name not in self.device_states:
                self.device_states[device.name] = DeviceState(
                    device=device,
                    last_state_change=current_time
                )
            else:
                # Update device reference in case it changed
                self.device_states[device.name].device = device
                
        # Remove states for devices that no longer exist
        self.device_states = {
            name: state for name, state in self.device_states.items()
            if name in {d.name for d in devices}
        }
        
    def get_device_power(self, device_state: DeviceState) -> float:
        """Calculate the current power draw of a device"""
        if not device_state.is_on:
            return 0.0
            
        device = device_state.device
        
        # If device has a power sensor, use that
        if device.current_power_sensor:
            try:
                response = requests.get(
                    f"{self.hass_url}/api/states/{device.current_power_sensor}",
                    headers=self.get_headers()
                )
                response.raise_for_status()
                power = float(response.json().get('state', 0))
                
                # Convert to watts if needed
                unit = response.json().get('attributes', {}).get('unit_of_measurement', 'W')
                if unit.lower() == 'kw':
                    power *= 1000
                    
                return power
            except Exception as e:
                logger.error(f"Failed to get power for {device.name}: {e}")
                
        # If device has variable amperage, calculate power
        if device.has_variable_amperage and device_state.current_amperage is not None:
            voltage = self.get_grid_voltage()
            return voltage * device_state.current_amperage
            
        # Fall back to typical power draw
        return device.typical_power_draw
        
    def check_device_completion(self, device_state: DeviceState) -> bool:
        """Check if a run-once device has completed its task"""
        if not device_state.device.completion_sensor:
            return False
            
        try:
            response = requests.get(
                f"{self.hass_url}/api/states/{device_state.device.completion_sensor}",
                headers=self.get_headers()
            )
            response.raise_for_status()
            return response.json().get('state', 'off').lower() == 'on'
        except Exception as e:
            logger.error(f"Failed to check completion for {device_state.device.name}: {e}")
            return False
            
    def set_device_state(self, device_state: DeviceState, turn_on: bool, amperage: Optional[float] = None):
        """Set a device's state in Home Assistant"""
        device = device_state.device
        current_time = datetime.now(timezone.utc)
        
        try:
            # Set switch state
            response = requests.post(
                f"{self.hass_url}/api/services/switch/turn_{'on' if turn_on else 'off'}",
                headers=self.get_headers(),
                json={"entity_id": device.switch_entity}
            )
            response.raise_for_status()
            
            # Update state tracking
            device_state.is_on = turn_on
            device_state.last_state_change = current_time
            
            # Set amperage if applicable
            if turn_on and device.has_variable_amperage and amperage is not None:
                # This assumes there's a service to set the amperage
                # You'll need to implement this based on your specific devices
                response = requests.post(
                    f"{self.hass_url}/api/services/switch/set_amperage",
                    headers=self.get_headers(),
                    json={
                        "entity_id": device.switch_entity,
                        "amperage": amperage
                    }
                )
                response.raise_for_status()
                device_state.current_amperage = amperage
                
        except Exception as e:
            logger.error(f"Failed to set state for {device.name}: {e}")
            
    def calculate_optimal_amperage(self, device: Device, available_power: float) -> float:
        """Calculate the optimal amperage for a variable amperage device"""
        if not device.has_variable_amperage:
            return None
            
        voltage = self.get_grid_voltage()
        max_amperage = min(
            device.max_amperage,
            available_power / voltage
        )
        
        return max(device.min_amperage, max_amperage)
        
    def run_control_loop(self):
        """Main control loop"""
        while True:
            try:
                # Initialize/update device states
                self.initialize_device_states()
                
                # Get current conditions
                available_power = self.get_available_power()
                voltage = self.get_grid_voltage()
                current_time = datetime.now(timezone.utc)
                
                # Load settings
                settings = self.load_settings()
                power_optimization_enabled = settings.get('power_optimization_enabled', True)
                
                # First pass: Handle mandatory devices
                for device_state in self.device_states.values():
                    device = device_state.device
                    
                    # Check if device has completed its task
                    if device.run_once and device_state.is_on:
                        if self.check_device_completion(device_state):
                            device_state.has_completed = True
                            self.set_device_state(device_state, False)
                            continue
                            
                    # Check minimum on/off times
                    if device_state.last_state_change:
                        time_since_change = (current_time - device_state.last_state_change).total_seconds()
                        
                        if device_state.is_on and time_since_change < device.min_on_time:
                            # Must stay on
                            power = self.get_device_power(device_state)
                            available_power -= power
                            continue
                            
                        if not device_state.is_on and time_since_change < device.min_off_time:
                            # Must stay off
                            continue
                
                # Only run optimization if enabled
                if power_optimization_enabled:
                    # Second pass: Handle optional devices by priority
                    # Sort devices by their order (priority)
                    sorted_devices = sorted(
                        self.device_states.values(),
                        key=lambda x: x.device.order
                    )
                    
                    for device_state in sorted_devices:
                        device = device_state.device
                        
                        # Skip if device is already on
                        if device_state.is_on:
                            continue
                            
                        # Skip if device has completed its task
                        if device.run_once and device_state.has_completed:
                            continue
                            
                        # Calculate power needed
                        if device.has_variable_amperage:
                            optimal_amperage = self.calculate_optimal_amperage(device, available_power)
                            if optimal_amperage is None:
                                continue
                            power_needed = voltage * optimal_amperage
                        else:
                            power_needed = device.typical_power_draw
                            
                        # Check if we have enough power
                        if power_needed <= available_power:
                            if device.has_variable_amperage:
                                self.set_device_state(device_state, True, optimal_amperage)
                            else:
                                self.set_device_state(device_state, True)
                            available_power -= power_needed
                else:
                    # If optimization is disabled, turn off all devices that aren't mandatory
                    for device_state in self.device_states.values():
                        device = device_state.device
                        
                        # Skip if device is mandatory (run-once and not completed)
                        if device.run_once and not device_state.has_completed:
                            continue
                            
                        # Skip if device is in minimum on time
                        if device_state.is_on and device_state.last_state_change:
                            time_since_change = (current_time - device_state.last_state_change).total_seconds()
                            if time_since_change < device.min_on_time:
                                continue
                                
                        # Turn off the device
                        if device_state.is_on:
                            self.set_device_state(device_state, False)
                        
                # Sleep for a minute
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in control loop: {e}")
                time.sleep(60)  # Sleep on error too
                
if __name__ == "__main__":
    controller = SolarController(
        config_file="/data/solar_config.json",
        devices_file="/data/devices.json"
    )
    controller.run_control_loop() 