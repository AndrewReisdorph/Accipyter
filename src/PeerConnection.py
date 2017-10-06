import socket
import struct
import time
import Queue
import threading
import hashlib
import errno
from io import BytesIO

import Torrent

INTERNAL_QUIT = -3
KEEP_ALIVE = -2
HANDSHAKE = -1
CHOKE = 0
UNCHOKE = 1
INTERESTED = 2
NOT_INTERESTED = 3
HAVE = 4
BITFIELD = 5
REQUEST = 6
PIECE = 7
CANCEL = 8
PORT = 9

MAX_BLOCK_LENGTH = 2**14


class PeerConnection(threading.Thread):
    def __init__(self, ip, port, torrent):
        threading.Thread.__init__(self)
        self.debug_level = 99
        # Consider a connection alive until proven otherwise. This prevents peers from being removed before they've had
        # a chance to connect
        self.alive = True
        self.socket = None
        self.received_handshake = False
        self.peer_ip = ip
        self.peer_port = port
        self.info_hash = torrent.info_hash
        self.peer_id = None
        self.message_queue = Queue.Queue()
        self.outgoing_message_queue = Queue.Queue()
        self.torrent = torrent
        self.choked = True
        self.assigned_piece = None
        self.received_block_ranges = []
        self.discreet_block_ranges = []

        num_pieces = len(torrent.info['pieces']) / 20
        self.bitfield = [0] * num_pieces

        self.start()

    def reset(self):
        self.assigned_piece = None
        self.received_block_ranges = []
        self.discreet_block_ranges = []

    def run(self):
        if self.connect():
            self.do_handshake()
            self.socket_read_loop()

    def kill(self):
        self.alive = False
        self.socket.close()
        self.message_queue.put({'MESSAGE_ID': INTERNAL_QUIT})

    def log_message(self, message, level):
        if level <= self.debug_level:
            print message

    def connect(self):
        self.log_message('Connecting to {}:{} ...'.format(self.peer_ip, self.peer_port), 2)
        try:
            self.socket = socket.create_connection((self.peer_ip, self.peer_port))
        except (socket.error, socket.timeout) as e:
            self.log_message("CONNECTION DONE GOOFED: {}".format(e), 1)
            self.alive = False
            return False
        self.socket.setblocking(0)
        self.log_message('connection established...', 2)
        self.alive = True
        return True

    def do_handshake(self):
        protocol_strlen = chr(19)
        protocol_string = 'BitTorrent protocol'
        reserved = chr(0) * 8
        info_hash = self.torrent.info_hash_bytes
        peer_id = self.torrent.peer_id
        message = '{}{}{}{}{}'.format(protocol_strlen, protocol_string, reserved, info_hash, peer_id)
        self.socket.sendall(message)

    @staticmethod
    def read_handshake(handshake_str):
        handshake_len = len(handshake_str)
        if handshake_len != 68:
            raise(Exception('Unexpected handshake length: {}'.format(handshake_len)))

        handshake_dict = {}
        handshake_file = BytesIO(handshake_str)
        length = struct.unpack('B', handshake_file.read(1))[0]
        handshake_dict['protocol'] = handshake_file.read(length)
        handshake_dict['reserved'] = handshake_file.read(8)
        handshake_dict['info_hash'] = handshake_file.read(20)
        handshake_dict['peer_id'] = handshake_file.read(20)
        handshake_dict['MESSAGE_ID'] = HANDSHAKE

        return handshake_dict

    def extract_messages(self, data):
        if not self.received_handshake:
            first_byte = data.read(1)
            if first_byte == '\x13':
                data.seek(0)
                handshake_message = self.read_handshake(data.read(68))
                self.message_queue.put(handshake_message)
            else:
                raise(Exception('Expected Handshake, got: {}'.format(repr(first_byte))))

        while True:
            current_position = data.tell()
            data.read()
            end_position = data.tell()
            data.seek(current_position)

            if (end_position - current_position) < 5:
                break

            message_length = struct.unpack('>I', data.read(4))[0]
            data_available = (end_position - data.tell())
            if data_available < message_length:
                data.seek(data.tell()-4)
                break

            new_message = {}
            if message_length == 0:
                new_message['MESSAGE_ID'] = KEEP_ALIVE
            else:
                message_id = struct.unpack('B', data.read(1))[0]
                message = BytesIO(data.read(message_length - 1))

                new_message['MESSAGE_ID'] = message_id

                if message_id == CHOKE:
                    pass
                elif message_id == UNCHOKE:
                    pass
                elif message_id == INTERESTED:
                    pass
                elif message_id == NOT_INTERESTED:
                    pass
                elif message_id == HAVE:
                    piece_index = struct.unpack('>I', message.read(4))[0]
                    new_message['piece_index'] = piece_index

                elif message_id == BITFIELD:
                    bitfield = message.read()
                    new_message['bitfield'] = bitfield

                elif message_id in [REQUEST, CANCEL]:
                    new_message['index'] = struct.unpack('>I', message.read(4))[0]
                    new_message['begin'] = struct.unpack('>I', message.read(4))[0]
                    new_message['length'] = struct.unpack('>I', message.read(4))[0]

                elif message_id == PIECE:
                    new_message['index'] = struct.unpack('>I', message.read(4))[0]
                    new_message['begin'] = struct.unpack('>I', message.read(4))[0]
                    new_message['block'] = message.read(message_length-9)

                elif message_id == PORT:
                    new_message['port'] = struct.unpack('>I', message.read(4))[0]

                else:
                    self.log_message('Unexpected message id: {}\n\tlength:{}\n\tpayload:{}'.format(message_id,
                                                                                                   message_length,
                                                                                                   message.read()), 1)

            self.message_queue.put(new_message)

    def find_block_gap(self):
        # If the beginning of the block has not been filled in, prioritize that
        if not self.received_block_ranges or self.received_block_ranges[0][0] != 0:
            if not self.received_block_ranges:
                gap_size = MAX_BLOCK_LENGTH
            else:
                gap_size = self.received_block_ranges[0][0] - 1
            gap_start = 0
        elif len(self.received_block_ranges) == 1:
            piece_length = self.torrent.info['piece length']
            gap_size = (piece_length - 1) - self.received_block_ranges[0][1]
            gap_start = self.received_block_ranges[0][1] + 1
        else:
            gap_size = self.received_block_ranges[1][0] - self.received_block_ranges[0][1] - 2
            gap_start = self.received_block_ranges[0][1] + 1

        gap_size = min(gap_size, MAX_BLOCK_LENGTH)

        return gap_start, gap_size

    def consolidate_block_ranges(self):
        while True:
            change_made = False
            for byte_range_A in self.received_block_ranges:
                for byte_range_B in self.received_block_ranges:
                    if byte_range_A != byte_range_B:
                        if byte_range_B[0] == (byte_range_A[1] + 1):
                            new_range = (byte_range_A[0], byte_range_B[1])
                            self.received_block_ranges.remove(byte_range_A)
                            self.received_block_ranges.remove(byte_range_B)
                            self.received_block_ranges.append(new_range)
                            change_made = True
                            break
                if change_made:
                    break
            if not change_made:
                break
        self.received_block_ranges = sorted(self.received_block_ranges, key=lambda x: x[0])

    def handle_piece_message(self, message):
        if self.assigned_piece is None:
            return
        if message['index'] == self.assigned_piece.index:
            self.assigned_piece.bytes.seek(message['begin'])
            self.assigned_piece.bytes.write(message['block'])
            block_range = (message['begin'], message['begin'] + len(message['block']) - 1)
            if block_range in self.received_block_ranges or block_range in self.discreet_block_ranges:
                pass
            else:
                self.discreet_block_ranges.append(block_range)
                self.received_block_ranges.append(block_range)
                self.consolidate_block_ranges()

                bytes_completed = 0
                for br in self.received_block_ranges:
                    bytes_completed += br[1] - br[0]
                completion_percent = (bytes_completed/float(self.torrent.info['piece length']))*100
                self.log_message("{} {}% complete with piece {}".format(self.peer_ip,
                                                                        completion_percent,
                                                                        self.assigned_piece.index), 1)

                if len(self.received_block_ranges) == 1:
                    if self.received_block_ranges[0] == (0, self.torrent.info['piece length']-1):
                        self.assigned_piece.bytes.seek(0)
                        piece_hash = hashlib.sha1(self.assigned_piece.bytes.read()).digest()
                        if piece_hash == self.assigned_piece.sha1_hash:
                            self.torrent.finished_piece_queue.put(self.assigned_piece)
                            self.reset()
                        else:
                            expected_hash = repr(self.assigned_piece.sha1_hash).replace('\'', '')
                            actual_hash = repr(piece_hash).replace('\'', '')
                            self.log_message('Hash mismatch expected:{} got:{}'.format(expected_hash, actual_hash), 1)
                            self.assigned_piece.bytes.seek(0)
                            self.received_block_ranges = []
                            self.discreet_block_ranges = []

        else:
            self.log_message('Piece index mismatch. Expected: {} Got: {}'.format(self.assigned_piece.index,
                                                                                 message['index']), 1)

    def handle_bitfield_message(self, message):
        bitfield_str = BytesIO(message['bitfield'])
        piece_index = 0
        while True:
            next_byte = bitfield_str.read(1)
            if next_byte:
                next_byte = struct.unpack('B', next_byte)[0]
                for i in range(7, -1, -1):
                    if next_byte & (1 << i):
                        self.bitfield[piece_index] = 1
                    piece_index += 1
            else:
                break

    def handle_handshake_message(self, message):
        self.received_handshake = True
        self.peer_id = message['peer_id']
        self.log_message('Got handshake from: {}'.format(self.peer_id), 2)
        interested_message = '\x00\x00\x00\x01\x02'
        self.outgoing_message_queue.put(interested_message)

    def request_block(self):
        message_len = struct.pack('>I', 13)
        message_id = struct.pack('B', REQUEST)
        piece_index = struct.pack('>I', self.assigned_piece.index)
        block_begin, block_length = self.find_block_gap()
        block_begin = struct.pack('>I', block_begin)
        block_length = struct.pack('>I', block_length)

        request_message = '{}{}{}{}{}'.format(message_len, message_id, piece_index, block_begin, block_length)
        self.outgoing_message_queue.put(request_message)

    def message_worker(self):
        while True:
            try:
                message = self.message_queue.get(5)
            except Queue.Empty:
                message = None

            if message:
                message_id = message['MESSAGE_ID']

                if message_id == KEEP_ALIVE:
                    self.log_message('Got Keep Alive from: {}'.format(repr(self.peer_id)), 2)
                    keep_alive_message = '\x00\x00\x00\x00'
                    self.outgoing_message_queue.put(keep_alive_message)
                elif message_id == CHOKE:
                    self.choked = True
                elif message_id == UNCHOKE:
                    self.choked = False
                elif message_id == HAVE:
                    self.bitfield[message['piece_index']] = 1
                elif message_id == BITFIELD:
                    self.handle_bitfield_message(message)
                elif message_id == PIECE:
                    self.handle_piece_message(message)
                elif message_id == HANDSHAKE:
                    self.handle_handshake_message(message)
                elif message_id == INTERNAL_QUIT:
                    break

            if not self.choked:
                if self.assigned_piece is None:
                    self.torrent.get_next_piece(self)

                    # If the connected peer does not have any of the pieces needed, close the connection
                    if self.assigned_piece is None:
                        self.log_message("No pieces left to download "
                                         "or peer {} does not have any pieces needed.".format(self.peer_ip), 1)
                        self.kill()
                        break
                    else:
                        self.log_message("{} assigned piece {}".format(self.peer_ip, self.assigned_piece.index), 2)

                self.request_block()

    def socket_read_loop(self):
        data = BytesIO()
        last_msg_time = time.time()
        message_worker = threading.Thread(target=self.message_worker)
        message_worker.start()

        while self.alive:
            try:
                socket_received = self.socket.recv(4096)
            except socket.error as e:
                error_number = e.args[0]
                if error_number == errno.EWOULDBLOCK:
                    socket_received = None
                else:
                    self.log_message("WE HAD A PROBLEM: {}".format(e), 1)
                    self.kill()
                    break

            if socket_received:
                # Seek to end of data
                data.read()
                data.write(socket_received)
                data.seek(0)
                self.extract_messages(data)
                data = BytesIO(data.read())
                last_msg_time = time.time()

            if not self.outgoing_message_queue.empty():
                outgoing_message = self.outgoing_message_queue.get()
                self.socket.sendall(outgoing_message)

            if time.time() - last_msg_time >= 120:
                self.log_message('Connection timed out', 1)
                self.alive = False
                break


if __name__ == '__main__':
    t = Torrent.Torrent(r"C:\Users\Andrew\Downloads\torrent stuff\ubuntu-16.10-desktop-amd64.iso.torrent",
                        r"C:\Users\Andrew\Downloads")
    t.start()
