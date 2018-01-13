
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
   show proper complete path. (done)
2. Add help cmd. (done)
3. Add recv cmd. (done)
4. Support sending directories. (done)
5. Support recving directories. (done)
6. Add a test script for all file passing cases. (done)
7. Use select.kqueue on mac.

How to support vi through ssh.
1. Too hard to support native vi. But we can copy the file to local, and open
it using visual studio code, gvim, or vi, and send the file back to remote
after editing.

We can study how to allow ssh control the terminal using cursor module.
The input and output is no longer based on line.
1. ssh_wrapper has two modes:
  line mode when waiting commands and executing builtin commands.
  raw mode when executing normal commands. It sends every keystroke to the command through ssh,
  reads how the command wants to control the terminal, and show it using console module.

About the protocol:
  https://en.wikipedia.org/wiki/ANSI_escape_code
  http://ascii-table.com/ansi-escape-sequences.php


Ssh2:
Use a single ssh connection, but can switch between terminal and non terminal mode.
Support vi mode, use a single shell backend.

use a protocol to wrap terminal msg and non terminal msg. (done)
support control msgs for vi.
terminal rows/columns. Or we try forkpty?
  send window size change signal, SIGWINCH.
  https://stackoverflow.com/questions/33155143/how-to-make-a-child-process-use-another-terminal-input-and-output

can support part of the vi function, but still need to further debug why something isn't correct.
  build a forkpty, dump all control data, analysis where is wrong.
TERM env is needed to support vi/man/info.

Split logs, enable only log part of the messages.

Add file transfer cmds.


Using cmd finish mark is too complex and not reliable. Switch to simple find cmd prompt and not intercept normal cmd flow.


SshSyncer: monitor file systems change and sync between local and server
  The sync is in one direction, either from server to local, or from local to server.

SshSyncer can read configs from ~/.sshwrapper.config or ./sshwrapper.config.

Support tab prompt.