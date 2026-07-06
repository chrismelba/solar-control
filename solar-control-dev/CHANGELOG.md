<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

## [1.8.10] - 2026-07-06
### Added
- Car / EV device type: mark a device as a car (with a state-of-charge sensor) and set two SoC targets — "Always charge to X%" (protection floor: charges immediately at max rate on any tariff when below X%) and "Charge on cheap power to Y%" (topped up during cheap/free tariff windows). Above Y% the car charges on excess solar only, up to 100%.
- Road trip mode: 🧳 button on the car's device card charges to 100% on cheap/free power; automatically clears itself once the car reaches 100%. Survives add-on restarts (persisted in state.json alongside one-off charges).
- New API endpoint `POST /api/devices/<name>/road_trip`; `/api/devices` now includes `car_soc` and `road_trip`.
- Car settings tab in both device forms (dashboard modal and configure page); live SoC shown on the device card.

### Fixed
- Minimum on-time timer no longer resets whenever a variable-amperage device's amperage changes — previously an EV in fluctuating solar could re-arm its own min-on-time window indefinitely and never be shed. Switch commands are also no longer re-sent to devices already in the desired state.
- Run-once completion status now resets in every control mode when the completion sensor goes off. Previously it only reset during cheap/free tariff windows, so on solar-only setups a run-once device would never restart until the add-on was rebooted.
- Control loop is now guarded by a lock: the dashboard's `POST /api/control/run` (fired on page load) can no longer overlap the 60-second background loop and race on shared state.
- A failed Home Assistant API call is no longer treated as an external "device turned off" event — the last-known state is kept, so a brief HA outage can't flap devices or corrupt the power budget.
- `calculate_optimal_amperage` no longer floors the result below a fractional `min_amperage` (e.g. min 6.5A used to become 6A).
- Device add/update API now applies numeric conversions server-side (`Device.from_dict`), so values like `min_daily_power` are stored as numbers rather than strings.
- Device card live-update label corrected from "Wh" to "kWh" for energy delivered.

## [1.8.9] - 2026-03-24
### Added
- Debug page: "← Home" link in toolbar so you can exit debug view
- Debug page: "Available power calculation" breakdown table showing each step — grid power reading, controlled devices added back, raw available, site export limit (if triggered), and bring-forward addition

## [1.8.8] - 2026-03-24
### Fixed
- Min on-time power accounting for variable amperage devices: power budget now uses actual sensor-ratioed draw rather than theoretical `voltage × amperage`. An unplugged EV (drawing ~0W) no longer consumes phantom budget and starves other devices (e.g. HWS) during the min-on-time window.
- Externally-controlled variable amperage devices (`current_amperage is None`): power budget now uses actual sensor power if available, falling back to `typical_power_draw` instead of `max_amperage × voltage`.
- Added `estimate_variable_power()` helper used consistently for all variable amperage power budget calculations in solar mode.

## [1.8.7] - 2026-02-28
### Changed
- Further contrast improvements: sensor card labels, "Mode:" text, section headers, and modal titles bumped from #555/#777 to #999; sensor entity names and unconfigured values from #444 to #777

## [1.8.6] - 2026-02-28
### Changed
- Mobile responsiveness: dashboard collapses to single column on screens ≤640px; card/content/toolbar padding reduced on mobile; modal forms stack vertically; tab buttons wrap
- Improved text contrast: muted grey text lightened from #555→#777 and #666→#888 for better readability on dark background

## [1.8.4] - 2026-02-28
### Fixed
- CSS cache-busting: static asset URLs now include `?v=<version>` so HA ingress always loads fresh CSS after updates
- One-off charge state restore race condition: device states now initialised synchronously before loading saved state on startup
- One-off charge persistence: target and start energy saved to `state.json` every 60s and on set/cancel; restored on restart

## [1.8.3] - 2026-02-28
### Fixed
- Embedded full modal/form CSS in base.html to guarantee correct styling in HA ingress iframe regardless of external CSS caching

## [1.8.2] - 2026-02-28
### Fixed
- Embedded critical modal CSS inline in base.html to bypass HA ingress CSS loading issues
- Modal visibility: added inline `style="display:none"` to modal divs; open/close now uses `el.style.display` directly

## [1.8.0] - 2026-02-28
### Changed
- Dashboard UI redesign: modals for device/grid/battery config, energy chart, compact forms
- One-off charge: persist state to disk (state.json) so it survives restarts

## [1.7.0] - 2026-02-28
### Changed
- One-off charge: charge EV to a kWh target using cheap tariff power

## [1.4.6] - 2025-06-13
### Fixed
- Removed nginx logging to file (was breaking installs)
- Fixed bug where variable current devices would charge at minimum current overnight

## [1.3.70] - 2025-05-25
### Changed
- Added tooltips

## [1.2.11] - 2024-03-19
### Changed
- Added nginx

## [1.2.7] - 2024-03-19
### Changed
- Modified amperage rounding to always round down to nearest whole number
- Added detailed debug logging for amperage control operations

## [1.2.6] - 2024-03-19
### Changed
- Added voltage to config
- More work on variable amperage entities

## [1.2.5] - 2024-03-19
### Changed
- Modified amperage control logic to allow amperage changes during minimum on time
- Separated switch state and amperage control into distinct service calls
- When a device must stay on due to minimum on time, variable amperage devices will now be set to minimum amperage instead of keeping current amperage

## [1.2.4]
### Fixed
- Fix syntax error in control loop implementation
- Improve thread safety for control loop execution
- Fix duplicate method definition in solar controller

## [1.2.3]
### Fixed
- Fix webserver responsiveness when turning devices on/off
- Fix device state setting for variable load devices
- Run control loop in separate thread to prevent blocking
- Improve error handling for device state changes

## [1.2.2]
### Changed
- Refactor control loop for better power optimization
- Improve handling of device priorities
- Fix issue with devices being incorrectly skipped when already on
- Add proper handling of variable load devices in optimization

## [1.2.1]
### Fixed
- Fix data persistence issues
- Improve file handling and permissions
- Add detailed logging for debugging

## [1.2.0]
### Changed
- Add an apparmor profile
- Update to 3.15 base image with s6 v3
- Add a sample script to run as service and constrain in aa profile

## [1.1.0]
### Changed
- Updates

## [1.0.0]
- Initial release
