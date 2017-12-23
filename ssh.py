#!/usr/bin/python

from __future__ import print_function
import argparse
import subprocess
import termios

from file_transfer import FileClient
#from mycmd import Cmd
from cmd import Cmd
from ssh_connection import SshConnectionTerminal, SshConnectionNonTerminal
from utils import *

logger = Logger('./sshwrapper.log')

cmd_helps = """
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
            """

class ShellClient(Cmd):
    def init(self, host_name):
        self.builtin_cmds = ['lls', 'lcp', 'lcd', 'lrm', 'lmkdir', 'local',
                             'rcp', 'send', 'recv']
        self.terminal_ssh = SshConnectionTerminal(host_name, logger)
        self.file_transfer_ssh = SshConnectionNonTerminal(host_name, logger)
        self.file_client = None
        self.file_transfer_ssh.open()
        self.file_transfer_ssh.write_line(
            'rm -rf .ssh_wrapper && mkdir .ssh_wrapper && ' +
            'git clone https://github.com/yabincui/ssh_wrapper .ssh_wrapper && ' +
            'python -u .ssh_wrapper/file_transfer.py')
        while True:
            line = self.file_transfer_ssh.read_line()
            if line == 'file_server_ready':
                break
        self.terminal_ssh.open()
        self.prompt = self.terminal_ssh.wait_prompt()
        self.file_client = FileClient(self.file_transfer_ssh.write_line,
                                      self.file_transfer_ssh.read_line,
                                      logger)

    def run(self):
        old_stdin_setting = termios.tcgetattr(sys.stdin.fileno())
        try:
            self.doc_header = cmd_helps
            self.cmdloop()
        finally:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_stdin_setting)
            

    def emptyline(self):
        self.run_terminal_cmd('')

    def default(self, line):
        cmd = line.strip()
        args = cmd.split()
        if args and args[0] in self.builtin_cmds:
            self.run_builtin_cmd(cmd)
        else:
            self.run_terminal_cmd(cmd)

    def error(self, msg):
        sys.stderr.write(msg + '\n')

    def run_terminal_cmd(self, cmd):
        self.terminal_ssh.write_line(cmd)
        self.prompt = self.terminal_ssh.wait_prompt()

    def run_builtin_cmd(self, cmd):
        args = cmd.split()
        if args[0] in ('lls', 'lrm', 'lcd', 'lmkdir'):
            self.run_local_cmd(cmd[1:])
        elif args[0] == 'local':
            self.run_local_cmd(' '.join(args[1:]))
        elif args[0] in ('send', 'lcp'):
            if len(args) != 3:
                self.error('wrong cmd, need `%s local remote`.' % args[0])
            else:
                self.send_files(args[1], args[2])
        elif args[0] in ('recv', 'rcp'):
            if len(args) != 3:
                self.error('wrong cmd, need `%s remote local`.' % args[0])
            else:
                self.recv_files(args[1], args[2])

    def run_local_cmd(self, cmd):
        args = cmd.split()
        if args[0] == 'cd':
            if len(args) != 2:
                sys.stderr.write('wrong cmd, need `lcd local_path`\n')
                return
            path = expand_path(args[1])
            if not os.path.isdir(path):
                sys.stderr.write('path "%s" not exist.\n' % path)
            os.chdir(path)
        else:
            subprocess.call(cmd, shell=True)
        # Add prompt
        self.run_terminal_cmd('')

    def sync_remote_cwd(self):
        pwd = self.terminal_ssh.get_cwd()
        self.prompt = self.terminal_ssh.wait_prompt()
        self.file_client.set_remote_cwd(pwd)

    def send_files(self, local, remote):
        self.sync_remote_cwd()
        self.file_client.send(local, remote)

    def recv_files(self, remote, local):
        self.sync_remote_cwd()
        self.file_client.recv(remote, local)

    def completedefault(self, text, line, begidx, endidx):
        logger.log('completedefault(text="%s", line="%s"' % (text, line))
        args = line.split()
        if not args:
            return []
        if line.endswith(' '):
            args.append('')
        result = []
        logger.log('args = "%s"' % args)
        if args[0] in ('lls', 'lcd', 'lrm', 'local', 'run'):
            result = get_possible_local_paths(args[-1])
        elif args[0] in ('send', 'lcp'):
            if len(args) == 2:
                result = get_possible_local_paths(args[-1])
            else:
                result = self.get_possible_remote_paths(args[-1])
        elif args[0] in ('recv', 'rcp'):
            if len(args) == 2:
                result = self.get_possible_remote_paths(args[-1])
            else:
                result = get_possible_local_paths(args[-1])
        else:
            logger.log('get_possible_remote_paths %s' % args[-1])
            result = self.get_possible_remote_paths(args[-1])
        logger.log('completedefault(text="%s", line="%s", result = "%s"' % (args[-1], line, result))
        return result

    def get_possible_remote_paths(self, path):
        self.sync_remote_cwd()
        return self.file_client.get_possible_paths(path)


def main():
    parser = argparse.ArgumentParser("""SSH with some convenient commands.
        It supports below cmds in addition to remote cmds through ssh:
            %s
    """ % cmd_helps)
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
    shell = ShellClient()
    shell.init(config['host_name'])
    shell.run()

if __name__ == '__main__':
    main()
