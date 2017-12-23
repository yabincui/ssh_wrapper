
import select

from utils import *

logger = Logger('test_kqueue.log')

def t1():
    kq = select.kqueue()
    make_file_nonblocking(sys.stdin)
    kevent = select.kevent(sys.stdin.fileno(), filter=select.KQ_FILTER_READ,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE)
    while True:
        revents = kq.control([kevent], 1, None)
        for event in revents:
            if (event.filter == select.KQ_FILTER_READ):
                data = sys.stdin.read()
                logger.log('read data [%s]' % data)
                if not data:
                    return


def main():
    old_stdin_setting = use_raw_stdin()
    try:
        t1()
    finally:
        restore_stdin(old_stdin_setting)

main()
