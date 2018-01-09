
import readline
import sys
import termios
import tty

from utils import Logger

logger = Logger('mycmd.log')

class Cmd1(object):
    def __init__(self):
        self.prompt = ''
        self.read_stdin_by_character()

    def read_stdin_by_character(self):
        fd = sys.stdin.fileno()
        self.old_stdin_setting = termios.tcgetattr(fd)
        tty.setraw(fd)

    def restore_stdin(self):
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old_stdin_setting)

    def cmdloop(self):
        while True:
            sys.stdout.write(self.prompt)
            line = self.read_line()
            if not line:
                break
            self.default(line)

    def default(self, line):
        pass

    def read_line(self):
        line = []
        while True:
            ch = sys.stdin.read(1)
            logger.log('read ch (0x%x)' % ord(ch))

class Cmd(object):
    def __init__(self):
        self.prompt = ''

    def cmdloop(self):
        while True:
            logger.log('prompt(%s)' % self.prompt)
            line = raw_input(self.prompt)
            logger.log('raw_input(%s)' % line)
            self.default(line)

    def default(self, line):
        pass

if __name__ == '__main__':
    cmd = Cmd()
    cmd.prompt = '> '
    cmd.prompt = 'yabinc@yabinc: ~/workspace/linux/android-kernelyabinc@yabinc:~/workspace/linux/android-kernel$ '
    cmd.cmdloop()


