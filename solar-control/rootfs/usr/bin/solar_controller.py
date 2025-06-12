#!/usr/bin/python3

import logging
import time
from datetime import datetime, timezone
import requests
import os
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from device import Device
import json
from utils import setup_logging

# Configure logging
logger = setup_logging()




@dataclass
class DeviceState:
    """Tracks the current state of a device"""
    device: Device
    is_on: bool = False
    last_state_change: datetime = None
    current_amperage: Optional[float] = None
    has_completed: bool = False

@dataclass
class DebugState:
    """Tracks debug information about the controller's decisions"""
    timestamp: datetime
    available_power: float
    grid_voltage: float
    grid_power: float
    mandatory_devices: List[Dict] = None
    optional_devices: List[Dict] = None
    power_optimization_enabled: bool = True
    manual_power_override: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'available_power': self.available_power,
            'grid_voltage': self.grid_voltage,
            'grid_power': self.grid_power,
            'mandatory_devices': self.mandatory_devices or [],
            'optional_devices': self.optional_devices or [],
            'power_optimization_enabled': self.power_optimization_enabled,
            'manual_power_override': self.manual_power_override
        }

class SolarController:
    def __init__(self, config_file: str, devices_file: str):
        self.config_file = config_file
        self.devices_file = devices_file
        self.settings_file = '/data/settings.json'
        self.device_states: Dict[str, DeviceState] = {}
        self.supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
        self.hass_url = "http://supervisor/core"
        self.debug_state: Optional[DebugState] = None
        self.manual_power_override: Optional[float] = None
        
    def get_headers(self) -> dict:
        """Get headers for Home Assistant API requests"""
        return {
            "Authorization": f"Bearer {self.supervisor_token}",
            "Content-Type": "application/json",
            "X-Solar-Controller": "solar-control-addon"  # Add custom header to identify our addon
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
            logger.debug(f"Fetching grid voltage from {config['grid_voltage']}")
            response = requests.get(
                f"{self.hass_url}/api/states/{config['grid_voltage']}", 
                headers=self.get_headers()
            )
            response.raise_for_status()
            voltage = float(response.json().get('state', 230.0))
            logger.debug(f"Grid voltage: {voltage}V")
            return voltage
        except Exception as e:
            logger.error(f"Failed to get grid voltage: {e}")
            return 230.0  # Default to 230V on error
            
    def get_available_power(self) -> float:
        """Calculate available power by subtracting controlled loads from grid power.
        Negative grid power means we're exporting to the grid, which is available power.
        Positive grid power means we're importing from the grid.
        We subtract the power consumption of all controlled devices to get the true available power.
        If tariff mode is 'free', returns effectively unlimited power."""
        if self.manual_power_override is not None:
            logger.info(f"Using manual power override: {self.manual_power_override}W")
            return self.manual_power_override

        # Check if we're in free tariff mode
        if self.get_current_tariff_mode() == 'free':
            logger.info("Free tariff mode - returning unlimited power")
            return float('inf')  # Return effectively unlimited power

        config = self.load_config()
        if not config.get('grid_power'):
            logger.error("No grid power sensor configured")
            return 0.0
            
        try:
            logger.debug(f"Fetching grid power from {config['grid_power']}")
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
                logger.debug(f"Converted grid power from kW to W: {grid_power}W")
                
            # Calculate total power consumption of controlled devices
            controlled_power = 0.0
            for device_state in self.device_states.values():
                if device_state.is_on:
                    power = self.get_device_power(device_state)
                    controlled_power += power
                    logger.debug(f"Device {device_state.device.name} consuming {power}W")
            
            # Subtract controlled power from grid power
            available_power = -grid_power + controlled_power
            logger.debug(f"Grid power: {grid_power}W, Controlled power: {controlled_power}W, Available power: {available_power}W")
            
            # Apply site export limit if configured
            site_export_limit = config.get('site_export_limit')
            if site_export_limit is not None and isinstance(site_export_limit, (int, float)):
                if grid_power < -site_export_limit:
                    available_power = max(0, available_power - (abs(grid_power) - site_export_limit))
                    logger.debug(f"Applied site export limit of {site_export_limit}W, new available power: {available_power}W")
            else:
                logger.debug("No valid site export limit configured, proceeding without export limit")
            
            return max(0, available_power)
            
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
            
    def get_device_state_from_hass(self, device: Device) -> bool:
        """Get the current state of a device from Home Assistant"""
        try:
            logger.debug(f"Fetching state for device {device.name} from {device.switch_entity}")
            response = requests.get(
                f"{self.hass_url}/api/states/{device.switch_entity}",
                headers=self.get_headers()
            )
            response.raise_for_status()
            state = response.json().get('state', 'off').lower() == 'on'
            logger.debug(f"Device {device.name} state: {'on' if state else 'off'}")
            return state
        except Exception as e:
            logger.error(f"Failed to get state for {device.name}: {e}")
            return False

    def initialize_device_states(self):
        """Initialize or update device states"""
        devices = Device.load_all(self.devices_file)
        current_time = datetime.now(timezone.utc)
        initial_time = 0 
        
        # Update existing states
        for device in devices:
            if device.name not in self.device_states:
                # Get current state from Home Assistant
                is_on = self.get_device_state_from_hass(device)
                self.device_states[device.name] = DeviceState(
                    device=device,
                    is_on=is_on,
                    last_state_change=initial_time
                )
            else:
                # Update device reference in case it changed
                self.device_states[device.name].device = device
                # Update current state from Home Assistant
                self.device_states[device.name].is_on = self.get_device_state_from_hass(device)
                
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
                logger.debug(f"Fetching power for {device.name} from {device.current_power_sensor}")
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
                    logger.debug(f"Converted power for {device.name} from kW to W: {power}W")
                    
                logger.debug(f"Device {device.name} power: {power}W")
                return power
            except Exception as e:
                logger.error(f"Failed to get power for {device.name}: {e}")
                
        # If device has variable amperage, calculate power
        if device.has_variable_amperage and device_state.current_amperage is not None:
            voltage = self.get_grid_voltage()
            power = voltage * device_state.current_amperage
            logger.debug(f"Calculated power for {device.name} from amperage: {power}W ({voltage}V * {device_state.current_amperage}A)")
            return power
            
        # Fall back to typical power draw
        logger.debug(f"Using typical power draw for {device.name}: {device.typical_power_draw}W")
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
            # For variable load devices, we can always set the amperage
            if device.has_variable_amperage and amperage is not None:
                logger.info(f"Setting amperage for {device.name} to {amperage}A")
                logger.debug(f"Device details - min_amperage: {device.min_amperage}A, max_amperage: {device.max_amperage}A")
                logger.debug(f"Control entity: {device.variable_amperage_control}")
                
                service_data = {
                    "entity_id": device.variable_amperage_control,
                    "value": amperage
                }
                logger.debug(f"Sending request to Home Assistant: {service_data}")
                
                # First check the entity type
                try:
                    logger.debug(f"Checking entity type for {device.variable_amperage_control}")
                    entity_response = requests.get(
                        f"{self.hass_url}/api/states/{device.variable_amperage_control}",
                        headers=self.get_headers()
                    )
                    entity_response.raise_for_status()
                    entity_type = entity_response.json().get('entity_id', '').split('.')[0]
                    
                    # Use appropriate service based on entity type
                    service = "input_number/set_value" if entity_type == "input_number" else "number/set_value"
                    logger.debug(f"Using service: {service} for entity type: {entity_type}")
                    
                    response = requests.post(
                        f"{self.hass_url}/api/services/{service}",
                        headers=self.get_headers(),
                        json=service_data
                    )
                    response.raise_for_status()
                    logger.info(f"Successfully set amperage for {device.name} to {amperage}A")
                    logger.debug(f"Response status: {response.status_code}")
                    logger.debug(f"Response content: {response.text}")
                    device_state.current_amperage = amperage
                except Exception as e:
                    logger.error(f"Failed to set amperage for {device.name}: {e}")
            else:
                logger.debug(f"No amperage change needed for {device.name} - has_variable_amperage: {device.has_variable_amperage}, amperage: {amperage}")
            
            # Only change switch state if we're allowed to
            if not (device_state.is_on and device_state.last_state_change and 
                   (current_time - device_state.last_state_change).total_seconds() < device.min_on_time):
                success = device.set_state(turn_on)
                if success:
                    device_state.is_on = turn_on
                    device_state.last_state_change = current_time
                    logger.info(f"Set {device.name} to {'on' if turn_on else 'off'}" + 
                              (f" with {amperage}A" if amperage is not None else ""))
                else:
                    logger.error(f"Failed to set state for {device.name}")
            
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
        
        # Round down to nearest whole number
        optimal_amperage = max(device.min_amperage, max_amperage)
        return math.floor(optimal_amperage)
        
    def set_manual_power_override(self, power: Optional[float]):
        """Set a manual override for available power"""
        self.manual_power_override = power

    def get_debug_state(self) -> Optional[DebugState]:
        """Get the current debug state"""
        return self.debug_state

    def get_grid_power(self) -> float:
        """Get the current grid power"""
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
                
            return grid_power
        except Exception as e:
            logger.error(f"Failed to get grid power: {e}")
            return 0.0

    def get_tariff_rate(self) -> str:
        """Get the current tariff rate from the configured entity
        
        Returns:
            str: The current tariff rate value
        """
        config = self.load_config()
        if not config.get('tariff_rate'):
            logger.error("No tariff rate configured")
            return ''
            
        try:
            response = requests.get(
                f"{self.hass_url}/api/states/{config['tariff_rate']}", 
                headers=self.get_headers()
            )
            response.raise_for_status()
            return response.json().get('state', '')
        except Exception as e:
            logger.error(f"Failed to get tariff rate: {e}")
            return ''

    def get_current_tariff_mode(self) -> str:
        """Determine the current tariff mode (normal, cheap, or free) based on the configured tariff rate and modes.
        
        Returns:
            str: The current tariff mode ('normal', 'cheap', or 'free')
        """
        config = self.load_config()
        if not config.get('tariff_rate'):
            logger.warning("No tariff rate configured, defaulting to normal mode")
            return 'normal'
            
        try:
            # Get current tariff rate from Home Assistant
            response = requests.get(
                f"{self.hass_url}/api/states/{config['tariff_rate']}", 
                headers=self.get_headers()
            )
            response.raise_for_status()
            current_tariff = response.json().get('state')
            
            if not current_tariff:
                logger.warning("No current tariff rate available, defaulting to normal mode")
                return 'normal'
                
            # Get the tariff modes configuration
            tariff_modes = config.get('tariff_modes', {})
            if not tariff_modes:
                logger.warning("No tariff modes configured, defaulting to normal mode")
                return 'normal'
                
            # Get the mode for the current tariff
            mode = tariff_modes.get(current_tariff)
            if not mode:
                logger.warning(f"No mode configured for tariff '{current_tariff}', defaulting to normal mode")
                return 'normal'
                
            # Validate the mode is one of the allowed values
            if mode not in ['normal', 'cheap', 'free']:
                logger.warning(f"Invalid mode '{mode}' for tariff '{current_tariff}', defaulting to normal mode")
                return 'normal'
                
            logger.info(f"Current tariff '{current_tariff}' maps to mode '{mode}'")
            return mode
            
        except Exception as e:
            logger.error(f"Failed to determine tariff mode: {e}")
            return 'normal'

    def is_between_dawn_and_dusk(self) -> bool:
        """Check if current time is between dawn and dusk using sun.sun entity"""
        try:
            response = requests.get(
                f"{self.hass_url}/api/states/sun.sun",
                headers=self.get_headers()
            )
            response.raise_for_status()
            sun_data = response.json()
            
            # Check if sun is above horizon
            return sun_data['state'] == 'above_horizon'
            
        except Exception as e:
            logger.error(f"Failed to check sun state: {e}")
            return True  # Default to True if we can't determine state

    def _run_free_mode(self, voltage: float, devices_to_turn_on: List[Tuple]):
        """Run free tariff mode control logic - maximize all devices"""
        logger.info("Running in free tariff mode - maximizing all devices")
        optional_devices = []
        
        # Turn on all devices at maximum power
        for device_state in self.device_states.values():
            device = device_state.device
            
            # Check if device is already in devices_to_turn_on
            existing_index = next((i for i, (d, _, _) in enumerate(devices_to_turn_on) if d == device_state), None)
            
            # Skip if device has completed its task
            if device.run_once and device_state.has_completed:
                optional_devices.append({
                    'name': device.name,
                    'power': 0,
                    'reason': 'Task completed'
                })
                if existing_index is not None:
                    devices_to_turn_on.pop(existing_index)
                continue
            
            # For variable amperage devices, set to maximum
            if device.has_variable_amperage:
                max_amperage = device.max_amperage
                power_needed = voltage * max_amperage
                if existing_index is not None:
                    devices_to_turn_on[existing_index] = (device_state, power_needed, max_amperage)
                else:
                    devices_to_turn_on.append((device_state, power_needed, max_amperage))
            else:
                power_needed = device.typical_power_draw
                if existing_index is not None:
                    devices_to_turn_on[existing_index] = (device_state, power_needed, None)
                else:
                    devices_to_turn_on.append((device_state, power_needed, None))
            
            optional_devices.append({
                'name': device.name,
                'power': power_needed,
                'reason': 'Free tariff mode - maximizing power'
            })
        
        self.debug_state.optional_devices = optional_devices

    def run_control_loop(self):
        """Main control loop - runs one iteration"""
        try:
            # Initialize/update device states
            self.initialize_device_states()
            
            # Get current conditions
            grid_power = self.get_grid_power()
            voltage = self.get_grid_voltage()
            current_time = datetime.now(timezone.utc)
            
            # Load settings
            settings = self.load_settings()
            power_optimization_enabled = settings.get('power_optimization_enabled', True)
            
            # Initialize debug state
            self.debug_state = DebugState(
                timestamp=current_time,
                available_power=0,  # Will be set by control mode
                grid_voltage=voltage,
                grid_power=grid_power,
                power_optimization_enabled=power_optimization_enabled,
                manual_power_override=self.manual_power_override
            )

            # Phase 1: Handle mandatory devices (common to all control modes)
            mandatory_devices = []
            devices_to_turn_on = []
            
            # Update energy delivered tracking for each device
            for device_state in self.device_states.values():
                device = device_state.device
                if device.energy_sensor:
                    device.update_energy_delivered()
            
            # Sync all device states with Home Assistant before processing
            for device_state in self.device_states.values():
                device = device_state.device
                # Get current state from Home Assistant
                hass_state = self.get_device_state_from_hass(device)
                # Update our local state if it differs from Home Assistant
                if device_state.is_on != hass_state:
                    logger.info(f"Syncing state for {device.name} with Home Assistant: {hass_state}")
                    device_state.is_on = hass_state
                    device_state.last_state_change = current_time
            
            for device_state in self.device_states.values():
                device = device_state.device
                
                # Check if device has completed its task
                if device.run_once and device_state.is_on:
                    if self.check_device_completion(device_state):
                        device_state.has_completed = True
                        logger.info(f"Device {device.name} has completed its task")
                        continue
                
                # Check minimum on/off times
                if device_state.last_state_change:
                    time_since_change = (current_time - device_state.last_state_change).total_seconds()
                    
                    if device_state.is_on and time_since_change < device.min_on_time:
                        # Must stay on
                        power = self.get_device_power(device_state)
                        mandatory_devices.append({
                            'name': device.name,
                            'power': power,
                            'reason': 'Minimum on time not met'
                        })
                        logger.info(f"Device {device.name} must stay on due to minimum on time")
                        # For variable amperage devices in tariff mode, set to maximum
                        if device.has_variable_amperage and self.get_current_tariff_mode() in ['cheap', 'free']:
                            max_amperage = device.max_amperage
                            power = voltage * max_amperage
                            devices_to_turn_on.append((device_state, power, max_amperage))
                        else:
                            devices_to_turn_on.append((device_state, power, device_state.current_amperage))
                        continue
                        
                    if not device_state.is_on and time_since_change < device.min_off_time:
                        # Must stay off
                        mandatory_devices.append({
                            'name': device.name,
                            'power': 0,
                            'reason': 'Minimum off time not met'
                        })
                        logger.info(f"Device {device.name} must stay off due to minimum off time")
                        continue

            self.debug_state.mandatory_devices = mandatory_devices

            # Determine control mode and run appropriate logic
            control_mode = self._determine_control_mode()
            logger.info(f"Selected control mode: {control_mode}")
            
            if control_mode == 'free':
                self._run_free_mode(voltage, devices_to_turn_on)
            elif control_mode == 'solar':
                available_power = self.get_available_power()
                self.debug_state.available_power = available_power
                self._run_solar_control(available_power, voltage, devices_to_turn_on)
            else:  # tariff mode
                self._run_tariff_control(voltage, devices_to_turn_on)

            # Only apply state changes if optimization is enabled
            if self.debug_state.power_optimization_enabled:
                self._apply_state_changes(devices_to_turn_on)
            else:
                logger.info("Power optimization is disabled - skipping state changes")

        except Exception as e:
            logger.error(f"Error in control loop: {e}")

    def _determine_control_mode(self) -> str:
        """Determine which control mode to use based on tariff mode and time of day."""
        current_tariff_mode = self.get_current_tariff_mode()
        
        # Free tariff mode takes precedence
        if current_tariff_mode == 'free':
            logger.info("Selected control mode: free (based on tariff mode)")
            return 'free'
            
        # During daylight hours, use solar control
        if self.is_between_dawn_and_dusk():
            logger.info("Selected control mode: solar (daylight hours)")
            return 'solar'
            
        # Otherwise use tariff control
        logger.info("Selected control mode: tariff (night hours)")
        return 'tariff'

    def _run_solar_control(self, available_power: float, voltage: float, devices_to_turn_on: List[Tuple]):
        """Run solar-based power control logic"""
        logger.info(f"Running solar control mode with {available_power}W available")
        optional_devices = []
        
        # First, handle mandatory devices that must stay on
        for device_state, power, amperage in devices_to_turn_on[:]:
            device = device_state.device
            if device.has_variable_amperage:
                # Calculate optimal amperage based on available power
                optimal_amperage = self.calculate_optimal_amperage(device, available_power)
                if optimal_amperage is None:
                    logger.info(f"Cannot calculate optimal amperage for {device.name}")
                    continue
                
                power_needed = voltage * optimal_amperage
                
                # Update the power in devices_to_turn_on
                for i, (d, p, a) in enumerate(devices_to_turn_on):
                    if d == device_state:
                        devices_to_turn_on[i] = (device_state, power_needed, optimal_amperage)
                        break
                
                logger.info(f"Setting power for mandatory device {device.name} to {power_needed}W at {optimal_amperage}A")
                available_power -= power_needed
            else:
                # For non-variable devices, we can't minimize power
                available_power -= power
        
        # Sort remaining devices by their order (priority)
        sorted_devices = sorted(
            [d for d in self.device_states.values() if not any(d == x[0] for x in devices_to_turn_on)],
            key=lambda x: x.device.order
        )
        
        # Process potential devices in priority order
        for device_state in sorted_devices:
            device = device_state.device
            logger.debug(f"Processing device {device.name} with {available_power}W available")
            
            # Skip if device has completed its task
            if device.run_once and device_state.has_completed:
                logger.info(f"Skipping {device.name} - task completed")
                optional_devices.append({
                    'name': device.name,
                    'power': 0,
                    'reason': 'Task completed'
                })
                continue
                
            # Skip if device is in minimum off time
            if not device_state.is_on and device_state.last_state_change:
                time_since_change = (datetime.now(timezone.utc) - device_state.last_state_change).total_seconds()
                if time_since_change < device.min_off_time:
                    logger.info(f"Skipping {device.name} - in minimum off time")
                    optional_devices.append({
                        'name': device.name,
                        'power': 0,
                        'reason': 'Minimum off time not met'
                    })
                    continue
            
            # Calculate power needed based on current state of devices_to_turn_on
            if device.has_variable_amperage:
                # Calculate optimal amperage considering current load
                optimal_amperage = self.calculate_optimal_amperage(device, available_power)
                logger.debug(f"Calculated optimal amperage for {device.name}: {optimal_amperage}A")
                if optimal_amperage is None:
                    logger.info(f"Cannot calculate optimal amperage for {device.name}")
                    optional_devices.append({
                        'name': device.name,
                        'power': 0,
                        'reason': 'Cannot calculate optimal amperage'
                    })
                    continue

                # If device is already on, scale power based on amperage ratio
                if device_state.is_on:
                    current_power = self.get_device_power(device_state)
                    if device_state.current_amperage and device_state.current_amperage > 0:
                        power_needed = current_power * (optimal_amperage / device_state.current_amperage)
                        logger.debug(f"Scaled power needed for {device.name} from {current_power}W to {power_needed}W based on amperage ratio")
                    else:
                        power_needed = voltage * optimal_amperage
                        logger.debug(f"Using calculated power for {device.name}: {power_needed}W (no current amperage available)")
                else:
                    power_needed = voltage * optimal_amperage
                    logger.debug(f"Using calculated power for {device.name}: {power_needed}W (device is off)")
            else:
                # For non-variable devices, use actual power if device is on
                if device_state.is_on:
                    power_needed = self.get_device_power(device_state)
                    logger.debug(f"Using actual power for {device.name}: {power_needed}W")
                else:
                    power_needed = device.typical_power_draw
                    logger.debug(f"Using typical power for {device.name}: {power_needed}W")
            
            # Check if we have enough power
            if power_needed <= available_power:
                logger.info(f"Turning on {device.name} with {power_needed}W" + 
                          (f" at {optimal_amperage}A" if device.has_variable_amperage else ""))
                devices_to_turn_on.append((device_state, power_needed, optimal_amperage if device.has_variable_amperage else None))
                available_power -= power_needed
                optional_devices.append({
                    'name': device.name,
                    'power': power_needed,
                    'reason': 'Will be turned on'
                })
            else:
                logger.info(f"Not enough power for {device.name} (needs {power_needed}W, has {available_power}W)")
                optional_devices.append({
                    'name': device.name,
                    'power': 0,
                    'reason': 'Not enough power available'
                })
        
        self.debug_state.optional_devices = optional_devices

    def _run_tariff_control(self, voltage: float, devices_to_turn_on: List[Tuple]):
        """Run tariff-based power control logic"""
        logger.info("Running tariff control mode")
        optional_devices = []
        
        # Check if we're in cheap or free tariff mode
        current_mode = self.get_current_tariff_mode()
        if current_mode not in ['cheap', 'free']:
            logger.info(f"Skipping tariff control - current mode is {current_mode}, not 'cheap' or 'free'")
            for device_state in self.device_states.values():
                optional_devices.append({
                    'name': device_state.device.name,
                    'power': 0,
                    'reason': f'Not in cheap/free tariff mode (current: {current_mode})'
                })
            self.debug_state.optional_devices = optional_devices
            return
        
        # Process each device
        for device_state in self.device_states.values():
            device = device_state.device
            logger.debug(f"Processing device {device.name} in tariff control mode")
            
            # Check if device is already in devices_to_turn_on
            existing_index = next((i for i, (d, _, _) in enumerate(devices_to_turn_on) if d == device_state), None)
            
            # Skip if no minimum daily power is specified
            if not device.min_daily_power:
                logger.info(f"Skipping {device.name} - no minimum daily power specified")
                optional_devices.append({
                    'name': device.name,
                    'power': 0,
                    'reason': 'No minimum daily power specified'
                })
                continue
                
            # Check if device has completed its task
            if device.run_once and device_state.is_on:
                if self.check_device_completion(device_state):
                    logger.info(f"Turning off {device.name} - task completed")
                    device_state.has_completed = True
                    optional_devices.append({
                        'name': device.name,
                        'power': 0,
                        'reason': 'Task completed'
                    })
                    if existing_index is not None:
                        devices_to_turn_on.pop(existing_index)
                    continue
            
            # Check if minimum daily power requirement is met
            if device.energy_delivered_today >= device.min_daily_power:
                logger.info(f"Turning off {device.name} - minimum daily power requirement met")
                optional_devices.append({
                    'name': device.name,
                    'power': 0,
                    'reason': 'Minimum daily power requirement met'
                })
                if existing_index is not None:
                    devices_to_turn_on.pop(existing_index)
                continue
                
            # If we get here, we need to turn the device on
            logger.info(f"Turning on {device.name} - minimum daily power requirement not met")
            
            # For variable amperage devices, set to maximum
            if device.has_variable_amperage:
                max_amperage = device.max_amperage
                power_needed = voltage * max_amperage
                logger.debug(f"Setting {device.name} to maximum amperage: {max_amperage}A ({power_needed}W)")
                if existing_index is not None:
                    devices_to_turn_on[existing_index] = (device_state, power_needed, max_amperage)
                else:
                    devices_to_turn_on.append((device_state, power_needed, max_amperage))
            else:
                power_needed = device.typical_power_draw
                logger.debug(f"Using typical power for {device.name}: {power_needed}W")
                if existing_index is not None:
                    devices_to_turn_on[existing_index] = (device_state, power_needed, None)
                else:
                    devices_to_turn_on.append((device_state, power_needed, None))
                
            optional_devices.append({
                'name': device.name,
                'power': power_needed,
                'reason': 'Minimum daily power requirement not met'
            })
            
        self.debug_state.optional_devices = optional_devices

    def _apply_state_changes(self, devices_to_turn_on: List[Tuple]):
        """Apply state changes to devices"""
        for device_state in self.device_states.values():
            # Find if this device should be on
            should_be_on = False
            power_needed = 0
            amperage = None
            
            for turn_on_device, power, amp in devices_to_turn_on:
                if turn_on_device == device_state:
                    should_be_on = True
                    power_needed = power
                    amperage = amp
                    break
            
            # Apply state changes
            if should_be_on:
                if not device_state.is_on or (device_state.device.has_variable_amperage and device_state.current_amperage != amperage):
                    self.set_device_state(device_state, True, amperage)
            else:
                if device_state.is_on:
                    self.set_device_state(device_state, False)

    def _handle_disabled_optimization(self):
        """Handle case when optimization is disabled - leave devices in their current state"""
        optional_devices = []
        for device_state in self.device_states.values():
            device = device_state.device
            current_power = self.get_device_power(device_state) if device_state.is_on else 0
            
            optional_devices.append({
                'name': device.name,
                'power': current_power,
                'reason': 'Optimization disabled - maintaining current state'
            })

        self.debug_state.optional_devices = optional_devices

    def start_control_loop(self):
        """Start the control loop in a separate thread"""
        import threading
        def loop():
            while True:
                self.run_control_loop()
                time.sleep(60)  # Sleep for a minute between iterations
                
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()

    def update_config(self, new_config: dict):
        """Update configuration with new values"""
        try:
            # Load existing config
            current_config = self.load_config()
            
            # Update with new values
            current_config.update(new_config)
            
            # Save updated config
            with open(self.config_file, 'w') as f:
                json.dump(current_config, f, indent=4)
                
            logger.info(f"Configuration updated: {current_config}")
            
        except Exception as e:
            logger.error(f"Failed to update config: {e}")
            raise

if __name__ == "__main__":
    controller = SolarController(
        config_file="/data/solar_config.json",
        devices_file="/data/devices.json"
    )
    controller.start_control_loop() 