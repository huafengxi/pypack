#!/usr/bin/env python3
'''
tar zc *.py -O | ./pack.py --pack entry.py >a-pack.py
curl -s $r/a.tar.gz | ./pack.py ...
pk=$r/a.tar.gz ./pack.py ...
'''
import sys
import os, os.path, subprocess
import re
import stat
import tempfile

def prepare_tfile(content):
    def mkfd():
        fd, name = tempfile.mkstemp()
        os.unlink(name)
        return fd
    def fd_path(fd): return '/dev/fd/%d'%(fd)
    fd = mkfd()
    try:
        os.write(fd, content)
        os.fchmod(fd, stat.S_IRUSR | stat.S_IXUSR)
        return fd_path(os.open(fd_path(fd), os.O_RDONLY))
    finally:
        os.close(fd)

import importlib.abc
import importlib.util
import importlib.machinery
class Pack(importlib.abc.MetaPathFinder, importlib.abc.Loader, list):
    def __init__(self, data):
        def remove_first_part(p):
            idx = p.find('/', 1)
            if idx < 0: return ''
            return p[idx:]
        def build_index(data):
            i = {}
            for k,v in reversed(data):
               p = os.path.join('/', k)
               fp = os.path.join('<tar>', p)
               while p:
                   i[p] = (fp, v)
                   p = remove_first_part(p)
            return i
        list.__init__(self, data)
        self.index = build_index(data)
    def find_file(self, key, nothrow=True):
        def path_norm(p): return os.path.join('/', p)
        d = self.index.get(path_norm(key), None)
        if d != None: return d
        if not nothrow:  raise IOError('not found file in pkg: ' + key)
    def __str__(self): return self.__repr__()
    def __repr__(self): return "Pack(cnt=%d)"%(len(self))
    def ls(self, pat=''): return ' '.join(k for k,v in self if re.match(pat, k))
    def list(self, prefix):
        def path_norm(p): return os.path.join('/', p)
        for path, content in self:
            if path_norm(path).startswith(path_norm(prefix)):
                yield path
    def read(self, key, limit=-1):
        res = self.find_file(key, nothrow=True)
        return res and res[1] or None
    def locate_module(self, fullname):
        path = fullname.replace('.', '/')
        return self.find_file(path + '/__init__.py') or self.find_file(path + '.py') or self.find_file(path + '.so')
    def find_spec(self, fullname, path, target=None): # MetaPathFinder
        if self.locate_module(fullname):
            return importlib.machinery.ModuleSpec(fullname, self)
    def create_module(self, spec): # Loader
        return None # Use default module creation
    def exec_module(self, mod):
        fullname = mod.__name__
        res = self.locate_module(fullname)
        if not res: raise IOError('not found module in pkg: %s'%(fullname))
        path, content = res
        mod.__file__ = path
        if path.endswith('__init__.py'): # is package
            mod.__path__ = []
            mod.__package__ = fullname
        else:
            mod.__package__ = fullname.rpartition('.')[0]
        if path.endswith('.py'):
            eval(compile(content, os.path.join('<tar>', path), 'exec'), mod.__dict__)
        return mod

def prepare_pack():
    def extract_tar(targz):
        import tarfile
        import gzip
        from io import BytesIO
        unzip_content = gzip.GzipFile(fileobj=BytesIO(targz)).read()
        tar = tarfile.TarFile(mode='r', fileobj=gzip.GzipFile(fileobj=BytesIO(targz)))
        return [(x.name, tar.extractfile(x).read()) for x in tar if x.isreg()]
    def read_file(url):
        if url == 'stdin':
            return sys.stdin.buffer.read()
        elif url.startswith('X:'):
            return base64.b64decode(url[2:])
        elif os.path.isfile(url):
            return file(url).buffer.read()
    def get_pk_src():
        def get_from_stdin(): return not sys.stdin.isatty() and 'stdin'
        return globals().get('__pk_src__', '') or os.getenv('pk', '')  or get_from_stdin() or ''
    src = get_pk_src()
    return src and Pack(extract_tar(read_file(src)))

def genpack(pack, entry=None):
    if not pack.read('pack.py'): pack.append(['pack.py', file(__file__).read()])
    if entry: pack.append(['pack.spec', ('__pk_entry__=%s'%(repr(entry))).encode('utf-8')])
    def build_tar(kv):
        import tarfile
        import gzip
        from io import BytesIO
        targz = BytesIO()
        gzipfile = gzip.GzipFile(mode='w', fileobj=targz)
        tar = tarfile.TarFile(mode='w', fileobj=gzipfile)
        for k,v in kv:
            tarinfo = tarfile.TarInfo(name=k)
            if v == None:
                print('v is None, k=%s'%(k))
            tarinfo.size = len(v)
            tar.addfile(tarinfo, fileobj=BytesIO(v))
        tar.close()
        gzipfile.close()
        return targz.getvalue()
    import base64, zlib
    return """#!/usr/bin/env python
import base64, zlib
__pk_src__ = 'X:%s'
exec(compile(zlib.decompress(base64.b64decode(b'%s')), "<tar>/pack.py", "exec"))
""" % (base64.b64encode(build_tar(pack)).decode('ascii'), base64.b64encode(zlib.compress(pack.read('pack.py'))).decode('utf-8'))

def run(pack): # sys.argv must > 1
    eval(compile(pack.read('pack.spec'), '<tar>/pack.spec', 'exec'), globals(), globals())
    def is_executable(text): return (type(text) == str or type(text) == bytes) and text.startswith(b'#!/')
    main_file = sys.argv.pop(1) if pack.read(sys.argv[1]) != None else __pk_entry__
    src = pack.read(main_file)
    if not src: raise Exception('%s not found!'%(main_file))
    if not is_executable(src):
        sys.stdout.write(src.decode('utf-8'))
    elif main_file.endswith('.py'):
        eval(compile(src, os.path.join('<tar>', main_file), 'exec'), globals(), globals())
    else:
        rfd, wfd = os.pipe()
        if os.fork() > 0:
            os.close(wfd)
            os.execv('/bin/bash', ['/bin/bash', '/dev/fd/%d'%(rfd,)] + sys.argv[1:])
        else:
            os.close(rfd)
            os.write(wfd, src)
            os.close(wfd)
__pack__ = prepare_pack()
if not __pack__:
    print(__doc__)
    sys.exit(1)

if len(sys.argv) <= 1:
    print(__pack__.read('readme.txt').decode('utf-8'))
elif sys.argv[1] == '--pack':
    print(genpack(__pack__, sys.argv[2]))
else:
    sys.meta_path.insert(0, __pack__)
    run(__pack__)
