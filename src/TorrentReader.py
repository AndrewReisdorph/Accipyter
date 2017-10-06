import struct
import hashlib
STRING = 0
INT = 1
LIST = 2
DICTIONARY = 3

info_dict_position = None
info_dict_size = None


def check_next_char(file):
    next_char = file.read(1)
    file.seek(file.tell()-1)
    return next_char


def read_number(file):
    digits = ''
    while True:
        next_digit = file.read(1)
        if next_digit.isdigit():
            digits += next_digit
        else:
            file.seek(file.tell()-1)
            break

    #print "get_data_size_and_delimiter detected size: {} with delimiter: {}".format(digits, repr(next_digit))

    digits = int(digits)

    return digits


def get_next_list(file):
    next_list = []
    list_specifier = file.read(1)
    while True:
        data_type = get_next_datatype(file)
        value = type_to_func[data_type](file)
        next_list.append(value)
        if check_next_char(file) == 'e':
            file.read(1)
            break

    return next_list


def get_next_string(file):
    data_size = read_number(file)
    delimiter = file.read(1)
    if delimiter != ':':
        raise (Exception("Unexpected delimiter: {}".format(delimiter)))
    next_string = file.read(data_size)
    return next_string


def get_next_int(file):
    int_specifier = file.read(1)
    number = read_number(file)
    end_specifier = file.read(1)
    return number


def get_next_dictionary(file):
    global info_dict_position
    global info_dict_size
    next_dict = dict()
    file.read(1)
    while True:
        key = get_next_string(file)
        #print "Key: {} at: {}".format(repr(key),file.tell())
        if key == 'info':
            info_dict_position = file.tell()
        data_type = get_next_datatype(file)
        value = type_to_func[data_type](file)
        if key == 'info':
            info_dict_size = file.tell() - info_dict_position
        #print "Key: {} ends at: {}".format(key,file.tell())
        #print "key: {} value: {}".format(key,value)
        next_dict[key] = value
        if check_next_char(file) == 'e':
            file.read(1)
            break

    return next_dict


def get_next_datatype(file):
    next_char = check_next_char(file)
    if next_char == '':
        data_type = None
    elif next_char.isdigit():
        data_type = STRING
    elif next_char == 'l':
        data_type = LIST
    elif next_char == 'i':
        data_type = INT
    elif next_char == 'd':
        data_type = DICTIONARY
    else:
        raise (Exception("Unknown data type: {}".format(repr(next_char))))

    #print "Found datatype: {}".format(data_type)

    return data_type

type_to_func = {STRING: get_next_string,
                LIST: get_next_list,
                INT: get_next_int,
                DICTIONARY: get_next_dictionary}


def get_next_element(file):
    while True:
        data_type = get_next_datatype(file)
        if data_type is None:
            break
        element = type_to_func[data_type](file)
        yield element


def read_torrent(file_path):
    document = []
    info_hash = None

    with open(file_path, 'rb') as input_file:
        document = [element for element in get_next_element(input_file)]
        if info_dict_size and info_dict_position:
            input_file.seek(info_dict_position)
            info = input_file.read(info_dict_size)
            hash_obj = hashlib.sha1(info)
            info_hash = hash_obj.hexdigest()

    return document, info_hash


def get_peers(bytes):
    peer_list = []
    while True:
        next_peer = bytes[:6]
        if not next_peer:
            break
        bytes = bytes[6:]
        ipa = struct.unpack("B",next_peer[0])[0]
        ipb = struct.unpack("B",next_peer[1])[0]
        ipc = struct.unpack("B",next_peer[2])[0]
        ipd = struct.unpack("B",next_peer[3])[0]
        ip = '{}.{}.{}.{}'.format(ipa,ipb,ipc,ipd)
        port_bytes = next_peer[4:]
        port = struct.unpack(">H",port_bytes)[0]
        #print 'found: {}:{}'.format(ip,port)
        peer_list.append((ip,port))
    return peer_list




#print read_torrent(r"C:\Users\Andrew\Downloads\_idea.torrent")

import StringIO
import socket


