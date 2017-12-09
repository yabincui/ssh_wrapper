
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


SshSyncer: monitor file systems change and sync between local and server
  The sync is in one direction, either from server to local, or from local to server.

SshSyncer can read configs from ~/.sshwrapper.config or ./sshwrapper.config.