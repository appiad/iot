# iot

## Non-RPi Stuff
PyAudio (use python 3.6): http://people.csail.mit.edu/hubert/pyaudio/
- Example: https://realpython.com/playing-and-recording-sound-python/#pyaudio
## Raspberry Pi Install stuff
- Install bluetooth stuff on RPi 
  ```
  sudo apt-get install pi-bluetooth 
  ```
- bluepy library for getting RSSI through python: https://github.com/IanHarvey/bluepy
  - bluepy programs must be run with ```sudo```

- command to get MAC addr and RSSI of nearby BLE transmitters:
  ```
  sudo btmgmt find
  ```
