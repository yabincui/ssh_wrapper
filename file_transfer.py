import collections
import os
from Queue import Queue

from utils import *


"""
file_transfer: used to send files between ssh client and server.


cmd formats between FileClient and FileServer:

[client] cmd: cd
[client] path: path

[client] cmd: get_possible_paths
[client] path: path
[server] possible_paths: a, b, c

[client] cmd: path_type
[client] path: path
[server] type: file or dir or not_exist

[client] cmd: exit

[client] cmd: send_file
[client] local: local_path
[client] remote: remote_path
[client] file_type: a, b, c  # valild types: executable
// Split to 4K per line
[client] data: data in hex format
[client] data: data in hex format
...
[client] data_end: data_size

[client] cmd: recv_file
[client] remote: remote_path
[client] local: local_path
[server] file_type: a, b, c # valid types: executable
// Split to 4K per line
[server] data: data in hex format
[server] data_end: data_size

[client] cmd: mkdir
[client] path: path

[client] cmd: rmdir
[client] path: path

[client] cmd: list_dir
[client] path: path
[server] dirs: a, b, c
[server] files: a, b, c
[server] links: a, b, c

[client] cmd: send_link
[client] local: local_path
[client] remote: remote_path
[client] link: link

[client] cmd: recv_link
[client] remote: remote_path
[client] local: local_path
[server] link: link

"""

class FileBase(object):
    def __init__(self, write_line_function, read_line_function, logger):
        self.write_line_function = write_line_function
        self.read_line_function = read_line_function
        self.logger = logger

    def read_item(self, expected_key):
        return self.read_items([expected_key])[1]

    def read_items(self, expected_keys):
        line = self.read_line_function()
        self.logger.log('read_items(%s) = %s' % (expected_keys, line))
        if not line:
            log_exit('unexpected end')
        for expected_key in expected_keys:
            if line.startswith(expected_key + ': '):
                return (expected_key, line[len(expected_key + ': '):])
        log_exit('expected_keys are %s, bug get %s' % (expected_keys, line))

    def write_item(self, key, value):
        self.logger.log('write_item(%s: %s)' % (key, value))
        self.write_line_function(key + ': ' + value)
    
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

    def error(self, msg):
        sys.stderr.write(msg + '\n')

class FileClient(FileBase):
    def set_remote_cwd(self, cwd):
        self.write_item('cmd', 'cd')
        self.write_item('path', cwd)

    def send(self, local, remote):
        local = expand_path(local)
        if os.path.isfile(local):
            local_type = 'file'
        elif os.path.isdir(local):
            local_type = 'dir'
        else:
            self.error('path %s not found' % local)
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
        elif local_type == 'dir':
            if remote_type == 'file':
                self.error("%s is a file, can't send dir to it" % remote)
            elif remote_type == 'dir':
                basename = os.path.basename(local[:-1] if local.endswith('/') else local)
                self.send_dir(local, os.path.join(remote, basename))
            elif remote_type == 'not_exist':
                self.send_dir(local, remote)

    def send_dir(self, local, remote):
        if not local.endswith('/'):
            local += '/'
        if not remote.endswith('/'):
            remote += '/'
        self.logger.log('send_dir(local %s, remote %s)' % (local, remote))
        self.rmdir(remote)
        self.mkdir(remote)
        for root, dirs, files in os.walk(local):
            for d in dirs:
                local_dir = os.path.join(root, d)
                remote_dir = remote + local_dir[len(local):]
                logger.log('local %s, remote %s, local_dir %s, remote_dir %s' %
                    (local, remote, local_dir, remote_dir))
                if os.path.islink(local_dir):
                    self.send_link(local_dir, remote_dir)
                else:
                    self.mkdir(remote_dir)
            for f in files:
                local_file = os.path.join(root, f)
                remote_file = remote + local_file[len(local):]
                logger.log('local %s, remote %s, local_file %s, remote_file %s' %
                    (local, remote, local_file, remote_file))
                if os.path.islink(local_file):
                    self.send_link(local_file, remote_file)
                else:
                    self.send_file(local_file, remote_file)


    def send_file(self, local, remote):
        self.write_item('cmd', 'send_file')
        self.write_item('local', local)
        self.write_item('remote', remote)
        file_type = get_file_type(local)
        self.write_item('file_type', ', '.join(file_type))
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

    def send_link(self, local, remote):
        if not os.path.islink(local):
            self.error("%s isn't a link" % local)
            return
        link = os.readlink(local)
        self.write_item('cmd', 'send_link')
        self.write_item('local', local)
        self.write_item('remote', remote)
        self.write_item('link', link)

    def recv(self, remote, local):
        local = expand_path(local)
        if os.path.isfile(local):
            local_type = 'file'
        elif os.path.isdir(local):
            local_type = 'dir'
        else:
            local_type = 'not_exist'
        self.write_item('cmd', 'path_type')
        self.write_item('path', remote)
        remote_type = self.read_item('type')
        if remote_type == 'file':
            if local_type == 'file' or local_type == 'not_exist':
                self.recv_file(remote, local)
            else:
                filename = os.path.basename(remote)
                self.recv_file(remote, os.path.join(local, filename))
        elif remote_type == 'dir':
            if local_type == 'file':
                self.error("%s is a file, can't recv dir to it" % local)
            elif local_type == 'dir':
                basename = os.path.basename(remote[:-1] if remote.endswith('/') else remote)
                self.recv_dir(remote, os.path.join(local, basename))
            elif local_type == 'not_exist':
                self.recv_dir(remote, local)

    def recv_dir(self, remote, local):
        if not local.endswith('/'):
            local += '/'
        if not remote.endswith('/'):
            remote += '/'
        self.logger.log('recv_dir(remote %s, local %s)' % (remote, local))
        mkdir(local)
        waiting_dirs = collections.deque()
        waiting_dirs.append(remote)
        while len(waiting_dirs) > 0:
            remote_path = waiting_dirs.popleft()
            self.write_item('cmd', 'list_dir')
            self.write_item('path', remote_path)
            dirs = split_string(self.read_item('dirs'))
            files = split_string(self.read_item('files'))
            links = split_string(self.read_item('links'))
            self.logger.log('dirs = %s, files = %s, links = %s' % (dirs, files, links))
            for d in dirs:
                remote_dir = os.path.join(remote_path, d)
                local_dir = local + remote_dir[len(remote):]
                mkdir(local_dir)
                waiting_dirs.append(remote_dir)
            for f in files:
                remote_file = os.path.join(remote_path, f)
                local_file = local + remote_file[len(remote):]
                self.recv_file(remote_file, local_file)
            for l in links:
                remote_link = os.path.join(remote_path, l)
                local_link = local + remote_link[len(remote):]
                self.recv_link(remote_link, local_link)

    def recv_file(self, remote, local):
        self.write_item('cmd', 'recv_file')
        self.write_item('remote', remote)
        self.write_item('local', local)
        dirpath = os.path.split(local)[0]
        if dirpath:
            run_cmd('mkdir -p %s' % dirpath)
        file_type = self.read_item('file_type')
        with open(local, 'wb') as f:
            size = 0
            while True:
                key, value = self.read_items(('data', 'data_end'))
                if key == 'data':
                    data = self.string_to_binary_data(value)
                    size += len(data)
                    f.write(data)
                elif key == 'data_end':
                    sent_size = int(value)
                    if size != sent_size:
                        self.error('recv_file %s to %s, sent_size %d, recv_size %d' %
                            (remote, local, sent_size, size))
                    break
        if 'executable' in file_type:
            run_cmd('chmod a+x %s' % local)

    def recv_link(self, remote, local):
        dirpath = os.path.split(local)[0]
        if dirpath:
            run_cmd('mkdir -p %s' % dirpath)
        self.write_item('cmd', 'recv_link')
        self.write_item('remote', remote)
        self.write_item('local', local)
        link = self.read_item('link')
        if link:
            run_cmd('ln -s %s %s' % (link, local))

    def get_possible_paths(self, path):
        self.write_item('cmd', 'get_possible_paths')
        self.write_item('path', path)
        return split_string(self.read_item('possible_paths'))

    def mkdir(self, path):
        self.write_item('cmd', 'mkdir')
        self.write_item('path', path)

    def rmdir(self, path):
        self.write_item('cmd', 'rmdir')
        self.write_item('path', path)

class FileTransferError(Exception):
    pass

class FileClientCmdInterface(object):
    def __init__(self, write_line_function, logger):
        self.logger = logger
        self.read_queue = Queue()
        def read_line_function():
            return self.read_queue.get()
        self.client = FileClient(write_line_function, read_line_function, logger)
        self.cmds = ['lls', 'lcp', 'lcd', 'lrm', 'lmkdir', 'local',
                     'rcp', 'send', 'recv', 'test', 'help']
        self.current_dir = ''

    def is_cmd_supported(self, cmdline):
        args = cmdline.split()
        return args and args[0] in self.cmds

    def error(self, msg):
        sys.stderr.write(msg + '\n')
        raise FileTransferError()

    def set_current_dir(self, new_current_dir):
        if self.current_dir != new_current_dir:
            self.current_dir = new_current_dir
            self.client.set_remote_cwd(self.current_dir)

    def add_input(self, data):
        self.read_queue.put(data)

    def run_cmd(self, cmdline):
        try:
            args = cmdline.split()
            if args[0] in ('lls', 'lrm', 'lmkdir'):
                args[0] = args[0][1:]
                self.run_local_cmd(args)
            elif args[0] == 'local':
                self.run_local_cmd(args[1:])
            elif args[0] == 'lcd':
                self.chdir(args)
            elif args[0] in ('lcp', 'send'):
                self.send_files(args)
            elif args[0] in ('rcp', 'recv'):
                self.recv_files(args)
            elif args[0] == 'test':
                self.run_test()
            elif args[0] == 'help':
                self.print_help()
            else:
                self.error('unexpected file transfer cmd: ' + args[0])
        except FileTransferError:
            return False
        return True

    def run_local_cmd(self, args):
        if subprocess.call(' '.join(args), shell=True) != 0:
            self.error('run %s failed' % (' '.join(args)))

    def chdir(self, args):
        if len(args) != 2:
            self.error('wrong chdir path')
        path = expand_path(args[1])
        if not os.path.isdir(path):
            self.error("path '%s' isn't a directory." % path)
        os.chdir(path)

    def send_files(self, args):
        if len(args) != 3:
            self.error('wrong options, need `%s local remote`.' % args[0])
        self.client.send(args[1], args[2])

    def recv_files(self, args):
        if len(args) != 3:
            self.error('wrong options, need `%s remote local`.' % args[0])
        self.client.recv(args[1], args[2])

    def run_test(self):
        run_file_transfer_tests(self.client)

    def print_help(self):
        sys.stdout.write(
"""
    lls   -- run `ls` in local machine.
    lcd   -- run `cd` in local machine.
    lrm   -- run `rm` in local machine.
    lmkdir -- run `mkdir` in local machine.
    local cmd args...  -- run `cmd args...` in local machine.
    rcp   -- alias to recv cmd.
    send local_path remote_path -- send local files to remote.
    recv remote_path local_path -- recv remote files to local.
    lcp   -- alias to send cmd.
    rcp   -- alias to recv cmd.
    run script_path -- run a script.
    test  -- run file transfer test.
""")


class FileServer(FileBase):
    def run(self):
        while True:
            cmd = self.read_item('cmd')
            if cmd == 'cd':
                self.handle_cd()
            elif cmd == 'get_possible_paths':
                self.handle_get_possible_paths()
            elif cmd == 'path_type':
                self.handle_path_type()
            elif cmd == 'exit':
                break
            elif cmd == 'send_file':
                self.handle_send_file()
            elif cmd == 'recv_file':
                self.handle_recv_file()
            elif cmd == 'mkdir':
                self.handle_mkdir()
            elif cmd == 'rmdir':
                self.handle_rmdir()
            elif cmd == 'send_link':
                self.handle_send_link()
            elif cmd == 'recv_link':
                self.handle_recv_link()
            elif cmd == 'list_dir':
                self.handle_list_dir()
            else:
                self.error('unknown cmd: %s' % cmd)

    def handle_cd(self):
        path = self.read_item('path')
        if os.path.isdir(path):
            os.chdir(path)
        else:
            self.error("Can't switch to %s" % path)

    def handle_get_possible_paths(self):
        path = self.read_item('path')
        possible_paths = get_possible_local_paths(path)
        self.write_item('possible_paths', ', '.join(possible_paths))

    def handle_path_type(self):
        path = self.read_item('path')
        path = expand_path(path)
        if os.path.isfile(path):
            path_type = 'file'
        elif os.path.isdir(path):
            path_type = 'dir'
        else:
            path_type = 'not_exist'
        self.write_item('type', path_type)

    def handle_send_file(self):
        local = self.read_item('local')
        remote = self.read_item('remote')
        dirpath = os.path.split(remote)[0]
        if dirpath:
            mkdir(dirpath)
        file_type = self.read_item('file_type')
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
        if 'executable' in file_type:
            run_cmd('chmod a+x %s' % remote)

    def handle_recv_file(self):
        remote = self.read_item('remote')
        local = self.read_item('local')
        file_type = get_file_type(remote)
        self.write_item('file_type', ', '.join(file_type))
        with open(remote, 'rb') as f:
            size = 0
            while True:
                data = f.read(4096)
                if not data:
                    break
                size += len(data)
                s = self.binary_data_to_string(data)
                self.write_item('data', s)
            self.write_item('data_end', '%d' % size)

    def handle_mkdir(self):
        path = self.read_item('path')
        path = expand_path(path)
        mkdir(path)

    def handle_rmdir(self):
        path = self.read_item('path')
        if path in ('~', '/'):
            return
        path = expand_path(path)
        remove(path)

    def handle_send_link(self):
        local = self.read_item('local')
        remote = self.read_item('remote')
        link = self.read_item('link')
        dirpath = os.path.split(remote)[0]
        if dirpath:
            mkdir(dirpath)
        run_cmd('ln -s %s %s' % (link, remote))

    def handle_recv_link(self):
        remote = self.read_item('remote')
        local = self.read_item('local')
        if os.path.islink(remote):
            self.write_item('link', os.readlink(remote))
        else:
            self.error("Remote %s is not a link" % remote)
            self.write_item('link', '')

    def handle_list_dir(self):
        path = self.read_item('path')
        path = expand_path(path)
        dirs = []
        files = []
        links = []
        for item in os.listdir(path):
            sub_path = os.path.join(path, item)
            if os.path.islink(sub_path):
                links.append(item)
            elif os.path.isdir(sub_path):
                dirs.append(item)
            elif os.path.isfile(sub_path):
                files.append(item)
        self.write_item('dirs', ', '.join(dirs))
        self.write_item('files', ', '.join(files))
        self.write_item('links', ', '.join(links))


class FileTransferTests(object):
    def __init__(self, file_client):
        self.file_client = file_client
        test_data = []
        for i in range(65536):
            test_data.append(chr(i / 256))
            test_data.append(chr(i % 256))
        self.test_data = ''.join(test_data)
        self.test_dir = 'file_transfer_test_dir'
        self.remote_test_dir = 'file_transfer_remote_test_dir'

    def write_test_file(self, path):
        with open(path, 'wb') as f:
            f.write(self.test_data)

    def check_file(self, path, expected_path):
        def get_file_data(path):
            with open(path, 'rb') as f:
                return f.read()
        file_type = get_file_type(path)
        expected_file_type = get_file_type(expected_path)
        if get_file_data(path) != get_file_data(expected_path) or file_type != expected_file_type:
            self.file_client.error('check_file(%s, %s) failed' % (path, expected_path))

    def check_link(self, path, expected_path):
        if not os.path.islink(path) or os.readlink(path) != os.readlink(expected_path):
            self.file_client.error('check_link(%s, %s) failed' % (path, expected_path))

    def check_dir(self, path, expected_path):
        waiting_dirs = collections.deque()
        waiting_dirs.append((path, expected_path))
        ok = True
        while waiting_dirs:
            path, expected = waiting_dirs.popleft()
            items = sorted(os.listdir(path))
            expected_items = sorted(os.listdir(expected))
            if items != expected_items:
                ok = False
                break
            for item in items:
                sub_path = os.path.join(path, item)
                sub_expected = os.path.join(expected, item)
                if os.path.islink(sub_expected):
                    if not os.path.islink(sub_path):
                        ok = False
                        break
                    self.check_link(sub_path, sub_expected)
                elif os.path.isdir(sub_expected):
                    if not os.path.isdir(sub_path):
                        ok = False
                        break
                    waiting_dirs.append((sub_path, sub_expected))
                elif os.path.isfile(sub_expected):
                    if not os.path.isfile(sub_path):
                        ok = False
                        break
                    self.check_file(sub_path, sub_expected)
        if not ok:
            self.file_client.error('check_dir(%s, %s) failed' % (path, expected_path))
        

    def setup_test(self):
        remove(self.test_dir)
        mkdir(self.test_dir)
        self.file_client.rmdir(self.remote_test_dir)
        self.file_client.mkdir(self.remote_test_dir)

    def teardown_test(self):
        remove(self.test_dir)
        self.file_client.rmdir(self.remote_test_dir)

    def test_send_recv_file(self):
        self.setup_test()
        test_file = os.path.join(self.test_dir, 'file_transfer_test')
        self.write_test_file(test_file)
        remote_test_file = os.path.join(self.remote_test_dir, 'file_transfer_test')
        self.file_client.send(test_file, remote_test_file)
        recv_file = os.path.join(self.test_dir, 'file_transfer_recv_file')
        self.file_client.recv(remote_test_file, recv_file)
        self.check_file(recv_file, test_file)
        self.teardown_test()

    def test_send_recv_file_with_mkdir(self):
        self.setup_test()
        test_file = os.path.join(self.test_dir, 'file_transfer_test')
        self.write_test_file(test_file)
        remote_test_file = os.path.join(self.remote_test_dir, 'dir1', 'file_transfer_test')
        self.file_client.send(test_file, remote_test_file)
        recv_file = os.path.join(self.test_dir, 'dir1', 'file_transfer_recv_file')
        self.file_client.recv(remote_test_file, recv_file)
        self.check_file(recv_file, test_file)
        self.teardown_test()

    def test_send_recv_exec_file(self):
        self.setup_test()
        test_file = os.path.join(get_script_dir(), 'testdata', 'exe_file')
        remote_test_file = os.path.join(self.remote_test_dir, 'dir1', 'file_transfer_test')
        self.file_client.send(test_file, remote_test_file)
        recv_file = os.path.join(self.test_dir, 'dir1', 'file_transfer_recv_file')
        self.file_client.recv(remote_test_file, recv_file)
        self.check_file(recv_file, test_file)
        self.teardown_test()

    def test_send_recv_link_file(self):
        self.setup_test()
        test_file = os.path.join(get_script_dir(), 'testdata', 'lnk_file')
        remote_test_file = os.path.join(self.remote_test_dir, 'dir1', 'file_transfer_test')
        self.file_client.send_link(test_file, remote_test_file)
        recv_file = os.path.join(self.test_dir, 'dir1', 'file_transfer_recv_file')
        self.file_client.recv_link(remote_test_file, recv_file)
        self.check_link(recv_file, test_file)
        self.teardown_test()

    def test_send_recv_dirs(self):
        self.setup_test()
        send_dir = os.path.join(get_script_dir(), 'testdata')
        self.file_client.send(send_dir, self.remote_test_dir)
        self.file_client.recv(os.path.join(self.remote_test_dir, 'testdata'), self.test_dir)
        recv_dir = os.path.join(self.test_dir, 'testdata')        
        self.check_dir(recv_dir, send_dir)
        self.teardown_test()

def run_file_transfer_tests(file_client):
    test = FileTransferTests(file_client)
    test.test_send_recv_file()
    test.test_send_recv_file_with_mkdir()
    test.test_send_recv_exec_file()
    test.test_send_recv_link_file()
    test.test_send_recv_dirs()
    sys.stdout.write('test done!\n')


def run_file_server():
    sys.stdout.write('file_server_ready\n')
    def write_line_function(data):
        sys.stdout.write(data + '\n')
    def read_line_function():
        line = sys.stdin.readline()
        if line and line[-1] == '\n':
            return line[:-1]
    logger = Logger('.ssh_wrapper.log')
    server = FileServer(write_line_function, read_line_function, logger)
    server.run()

if __name__ == '__main__':
    run_file_server()