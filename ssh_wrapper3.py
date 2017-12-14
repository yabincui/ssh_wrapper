#!/usr/bin/env python

from __future__ import print_function
import argparse
import fcntl
import os
import select
import subprocess
import sys
import threading

from file_transfer2 import FileClient
from utils import *

def is_prompt_line(line):
    return line[-2:] == '$ ' or line[-2:] == '# '

class SshWrapper(object):
    def __init__(self, host_name):
        self.host_name = host_name
        self.logger = Logger('./sshwrapper.log')
        self.end_flag_content = 'end_flag_of_ssh_wrapper'
        self.popen_obj = None
        self.poll_thread = None
        self.lock = threading.Lock()
        self.last_stdout_line = ''
        # Variables protected by self.lock
        self.end_flag_cond = threading.Condition(self.lock)
        self.end_flag = False
        self.is_closed = False
        self.omit_cmd_line = False
        self.print_stdout = False
        self.stdout_lines = []
        self.stdout_line_cond = threading.Condition(self.lock)

    def open(self):
        self.popen_obj = subprocess.Popen(['ssh', '-T', self.host_name],
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        self.poll_thread = threading.Thread(target=self._run_poll_thread)
        self.poll_thread.start()
        self._send_end_flag_cmd()
        self._wait_end_flag()

    def _set_end_flag(self, value):
        self.end_flag_cond.acquire()
        self.end_flag = value
        if self.end_flag:
            self.end_flag_cond.notify()
        self.end_flag_cond.release()

    def _wait_end_flag(self):
        self.end_flag_cond.acquire()
        while not self.end_flag:
            self.end_flag_cond.wait()
        self.end_flag_cond.release()

    def _set_closed(self):
        with self.lock:
            self.is_closed = True
        self._set_end_flag(True)

    def closed(self):
        with self.lock:
            return self.is_closed

    def _set_omit_cmd_line(self, value):
        with self.lock:
            self.omit_cmd_line = value
            self.logger.log('set omit_cmd_line = %s' % value)

    def _get_and_clear_omit_cmd_line(self):
        with self.lock:
            value = self.omit_cmd_line
            self.omit_cmd_line = False
        self.logger.log('get and clear omit_cmd_line = %s' % value)
        return value

    def _set_print_stdout(self, value):
        with self.lock:
            self.print_stdout = value

    def _get_print_stdout(self):
        with self.lock:
            return self.print_stdout

    def _add_stdout_lines(self, lines):
        with self.lock:
            self.stdout_lines.extend(lines)
            if self.stdout_lines:
                self.stdout_line_cond.notify()
    
    def _get_and_clear_stdout_lines(self):
        with self.lock:
            lines = self.stdout_lines
            self.stdout_lines = []
        return lines

    def _run_poll_thread(self):
        # poll thread
        poll_obj = select.poll()
        poll_obj.register(self.popen_obj.stdout)
        event_mask = select.POLLIN | select.POLLERR | select.POLLHUP | select.POLLNVAL
        make_file_nonblocking(self.popen_obj.stderr)
        make_file_nonblocking(self.popen_obj.stdout)
        poll_obj.register(self.popen_obj.stderr.fileno(), event_mask)
        poll_obj.register(self.popen_obj.stdout.fileno(), event_mask)
        while not self.closed():
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
        self.logger.log('event: fd = %s, event_name %s' % (fd_name, event_name))

    def _handle_remote_stdout_event(self, event):
        # poll thread
        if event & select.POLLIN:
            data = self.popen_obj.stdout.read()
            if not data:
                self._set_closed()
                return
            self.logger.log('remote stdout "%s"' % data)
            data = self.last_stdout_line + data
            lines = split_lines(data)
            if is_prompt_line(lines[-1]):
                self.last_stdout_line = ''
            else:
                self.last_stdout_line = lines[-1]
                lines = lines[:-1]
            if not lines:
                return
            self.logger.log('remote stdout process lines "%s"' % lines)
            if self._get_and_clear_omit_cmd_line():
                self.logger.log('omit one line')
                lines = lines[1:]
            new_stdout_lines = []
            has_end_flag = False
            prompt_line = ''
            for i, line in enumerate(lines):
                if line == self.end_flag_content:
                    has_end_flag = True
                elif line.endswith(self.end_flag_content):
                    continue
                elif i == len(lines) - 1 and is_prompt_line(line):
                    prompt_line = line
                else:
                    new_stdout_lines.append(line)
            if new_stdout_lines:
                self.logger.log('new_stdout_lines "%s"' % new_stdout_lines)
                self._add_stdout_lines(new_stdout_lines)
            if self._get_print_stdout():
                for i, line in enumerate(new_stdout_lines):
                    sys.stdout.write(line + '\n')
                if prompt_line:
                    sys.stdout.write(prompt_line)
            sys.stdout.flush()
            if has_end_flag:
                self.logger.log('has_end_flag')
                self._set_end_flag(True)
        if event & select.POLLHUP:
            self._set_closed()

    def _handle_remote_stderr_event(self, event):
        # poll thread
        if event & select.POLLIN:
            data = self.popen_obj.stderr.read()
            if not data:
                self._set_closed()
            sys.stderr.write(data)
        if event & select.POLLHUP:
            self._set_closed()

    def _send_end_flag_cmd(self):
        self._set_print_stdout(True)
        self._set_end_flag(False)
        self.popen_obj.stdin.write('echo %s\n' % self.end_flag_content)
        self._wait_end_flag()

    def run_cmd(self, cmd, print_stdout=True):
        self._set_end_flag(False)
        self._get_and_clear_stdout_lines()
        self._set_omit_cmd_line(True)
        self._set_print_stdout(print_stdout)
        self.popen_obj.stdin.write('%s\necho %s\n' % (cmd, self.end_flag_content))
        self._wait_end_flag()
        self.logger.log('after wait_end_flag')
        return self._get_and_clear_stdout_lines()

    def start_cmd(self, cmd, print_stdout=True):
        self._set_end_flag(False)
        self._get_and_clear_stdout_lines()
        self._set_omit_cmd_line(True)
        self._set_print_stdout(print_stdout)
        self.popen_obj.stdin.write('%s\n' % (cmd))
    
    def write_line(self, data):
        self.popen_obj.stdin.write(data + '\n')

    def read_line(self):
        self.stdout_line_cond.acquire()
        while not self.stdout_lines:
            self.stdout_line_cond.wait()
        line = self.stdout_lines[0]
        self.stdout_lines = self.stdout_lines[1:]
        return line.strip()


builtin_cmds = ['recv', 'send']
def run_builtin_cmd(ssh, args):
    if args[0] == 'send':
        if len(args) != 3:
            sys.stderr.write('send [local_file_or_dir] [remote_file_or_dir]\n')
            return
        ssh.run_cmd('rm -rf ~/.ssh_wrapper', print_stdout=False)
        ssh.run_cmd('mkdir ~/.ssh_wrapper', print_stdout=False)
        ssh.run_cmd('git clone https://github.com/yabincui/ssh_wrapper.git ~/.ssh_wrapper',
                    print_stdout=False)
        ssh.start_cmd('python ~/.ssh_wrapper/file_transfer2.py', print_stdout=False)
        file_client = FileClient(write_line_function=ssh.write_line,
                                 read_line_function=ssh.read_line)
        file_client.send(args[1], args[2])
    

def run(ssh):
    while not ssh.closed():
        cmd = sys.stdin.readline()
        if not cmd:
            break
        cmd = cmd.strip()
        ssh.logger.log('read cmd "%s"' % cmd)
        args = cmd.split()
        if args[0] in builtin_cmds:
            run_builtin_cmd(ssh, args)
        else:
            ssh.run_cmd(cmd)


def main():
    parser = argparse.ArgumentParser(description="""
        SshWrapper: normal ssh plus two scp commands.
        send [local] [remote] -- send local files to host.
        recv [remote] [local] -- recv remote files to local.
        It is configured in ./sshwrapper.config and ~/.sshwrapper.config.
        supported configurations:
          host_name=xxx@xxx  -- remote machine to ssh to.
        """)
    parser.parse_args()
    config = {}
    load_config('./sshwrapper.config', config)
    load_config('~/.sshwrapper.config', config)
    if 'host_name' not in config:
        log_exit('Please config host_name in config files.')
    ssh = SshWrapper(host_name=config['host_name'])
    ssh.open()
    run(ssh)

if __name__ == '__main__':
    main()
