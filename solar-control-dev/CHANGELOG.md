<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

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
