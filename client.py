import socket
import pyaudio
import time
import multiprocessing as mp
from struct import *
from enum import IntEnum, auto

host = '127.0.0.1'
port = 8000
NUM_BYTES_TO_RECV = 65536  # max number of bytes to recv from socket

MSG_HEADER_LEN = 6 # 4 bytes (msg length) + 2 bytes (ClientServer.Msg)
MSG_LEN_PACKING_FORMAT = 'I' # uint32
MSG_CODE_PACKING_FORMAT = 'H' # uint16, packing format of ClientServerMsg

# TODO: Add format for frame size and check header still works
# Packing format of duration (seconds) song has been played for
DURATION_FORMAT = 'f' # float32

# Packing format of PyAudio stream initialization parameters
AUDIO_FORMAT = 'I' #uint32
CHANNEL_FORMAT = 'H' # uint16
FPB_FORMAT = 'H' #uint16
FRAMERATE_FORMAT = 'H' #uint16
FRAME_LEN_FORMAT = 'I' #uint32

# frames per buffer for PyAudio
FRAMES_PER_BUFFER = 16384

MIN_QUEUE_LEN = 15

# sleep time in seconds
SLEEP_INTERVAL = .05
SLEEP_INT_LARGE = .1

# Message subject sent between the Client and server through sockets
class ClientServerMsg(IntEnum):
    # TODO: Add termination command from Server to terminate processes
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

py_audio = pyaudio.PyAudio()

class AudioStream:
    def __init__(self):
        self.stream = None  # PyAudio stream
        # end and start time of the current music being played
        self.start_time = 0.
        self.end_time = 0.
        self.state = AudioStreamState.NOT_PLAYING

    def create_stream(self,form, channels, rate,frames_per_buffer, stream_callback):
        """
        Create PyAudio stream with given parameters
        :param form: Sampling size and format
        :param channels: Number of channels
        :param rate: Sampling rate
        :param frames_per_buffer: Specifies the number of frames per buffer
        :param stream_callback: Specifies a callback function for non-blocking (callback) operation
        """
        self.stream =  py_audio.open(format=form,
                                     channels=channels, rate=rate, output=True,
                                     frames_per_buffer=frames_per_buffer,
                                     stream_callback=stream_callback, start=False
                                     )
    def close_active_stream(self):
        """
        Close the current PyAudio stream and reset our tracking of stream time
        """
        if self.stream is not None:
            if self.stream.is_active():
                self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        self.start_time = 0.
        self.end_time = 0.


class Client:
    def __init__(self,hostname,portname, comm_queue, comm_arr, comm_val):
        """
        Client: handles communication between AudioStream and Server
        :param hostname: host for socket to bind to
        :param portname: port for socket to bind to
        :param comm_queue: queue shared with the AudioStream process for inter-process
            communication (IPC)
        :param comm_arr: array shared with the AudioStream process for IPC
        :param comm_val: integer variable shared with the AudioStream process for IPC
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((hostname, portname))
        # set recv calls to raise a socket.timeout exception after the given interval
        self.sock.settimeout(SLEEP_INTERVAL)
        self.byte_buffer = bytearray() # stores raw bytes received from socket communication
        self.comm_queue = comm_queue
        self.comm_arr = comm_arr
        self.comm_val = comm_val
        self.state = ClientState.INACTIVE
        # holds the size of each frame of stream data that is expected in the AudioStream
        # read_callback. Accounts for number of channels and bytes-per-channel
        self.cur_stream_info = {
            'frame_len': -1
        }

    def encode_message(self, msg_code, msg_bytes=b''):
        """
        Used for sending messages through sockets.
        Takes a message code (integer) and an optional message body (bytes) and converts it to bytes
        and appends a header containing the entire message length and the message code.

        :param msg_code: The message code of the message to be sent. Should be its integer value not
            instead of bytes
        :param msg_bytes: The body of the message to be sent in bytes.
        :return bytes: The full encoded message with header ready to be sent.
        """
        len_msg = len(msg_bytes)
        len_msg += MSG_HEADER_LEN
        encoded_message = pack(MSG_LEN_PACKING_FORMAT, len_msg) \
                          + pack(MSG_CODE_PACKING_FORMAT, msg_code) + msg_bytes
        return encoded_message

    def receive_complete_message(self, expected_msg_len=float("inf")):
        """
        Continuously tries to receive a message through socket. If no message is received before the
        socket.timeout exception is raised it will sleep and then try again. This function will not return
        until it receives a message from the socket and the entire message is received as identified
        in the message header of the received message.
        Entire msg (including header) is stored in self.byte_buffer

        :param expected_msg_len: Optional length of message to be received. Defaults to infinity but will
            automatically be set to proper value once message is received and the length of the message
            is read from the header.
        :return ClientServerMsg: The message code of the message
        """
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


    def quick_read(self):
        """
        Attempts to receive a socket message just once. If timeout occurs a msg code of None is
        returned. If any part of a message is retrieved then self.receive_complete_message() is
        called to ensure we receive the entire msg and only return once it gets it. That msg_code
        is then returned. Entire msg (including header) is stored in self.byte_buffer
        :return msg_code: None if socket was empty, else ClientServerMsg
        """
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


    def get_new_stream_params(self):
        """
        Decodes and returns the parameters of the incoming audio stream.
        :return: PuAudio stream parameters
        """
        form = unpack(AUDIO_FORMAT,self.byte_buffer[6:10])[0]
        channels = unpack(CHANNEL_FORMAT, self.byte_buffer[10:12])[0]
        rate = unpack(FRAMERATE_FORMAT, self.byte_buffer[12:14])[0]
        frames_per_buffer = unpack(FPB_FORMAT, self.byte_buffer[14:16])[0]
        self.cur_stream_info['frame_len'] = unpack(FRAME_LEN_FORMAT, self.byte_buffer[16:20])[0]
        return form, channels, rate, frames_per_buffer

    def send_new_stream_params(self):
        """
        Sends the parameters of the incoming audio stream to the AudioStream so it can initialize its
        PyAudio stream with them.
        """
        form, channels, rate, frames_per_buffer = self.get_new_stream_params()
        self.comm_arr[0] = form
        self.comm_arr[1] = channels
        self.comm_arr[2] = rate
        self.comm_arr[3] = frames_per_buffer
        self.comm_val.value = ClientAudioMsg.NEW_STREAM_INFO


    def preload_queue(self):
        """
        After receiving a ClientServerMsg.NEW_STREAM msg, ask the Server for audio data
        (ClientServerMsg.STREAM_REQ) to preload the queue that AudioStream will consume from.
        Once done notify the AudioStream that the data is ready so it can start playing.
        If a ClientServerMsg.HALT msg is received during communication it is handled properly in here.
        """
        received_halt_code = False
        print("Client: Preloading queue")
        for i in range(3):
            req = ClientServerMsg.STREAM_REQ
            m = self.encode_message(req)
            self.sock.sendall(m)
            msg_code = self.receive_complete_message()
            if msg_code == ClientServerMsg.HALT:
                received_halt_code = True
                break
            frames = self.get_stream_frames()
            for frame in frames:
                self.comm_queue.put(frame)

        if received_halt_code:
            print("Client: Received HALT during queue preloading")
            self.handle_halt()
        else:
            print("Client: Queue preloading done")
            while True:
                if self.comm_val.value != ClientAudioMsg.WAITING_FOR_STREAM:
                    time.sleep(.3)
                else:
                    break
            self.comm_val.value = ClientAudioMsg.STREAM_READY


    def get_stream_frames(self):
        """
        Returns the individual frames stored in a list of the next audio stream frames received
        from the Server.
        :return list(bytes): list of audio frames
        """
        frames = []
        pos = MSG_HEADER_LEN
        # actual size of each frame of data accounting for # of channels and bytes-per-channel
        data_size = self.cur_stream_info['frame_len']
        while pos < len(self.byte_buffer):
            frames.append(bytes(self.byte_buffer[pos:pos+data_size]))
            pos += data_size
        self.byte_buffer.clear()
        return frames

    def handle_halt(self):
        """
        Handles a HALT msg received from server. Tells the AudioStream to stop playing, send the
        duration of time it played for (through queue) and then go inactive. Forwards the stream
        duration to the Server in a HALT_RSP. Then clears any remaining data in queue and goes
        inactive.
        :return:
        """
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
    """Entry point for process that handles communicating with AudioStream process and Server"""

    print("Client: Client process entered")
    client = Client(host, port, comm_queue, comm_arr, comm_val)
    need_more_data = False; new_stream_soon = False

    while True: # replace True w/ while not_terminated or something
        while client.state == ClientState.INACTIVE:
            msg_code = client.receive_complete_message()
            if msg_code == ClientServerMsg.NEW_STREAM:
                print("Client: Got New Stream from Server")
                client.send_new_stream_params()
                client.byte_buffer.clear()
                client.state = ClientState.ACTIVE
                client.preload_queue()

        while client.state == ClientState.ACTIVE:
            if client.comm_queue.qsize() < MIN_QUEUE_LEN and not new_stream_soon:
                print(f'Client: Q size: {client.comm_queue.qsize()}')
                need_more_data = True

            if need_more_data:
                # Ask server for more stream data and perform blocking socket read until we
                # receive a response
                msg_code = ClientServerMsg.STREAM_REQ
                client.sock.sendall(client.encode_message(msg_code))
                need_more_data = False
                msg_rsp = client.receive_complete_message()

            else:
                # Data isn't needed, perform a quick non-blocking read to see if we've received
                # any important msg (e.g. HALT or TERMINATE)
                msg_rsp = client.quick_read()

            if msg_rsp == ClientServerMsg.HALT:
                client.handle_halt()
                new_stream_soon = False

            elif msg_rsp == ClientServerMsg.STREAM_RSP:
                # add more frames to queue
                frames = client.get_stream_frames()
                for frame in frames:
                    client.comm_queue.put(frame)

            # Different audio file will be played after next STREAM_REQ. Notify AudioStream and send
            # new parameters to use once its done playing last bytes of current stream.
            elif msg_rsp == ClientServerMsg.NEW_STREAM:
                new_stream_soon = True
                client.send_new_stream_params()
                client.comm_val.value = ClientAudioMsg.NEW_STREAM_INFO
                client.byte_buffer.clear()

            # If AudioStream is ready for the new stream then preload the queue and notify it.
            if new_stream_soon:
                if client.comm_val.value == ClientAudioMsg.WAITING_FOR_STREAM:
                    new_stream_soon = False
                    client.preload_queue()

            time.sleep(SLEEP_INTERVAL)


def audio_stream_process(comm_queue, comm_arr, comm_val):
    """Entry point for process that handles playing music through PyAudio"""

    print("AS: process entry")
    audio_stream = AudioStream()
    def read_callback(in_data, frame_count, time_info, status):
        """
        Callback called automatically by PyAudio stream in a separate thread when it needs more
        audio data. Retrieves it from the queue.
        :return data (bytes): The audio stream data to be played
                return_code (int): code telling PyAudio if there will be more data to be played after
                    this call. If not it terminates after playing the data about to be returned.
        """
        return_code = pyaudio.paContinue
        data = comm_queue.get() if not comm_queue.empty() else b'0'
        print("AS: got more data")
        if comm_val.value == ClientAudioMsg.HALT:
            audio_stream.end_time = time.time()
            audio_stream.state = AudioStreamState.NEED_SEND_HALT_RSP
            return_code = pyaudio.paComplete
            data = data[:5] # just random bytes PyAudio will play before terminating

        if data == b'0':
            print("AS: queue empty unexpectedly")
        return data, return_code

    while True: # replace True w/ while not_terminated or something
        if audio_stream.state == AudioStreamState.NOT_PLAYING:
            # create new stream with parameters received from Client when signaled
            if comm_val.value == ClientAudioMsg.NEW_STREAM_INFO:
                audio_stream.create_stream(form=int(comm_arr[0]), channels=int(comm_arr[1]),
                                           rate=int(comm_arr[2]), frames_per_buffer=int(comm_arr[3]),
                                           stream_callback=read_callback)
                audio_stream.state = AudioStreamState.WAITING_FOR_STREAM
                comm_val.value = ClientAudioMsg.WAITING_FOR_STREAM
                print("AS: waiting for stream bytes in queue")
            else:
                time.sleep(SLEEP_INT_LARGE)

        elif audio_stream.state == AudioStreamState.WAITING_FOR_STREAM:
            # Start stream once Client has preloaded the queue with stream frames
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
            if audio_stream.stream is None or not audio_stream.stream.is_active():
                audio_stream.state = AudioStreamState.NOT_PLAYING
            else:
                # If PLAYING then main thread sleeps while PyAudio periodically calls read_callback in a
                # separate thread when it needs more data .
                time.sleep(SLEEP_INT_LARGE)


def main():
    # Inter-process communication (IPC) objects used for communication between Client and AudioStream
    # processes
    comm_queue = mp.Queue()
    comm_array = mp.Array('f',4)
    comm_val = mp.Value('i',0)

    # start Client process
    p2 = mp.Process(target=client_process, args=(comm_queue, comm_array, comm_val))
    p2.start()

    audio_stream_process(comm_queue, comm_array, comm_val)
    print("AudioStream process completed.")
    p2.join()

if __name__ == '__main__':
    main()
    py_audio.terminate()