
SshWrapper: ssh + scp
contines three functions:
  normal ssh
  send local remote
  recv remote local

In order to let the remote server has the ability to execute some code, let the server
'git clone' SshWrapper project, and run the ssh_wrapper.py --server cmd.

SshWrapper can read configs from ~/.sshwrapper.config or ./sshwrapper.config.

SshWrapper uses one thread to listen to ssh stdout and stderr, and uses one thread
  to send commands and handle outputs.

  Start up two ssh connections, one use -T (non terminal), one use -t -t (terminal).
  Normal shell cmd goes through terminal, file send/recv cmd goes through
  non-terminal.

1. Use cmd.Cmd.
   show correct prompt. (done)
   show proper complete path.
2. Add help cmd. (done)
3. Add recv cmd.
4. Support sending directories.
5. Support recving directories.
6. Add a test script for all file passing cases.
7. Use select.kqueue on mac.

How to support vi through ssh.
1. Too hard to support native vi. But we can copy the file to local, and open
it using visual studio code, gvim, or vi, and send the file back to remote
after editing.


SshSyncer: monitor file systems change and sync between local and server
  The sync is in one direction, either from server to local, or from local to server.

SshSyncer can read configs from ~/.sshwrapper.config or ./sshwrapper.config.