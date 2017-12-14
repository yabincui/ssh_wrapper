
import os
from utils import *


"""
file_transfer: used to send files between ssh client and server.


cmd formats between FileClient and FileServer:

[client] cmd: path_type
[client] path: path
[server] type: file or dir or not_exist

[client] cmd: exit

[client] cmd: send_file
[client] local: local_path
[client] remote: remote_path
// Split to 4K per line
[client] data: data in hex format
[client] data: data in hex format
...
[client] data_end: data_size

"""

class FileBase(object):
    def __init__(self, write_line_function, read_line_function):
        self.write_line_function = write_line_function
        self.read_line_function = read_line_function

    def read_item(self, expected_key):
        return self.read_items([expected_key])[1]

    def read_items(self, expected_keys):
        line = self.read_line_function()
        if not line:
            log_exit('unexpected end')
        for expected_key in expected_keys:
            if line.startswith(expected_key + ': '):
                return (expected_key, line[len(expected_key + ': '):])
        log_exit('expected_keys are %s, bug get %s' % (expected_keys, line))

    def write_item(self, key, value):
        self.write_line_function(key + ': ' + value)
    
    def expand_path(self, path):
        return os.path.expanduser(os.path.expandvars(path))

    def binary_data_to_string(self, data):
        s = []
        for c in data:
            s.append('%02x' % ord(c))
        return ''.join(s)

    def string_to_binary_data(self, s):
        data = []
        for i in range(0, len(s), 2):
            data.append(chr(int(s[i:i+2], 16)))
        return ''.join(data)

class FileClient(FileBase):
    def send(self, local, remote):
        local = self.expand_path(local)
        if os.path.isfile(local):
            local_type = 'file'
        elif os.path.isdir(local):
            local_type = 'dir'
        else:
            sys.stderr.write('path %s not found\n' % local)
            return
        self.write_item('cmd', 'path_type')
        self.write_item('path', remote)
        remote_type = self.read_item('type')
        if local_type == 'file':
            if remote_type == 'file' or remote_type == 'not_exist':
                self.send_file(local, remote)
            else:
                filename = os.path.basename(local)
                self.send_file(local, os.path.join(remote, filename))

    def send_file(self, local, remote):
        self.write_item('cmd', 'send_file')
        self.write_item('local', local)
        self.write_item('remote', remote)
        with open(local, 'rb') as f:
            size = 0
            while True:
                data = f.read(4096)
                if not data:
                    break
                size += len(data)
                s = self.binary_data_to_string(data)
                self.write_item('data', s)
            self.write_item('data_end', '%d' % size)
    
    def recv(self, remote, local):
        pass


class FileServer(FileBase):
    def run(self):
        while True:
            cmd = self.read_item('cmd')
            if cmd == 'path_type':
                path = self.read_item('path')
                path = self.expand_path(path)
                if os.path.isfile(path):
                    path_type = 'file'
                elif os.path.isdir(path):
                    path_type = 'dir'
                else:
                    path_type = 'not_exist'
                self.write_item('type', path_type)
            elif cmd == 'exit':
                break
            elif cmd == 'send_file':
                self.handle_send_file()
    
    def handle_send_file(self):
        local = self.read_item('local')
        remote = self.read_item('remote')
        with open(remote, 'wb') as f:
            size = 0
            while True:
                key, value = self.read_items(['data', 'data_end'])
                if key == 'data':
                    data = self.string_to_binary_data(value)
                    size += len(data)
                    f.write(data)
                elif key == 'data_end':
                    sent_size = int(value)
                    if size != sent_size:
                        sys.stderr.write('send_file %s to %s, sent_size %d, recv_size %d' % (
                            local, remote, sent_size, size))
                    break



def run_file_server():
    sys.stdout.write('file_server_ready\n')
    def write_line_function(data):
        sys.stdout.write(data + '\n')
    def read_line_function():
        line = sys.stdin.readline()
        if line and line[-1] == '\n':
            return line[:-1]
    server = FileServer(write_line_function, read_line_function)
    server.run()

if __name__ == '__main__':
    run_file_server()