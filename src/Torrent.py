import requests
import bencode
import struct
import time
import threading
import os
import random
import string
from io import BytesIO
import Queue

import TorrentReader
import PeerConnection

DEBUG = True


class Piece(object):

    NOT_FOUND = 1
    WAITING = 2
    ASSIGNED = 3
    COMPLETE = 4

    def __init__(self, index, file_path, sha1_hash):
        self.index = index
        self.file_path = file_path
        self.owners = set()
        self.sha1_hash = sha1_hash
        self.assigned_peers = set()
        self.bytes = BytesIO()
        self.status = Piece.NOT_FOUND

    def add_owner(self, peer):
        self.owners.add(peer)
        if self.status == Piece.NOT_FOUND:
            self.status = Piece.WAITING

    def remove_owner(self, peer):
        self.owners.discard(peer)
        if len(self.owners) == 0:
            self.status = Piece.NOT_FOUND

    def remove_assigned_peer(self, peer):
        self.assigned_peers.discard(peer)
        if len(self.assigned_peers) == 0:
            self.status = Piece.WAITING

    def assign_peer(self, peer):
        self.assigned_peers.add(peer)
        self.status = Piece.ASSIGNED

    def __str__(self):
        return 'Piece Number: {}\nOwners: {}\nsha1: {}\npeers: {}\nbytes: {}\nstatus: {}\n'.format(self.index,
                                                                                                   self.owners,
                                                                                                   self.sha1_hash,
                                                                                                   self.assigned_peers,
                                                                                                   self.bytes,
                                                                                                   self.status)


class Torrent(object):

    def __init__(self, file_path, download_directory):
        self.complete = False
        self.finished_piece_queue = Queue.Queue()
        self.available_peers = []
        self.connected_peers = []
        self.dead_peers = []
        self.files = []
        self.download_directory = download_directory
        self.document, self.info_hash = TorrentReader.read_torrent(file_path)
        self.info = self.document[0]['info']
        self.port = 21
        self.uploaded = 0
        self.downloaded = 0
        self.peer_limit = 15
        self.total_size = None
        self.name = self.info['name']
        self.piece_acquisition_lock = threading.Lock()
        self.read_info()

        self.peer_id = '-AC0000-{}'.format(''.join(random.choice(string.ascii_uppercase +
                                                                 string.ascii_lowercase +
                                                                 string.digits) for _ in range(12)))
        self.info_hash_bytes = self.get_hash_bytes(self.info_hash)
        piece_hashes = self.info['pieces']
        piece_hashes = [piece_hashes[i:i+20] for i in range(0, len(piece_hashes), 20)]
        self.num_pieces = len(self.info['pieces']) / 20
        self.piece_map = [Piece(piece_index, file_path, piece_hashes[piece_index])
                          for piece_index in range(self.num_pieces)]

    def read_info(self):
        # Read Files and Paths
        base_dir = self.info['name']
        if 'files' in self.info.keys():
            byte_position = 0
            for dl_file in self.info['files']:
                path = base_dir
                for path_element in dl_file['path']:
                    path = os.path.join(path, path_element)
                file_dict = {'path': path,
                             'length': dl_file['length'],
                             'md5sum': dl_file.get('md5sum', None),
                             'byte_position': byte_position,
                             'selected': True}
                self.files.append(file_dict)
                byte_position += file_dict['length']
            self.total_size = byte_position
        else:
            # Single file mode
            self.total_size = self.info['length']
            single_file_dict = {'path': self.info['name'],
                                'length': self.info['length'],
                                'md5sum': self.info.get('md5sum', None),
                                'byte_position': 0,
                                'selected': True}
            self.files.append(single_file_dict)

    def update_selected_files(self):
        pass

    def update_available_peers(self, new_peers):
        for new_peer in new_peers:
            for old_peer in self.available_peers:
                if old_peer['ip'] == new_peer['ip']:
                    break
            else:
                self.available_peers.append(new_peer)

    def aggregate_bitfields(self):
        for piece in self.piece_map:
            piece_owners = set()
            for peer in self.connected_peers:
                if peer.bitfield[piece.index] == 1:
                    piece_owners.add(peer)
            piece.owners = piece_owners

    def get_next_piece(self, peer):
        self.piece_acquisition_lock.acquire()

        sorted_pieces = sorted(self.piece_map, key=lambda x: len(x.owners))
        undownloaded_pieces = [piece for piece in sorted_pieces if piece.status == Piece.NOT_FOUND]
        rarest_pieces = [piece for piece in undownloaded_pieces if peer.bitfield[piece.index] == 1]

        if rarest_pieces:
            rarest_piece = rarest_pieces[0]
            rarest_piece.assign_peer(peer)
            peer.assigned_piece = rarest_piece
        else:
            peer.assigned_piece = None

        self.piece_acquisition_lock.release()

    def peer_dispatch_worker(self):
        while not self.complete:
            # Remove dead connections
            dead_peers = [peer for peer in self.connected_peers if peer.alive is False]
            for peer in dead_peers:
                self.dead_peers.append(peer.peer_ip)
                self.log_msg('Removing dead peer: {}'.format(peer.peer_ip))
                self.connected_peers.remove(peer)
                if peer.assigned_piece:
                    peer.assigned_piece.remove_owner(peer)

            # Connect to new peers
            # Check to see that there are pieces left to download, otherwise, no need to connect to new peers
            pieces_left = len([piece for piece in self.piece_map if piece.status == Piece.NOT_FOUND])
            if pieces_left:
                connected_peer_ips = [peer.peer_ip for peer in self.connected_peers]
                eligible_peers = [p for p in self.available_peers
                                  if (p['ip'] not in connected_peer_ips) and p['ip'] not in self.dead_peers]
                for peer in eligible_peers:
                    if len(self.connected_peers) >= self.peer_limit or pieces_left == 0:
                        break
                    pieces_left -= 1
                    self.connected_peers.append(PeerConnection.PeerConnection(peer['ip'], peer['port'], self))

    def peer_request_worker(self):
        interval = None

        while not self.complete:
            event = 'started' if interval is None else None
            peer_data = self.request_peers(event=event)
            interval = peer_data['interval']
            self.update_available_peers(peer_data['peers'])
            self.log_msg('Peer Update: {}'.format(self.available_peers))
            time.sleep(interval)

    def allocate_files(self):
        for dl_file in self.files:
            file_path = os.path.join(self.download_directory, dl_file['path'])
            if not os.path.exists(os.path.dirname(file_path)):
                os.makedirs(os.path.dirname(file_path))
            with open(file_path, 'wb') as output_file:
                output_file.seek(dl_file['length'] - 1)
                output_file.write('\0')
                output_file.close()

    def write_piece(self, piece):
        piece_size = self.info['piece length']
        piece_byte_position = (piece.index * piece_size)
        piece_end = piece_byte_position + piece_size

        # Mark the piece as complete
        piece.status = Piece.COMPLETE

        # Find file/s the piece spans
        if 'files' in self.info.keys():
            piece_files = []
            for dl_file in self.files:
                dl_start = dl_file['byte_position']
                dl_end = dl_start + dl_file['length']
                total_range_width = min(dl_start, piece_byte_position) + max(dl_end, piece_end)
                piece_and_file_width = dl_file['length'] + piece_size
                if total_range_width <= piece_and_file_width:
                    piece_files.append(dl_file)
        else:
            piece_files = self.files

        for dl_file in piece_files:
            file_path = os.path.join(self.download_directory, dl_file['path'])
            with open(file_path, 'rb+') as f:
                # Seek to offset in piece
                piece_offset = max(0, dl_file['byte_position'] - piece_byte_position)
                piece.bytes.seek(piece_offset)

                # Seek to offset in file
                file_offset = 0
                if piece_byte_position > dl_file['byte_position']:
                    file_offset = piece_byte_position - dl_file['byte_position']
                    f.seek(file_offset)

                bytes_to_end_of_file = dl_file['length'] - file_offset

                num_bytes_to_write = min(piece_size, dl_file['length'], bytes_to_end_of_file)
                f.write(piece.bytes.read(num_bytes_to_write))

        # Free the memory for the bytes that were just written
        piece.bytes = BytesIO()

        # Check if all pieces have been written
        num_pieces = len(self.piece_map)
        num_complete_pieces = 0
        for piece in self.piece_map:
            if piece.status == Piece.COMPLETE:
                num_complete_pieces += 1

        if num_pieces == num_complete_pieces:
            self.complete_torrent_transfer()
            print "\n\n\n\n\n\n=============================================================================\nFINISHED"
            print "=============================================================================\n\n\n\n\n\n\n"
        else:
            print "\n\n\n\n\n\n"
            print "============================================================================="
            print "||                 PERCENT COMPLETE: {}% ".format((float(num_complete_pieces)/num_pieces)*100)
            print "=============================================================================\n\n\n\n\n\n\n"

    def complete_torrent_transfer(self):
        self.complete = True
        self.finished_piece_queue.put(None)

    def file_write_worker(self):
        self.allocate_files()

        while True:
            finished_piece = self.finished_piece_queue.get()
            if finished_piece is None:
                break
            self.write_piece(finished_piece)

    def start(self):
        peer_request_thread = threading.Thread(target=self.peer_request_worker)
        peer_request_thread.start()
        peer_dispatch_thread = threading.Thread(target=self.peer_dispatch_worker)
        peer_dispatch_thread.start()
        file_write_thread = threading.Thread(target=self.file_write_worker)
        file_write_thread.start()

    @staticmethod
    def log_msg(message):
        if DEBUG:
            print message

    def tracker_request(self, event):
        # Send request to tracker
        data = {'info_hash': self.info_hash_bytes,
                'peer_id': self.peer_id,
                'port': self.port,
                'uploaded': self.uploaded,
                'downloaded': self.downloaded,
                'left': self.total_size - self.downloaded,
                'compact': 1}

        if event:
            data['event'] = event

        tracker_url = self.document[0]['announce']
        self.log_msg('Tracker Request Data: {}'.format(data))
        response = requests.get(url=tracker_url, params=data)
        self.log_msg('Tracker Request URL: {}'.format(response.url))
        self.log_msg('Tracker Response: {}'.format(response.content))
        tracker_data = bencode.bdecode(response.content)
        self.log_msg('Tracker Response Decoded: {}'.format(tracker_data))

        if 'failure reason' in tracker_data.keys():
            raise Exception('No Peers Found. Error: {}'.format(tracker_data['failure reason']))

        return tracker_data

    def request_peers(self, event=''):
        peer_data = self.tracker_request(event=event)

        # Read IPV4 peers
        if 'peers' in peer_data:
            peers = peer_data['peers']
            peer_list = []
            if len(peers) % 6 != 0:
                raise Exception('Unexpected peer byte length')
            while peers:
                ip_addr_bytes = peers[:4]
                port = peers[4:6]
                peers = peers[6:]
                ip_str = '.'.join([str(b) for b in bytearray(ip_addr_bytes)])
                port_num = struct.unpack('>H', port)[0]
                peer_list.append({'ip': ip_str,
                                  'port': port_num})
            peer_data['peers'] = peer_list

        # Get ipv6 peers
        for peer_dict in peer_data.get('peers6', []):
            ipbytes = peer_dict['ip']
            ipv6 = []
            while True:
                next_two = hex(struct.unpack('>H', ipbytes[0:2])[0]).replace('0x', '')
                ipv6.append(next_two)
                ipbytes = ipbytes[2:]
                if not ipbytes:
                    break
            ipv6 = ':'.join(ipv6)
            peer_dict['ip'] = ipv6

        self.log_msg('Found Peers:{}'.format(peer_data))
        return peer_data

    @staticmethod
    def get_hash_bytes(hash_string):
        hex_hash = ''

        while True:
            next_two = hash_string[:2]
            hash_string = hash_string[2:]
            hex_hash += chr(int(next_two, 16))
            if not hash_string:
                break

        return hex_hash
