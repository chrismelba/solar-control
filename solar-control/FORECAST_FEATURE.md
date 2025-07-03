# Solar Forecast Feature

This document describes the solar forecast functionality that has been added to the solar controller.

## Overview

The solar forecast feature implements a simple battery priority system that ensures the battery gets charged before allowing discretionary devices to use solar power. This helps ensure that there's enough energy left to fully charge the battery before sunset.

**Important**: This feature only activates when a battery is properly configured with the `expected_kwh_per_hour` field. If no battery is configured or the field is not set, the system will use normal solar control without battery restrictions.

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

### 5. `is_battery_full_enough()`
- **Purpose**: Checks if the battery is full enough (>95%) to allow normal device control
- **Returns**: `bool` - True if battery is >95% charged, False otherwise
- **Logic**: If battery is >95%, normal device control is allowed regardless of energy forecasts

### 6. `get_expected_energy_remaining()`
- **Purpose**: Calculates the expected energy remaining after accounting for household consumption and battery charging
- **Returns**: `float` representing net available energy in kWh, or `None` if unable to determine
- **Calculation**: `solar_forecast - (house_energy_needed + battery_charging_requirement)`
- **House Energy**: `expected_kwh_per_hour * hours_until_sunset` (household consumption)
- **Battery Energy**: `get_battery_charging_requirement()` (actual energy to charge battery)
- **Requirements**: Only performs adjustments if battery is configured with `expected_kwh_per_hour`

## Configuration

### Battery Configuration
The battery configuration includes an `expected_kwh_per_hour` field:

```json
{
  "size_kwh": 10.0,
  "battery_percent_entity": "sensor.battery_percentage",
  "max_charging_speed_kw": 5.0,
  "expected_kwh_per_hour": 2.5
}
```

- **`expected_kwh_per_hour`**: Expected household energy consumption per hour (kWh). This value represents the typical household load that needs to be accounted for.
- **Required for energy planning**: If this field is not set, the system will use normal solar control without battery restrictions.

### Grid Configuration
Ensure the `solar_forecast` entity is configured in the grid settings:

```json
{
  "solar_forecast": "sensor.solar_forecast_remaining"
}
```

## Integration with Solar Control Mode

The solar control mode now uses a simple battery priority system:

1. **Battery Full Check**: First checks if battery is >95% charged
   - If yes: Allow normal device control
2. **Excess Energy Check**: If battery is not full, check if there's excess energy remaining
   - If `expected_energy_remaining > 0`: Allow normal device control
3. **Battery Priority**: If neither condition is met, reserve all solar for battery charging
4. **Fallback**: If no battery is configured, use normal solar control
5. **Logging**: Clear logging shows the battery priority decisions

### Battery Priority Logic
```
If battery > 95%:
    Allow normal device control
Else if expected_energy_remaining > 0:
    Allow normal device control  
Else:
    Reserve solar for battery charging only
```

### Example Log Output
```
Battery is full enough (>95%) - allowing normal device control
Processing device EV Charger with 5000W available
Turning on EV Charger with 5000W
```

Or with battery priority active:
```
Battery priority active - reserving solar for battery charging
Processing device EV Charger with 5000W available
Not turning on EV Charger - Battery priority active - reserving solar for battery charging
```

## Dashboard Updates

The dashboard now displays:
- **Expected Energy Remaining**: Shows the net energy available after household consumption and battery charging (or raw forecast if no battery configured)
- **Hours Until Sunset**: Shows the remaining daylight hours

When no battery is configured, the "Expected Energy Remaining" will show "(raw forecast)" to indicate it's the unadjusted solar forecast value.

These values are updated every minute and provide real-time visibility into the energy planning decisions.

## Debug State

The debug state now includes additional fields:
- `solar_forecast_remaining`: Raw solar forecast value
- `expected_energy_remaining`: Net energy after household consumption and battery charging (null if no battery configured)
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
- If no battery is configured, uses normal solar control without restrictions
- If battery is configured but `expected_kwh_per_hour` is not set, uses normal solar control
- If solar forecast is not configured, falls back to using only current available power
- If sunset time cannot be determined, logs warnings but continues operation
- All methods return `None` on error, allowing the calling code to handle gracefully

## Behavior Without Battery

When no battery is configured or `expected_kwh_per_hour` is not set:
1. The system will use normal solar control logic
2. Device decisions are based only on current available power
3. No battery priority restrictions are applied
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