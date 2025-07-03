#!/usr/bin/python3

"""
Test script for the new solar forecast functionality.
This script tests the new methods added to the SolarController class.
"""

import sys
import os
sys.path.append('/usr/bin')

from solar_controller import SolarController
from battery import Battery
import json

def test_forecast_functionality():
    """Test the new forecast functionality"""
    print("Testing Solar Forecast Functionality")
    print("=" * 50)
    
    # Initialize controller
    controller = SolarController(
        config_file="/data/solar_config.json",
        devices_file="/data/devices.json"
    )
    
    # Test 1: Get sunset time
    print("\n1. Testing get_sunset_time()")
    sunset_time = controller.get_sunset_time()
    if sunset_time:
        print(f"   Sunset time: {sunset_time}")
    else:
        print("   Could not get sunset time")
    
    # Test 2: Get hours until sunset
    print("\n2. Testing get_hours_until_sunset()")
    hours_until_sunset = controller.get_hours_until_sunset()
    if hours_until_sunset is not None:
        print(f"   Hours until sunset: {hours_until_sunset:.2f}")
    else:
        print("   Could not get hours until sunset")
    
    # Test 3: Get solar forecast remaining
    print("\n3. Testing get_solar_forecast_remaining()")
    solar_forecast = controller.get_solar_forecast_remaining()
    if solar_forecast is not None:
        print(f"   Solar forecast remaining: {solar_forecast:.2f} kWh")
    else:
        print("   Could not get solar forecast remaining")
    
    # Test 4: Get battery charging requirement
    print("\n4. Testing get_battery_charging_requirement()")
    battery_requirement = controller.get_battery_charging_requirement()
    if battery_requirement is not None:
        print(f"   Battery charging requirement: {battery_requirement:.2f} kWh")
    else:
        print("   Could not get battery charging requirement")
    
    # Test 5: Get expected energy remaining
    print("\n5. Testing get_expected_energy_remaining()")
    expected_energy = controller.get_expected_energy_remaining()
    if expected_energy is not None:
        print(f"   Expected energy remaining: {expected_energy:.2f} kWh")
    else:
        print("   Could not get expected energy remaining")
    
    # Test 6: Test battery configuration
    print("\n6. Testing battery configuration")
    try:
        battery = Battery.load('/data/battery.json')
        if battery:
            print(f"   Battery size: {battery.size_kwh} kWh")
            print(f"   Battery percentage entity: {battery.battery_percent_entity}")
            print(f"   Expected kWh per hour: {battery.expected_kwh_per_hour}")
        else:
            print("   No battery configuration found")
    except Exception as e:
        print(f"   Error loading battery configuration: {e}")
    
    print("\n" + "=" * 50)
    print("Test completed!")

if __name__ == "__main__":
    test_forecast_functionality() 