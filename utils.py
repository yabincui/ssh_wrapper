import fcntl
import os
import sys
import threading

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
        self.log_file = log_file
        self.fh = open(log_file, 'w')
    
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
    fd = fh.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def to_hex_str(s):
    res = []
    for c in s:
        res.append('\\x%02x' % ord(c))
    return ''.join(res)
