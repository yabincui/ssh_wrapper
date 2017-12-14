
from __future__ import print_function
import os
from Queue import Queue
import select
import subprocess
import sys
import threading

from utils import *

class SshConnectionBase(object):
    def __init__(self, host_name, logger, log_tag):
        self.host_name = host_name
        self.logger = logger
        self.log_tag = log_tag
        self.popen_obj = None
        self.poll_thread = None

    def _open(self, ssh_args):
        self.popen_obj = subprocess.Popen(ssh_args,
                                          stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
        self.poll_thread = threading.Thread(target=self._run_poll_thread)
        self.poll_thread.start()
    
    def close(self):
        os._exit(0)

    def _log(self, data):
        self.logger.log('%s: %s\n' % (self.log_tag, data))

    def _run_poll_thread(self):
        # poll thread
        poll_obj = select.poll()
        poll_obj.register(self.popen_obj.stdout)
        event_mask = select.POLLIN | select.POLLERR | select.POLLHUP | select.POLLNVAL
        make_file_nonblocking(self.popen_obj.stderr)
        make_file_nonblocking(self.popen_obj.stdout)
        poll_obj.register(self.popen_obj.stderr.fileno(), event_mask)
        poll_obj.register(self.popen_obj.stdout.fileno(), event_mask)
        while True:
            event_list = poll_obj.poll()
            for fd, event in event_list:
                self._dump_event(fd, event)
                if fd == self.popen_obj.stdout.fileno():
                    self._handle_remote_stdout_event(event)
                elif fd == self.popen_obj.stderr.fileno():
                    self._handle_remote_stderr_event(event)        

    def _dump_event(self, fd, event):
        # poll thread
        fd_name = '%s' % fd
        if fd == self.popen_obj.stderr.fileno():
            fd_name = 'remote_stderr'
        elif fd == self.popen_obj.stdout.fileno():
            fd_name = 'remote_stdout'
        event_name = ''
        if event & select.POLLIN:
            event_name += 'POLLIN '
        if event & select.POLLERR:
            event_name += 'POLLERR '
        if event & select.POLLHUP:
            event_name += 'POLLHUP '
        if event & select.POLLNVAL:
            event_name += 'POLLNVAL '
        self._log('event: fd = %s, event_name %s' % (fd_name, event_name))

    def _handle_remote_stdout_event(self, event):
        # poll thread
        if event & select.POLLIN:
            data = self.popen_obj.stdout.read()
            if not data:
                self.close()
                return
            self._log('remote stdout "%s"' % data)
            self.receive_stdout_data(data)
        if event & select.POLLHUP:
            self.close()

    def _handle_remote_stderr_event(self, event):
        # poll thread
        if event & select.POLLIN:
            data = self.popen_obj.stderr.read()
            self._log('remote stderr "%s"' % data)
            if not data:
                self.close()
            sys.stderr.write(data)
        if event & select.POLLHUP:
            self.close()

    def receive_stdout_data(self, data):
        # poll thread
        pass

    def write_line(self, data):
        self._log('write_line(%s)' % data)
        self.popen_obj.stdin.write(data + '\n')


class SshConnectionNonTerminal(SshConnectionBase):
    def __init__(self, host_name, logger):
        super(SshConnectionNonTerminal, self).__init__(host_name, logger, 'NonTerminal')
        self.last_stdout_line = ''
        self.stdout_line_queue = Queue()

    def open(self):
        self._open(['ssh', '-T', self.host_name])

    def receive_stdout_data(self, data):
        # poll thread
        data = self.last_stdout_line + data
        lines = split_lines(data)
        self.last_stdout_line = lines[-1]
        lines = lines[:-1]
        for line in lines:
            self._log('put stdout_line "%s"' % line)
            self.stdout_line_queue.put(line)

    def read_line(self):
        return self.stdout_line_queue.get()

class SshConnectionTerminal(SshConnectionBase):
    def __init__(self, host_name, logger):
        super(SshConnectionTerminal, self).__init__(host_name, logger, 'Terminal')
        self.lock = threading.Lock()
        self.omit_echo_line = False

    def open(self):
        self._open(['ssh', '-t', '-t', self.host_name])

    def receive_stdout_data(self, data):
        with self.lock:
            omit_line = self.omit_echo_line
        if omit_line:
            lines = split_lines(data)
            if len(lines) == 1:
                return
            data = '\n'.join(lines[1:])
            with self.lock:
                self.omit_echo_line = False
        sys.stdout.write(data)
        sys.stdout.flush()

    def write_line(self, data):
        with self.lock:
            self.omit_echo_line = True
        super(SshConnectionTerminal, self).write_line(data)
