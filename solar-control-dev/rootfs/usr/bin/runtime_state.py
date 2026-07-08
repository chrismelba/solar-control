"""Per-device runtime state (de)serialization.

Covers state that isn't device *configuration* but must survive restarts:
one-off charge targets, road trip mode, and the auto-control flag.
Only non-default values are stored, so state.json stays minimal and
defaults can evolve without stale files pinning old behaviour.
"""

import logging

logger = logging.getLogger(__name__)


def serialize_runtime_state(device_states):
    """Build the state.json dict from live DeviceState objects."""
    state = {}
    for name, ds in device_states.items():
        entry = {}
        if ds.one_off_charge_target is not None:
            entry['one_off_charge_target'] = ds.one_off_charge_target
            entry['one_off_charge_start_energy'] = ds.one_off_charge_start_energy
        if ds.road_trip:
            entry['road_trip'] = True
        if not ds.auto_control:
            entry['auto_control'] = False
        if entry:
            state[name] = entry
    return state


def apply_runtime_state(device_states, state):
    """Restore saved runtime state onto live DeviceState objects.

    Unknown device names are ignored (device may have been deleted)."""
    for name, values in state.items():
        ds = device_states.get(name)
        if not ds:
            continue
        if values.get('one_off_charge_target') is not None:
            ds.one_off_charge_target = values['one_off_charge_target']
            ds.one_off_charge_start_energy = values.get('one_off_charge_start_energy')
            logger.info(f"Restored one-off charge for {name}: target={ds.one_off_charge_target} kWh")
        if values.get('road_trip'):
            ds.road_trip = True
            logger.info(f"Restored road trip mode for {name}")
        if values.get('auto_control') is False:
            ds.auto_control = False
            logger.info(f"Restored auto control OFF for {name}")
