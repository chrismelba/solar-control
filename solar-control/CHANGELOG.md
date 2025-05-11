<!-- https://developers.home-assistant.io/docs/add-ons/presentation#keeping-a-changelog -->

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
