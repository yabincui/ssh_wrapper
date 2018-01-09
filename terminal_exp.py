
import os
import pty
import select
import signal
import subprocess
import termios
import threading
import tty

from utils import *

logger = Logger('terminal_exp.log')

class TerminalOutputHandler(object):
    def __init__(self):
        self.last_data = ''

    def receive_output(self, data):
        data = self.last_data + data
        sys.stdout.write(data)
        sys.stdout.flush()
        logger.log('[stdout]"%s"(%s)' % (data, to_hex_str(data)))

    def receive_error(self, data):
        sys.stderr.write(data)

class Terminal(object):
    def __init__(self):
        self.popen_obj = subprocess.Popen(['/usr/bin/script', '-fqc', '/bin/bash'],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
        self.terminal_output_handler = TerminalOutputHandler()
        self.poll_thread = threading.Thread(target=self._run_poll_thread)
        self.poll_thread.start()

    def _run_poll_thread(self):
        # poll thread
        stdout_fd = self.popen_obj.stdout.fileno()
        stderr_fd = self.popen_obj.stderr.fileno()
        make_file_nonblocking(self.popen_obj.stdout)
        make_file_nonblocking(self.popen_obj.stderr)
        while True:
            rlist, _, xlist = select.select([stdout_fd, stderr_fd], [], [stdout_fd, stderr_fd])
            if stdout_fd in rlist or stdout_fd in xlist:
                data = self.popen_obj.stdout.read()
                if not data:
                    self.close()
                self.receive_stdout_data(data)
            if stderr_fd in rlist or stderr_fd in xlist:
                data = self.popen_obj.stderr.read()
                if not data:
                    self.close()
                self.receive_stderr_data(data)

    def receive_stdout_data(self, data):
        # poll thread
        self.terminal_output_handler.receive_output(data)

    def receive_stderr_data(self, data):
        # poll thread
        self.terminal_output_handler.receive_error(data)

    def close(self):
        os._exit(0)

    def write(self, data):
        self.popen_obj.stdin.write(data)
        logger.log('[stdin]"%s"(%s)' % (data, to_hex_str(data)))

class InputController(object):
    def __init__(self):
        self.old_stdin_setting = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())

    def restore_stdin(self):
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old_stdin_setting)

    def read(self):
        return sys.stdin.read(1)


def t1():
    terminal = Terminal()
    input = InputController()
    while True:
        data = input.read()
        if not data:
            os._exit()
        terminal.write(data)

def use_script():
    obj = subprocess.Popen(['/usr/bin/script', '-fqc', '/bin/bash'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    obj.stdin.write('ls ; echo cmd finish with code $?. >&2\n')
    #obj.stdin.write('ls\n')
    #obj.stdin.write('sleep 1\n')
    obj.stdin.write('exit\n')
    stdout = obj.stdout.read()
    stderr = obj.stderr.read()
    print('stdout (%s), stderr (%s)' % (stdout, stderr))

class TerminalPty(object):
    def __init__(self):
        pid, fd = pty.fork()
        if pid == 0:
            # child process
            subprocess.call(['/bin/bash'], shell=False)
            os._exit(0)
        self.child_pid = pid
        self.pty_fd = fd

    def run(self):
        old_stdin_setting = set_stdin_raw()
        try:
            make_file_nonblocking(self.pty_fd)
            make_file_nonblocking(sys.stdin)
            self.install_window_size_change_signal_handler()
            while True:
                try:
                    rlist, _, xlist = select.select([self.pty_fd, sys.stdin.fileno()], [], [self.pty_fd, sys.stdin.fileno()])
                except select.error as ex:
                    if ex[0] == 4:
                        continue
                    raise
                if self.pty_fd in rlist or self.pty_fd in xlist:
                    try:
                        data = os.read(self.pty_fd, 1024)
                    except OSError:
                        break
                    if not data:
                        logger.log('no pty_fd data')
                        raise Exception()
                    logger.log('[from shell](%s)' % data)
                    sys.stdout.write(data)
                    sys.stdout.flush()
                if sys.stdin.fileno() in rlist or sys.stdin.fileno() in xlist:
                    data = sys.stdin.read()
                    if not data:
                        logger.log('no input data')
                        raise Exception()
                    logger.log('[from terminal](%s)' % data)
                    os.write(self.pty_fd, data)
        
        finally:
            restore_stdin(old_stdin_setting)
        
    def install_window_size_change_signal_handler(self):
        def handler(signum, _):
            w, h = get_terminal_size(sys.stdin.fileno())
            set_terminal_size(self.pty_fd, w, h)
            logger.log('adjust terminal size to w = %d, h = %d' % (w, h))
            
        signal.signal(signal.SIGWINCH, handler)


def use_forkpty():
    w, h = get_terminal_size(sys.stdin.fileno())
    print('w = %d, h = %d' % (w, h))
    terminal = TerminalPty()
    terminal.run()

def main():
    use_forkpty()

if __name__ == '__main__':
    main()

