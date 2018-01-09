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
        // SSHServer to SSHClient:
        // T - terminal data, please pass directly to the client terminal.
        // F - for file transfer cmd.
        // E - server has closed connection.
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
    def __init__(self):
        sys.stdout.write('\nssh server started\n')
        sys.stdout.flush()
        self.logger = Logger('~/ssh2.log')
        self.msg_helper = MsgHelper(sys.stdin, sys.stdout, self.logger)
        self.create_child_shell()
        self.child_pid, self.pty_fd = self.create_child_shell()
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
                else:
                    sys.stderr.write('unsupported msg_type %s' % msg_type)
        except Exception as e:
            self.logger.log('exception %s' % e)
            raise

def run_ssh_server():
    ssh_server = SSHServer()
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
        sys.stdout.write('\033[%dD\033[0K' % count)
        sys.stdout.flush()

class CmdHistory(object):
    def __init__(self, logger):
        self.logger = logger
        self.history = []
        self.pos = 0

    def get_prev_cmd(self):
        if self.pos > 0:
            self.pos -= 1
            self.logger.log('history pos = %d' % self.pos)
            return self.history[self.pos]
        return ''

    def get_next_cmd(self):
        if self.pos < len(self.history):
            self.pos += 1
            self.logger.log('history pos = %d' % self.pos)
            return self.history[self.pos - 1]
        return ''

    def add_cmd(self, cmdline):
        cmdline = cmdline.strip('\r\n')
        if not cmdline:
            return
        self.logger.log('history[%d] = %s' % (len(self.history), cmdline))
        self.history.append(cmdline)
        self.pos = len(self.history)

class NoInputException(Exception):
    pass

class InputController(object):
    """ Read input in a separate thread.
    """
    def __init__(self, terminal, logger):
        self.terminal = terminal
        self.logger = logger
        self.cmd_history = CmdHistory(self.logger)
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
        in_esc_mode = False
        esc_data = ''
        self.cmdline = ''
        while True:
            for c in data:
                if in_esc_mode:
                    esc_data += c
                    if self.handle_esc_data(esc_data):
                        in_esc_mode = False
                        esc_data = ''
                elif ord(c) == 0x7f:  # DEL
                    if self.cmdline:
                        self.cmdline = self.cmdline[:-1]
                        self.terminal.erase_last_characters()
                elif ord(c) == 0x1b: # ESC
                    in_esc_mode = True
                else:
                    self.cmdline += c
                    sys.stdout.write(c)
                    sys.stdout.flush()
            if self.cmdline.endswith('\n') or self.cmdline.endswith('\r'):
                break
            data = self.read_data()
            self.logger.log('read_cmd, read_data(%s)(%s)' % (data, to_hex_str(data)))
        self.logger.log('read_cmdline(%s)' % self.cmdline)
        if self.cmdline.endswith('\r'):
            #cmdline += '\n'
            sys.stdout.write('\n')
        self.cmd_history.add_cmd(self.cmdline)
        return self.cmdline

    def handle_esc_data(self, esc_data):
        if esc_data[0] == '[':
            if len(esc_data) == 1:
                return False
            if esc_data[1] == 'A':
                # Esc[A  Move cursor up 1 line  -- use prev cmd in history
                cmdline = self.cmd_history.get_prev_cmd()
                self.reset_cmdline(cmdline)
                return True
            elif esc_data[1] == 'B':
                # Esc[B Move cursor down 1 line  -- use next cmd in history
                cmdline = self.cmd_history.get_next_cmd()
                self.reset_cmdline(cmdline)
                return True
            #elif esc_data.endswith('R'):
            #    # Esc[{Row};{Column}R  -- report current cursor position.
            #    m = re.match(r'[\d+;\d+R', esc_data)
            #    if m:
                    
        self.logger.log('unexpected esc_data %s(%s)' % (esc_data, to_hex_str(esc_data)))
        return False

    def reset_cmdline(self, cmdline):
        if self.cmdline:
            self.terminal.erase_last_characters(len(self.cmdline))
        self.cmdline = cmdline
        self.logger.log('reset_cmdline %s' % self.cmdline)
        sys.stdout.write(self.cmdline)
        sys.stdout.flush()

    def read_data(self):
        data = self.input_queue.get()
        with self.eof_lock:
            if self.eof_flag:
                raise NoInputException()
        return data

    def restore_stdin(self):
        restore_stdin(self.old_stdin_setting)

class CmdEndMarker(object):
    """ Mark the end of a command. Decide what to show in the terminal. """

    CMD_END_MARK = 'cmd has finished with code '

    def __init__(self, terminal, logger):
        self.terminal = terminal
        self.logger = logger
        self.lock = threading.Lock()
        # All below are protected by self.lock.
        self.need_omit_cmdline_echo = False
        self.want_cmd_end_mark = False
        self.has_cmd_end_mark = False
        self.last_line = ''
        self.mark_pattern = re.compile(r'%s(\d+)(.+)\.%s' % (self.CMD_END_MARK, '\r\n'))
        self.wait_init_prompt_flag = True
        self.init_prompt_q = Queue()
        self.current_dir = ''

    def wait_init_prompt(self):
        self.init_prompt_q.get()

    def mark_new_cmdline(self, cmdline):
        with self.lock:
            self.need_omit_cmdline_echo = True
            self.want_cmd_end_mark = True
            self.has_cmd_end_mark = False
            self.last_line = ''
        cmdline = cmdline.rstrip()
        if cmdline:
            cmdline += ' ; '
        return cmdline + ('echo %s$?$PWD.\n' % self.CMD_END_MARK)

    def receive_output(self, data):
        with self.lock:
            if self.wait_init_prompt_flag:
                total_data = self.last_line + data
                if data.endswith('$ ') or data.endswith('# '):
                    self.wait_init_prompt_flag = False
                    self.init_prompt_q.put('a')
                else:
                    self.last_line = total_data[total_data.rfind('\n')+1:]
                return
            if self.need_omit_cmdline_echo:
                pos = data.find('\n')
                if pos == -1:
                    return
                data = data[pos + 1:]
                self.need_omit_cmdline_echo = False
            self.logger.log('want_cmd_end_mark = %d, has_end_mark = %d' % (self.want_cmd_end_mark, self.has_cmd_end_mark))
            if self.want_cmd_end_mark and not self.has_cmd_end_mark:
                total_data = self.last_line + data
                m = self.mark_pattern.search(total_data)
                self.logger.log('m = %s' % m)
                if m:
                    self.has_cmd_end_mark = True
                    if m.start() < len(self.last_line):
                        self.terminal.erase_last_characters(len(self.last_line) - m.start())
                    data = total_data[len(self.last_line):m.start()]
                    if int(m.group(1)) != 0:
                        data += self.CMD_END_MARK + m.group(1) + '.\r\n'
                    data += total_data[m.end():]
                    self.current_dir = m.group(2)
                else:
                    self.last_line = total_data[total_data.rfind('\n')+1:]
                    if len(self.last_line) > 300:
                        self.last_line = self.last_line[-300:]
        self.terminal.receive_output(data)

    def is_cmd_finished(self):
        with self.lock:
            if self.want_cmd_end_mark and self.has_cmd_end_mark:
                self.want_cmd_end_mark = False
                self.has_cmd_end_mark = False
                return True
        return False

    def get_current_dir(self):
        with self.lock:
            return self.current_dir


class SSHClient(object):
    """ Send terminal and file transfer msgs to remote server. """

    def __init__(self, host_name, update_server):
        self.logger = Logger('../ssh2.log')
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
        self.popen_obj.stdin.write('%spython -u .ssh_wrapper/ssh2.py --server\n' % cmd)
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
            self.cmd_end_marker.wait_init_prompt()
            init_data = self.set_terminal_env()
            while True:
                cmdline = self.input_obj.read_cmdline(init_data)
                init_data = self.run_cmdline(cmdline)

        except NoInputException:
            pass
        self.msg_helper.write_exit_msg()
        self.logger.log('run finished')
        self.input_obj.restore_stdin()
        os._exit(0)

    def set_terminal_env(self):
        if 'TERM' in os.environ:
            return self.run_cmdline('export TERM=%s' % os.environ['TERM'])
        return ''

    def handle_window_size_change(self):
        def update_window_size():
            w, h = get_terminal_size(sys.stdin.fileno())
            self.msg_helper.write_window_msg('%d_%d' % (w, h))
            
        def handler(signum, frames):
            update_window_size()
        signal.signal(signal.SIGWINCH, handler)
        update_window_size()

    def run_cmdline(self, cmdline):
        if self.file_transfer_cmd_handler.is_cmd_supported(cmdline):
            self.file_transfer_cmd_handler.run_cmd(cmdline)
            return self.run_terminal_cmdline('')
        else:
            return self.run_terminal_cmdline(cmdline)

    def run_terminal_cmdline(self, cmdline):
        cmdline = self.cmd_end_marker.mark_new_cmdline(cmdline)
        self.msg_helper.write_terminal_msg(cmdline)
        while True:
            data = self.input_obj.read_data()
            if self.cmd_end_marker.is_cmd_finished():
                self.file_transfer_cmd_handler.set_current_dir(self.cmd_end_marker.get_current_dir())
                return data
            self.msg_helper.write_terminal_msg(data)


def run_ssh_client(args):
    config = {}
    load_config('~/.sshwrapper.config', config)
    if args.host_name:
        config['host_name'] = args.host_name
    if 'host_name' not in config:
        log_exit('please set host_name in argument or ~/.sshwrapper.config.')
    ssh_client = SSHClient(config['host_name'], args.update_server)
    ssh_client.run()

def main():
    parser = argparse.ArgumentParser(help_msg)
    parser.add_argument('--host-name', help="""
        Set remote machine host name. It can be configured in ~/.sshwrapper.config:"
            host_name=xxx@xxx
    """)
    parser.add_argument('--server', action='store_true', help="Run SSHServer in the server.")
    parser.add_argument('--update-server', action='store_true', help="Update SSHWrapper in the server.")
    args = parser.parse_args()
    if args.server:
        run_ssh_server()
    else:
        run_ssh_client(args)

if __name__ == '__main__':
    main()