# Location based audio streaming

## Client installs
PyAudio (use python 3.6): http://people.csail.mit.edu/hubert/pyaudio/
- Example: https://realpython.com/playing-and-recording-sound-python/#pyaudio
- Docs: https://people.csail.mit.edu/hubert/pyaudio/docs/


## Server (Raspberry Pi) Installs
- Install bluetooth stuff on RPi 
  ```
  sudo apt-get install pi-bluetooth 
  ```
  or 
  ```
  sudo apt-get install pi-bluetooth bluez
  ```
- bluepy library for getting RSSI through python: https://github.com/IanHarvey/bluepy
  - bluepy programs must be run with ```sudo```
  - bluepy is not supported by Python 3.7. It is recomended to run with Python 2.7.
  -     This can cause problems with other code aspects, however, so please note which version of the code you are running
  - bluepy can be installed with   
  ```
  pip install bluepy 
  ```

- command to get MAC address and RSSI of nearby BLE beacons like the Tile:
  ```
  sudo btmgmt find
  ```
  
## Running the system
