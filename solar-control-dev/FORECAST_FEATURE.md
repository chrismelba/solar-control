# Solar Forecast Feature

This document describes the new solar forecast functionality that has been added to the solar controller.

## Overview

The solar forecast feature calculates the expected energy remaining in the solar forecast today after accounting for battery charging requirements. This helps ensure that there's enough energy left to fully charge the battery before sunset.

**Important**: This feature only activates when a battery is properly configured with the `expected_kwh_per_hour` field. If no battery is configured or the field is not set, the system will use the full solar forecast without battery adjustments.

## New Methods Added

### 1. `get_sunset_time()`
- **Purpose**: Gets the sunset time for today from the `sun.sun` entity
- **Returns**: `datetime` object with sunset time in local timezone, or `None` if unable to determine
- **Source**: Uses Home Assistant's `sun.sun` entity `next_setting` attribute

### 2. `get_hours_until_sunset()`
- **Purpose**: Calculates the number of hours until sunset
- **Returns**: `float` representing hours until sunset, or `None` if unable to determine
- **Calculation**: `(sunset_time - current_time) / 3600`

### 3. `get_solar_forecast_remaining()`
- **Purpose**: Gets the remaining solar forecast energy for today
- **Returns**: `float` representing remaining solar forecast in kWh, or `None` if unable to determine
- **Source**: Uses the configured `solar_forecast` entity from the grid configuration
- **Unit Conversion**: Automatically converts between Wh, kWh, and MWh as needed

### 4. `get_battery_charging_requirement()`
- **Purpose**: Calculates the energy required to fully charge the battery
- **Returns**: `float` representing energy required in kWh, or `None` if unable to determine
- **Calculation**: `battery_size_kwh * (100 - current_percentage) / 100`

### 5. `get_expected_energy_remaining()`
- **Purpose**: Calculates the expected energy remaining after accounting for battery charging
- **Returns**: `float` representing net available energy in kWh, or `None` if unable to determine
- **Calculation**: `solar_forecast - (expected_kwh_per_hour * hours_until_sunset)`
- **Battery Requirement**: Only performs battery adjustment if battery is configured with `expected_kwh_per_hour`

## Configuration

### Battery Configuration
The battery configuration now includes an `expected_kwh_per_hour` field:

```json
{
  "size_kwh": 10.0,
  "battery_percent_entity": "sensor.battery_percentage",
  "max_charging_speed_kw": 5.0,
  "expected_kwh_per_hour": 2.5
}
```

- **`expected_kwh_per_hour`**: Expected household energy consumption per hour (kWh). This value is subtracted from the solar forecast to determine if there's enough energy left for battery charging.
- **Required for battery adjustment**: If this field is not set, the system will use the full solar forecast without battery adjustments.

### Grid Configuration
Ensure the `solar_forecast` entity is configured in the grid settings:

```json
{
  "solar_forecast": "sensor.solar_forecast_remaining"
}
```

## Integration with Solar Control Mode

The solar control mode now considers the expected energy remaining when making decisions about turning on devices:

1. **Battery Check**: First checks if a battery is configured with `expected_kwh_per_hour`
2. **Energy Calculation**: If battery is configured, calculates the energy each device would consume over the remaining daylight hours
3. **Battery Priority**: If turning on a device would leave insufficient energy for battery charging, the device is not turned on
4. **Fallback**: If no battery is configured, uses standard power-based logic
5. **Logging**: Detailed logging shows the energy calculations and decisions made

### Example Log Output
```
No battery configured or expected_kwh_per_hour not set - using current available power only
Processing device EV Charger with 5000W available
Turning on EV Charger with 5000W
```

Or with battery configured:
```
Expected energy remaining today: 15.5kWh
Processing device EV Charger with 5000W available
Not enough expected energy for EV Charger - would consume 12.5kWh but only 15.5kWh available
```

## Dashboard Updates

The dashboard now displays:
- **Expected Energy Remaining**: Shows the net energy available after battery charging (or raw forecast if no battery configured)
- **Hours Until Sunset**: Shows the remaining daylight hours

When no battery is configured, the "Expected Energy Remaining" will show "(raw forecast)" to indicate it's the unadjusted solar forecast value.

These values are updated every minute and provide real-time visibility into the energy planning decisions.

## Debug State

The debug state now includes additional fields:
- `solar_forecast_remaining`: Raw solar forecast value
- `expected_energy_remaining`: Net energy after battery charging (null if no battery configured)
- `hours_until_sunset`: Remaining daylight hours

This information is available through the `/api/status` endpoint and can be used for monitoring and debugging.

## Testing

A test script `test_forecast.py` is provided to verify the functionality:

```bash
python3 test_forecast.py
```

This script tests all the new methods and provides output showing the calculated values.

## Error Handling

The system gracefully handles missing or invalid data:
- If no battery is configured, uses full solar forecast without adjustments
- If battery is configured but `expected_kwh_per_hour` is not set, uses full solar forecast
- If solar forecast is not configured, falls back to using only current available power
- If sunset time cannot be determined, logs warnings but continues operation
- All methods return `None` on error, allowing the calling code to handle gracefully

## Behavior Without Battery

When no battery is configured or `expected_kwh_per_hour` is not set:
1. The system will use the full solar forecast value
2. Device decisions are based only on current available power
3. No energy planning over time is performed
4. The dashboard shows "(raw forecast)" for the expected energy remaining
5. All other functionality remains unchanged

This ensures the system works for users who don't have a battery while providing enhanced functionality for those who do.

## Future Enhancements

Potential future improvements:
1. **Weather Integration**: Use weather forecasts to adjust solar predictions
2. **Historical Analysis**: Learn from past performance to improve predictions
3. **Battery State Optimization**: Consider battery state of charge in energy planning
4. **Device Priority**: Allow devices to specify their energy requirements and priorities
5. **Multiple Battery Support**: Support for systems with multiple batteries 