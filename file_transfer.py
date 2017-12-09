
import os

# File protocol:
# [LOCAL TO REMOTE]
# cmd: send
# from: from_path
# to: from_path
# from_type: file or dir
# file: from_file_path
# data: data in hex format
# dir: from_dir_path
# other files or dirs
# done: done
#
# [LOCAL TO REMOTE]
# cmd: recv
# from: from_path
# to: to_path
# [REMOTE TO LOCAL]
# from_type: file or dir
# file: from_file_path
# data: data in hex format
# dir: from_dir_path
# other files or dirs
# done: done

class FileItem(object):
    def __init__(self, is_file, path):
        self.is_file = is_file
        self.path = path

def collect_file_items(path):
    if os.path.isfile(path):
        return [FileItem(True, path)]
    items = []
    if not os.path.isdir(path):
        return items
    if not path.endswith('/'):
        path += '/'
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            items.append(FileItem(True, file_path))
        for d in dirs:
            dir_path = os.path.join(root, d)
            items.append(FileItem(False, dir_path))
    return items

def compile_file_data(file_path):
    with open(file_path, 'rb') as fh:
        binary_data = fh.read()
    data = []
    for c in binary_data:
        data.append('%02x' % c)
    return ''.join(data)

def decompile_file_data(data):
    binary_data = []
    for i in range(0, len(data), 2):
        binary_data.append(chr(int(data[i:i+2], 16)))
    return ''.join(binary_data)

def send_local_to_remote(local_path, remote_path, write_line_function):
    if os.path.isfile(local_path):
        is_file = True
    elif os.path.isdir(local_path):
        is_file = False
    else:
        return (False, "%s doesn't exist" % is_file)
    if local_path.endswith('/'):
        local_path = local_path[:-1]
    items = collect_file_items(local_path)
    write_line_function('cmd: send')
    write_line_function('from: %s' % local_path)
    write_line_function('to: %s' % remote_path)
    write_line_function('from_type: %s' % ('file' if is_file else 'dir'))
    for item in items:
        if item.is_file:
            write_line_function('file: %s' % item.path)
            data = compile_file_data(os.path.join(local_path, item.path))
            write_line_function('data: %s' % data)
        else:
            write_line_function('dir: %s' % item.path)
    write_line_function('done: done')
    return (True, '')

def recv_remote_to_local(local_path, remote_path, read_line_function,
                         write_line_function):
    is_exist = True
    if os.path.isfile(local_path):
        is_file = True
    elif os.path.isdir(local_path):
        is_file = False
    else:
        is_exist = False
    write_line_function('cmd: recv')
    write_line_function('from: %s' % remote_path)    
    write_line_function('to: %s' % local_path)
    from_type = ''
    cur_file = ''
    while True:
        line = read_line_function()
        colon_pos = line.find(':')
        if colon_pos == -1:
            continue
        key = line[:colon_pos]
        value = line[colon_pos + 1:]
        if key == 'from_type':
            from_type = value


    

class FileTransfer(object):
    def __init__(self):
        pass

    def send_file():
        pass

    def receive_package(self):
        pass

    def send_package(self):
        pass


def main():
    print('hello, my friend')
    print('are you ok?')
    

if __name__ == '__main__':
    main()