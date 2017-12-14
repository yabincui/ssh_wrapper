#!/usr/bin/env python

from __future__ import print_function
import argparse
import os
from Queue import Queue
import select
import subprocess
import sys
import threading

from file_transfer2 import run_file_server
from utils import *

logger = Logger('./sswrapper.log')

class SshWrapper(object):
    def __init__(self, host_name):
        self.host_name = host_name
        self.popen_obj = None
        self.poll_thread = None
        self.last_stdout_line = ''
        self.stdout_line_queue = Queue()
        self.lock = threading.Lock()
        self.print_stdout = False

    def open(self):
        self.popen_obj = subprocess.Popen(['ssh', '-T', self.host_name],
                                          stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE)
        self.poll_thread = threading.Thread(target=self._run_poll_thread)
        self.poll_thread.start()
    
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
        logger.log('event: fd = %s, event_name %s' % (fd_name, event_name))

    def _handle_remote_stderr_event(self, event):
        # poll thread
        if event & select.POLLIN:
            data = self.popen_obj.stderr.read()
            logger.log('remote stderr "%s"' % data)
            if not data:
                self._close()
            sys.stderr.write(data)
        if event & select.POLLHUP:
            self._close()

    def _close(self):
        os._exit(0)

    def _handle_remote_stdout_event(self, event):
        # poll thread
        if event & select.POLLIN:
            data = self.popen_obj.stdout.read()
            if not data:
                self._close()
                return
            logger.log('remote stdout "%s"' % data)
            data = self.last_stdout_line + data
            lines = split_lines(data)
            self.last_stdout_line = lines[-1]
            lines = lines[:-1]
            self._add_stdout_lines(lines)
        if event & select.POLLHUP:
            self._close()
    
    def _add_stdout_lines(self, lines):
        for line in lines:
            logger.log('put stdout_line "%s"' % line)
            self.stdout_line_queue.put(line)
    
    def read_line(self):
        return self.stdout_line_queue.get()

    def write_line(self, data):
        self.popen_obj.stdin.write(data + '\n')

class ShellClient(object):
    def __init__(self, ssh):
        self.ssh = ssh
        self.builtin_cmds = ['lls', 'lcp', 'lcd', 'lrm', 'lmkdir', 'local', 'rcp', 'send', 'recv']

    def run(self):
        self.run_init_cmd()
        while True:
            sys.stdout.write('> ')
            sys.stdout.flush()
            cmd = sys.stdin.readline()
            if not cmd:
                break
            args = cmd.strip().split()
            if not args:
                continue
            if args[0] in self.builtin_cmds:
                self.run_builtin_cmd(args)
            else:
                self.run_remote_cmd(args)

    def run_init_cmd(self):
        init_cmd = ('rm -rf .ssh_wrapper && mkdir .ssh_wrapper && ' +
                    'git clone https://github.com/yabincui/ssh_wrapper .ssh_wrapper && ' +
                    'python -u .ssh_wrapper/ssh_wrapper4.py --server')
        self.ssh.write_line(init_cmd)
        while True:
            logger.log('wait read_line')
            line = self.ssh.read_line()
            logger.log('read_line return "%s"' % line)
            if line == ShellServer.CMD_END:
                break
            sys.stdout.write(line + '\n')
            sys.stdout.flush()

    def run_remote_cmd(self, args):
        self.ssh.write_line(ShellServer.BUILTIN_CMD_PREFIX + ' '.join(args))
        while True:
            logger.log('wait read_line')
            line = self.ssh.read_line()
            logger.log('read_line return "%s"' % line)
            if line == ShellServer.CMD_END:
                break
            sys.stdout.write(line + '\n')
            sys.stdout.flush()

    def run_builtin_cmd(self, args):
        pass


class ShellServer(object):
    BUILTIN_CMD_PREFIX = 'builtin: '
    CMD_END = 'XXXcmd_endXXX: '

    def __init__(self):
        pass

    def run(self):
        sys.stdout.write(self.CMD_END + '\n')
        while True:
            cmd = sys.stdin.readline()
            cmd = cmd.strip()
            if cmd.startswith(self.BUILTIN_CMD_PREFIX):
                self.run_builtin_cmd(cmd[len(self.BUILTIN_CMD_PREFIX):])
            else:
                if cmd == 'exit':
                    break
                self.run_normal_cmd(cmd)
            sys.stdout.write(self.CMD_END + '\n')

    def run_normal_cmd(self, cmd):
        sys.stdout.write('run cmd: "%s"\n' % cmd)
        subprocess.call(cmd, shell=True)
        sys.stdout.write('run cmd over\n')

    def run_builtin_cmd(self, cmd):
        args = cmd.split()
        if args[0] == 'file_transfer':
            run_file_server()
            

def main():
    parser = argparse.ArgumentParser("""SSH with some convenient commands.
        It supports below cmds in addition to remote cmds through ssh:
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
    """)
    parser.add_argument('--server', action='store_true', help="""
        Run shell server in remote machine.
    """)
    parser.add_argument('--host-name', help="""
        Set remote machine host name. It can be configured in ~/.sshwrapper.config:
          host_name=xxx@xxx
    """)
    args = parser.parse_args()
    if args.server:
        shell = ShellServer()
        shell.run()
    else:
        config = {}
        load_config('~/.sshwrapper.config', config)
        if args.host_name:
            config['host_name'] = args.host_name
        if 'host_name' not in config:
            log_exit('please set host_name in argument or ~/.sshwrapper.config.')
        ssh = SshWrapper(host_name=config['host_name'])
        ssh.open()
        shell = ShellClient(ssh)
        shell.run()

if __name__ == '__main__':
    main()