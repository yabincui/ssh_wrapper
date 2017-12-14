#!/usr/bin/python

from __future__ import print_function
import argparse

from ssh_connection import SshConnectionTerminal, SshConnectionNonTerminal
from utils import *

logger = Logger('./sshwrapper.log')


class ShellClient(object):
    def __init__(self, host_name):
        self.builtin_cmds = ['lls', 'lcp', 'lcd', 'lrm', 'lmkdir', 'local',
                             'rcp', 'send', 'recv']
        self.terminal_ssh = SshConnectionTerminal(host_name, logger)
        self.file_transfer_ssh = SshConnectionNonTerminal(host_name, logger)
        self.init()
    
    def init(self):
        self.terminal_ssh.open()
        self.file_transfer_ssh.open()
        self.file_transfer_ssh.write_line(
            'rm -rf .ssh_wrapper && mkdir .ssh_wrapper && ' +
            'git clone https://github.com/yabincui/ssh_wrapper .ssh_wrapper && ' +
            'python -u .ssh_wrapper/file_transfer2.py')
        while True:
            line = self.file_transfer_ssh.read_line()
            if line == 'file_server_ready':
                break

    def run(self):
        while True:
            logger.log('wait stdin line')
            cmd = sys.stdin.readline()
            logger.log('after wait stdin line "%s"' % cmd)
            if not cmd:
                break
            cmd = cmd.strip()
            args = cmd.split()
            logger.log('run cmd = "%s"' % cmd)
            if args and args[0] in self.builtin_cmds:
                self.run_builtin_cmd(cmd)
            else:
                self.run_terminal_cmd(cmd)

    def run_terminal_cmd(self, cmd):
        self.terminal_ssh.write_line(cmd)

    def run_builtin_cmd(self, cmd):
        pass


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
    parser.add_argument('--host-name', help="""
        Set remote machine host name. It can be configured in ~/.sshwrapper.config:
          host_name=xxx@xxx
    """)
    args = parser.parse_args()
    config = {}
    load_config('~/.sshwrapper.config', config)
    if args.host_name:
        config['host_name'] = args.host_name
    if 'host_name' not in config:
        log_exit('please set host_name in argument or ~/.sshwrapper.config.')
    shell = ShellClient(config['host_name'])
    shell.run()

if __name__ == '__main__':
    main()