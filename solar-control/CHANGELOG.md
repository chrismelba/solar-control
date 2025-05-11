<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

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
- more work on variable amperage entities

## [1.2.5] - 2024-03-19
### Changed
- Modified amperage control logic to allow amperage changes during minimum on time
- Separated switch state and amperage control into distinct service calls
- When a device must stay on due to minimum on time, variable amperage devices will now be set to minimum amperage instead of keeping current amperage

## 1.2.4

- Fix syntax error in control loop implementation
- Improve thread safety for control loop execution
- Fix duplicate method definition in solar controller

## 1.2.3

- Fix webserver responsiveness when turning devices on/off
- Fix device state setting for variable load devices
- Run control loop in separate thread to prevent blocking
- Improve error handling for device state changes

## 1.2.2

- Refactor control loop for better power optimization
- Improve handling of device priorities
- Fix issue with devices being incorrectly skipped when already on
- Add proper handling of variable load devices in optimization

## 1.2.1

- Fix data persistence issues
- Improve file handling and permissions
- Add detailed logging for debugging

## 1.2.0

- Add an apparmor profile
- Update to 3.15 base image with s6 v3
- Add a sample script to run as service and constrain in aa profile

## 1.1.0

- Updates

## 1.0.0

- Initial release
