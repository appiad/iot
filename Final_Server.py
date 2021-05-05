from bluepy.btle import Scanner, DefaultDelegate
import socket
import wave
import pyaudio
import time
import multiprocessing
from struct import *
from aenum import IntEnum, auto

host = '128.113.194.238'

port_room_one = 8888
port_room_two = 8000

CURRENT_CONNECTION = 0

NUM_BYTES_TO_RECV = 65536

MSG_HEADER_LEN = 6
MSG_LEN_PACKING_FORMAT = 'I'
MSG_CODE_PACKING_FORMAT = 'H'

DURATION_FORMAT = 'f'

AUDIO_FORMAT = 'I'
CHANNEL_FORMAT = 'H'
FPB_FORMAT = 'H'
FRAMERATE_FORMAT = 'H'
FRAME_LEN_FORMAT = 'I'

FRAMES_PER_BUFFER = 16384

SLEEP_INTERVAL = 0.05
SLEEP_INT_LARGE = 0.1

rooms_dict = {1: [[[-15, -83], [-83, -88]], [[-74, -90], [-78, -89]]], 2: [[[-71, -82], [-73, -79]], [[-80, -96], [-28, -83]]]}


wf = wave.open('wave_files/a_boogie.wav', 'rb')
py_audio = pyaudio.PyAudio()


class ScanDelegate(DefaultDelegate):
    def __init__(self, R1_RSSI, R2_RSSI):
        DefaultDelegate.__init__(self)
        self.R1_RSSI = R1_RSSI
        self.R2_RSSI = R2_RSSI

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if isNewDev or isNewData:
            if dev.addr == u'fb:13:5e:5d:d1:d5':
                self.R1_RSSI = dev.rssi
            elif dev.addr == u'ec:b6:d0:1e:0c:5e':
                self.R2_RSSI = dev.rssi


class ClientServerMsg(IntEnum):
    # Server sends
    HALT = auto()
    NEW_STREAM = auto()
    STREAM_RSP = auto()

    # Client sends
    HALT_RSP = auto()
    STREAM_REQ = auto()


def get_data():
    data = wf.readframes(FRAMES_PER_BUFFER)
    return data


def get_stream_params():
    """Stream parameters for current stream"""
    stream_format = py_audio.get_format_from_width(wf.getsampwidth())
    num_channels = wf.getnchannels()
    stream_rate = wf.getframerate()
    stream_frame_len = len(wf.readframes(FRAMES_PER_BUFFER))
    wf.rewind()
    return stream_format, num_channels, stream_rate, stream_frame_len


def seconds_to_frame(seconds):
    """return the number of frames a duration in seconds represents"""
    # https://stackoverflow.com/questions/18721780/play-a-part-of-a-wav-file-in-python
    n_frames = int(seconds * wf.getframerate())


def encode_message(msg_code, msg_bytes=b''):
    len_msg = 0 if msg_bytes is None else len(msg_bytes)
    len_msg += MSG_HEADER_LEN
    encoded_message = pack(MSG_LEN_PACKING_FORMAT, len_msg) \
                      + pack(MSG_CODE_PACKING_FORMAT, msg_code) + msg_bytes
    return encoded_message


sock_one = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock_two = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

sock_one.bind((host, port_room_one))
sock_two.bind((host, port_room_two))

print("server listening on port one")
print("server listening on port two")

sock_one.listen(1)

sock_two.listen(1)

conn_one, addr_one = sock_one.accept()
conn_two, addr_two = sock_two.accept()

# get params of new stream
form, channels, rate, frame_len = get_stream_params()
msg_bytes = pack(AUDIO_FORMAT, form) + pack(CHANNEL_FORMAT, channels) + pack(FRAMERATE_FORMAT, rate) \
            + pack(FPB_FORMAT, FRAMES_PER_BUFFER) + pack(FRAME_LEN_FORMAT, frame_len)
msg_code = ClientServerMsg.NEW_STREAM
msg = encode_message(msg_code, msg_bytes)

conn_one.sendall(msg)
conn_two.sendall(msg)

data_one = conn_one.recv(1024)
data_two = conn_two.recv(1024)

code_one = unpack(MSG_CODE_PACKING_FORMAT, data_one[4:6])[0]
code_two = unpack(MSG_CODE_PACKING_FORMAT, data_two[4:6])[0]

assert code_one == ClientServerMsg.STREAM_REQ
print("got req code_one")
time.sleep(.2)

assert code_two == ClientServerMsg.STREAM_REQ
print("got req code_two")
time.sleep(.2)

def get_location():
    Room1_Read = 0
    Room2_Read = 0
    Current_Read = 0
    in_room = 0

    scanner = Scanner().withDelegate(ScanDelegate(Room1_Read, Room2_Read))

    while True:
        scanner.scan()

        for room in rooms_dict:
            for sub in rooms_dict[room]:
                if ((Room1_Read <= sub[0][0]) and (Room1_Read >= sub[0][1])) and ((Room2_Read <= sub[1][0]) and (Room2_Read >= sub[1][1])):
                    Current_Read = room
                    in_room = 1
                    break
            if in_room:
                break
        if in_room:
            if (Current_Read == 1) and (CURRENT_CONNECTION != conn_one):
                CURRENT_CONNECTION = conn_one
            elif (Current_Read == 2) and (CURRENT_CONNECTION != conn_one):
                CURRENT_CONNECTION = conn_two
            in_room = 0
            Current_Read = 0
        else:
            if CURRENT_CONNECTION != 0:
                CURRENT_CONNECTION = 0

        time.sleep(1)


def stream_music():
    while True:
        while CURRENT_CONNECTION != 0:
            if CURRENT_CONNECTION == conn_one:
                print("waiting...")

                print('Server: got rsp')
                code_one = unpack(MSG_CODE_PACKING_FORMAT, data_one[4:6])[0]
                print(code_one)
                assert code_one == ClientServerMsg.STREAM_REQ
                frames = b''
                for i in range(10):
                    frames += get_data()
                code_one = ClientServerMsg.STREAM_RSP
                print("Server: sending data")
                conn_one.sendall(encode_message(code_one, frames))
                data_one = conn_one.recv(1024)
            elif CURRENT_CONNECTION == conn_two:
                print("waiting...")

                print('Server: got rsp')
                code_two = unpack(MSG_CODE_PACKING_FORMAT, data_two[4:6])[0]
                print(code_two)
                assert code_two == ClientServerMsg.STREAM_REQ
                frames = b''
                for i in range(10):
                    frames += get_data()
                code_two = ClientServerMsg.STREAM_RSP
                print("Server: sending data")
                conn_two.sendall(encode_message(code_two, frames))
                data_two = conn_two.recv(1024)


if __name__ == "__main__":
    location_process = multiprocessing.Process(name='location_process', target=get_location)
    stream_process = multiprocessing.Process(name='stream_process', target=stream_music)

    location_process.start()
    stream_process.start()