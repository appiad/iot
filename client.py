import socket
import pyaudio
import time
import multiprocessing as mp
from struct import *
from enum import IntEnum, auto

host = '127.0.0.1'
port = 8000
NUM_BYTES_TO_RECV = 65536

MSG_HEADER_LEN = 6 # 4 bytes + 2
MSG_LEN_PACKING_FORMAT = 'I' # uint32
MSG_CODE_PACKING_FORMAT = 'H' # uint16

DURATION_FORMAT = 'f' # float32

AUDIO_FORMAT = 'I' #uint32
CHANNEL_FORMAT = 'H' # uint16
FPB_FORMAT = 'H' #uint16
FRAMERATE_FORMAT = 'H' #uint16

MIN_QUEUE_LEN = 15

SLEEP_INTERVAL = .05
SLEEP_INT_LARGE = .1

class ClientServerMsg(IntEnum):
    HALT = auto()
    NEW_STREAM = auto()
    STREAM_RSP = auto()
    # Client
    HALT_RSP = auto()
    STREAM_REQ = auto()

class ClientAudioMsg(IntEnum):
    # Client
    HALT = auto()
    NEW_STREAM_INFO = auto()
    STREAM_READY = auto()

    # AudioStream
    HALT_RSP = auto()
    WAITING_FOR_STREAM = auto()
    INACTIVE = auto()

class ClientState(IntEnum):
    INACTIVE = auto()
    ACTIVE = auto()
    WAITING_FOR_STREAM = auto()

class AudioStreamState(IntEnum):
    PLAYING = auto()
    NOT_PLAYING = auto()
    WAITING_FOR_STREAM = auto()
    NEED_SEND_HALT_RSP = auto()
    NEED_CLEANUP = auto()

py_audio = pyaudio.PyAudio()

class AudioStream:
    def __init__(self):
        self.stream = None
        self.start_time = 0.
        self.end_time = 0.
        self.state = AudioStreamState.NOT_PLAYING

    def create_stream(self,form, channels, rate,frames_per_buffer, stream_callback):
        self.stream =  py_audio.open(format=form,
                                     channels=channels, rate=rate, output=True,
                                     frames_per_buffer=frames_per_buffer,
                                     stream_callback=stream_callback, start=False
                                     )
    def close_active_stream(self):
        if self.stream is not None:
            if self.stream.is_active():
                self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        self.start_time = 0.
        self.end_time = 0.


class Client:
    def __init__(self,hostname,portname, comm_queue, comm_arr, comm_val):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((hostname, portname))
        self.sock.settimeout(SLEEP_INTERVAL)
        self.byte_buffer = bytearray()
        self.comm_queue = comm_queue
        self.comm_arr = comm_arr
        self.comm_val = comm_val
        self.state = ClientState.INACTIVE
        self.cur_stream_info = {
            'size': 65536  # change to -1 later
        }

    def encode_message(self, msg_code, msg_bytes=b''):
        len_msg = 0 #if msg_bytes is None else len(msg_bytes)
        len_msg += MSG_HEADER_LEN
        encoded_message = pack(MSG_LEN_PACKING_FORMAT, len_msg) \
                          + pack(MSG_CODE_PACKING_FORMAT, msg_code) #+ msg_bytes
        return encoded_message

    def receive_complete_message(self, expected_msg_len=float("inf")):
        """read socket stream until entire message is read"""
        got_msg_header = False
        msg_code = None
        while len(self.byte_buffer) < expected_msg_len:
            try:
                data = self.sock.recv(NUM_BYTES_TO_RECV)
                self.byte_buffer += data
                if not got_msg_header:
                    if len(self.byte_buffer) >= MSG_HEADER_LEN:
                        msg_code = unpack(MSG_CODE_PACKING_FORMAT, self.byte_buffer[4:6])[0]
                        expected_msg_len = unpack(MSG_LEN_PACKING_FORMAT, self.byte_buffer[:4])[0]
                        got_msg_header = True
            except socket.timeout:
                time.sleep(SLEEP_INTERVAL)
        return msg_code

    def get_new_stream_params(self):
        form = unpack(AUDIO_FORMAT,self.byte_buffer[6:10])[0]
        channels = unpack(CHANNEL_FORMAT, self.byte_buffer[10:12])[0]
        rate = unpack(FRAMERATE_FORMAT, self.byte_buffer[12:14])[0]
        frames_per_buffer = unpack(FPB_FORMAT, self.byte_buffer[14:16])[0]
        return form, channels, rate, frames_per_buffer

    def send_new_stream_params(self):
        form, channels, rate, frames_per_buffer = self.get_new_stream_params()
        self.comm_arr[0] = form
        self.comm_arr[1] = channels
        self.comm_arr[2] = rate
        self.comm_arr[3] = frames_per_buffer
        self.comm_val.value = ClientAudioMsg.NEW_STREAM_INFO


    def preload_queue(self):
        received_halt_code = False
        for i in range(3):
            req = ClientServerMsg.STREAM_REQ
            print("Client sending req")
            try:
                m = self.encode_message(req)
                self.sock.sendall(m)
            except:
                print("FAIL")
            msg_code = self.receive_complete_message()
            print("Client: got req")
            if msg_code == ClientServerMsg.HALT:
                received_halt_code = True
                break
            frames = self.get_stream_frames()
            for frame in frames:
                self.comm_queue.put(frame)

        if received_halt_code:
            self.handle_halt()
        else:
            while True:
                if self.comm_val.value != ClientAudioMsg.WAITING_FOR_STREAM:
                    time.sleep(.3)
                else:
                    break
            self.comm_val.value = ClientAudioMsg.STREAM_READY
            print(self.comm_val.value)

    def get_stream_frames(self):
        frames = []
        pos = MSG_HEADER_LEN
        data_size = self.cur_stream_info['size']
        while pos < len(self.byte_buffer):
            frames.append(bytes(self.byte_buffer[pos:pos+data_size]))
            pos += data_size
        self.byte_buffer.clear()
        return frames

    def quick_read(self):
        msg_code = None
        try:
            data = self.sock.recv(NUM_BYTES_TO_RECV)
            self.byte_buffer += data
            if len(self.byte_buffer) >= MSG_HEADER_LEN:
                msg_code = unpack(MSG_CODE_PACKING_FORMAT, self.byte_buffer[4:6])[0]
                expected_msg_len = unpack(MSG_LEN_PACKING_FORMAT, self.byte_buffer[:4])[0]
                self.receive_complete_message(expected_msg_len[0])
            else:
                self.receive_complete_message()
        except socket.timeout:
            pass
        return msg_code

    def handle_halt(self):
        self.byte_buffer.clear()
        self.comm_val.value = ClientAudioMsg.HALT
        while True:
            if self.comm_val.value == ClientAudioMsg.HALT_RSP:
                break
            time.sleep(SLEEP_INTERVAL)
        msg_code = ClientServerMsg.HALT_RSP
        duration_bytes = pack(DURATION_FORMAT,self.comm_arr[0])
        msg = self.encode_message(msg_code, duration_bytes)
        self.sock.sendall(msg)
        while not self.comm_queue.empty():
            self.comm_queue.get()
        self.state = ClientState.INACTIVE


def client_process(comm_queue, comm_arr, comm_val):
    print("started client process")
    client = Client(host, port, comm_queue, comm_arr, comm_val)
    need_more_data = False; new_stream_soon = False
    while True:
        while client.state == ClientState.INACTIVE:
            msg_code = client.receive_complete_message()
            if msg_code == ClientServerMsg.NEW_STREAM:
                print("Client: Got Stream")
                client.send_new_stream_params()
                client.byte_buffer.clear()
                client.state = ClientState.ACTIVE
                client.preload_queue()
                print("Client: preloaded data")

        while client.state == ClientState.ACTIVE:
            if client.comm_queue.qsize() < MIN_QUEUE_LEN and not new_stream_soon:
                print(f'Q size: {client.comm_queue.qsize()}')
                need_more_data = True

            if need_more_data:
                msg_code = ClientServerMsg.STREAM_REQ
                client.sock.sendall(client.encode_message(msg_code))
                need_more_data = False
                msg_rsp = client.receive_complete_message()
            else:
                msg_rsp = client.quick_read()

            if msg_rsp == ClientServerMsg.HALT:
                client.handle_halt()
                new_stream_soon = False

            elif msg_rsp == ClientServerMsg.STREAM_RSP:
                frames = client.get_stream_frames()
                for frame in frames:
                    client.comm_queue.put(frame)

            elif msg_rsp == ClientServerMsg.NEW_STREAM:
                new_stream_soon = True
                client.send_new_stream_params()
                client.comm_val.value = ClientAudioMsg.NEW_STREAM_INFO
                client.byte_buffer.clear()

            if new_stream_soon:
                if client.comm_val.value == ClientAudioMsg.WAITING_FOR_STREAM:
                    new_stream_soon = False
                    client.preload_queue()

            time.sleep(SLEEP_INTERVAL)


def audio_stream_process(comm_queue, comm_arr, comm_val):
    print("AS: entry")
    audio_stream = AudioStream()
    def read_callback(in_data, frame_count, time_info, status):

        return_code = pyaudio.paContinue
        data = comm_queue.get() if not comm_queue.empty() else b'0'
        print("got more")
        if comm_val.value == ClientAudioMsg.HALT:
            audio_stream.end_time = time.time()
            audio_stream.state = AudioStreamState.NEED_SEND_HALT_RSP
            return_code = pyaudio.paComplete
            data = data[:5] # just random bytes

        if data == b'0':
            print("queue empty unexpectedly")
        return data, return_code

    while True:
        if audio_stream.state == AudioStreamState.NOT_PLAYING:
            if comm_val.value == ClientAudioMsg.NEW_STREAM_INFO:
                audio_stream.create_stream(form=int(comm_arr[0]), channels=int(comm_arr[1]),
                                           rate=int(comm_arr[2]), frames_per_buffer=int(comm_arr[3]),
                                           stream_callback=read_callback)
                audio_stream.state = AudioStreamState.WAITING_FOR_STREAM
                comm_val.value = ClientAudioMsg.WAITING_FOR_STREAM
                print("AS: waiting for stream")
            else:
                time.sleep(SLEEP_INT_LARGE)

        elif audio_stream.state == AudioStreamState.WAITING_FOR_STREAM:
            if comm_val.value == ClientAudioMsg.STREAM_READY:
                print("AS: STARTING STREAM!")
                audio_stream.state = AudioStreamState.PLAYING
                audio_stream.stream.start_stream()
                audio_stream.start_time = time.time()
            elif comm_val.value == ClientAudioMsg.HALT:
                audio_stream.state = AudioStreamState.NEED_SEND_HALT_RSP
            time.sleep(SLEEP_INT_LARGE)

        elif audio_stream.state == AudioStreamState.NEED_CLEANUP:
            audio_stream.close_active_stream()
            audio_stream.state = AudioStreamState.NOT_PLAYING

        elif audio_stream.state == AudioStreamState.NEED_SEND_HALT_RSP:
            duration = audio_stream.end_time - audio_stream.start_time
            comm_arr[0] = duration
            audio_stream.close_active_stream()
            audio_stream.state = AudioStreamState.NOT_PLAYING
            comm_val.value = ClientAudioMsg.HALT_RSP

        else:
            time.sleep(SLEEP_INT_LARGE)


def main():
    comm_queue = mp.Queue()
    comm_array = mp.Array('f',4)
    comm_val = mp.Value('i',0)
    p2 = mp.Process(target=client_process, args=(comm_queue, comm_array, comm_val))
    p2.start()
    audio_stream_process(comm_queue, comm_array, comm_val)
    print("did aud stream")
    p2.join()

if __name__ == '__main__':
    main()
    py_audio.terminate()