
import subprocess
import unittest

from utils import *

def run_cmd(cmd):
    subprocess.check_call(cmd, shell=True)

def mkdir(path):
    run_cmd('rm -rf %s' % path)
    run_cmd('mkdir -p %s' % path)

def touch(path):
    run_cmd('rm -rf %s' % path)
    run_cmd('touch %s' % path)

def remove(path):
    run_cmd('rm -rf %s' % path)

class TestUtils(unittest.TestCase):
    def test_get_possible_paths(self):
        mkdir('test_tmp')
        mkdir('test_tmp/test_dir')
        touch('test_tmp/test_file')
        paths = get_possible_local_paths('t')
        self.assertTrue('test_tmp' in paths)
        paths = get_possible_local_paths('test_tmp/')
        self.assertTrue('test_dir' in paths)
        self.assertTrue('test_file' in paths)
        paths = get_possible_local_paths('test_tmp/test_d')
        self.assertTrue('test_dir' in paths)
        self.assertTrue('test_file' not in paths)
        remove('test_tmp')

def main():
    unittest.main(failfast=True)

if __name__ == '__main__':
    main()