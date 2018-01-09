import fcntl
import os
import struct
import subprocess
import sys
import termios
import threading
import tty

def expand_path(path):
    return os.path.expandvars(os.path.expanduser(path))

def load_config(config_path, config):
    config_path = expand_path(config_path)
    if os.path.isfile(config_path):
        with open(config_path) as fh:
            for line in fh.readlines():
                line = line.strip()
                items = line.split('=')
                if len(items) != 2:
                    continue
                config[items[0].strip()] = items[1].strip()

def log_exit(msg):
    sys.stderr.write(msg + '\n')
    sys.exit(1)

class Logger(object):
    def __init__(self, log_file):
        self.lock = threading.Lock()
        self.log_file = expand_path(log_file)
        self.fh = open(self.log_file, 'w')
    
    def log(self, msg):
        if not msg or msg[-1] != '\n':
            msg += '\n'
        with self.lock:
            self.fh.write(msg)
            self.fh.flush()

def split_lines(s):
    lines = s.splitlines()
    if not lines or (s and (s[-1] == '\r' or s[-1] == '\n')):
        lines.append('')
    return lines

def make_file_nonblocking(fh):
    if type(fh) == int:
        fd = fh
    else:
        fd = fh.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def to_hex_str(s):
    res = []
    for c in s:
        res.append('\\x%02x' % ord(c))
    return ''.join(res)

logger = Logger('util.log')

def get_possible_local_paths(path):
    if not path:
        return os.listdir('.')
    path = expand_path(path)
    result = []
    dirpath, basename = os.path.split(path)
    if not dirpath:
        dirpath = '.'
    if os.path.isdir(dirpath):
        for item in os.listdir(dirpath):
            if item.startswith(basename):
                result.append(item)
    logger.log('path = %s, dirpath = %s, basename = %s' % (path, dirpath, basename))
    return result

def run_cmd(cmd):
    subprocess.check_call(cmd, shell=True)

def mkdir(path):
    if not os.path.exists(path):
        run_cmd('mkdir -p %s' % path)

def touch(path):
    run_cmd('rm -rf %s' % path)
    run_cmd('touch %s' % path)

def remove(path):
    run_cmd('rm -rf %s' % path)

def get_file_type(path):
    result = []
    if os.path.isfile(path) and os.access(path, os.X_OK):
        result.append('executable')
    return result

def get_script_dir():
    return os.path.dirname(os.path.realpath(__file__))

def split_string(s, sep=', '):
    if not s:
        return []
    return s.split(sep)

def set_stdin_raw():
    old_stdin_setting = termios.tcgetattr(sys.stdin.fileno())
    tty.setraw(sys.stdin.fileno())
    new_stdin_setting = termios.tcgetattr(sys.stdin.fileno())
    # Still want to change \n to \r\n.
    new_stdin_setting[1] |= termios.OPOST
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, new_stdin_setting)
    return old_stdin_setting

def restore_stdin(stdin_setting):
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, stdin_setting)

def get_terminal_size(fd):
    h, w, hp, wp = struct.unpack('HHHH', fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0)))
    return w, h

def set_terminal_size(fd, width, height):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
