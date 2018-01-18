"""
Normal ssh connection with additional file transfer commands.

It supports both terminal and non terminal mode.
It supports terminal commands like vi, info, man.
It uses only one ssh connection.
"""

from __future__ import print_function
import argparse
import os
import pty
from Queue import Queue
import re
import select
import signal
import subprocess
import termios
import threading
import time
import tty

from file_transfer import FileClientCmdInterface, FileServer
from utils import *

help_msg = """
Normal ssh connection with additional file transfer commands.

It suppoprts both terminal and non terminal mode.
It supports terminal commands like vi, info, man.
It uses only one ssh connection.
"""

class MsgHelper(object):
    """
    We send msg between SSHClient and SSHServer:
    struct msg {
        // SSHClient to SSHServer:
        // T - terminal data, please pass directly to shell.
        // F - for file transfer cmd.
        // E - client has closed connection.
        // W - set window size.
        // S - sync dir between shell and SSHServer.
        // SSHServer to SSHClient:
        // T - terminal data, please pass directly to the client terminal.
        // F - for file transfer cmd.
        // E - server has closed connection.
        // S - reply new dir of SSHServer.
        char type;
        uint32_t size;  // size of msg data
        char data[size];
    };
    """
    def __init__(self, read_fh, write_fh, logger):
        self.read_fh = read_fh
        self.write_fh = write_fh
        self.logger = logger

    def write_terminal_msg(self, data):
        self.write_msg('T', data)

    def write_exit_msg(self):
        self.write_msg('E', '')

    def write_window_msg(self, data):
        self.write_msg('W', data)

    def write_file_msg(self, data):
        self.write_msg('F', data)

    def write_sync_dir_msg(self, data):
        self.write_msg('S', data)

    def write_msg(self, type, data):
        msg = type + ('%04x' % len(data)) + data
        self.logger.log('write_msg(%s, %s)' % (msg, to_hex_str(data)))
        self.write_fh.write(msg)
        self.write_fh.flush()

    def read_msg(self):
        def read_fully(size):
            data = ''
            while len(data) < size:
                data += self.read_fh.read(size - len(data))
            return data
        msg_type = read_fully(1)
        size = int(read_fully(4), 16)
        msg_data = read_fully(size)
        self.logger.log('read_msg(%c, %s, %s)' % (msg_type, msg_data, to_hex_str(msg_data)))
        return msg_type, msg_data


class SSHServer(object):
    """ Start a server, run terminal and file transfer cmds.
    """
    def __init__(self, enable_log):
        sys.stdout.write('\nssh server started\n')
        sys.stdout.flush()
        self.logger = Logger('~/ssh2.log', enable_log)
        self.msg_helper = MsgHelper(sys.stdin, sys.stdout, self.logger)
        self.child_pid, self.pty_fd = self.create_child_shell()
        self.shell_pid = None
        self.poll_thread = threading.Thread(target=self._run_poll_thread)
        self.poll_thread.start()
        self.start_file_server()

    def start_file_server(self):
        self.file_data_q = Queue()
        def write_line_function(data):
            self.msg_helper.write_file_msg(data)
        def read_line_function():
            return self.file_data_q.get()

        def file_server_thread_func():
            server = FileServer(write_line_function, read_line_function, self.logger)
            server.run()
        self.file_server_thread = threading.Thread(target=file_server_thread_func)
        self.file_server_thread.start()

    def create_child_shell(self):
        pid, fd = pty.fork()
        if pid == 0:
            # child process
            subprocess.call(['/bin/bash'], shell=False)
            os._exit(0)
        return pid, fd

    def _run_poll_thread(self):
        # poll thread
        try:
            make_file_nonblocking(self.pty_fd)
            while True:
                rlist, _, xlist = select.select([self.pty_fd], [], [self.pty_fd])
                if self.pty_fd in rlist or self.pty_fd in xlist:
                    try:
                        data = os.read(self.pty_fd, 1024)
                    except OSError:
                        data = ''
                    if not data:
                        self.msg_helper.write_exit_msg()
                        break
                    self.msg_helper.write_terminal_msg(data)
        finally:
            pass

    def run(self):
        try:
            while True:
                msg_type, msg_data = self.msg_helper.read_msg()
                if msg_type == 'E':
                    os.kill(self.child_pid, signal.SIGTERM)
                    break
                elif msg_type == 'T':
                    os.write(self.pty_fd, msg_data)
                elif msg_type == 'W':
                    w, h = [int(x) for x in msg_data.split('_')]
                    self.logger.log('set_window_size(%d, %d)' % (w, h))
                    set_terminal_size(self.pty_fd, w, h)
                elif msg_type == 'F':
                    self.file_data_q.put(msg_data)
                elif msg_type == 'S':
                    self.sync_dir_with_shell()
                else:
                    sys.stderr.write('unsupported msg_type %s' % msg_type)
        except Exception as e:
            self.logger.log('exception %s' % e)
            raise

    def sync_dir_with_shell(self):
        cur_dir = os.getcwd()
        if self.shell_pid is None:
            self.shell_pid = self.find_shell_pid()
        shell_dir = os.readlink('/proc/%d/cwd' % self.shell_pid)
        if cur_dir != shell_dir:
            os.chdir(shell_dir)
        self.msg_helper.write_sync_dir_msg(('readlink /proc/%d/cwd, ' % self.shell_pid) + shell_dir)

    def find_shell_pid(self):
        output = subprocess.check_output('ps -eo ppid,pid | grep %d' % self.child_pid, shell=True)
        for line in output.split('\n'):
            items = line.strip().split()
            if len(items) == 2 and items[0] == str(self.child_pid):
                return int(items[1])
        return None


def run_ssh_server(args):
    ssh_server = SSHServer(args.log)
    ssh_server.run()


class TerminalController(object):
    """ Control the terminal: cursor, color, etc. """

    def __init__(self, logger):
        self.logger = logger

    def receive_output(self, data):
        data = data.replace('\n', '\r\n')
        sys.stdout.write(data)
        sys.stdout.flush()
        self.logger.log('receive_output[%s]' % data)
        self.logger.log('receive_output_hex[%s]' % to_hex_str(data))

    def erase_last_characters(self, count=1):
        self.logger.log('erase %d characters' % count)
        sys.stdout.write('\033[%dD\033[0K' % count)
        sys.stdout.flush()

class NoInputException(Exception):
    pass

class InputController(object):
    """ Read input in a separate thread.
    """
    def __init__(self, terminal, logger):
        self.terminal = terminal
        self.logger = logger
        self.old_stdin_setting = set_stdin_raw()
        self.input_queue = Queue()
        self.eof_lock = threading.Lock()
        self.eof_flag = False
        self.poll_thread = threading.Thread(target=self._run_poll_thread)
        self.poll_thread.start()
    
    def _run_poll_thread(self):
        while True:
            data = sys.stdin.read(1)
            if not data:
                with self.eof_lock:
                    self.eof_flag = True
                self.input_queue.put('EOF')
                break
            else:
                self.input_queue.put(data)

    def read_cmdline(self, init_data):
        data = init_data
        cmdline = ''
        want_return = False
        while True:
            i = 0
            while i < len(data):
                c = data[i]
                if ord(c) == 0x7f:  # DEL
                    if cmdline:
                        cmdline = cmdline[:-1]
                        self.terminal.erase_last_characters()
                    i += 1
                    continue
                elif ord(c) == 0x1b:  # ESC
                    want_return = True
                elif ord(c) in [0x3, 0x9, 0x12, 0x0a, 0x0d]:  # ctrl-c, tab, ctrl-r, \n, \r
                    want_return = True
                if want_return:
                    if cmdline:
                        self.terminal.erase_last_characters(len(cmdline))
                    cmdline += data[i:]
                    return cmdline
                cmdline += c
                sys.stdout.write(c)
                sys.stdout.flush()
                i += 1
            data = self.read_data()

    def read_data(self):
        data = self.input_queue.get()
        with self.eof_lock:
            if self.eof_flag:
                raise NoInputException()
        self.logger.log('read_data(%s)' % to_hex_str(data))
        return data

    def restore_stdin(self):
        restore_stdin(self.old_stdin_setting)

class CmdEndMarker(object):
    """ Find cmd prompt from output flow. """

    def __init__(self, terminal, logger):
        self.terminal = terminal
        self.logger = logger
        self.lock = threading.Lock()
        # All below are protected by self.lock.
        self.last_line = ''
        self.prompt_pattern = re.compile(r'[\$\#][ ]+%s?$' % '\r')
        self.has_prompt = False

    def receive_output(self, data):
        with self.lock:
            total_data = self.last_line + data
            if self.prompt_pattern.search(total_data):
                self.has_prompt = True
                self.last_line = ''
            else:
                self.last_line = total_data[total_data.rfind('\n')+1:]
        self.terminal.receive_output(data)

    def check_cmd_prompt(self):
        with self.lock:
            if self.has_prompt:
                self.has_prompt = False
                return True
            return False


class SSHClient(object):
    """ Send terminal and file transfer msgs to remote server. """

    def __init__(self, host_name, update_server, enable_log):
        self.logger = Logger('~/ssh2.log', enable_log)
        self.terminal_obj = TerminalController(self.logger)
        self.input_obj = InputController(self.terminal_obj, self.logger)
        self.cmd_end_marker = CmdEndMarker(self.terminal_obj, self.logger)
        self.popen_obj = subprocess.Popen(['ssh', '-T', host_name],
                                          stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE)
        if update_server:
            cmd = ('rm -rf .ssh_wrapper && mkdir .ssh_wrapper && ' +
                   'git clone https://github.com/yabincui/ssh_wrapper .ssh_wrapper && ')
        else:
            cmd = ''
        self.popen_obj.stdin.write('%spython -u .ssh_wrapper/ssh2.py --server %s\n' % (cmd, '--log' if enable_log else ''))
        self.popen_obj.stdin.flush()
        while True:
            line = self.popen_obj.stdout.readline()
            if line.strip() == 'ssh server started':
                break
        self.msg_helper = MsgHelper(self.popen_obj.stdout, self.popen_obj.stdin, self.logger)
        self.poll_thread = threading.Thread(target=self._run_poll_thread)
        self.poll_thread.start()
        self.file_transfer_cmd_handler = self.create_file_transfer_cmd_handler()

    def create_file_transfer_cmd_handler(self):
        def write_line_function(data):
            self.msg_helper.write_file_msg(data)
        return FileClientCmdInterface(write_line_function, self.logger)

    def _run_poll_thread(self):
        # poll thread
        try:
            while True:
                msg_type, msg_data = self.msg_helper.read_msg()
                self.logger.log('read_msg(%c, %s)' % (msg_type, msg_data))
                if msg_type == 'E':
                    break
                elif msg_type == 'T':
                    self.cmd_end_marker.receive_output(msg_data)
                elif msg_type == 'F':
                    self.file_transfer_cmd_handler.add_input(msg_data)
                elif msg_type == 'S':
                    pass
                else:
                    self.logger.log('unsupported msg_type %s' % msg_type)
                    break
        finally:
            self.logger.log('poll finished')
            self.msg_helper.write_exit_msg()
            self.input_obj.restore_stdin()
        os._exit(0)

    def run(self):
        self.logger.log('run')
        try:
            self.handle_window_size_change()
            while not self.cmd_end_marker.check_cmd_prompt():
                time.sleep(0.1)
            init_data = self.set_terminal_env()
            while True:
                cmdline = self.input_obj.read_cmdline(init_data)
                self.logger.log('read_cmdline(%s,%s)' % (cmdline, to_hex_str(cmdline)))
                if cmdline.endswith('\t'):
                    init_data = self.run_complete_cmdline(cmdline)
                else:
                    init_data = self.run_cmdline(cmdline)

        except NoInputException:
            pass
        self.msg_helper.write_exit_msg()
        self.logger.log('run finished')
        self.input_obj.restore_stdin()
        os._exit(0)

    def run_complete_cmdline(self, cmdline):
        self.msg_helper.write_terminal_msg(cmdline)
        return self.wait_cmd_finish()

    def set_terminal_env(self):
        if 'TERM' in os.environ:
            return self.run_cmdline('export TERM=%s\n' % os.environ['TERM'])
        return ''

    def handle_window_size_change(self):
        def update_window_size():
            w, h = get_terminal_size(0)
            self.msg_helper.write_window_msg('%d_%d' % (w, h))
            
        def handler(signum, frames):
            update_window_size()
        signal.signal(signal.SIGWINCH, handler)
        update_window_size()

    def run_cmdline(self, cmdline):
        if cmdline and cmdline[-1] in ['\x03', '\x12', '\x1b']:  # ctrl-c, ctrl-r, esc
            return self.run_terminal_cmdline(cmdline)
        if self.file_transfer_cmd_handler.is_cmd_supported(cmdline):
            return self.run_file_transfer_cmd(cmdline)
        return self.run_terminal_cmdline(cmdline)

    def run_file_transfer_cmd(self, cmdline):
        sys.stdout.write(cmdline.rstrip() + '\r\n')
        sys.stdout.flush()
        self.msg_helper.write_sync_dir_msg('')
        self.file_transfer_cmd_handler.run_cmd(cmdline)
        return self.run_terminal_cmdline('\n')

    def run_terminal_cmdline(self, cmdline):
        self.msg_helper.write_terminal_msg(cmdline)
        return  self.wait_cmd_finish()

    def wait_cmd_finish(self):
        while True:
            data = self.input_obj.read_data()
            if self.cmd_end_marker.check_cmd_prompt():
                return data
            self.msg_helper.write_terminal_msg(data)


def run_ssh_client(args):
    config = {}
    load_config('~/.sshwrapper.config', config)
    if args.host_name:
        config['host_name'] = args.host_name
    if 'host_name' not in config:
        log_exit('please set host_name in argument or ~/.sshwrapper.config.')
    ssh_client = SSHClient(config['host_name'], args.update_server, args.log)
    ssh_client.run()

def main():
    parser = argparse.ArgumentParser(help_msg)
    parser.add_argument('--host-name', help="""
        Set remote machine host name. It can be configured in ~/.sshwrapper.config:"
            host_name=xxx@xxx
    """)
    parser.add_argument('--server', action='store_true', help="Run SSHServer in the server.")
    parser.add_argument('--update-server', action='store_true', help="Update SSHWrapper in the server.")
    parser.add_argument('--log', action='store_true', help="enable log")
    args = parser.parse_args()
    if args.server:
        run_ssh_server(args)
    else:
        run_ssh_client(args)

if __name__ == '__main__':
    main()
