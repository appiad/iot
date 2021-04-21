import socket
import wave
import pyaudio
import time
from struct import *
from enum import IntEnum, auto

host = '127.0.0.1'
port = 8000
NUM_BYTES_TO_RECV = 65536  # max number of bytes to recv from socket

MSG_HEADER_LEN = 6  # 4 bytes (msg length) + 2 bytes (ClientServer.Msg)
MSG_LEN_PACKING_FORMAT = 'I'  # uint32
MSG_CODE_PACKING_FORMAT = 'H'  # uint16, packing format of ClientServerMsg

"""TODO: Add format for frame size and check header still works"""
# Packing format of duration (seconds) song has been played for
DURATION_FORMAT = 'f'  # float32

# Packing format of PyAudio stream initialization parameters
AUDIO_FORMAT = 'I'  # uint32
CHANNEL_FORMAT = 'H'  # uint16
FPB_FORMAT = 'H'  # uint16
FRAMERATE_FORMAT = 'H'  # uint16

MIN_QUEUE_LEN = 15

# sleep time in seconds
SLEEP_INTERVAL = .05
SLEEP_INT_LARGE = .1


# Message subject sent between the Client and server through sockets
class ClientServerMsg(IntEnum):
    """TODO: Add termination command from Server to terminate processes"""
    # Server sends
    HALT = auto()
    NEW_STREAM = auto()
    STREAM_RSP = auto()

    # Client sends
    HALT_RSP = auto()
    STREAM_REQ = auto()


# Messages sent between the Client and AudioStream process by setting shared
# comm_val
class ClientAudioMsg(IntEnum):
    # Client sends
    HALT = auto()
    NEW_STREAM_INFO = auto()
    STREAM_READY = auto()

    # AudioStream sends
    HALT_RSP = auto()
    WAITING_FOR_STREAM = auto()
    INACTIVE = auto()


# States of the Client
class ClientState(IntEnum):
    INACTIVE = auto()
    ACTIVE = auto()


# States of the AudioStream
class AudioStreamState(IntEnum):
    PLAYING = auto()
    NOT_PLAYING = auto()
    WAITING_FOR_STREAM = auto()
    NEED_SEND_HALT_RSP = auto()
    NEED_CLEANUP = auto()

wf = wave.open('wave_files/a_boogie.wav', 'rb')

def get_data():
    data = wf.readframes(16384)
    return data

def encode_message(msg_code, msg_bytes=b''):
    len_msg = 0 if msg_bytes is None else len(msg_bytes)
    len_msg += MSG_HEADER_LEN
    encoded_message = pack(MSG_LEN_PACKING_FORMAT, len_msg) \
                      + pack(MSG_CODE_PACKING_FORMAT, msg_code) + msg_bytes
    return encoded_message

# audio, channel, framerate, FPB
py_audio = pyaudio.PyAudio()
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind((host,port))
    print("server listening")
    sock.listen()
    conn, addr = sock.accept()

    form = py_audio.get_format_from_width(wf.getsampwidth())
    channels = wf.getnchannels()
    rate = wf.getframerate()
    frames_per_buffer = 16384
    msg_b = pack(AUDIO_FORMAT, form) + pack(CHANNEL_FORMAT, channels) + pack(FRAMERATE_FORMAT, rate) \
       + pack(FPB_FORMAT, frames_per_buffer)
    msg_code = ClientServerMsg.NEW_STREAM
    msg = encode_message(msg_code, msg_b)
    conn.sendall(msg)

    data = conn.recv(1024)
    code = unpack(MSG_CODE_PACKING_FORMAT, data[4:6])[0]
    assert code == ClientServerMsg.STREAM_REQ
    print ("got req code")
    time.sleep(.2)
    while True:
        print("waiting...")

        print('Server: got rsp')
        code = unpack(MSG_CODE_PACKING_FORMAT, data[4:6])[0]
        print(code)
        assert code == ClientServerMsg.STREAM_REQ
        frames = b''
        for i in range(10):
            frames += get_data()
        code = ClientServerMsg.STREAM_RSP
        print("Server: sending data")
        conn.sendall(encode_message(code, frames))
        data = conn.recv(1024)



