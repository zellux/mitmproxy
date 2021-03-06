# Copyright (C) 2010  Aldo Cortesi
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import re, os, subprocess, datetime, textwrap, errno, sys, time, functools

CERT_SLEEP_TIME = 1

def timestamp():
    """
        Returns a serializable UTC timestamp.
    """
    return time.time()


def format_timestamp(s):
    s = time.localtime(s)
    d = datetime.datetime.fromtimestamp(time.mktime(s))
    return d.strftime("%Y-%m-%d %H:%M:%S")


def isBin(s):
    """
        Does this string have any non-ASCII characters?
    """
    for i in s:
        i = ord(i)
        if i < 9:
            return True
        elif i > 13 and i < 32:
            return True
        elif i > 126:
            return True
    return False


def cleanBin(s):
    parts = []
    for i in s:
        o = ord(i)
        if o > 31 and o < 127:
            parts.append(i)
        else:
            parts.append(".")
    return "".join(parts)
    

TAG = r"""
        <\s*
        (?!\s*[!"])
        (?P<close>\s*\/)?
        (?P<name>\w+)
        (
            [^'"\t >]+ |
            "[^\"]*"['\"]* |
            '[^']*'['\"]* |
            \s+
        )*
        (?P<selfcont>\s*\/\s*)?
        \s*>
      """
UNI = set(["br", "hr", "img", "input", "area", "link"])
INDENT = " "*4
def pretty_xmlish(s):
    """
        A robust pretty-printer for XML-ish data.
        Returns a list of lines.
    """
    s = cleanBin(s)
    data, offset, indent, prev = [], 0, 0, None
    for i in re.finditer(TAG, s, re.VERBOSE|re.MULTILINE):
        start, end = i.span()
        name = i.group("name")
        if start > offset:
            txt = []
            for x in textwrap.dedent(s[offset:start]).split("\n"):
                if x.strip():
                    txt.append(indent*INDENT + x)
            data.extend(txt)
        if i.group("close") and not (name in UNI and name==prev):
            indent = max(indent - 1, 0)
        data.append(indent*INDENT + i.group().strip())
        offset = end
        if not any([i.group("close"), i.group("selfcont"), name in UNI]):
            indent += 1
        prev = name
    trail = s[offset:]
    if trail.strip():
        data.append(s[offset:])
    return data


def hexdump(s):
    """
        Returns a set of typles:
            (offset, hex, str)
    """
    parts = []
    for i in range(0, len(s), 16):
        o = "%.10x"%i
        part = s[i:i+16]
        x = " ".join(["%.2x"%ord(i) for i in part])
        if len(part) < 16:
            x += " "
            x += " ".join(["  " for i in range(16-len(part))])
        parts.append(
            (o, x, cleanBin(part))
        )
    return parts


def isStringLike(anobj):
    try:
        # Avoid succeeding expensively if anobj is large.
        anobj[:0]+''
    except:
        return 0
    else:
        return 1


def isSequenceLike(anobj):
    """
        Is anobj a non-string sequence type (list, tuple, iterator, or
        similar)?  Crude, but mostly effective.
    """
    if not hasattr(anobj, "next"):
        if isStringLike(anobj):
            return 0
        try:
            anobj[:0]
        except:
            return 0
    return 1


def _caseless(s):
    return s.lower()


def try_del(dict, key):
    try:
        del dict[key]
    except KeyError:
        pass


class MultiDict:
    """
        Simple wrapper around a dictionary to make holding multiple objects per
        key easier.

        Note that this class assumes that keys are strings.

        Keys have no order, but the order in which values are added to a key is
        preserved.
    """
    # This ridiculous bit of subterfuge is needed to prevent the class from
    # treating this as a bound method.
    _helper = (str,)
    def __init__(self):
        self._d = dict()

    def copy(self):
        m = self.__class__()
        m._d = self._d.copy()
        return m

    def clear(self):
        return self._d.clear()

    def get(self, key, d=None):
        key = self._helper[0](key)
        return self._d.get(key, d)

    def __contains__(self, key):
        key = self._helper[0](key)
        return self._d.__contains__(key)

    def __eq__(self, other):
        return dict(self) == dict(other)

    def __delitem__(self, key):
        self._d.__delitem__(key)

    def __getitem__(self, key):
        key = self._helper[0](key)
        return self._d.__getitem__(key)
    
    def __setitem__(self, key, value):
        if not isSequenceLike(value):
            raise ValueError, "Cannot insert non-sequence."
        key = self._helper[0](key)
        return self._d.__setitem__(key, value)

    def has_key(self, key):
        key = self._helper[0](key)
        return self._d.has_key(key)

    def setdefault(self, key, default=None):
        key = self._helper[0](key)
        return self._d.setdefault(key, default)

    def keys(self):
        return self._d.keys()

    def extend(self, key, value):
        if not self.has_key(key):
            self[key] = []
        self[key].extend(value)

    def append(self, key, value):
        self.extend(key, [value])

    def itemPairs(self):
        """
            Yield all possible pairs of items.
        """
        for i in self.keys():
            for j in self[i]:
                yield (i, j)

    def get_state(self):
        return list(self.itemPairs())

    @classmethod
    def from_state(klass, state):
        md = klass()
        for i in state:
            md.append(*i)
        return md


class Headers(MultiDict):
    """
        A dictionary-like class for keeping track of HTTP headers.

        It is case insensitive, and __repr__ formats the headers correcty for
        output to the server.
    """
    _helper = (_caseless,)
    def __repr__(self):
        """
            Returns a string containing a formatted header string.
        """
        headerElements = []
        for key in sorted(self.keys()):
            for val in self[key]:
                headerElements.append(key + ": " + val)
        headerElements.append("")
        return "\r\n".join(headerElements)

    def match_re(self, expr):
        """
            Match the regular expression against each header (key, value) pair.
        """
        for k, v in self.itemPairs():
            s = "%s: %s"%(k, v)
            if re.search(expr, s):
                return True
        return False

    def read(self, fp):
        """
            Read a set of headers from a file pointer. Stop once a blank line
            is reached.
        """
        name = ''
        while 1:
            line = fp.readline()
            if not line or line == '\r\n' or line == '\n':
                break
            if line[0] in ' \t':
                # continued header
                self[name][-1] = self[name][-1] + '\r\n ' + line.strip()
            else:
                i = line.find(':')
                # We're being liberal in what we accept, here.
                if i > 0:
                    name = line[:i]
                    value = line[i+1:].strip()
                    if self.has_key(name):
                        # merge value
                        self.append(name, value)
                    else:
                        self[name] = [value]


def pretty_size(size):
    suffixes = [
        ("B",   2**10),
        ("kB",   2**20),
        ("M",   2**30),
    ]
    for suf, lim in suffixes:
        if size >= lim:
            continue
        else:
            x = round(size/float(lim/2**10), 2)
            if x == int(x):
                x = int(x)
            return str(x) + suf


class Data:
    def __init__(self, name):
        m = __import__(name)
        dirname, _ = os.path.split(m.__file__)
        self.dirname = os.path.abspath(dirname)

    def path(self, path):
        """
            Returns a path to the package data housed at 'path' under this
            module.Path can be a path to a file, or to a directory.

            This function will raise ValueError if the path does not exist.
        """
        fullpath = os.path.join(self.dirname, path)
        if not os.path.exists(fullpath):
            raise ValueError, "dataPath: %s does not exist."%fullpath
        return fullpath
data = Data(__name__)


def dummy_ca(path):
    """
        Creates a dummy CA, and writes it to path.

        This function also creates the necessary directories if they don't exist.

        Returns True if operation succeeded, False if not.
    """
    dirname = os.path.dirname(path)
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    if path.endswith(".pem"):
        basename, _ = os.path.splitext(path)
    else:
        basename = path

    cmd = [
        "openssl",
        "req",
        "-new",
        "-x509",
        "-config", data.path("resources/ca.cnf"),
        "-nodes",
        "-days", "9999",
        "-out", path,
        "-newkey", "rsa:1024",
        "-keyout", path,
    ]
    ret = subprocess.call(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE
    )
    # begin nocover
    if ret:
        return False
    # end nocover

    cmd = [
        "openssl",
        "pkcs12",
        "-export",
        "-password", "pass:",
        "-nokeys",
        "-in", path,
        "-out", os.path.join(dirname, basename + "-cert.p12")
    ]
    ret = subprocess.call(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE
    )
    # begin nocover
    if ret:
        return False
    # end nocover
    cmd = [
        "openssl",
        "x509",
        "-in", path,
        "-out", os.path.join(dirname, basename + "-cert.pem")
    ]
    ret = subprocess.call(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE
    )
    # begin nocover
    if ret:
        return False
    # end nocover

    return True


def dummy_cert(certdir, ca, commonname):
    """
        certdir: Certificate directory.
        ca: Path to the certificate authority file, or None.
        commonname: Common name for the generated certificate.

        Returns cert path if operation succeeded, None if not.
    """
    certpath = os.path.join(certdir, commonname + ".pem")
    if os.path.exists(certpath):
        return certpath

    confpath = os.path.join(certdir, commonname + ".cnf")
    reqpath = os.path.join(certdir, commonname + ".req")

    template = open(data.path("resources/cert.cnf")).read()
    f = open(confpath, "w").write(template%(dict(commonname=commonname)))

    if ca:
        # Create a dummy signed certificate. Uses same key as the signing CA
        cmd = [
            "openssl",
            "req",
            "-new",
            "-config", confpath,
            "-out", reqpath,
            "-key", ca,
        ]
        ret = subprocess.call(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        if ret: return None
        cmd = [
            "openssl",
            "x509",
            "-req",
            "-in", reqpath,
            "-days", "9999",
            "-out", certpath,
            "-CA", ca,
            "-CAcreateserial",
            "-extfile", confpath,
            "-extensions", "v3_cert",
        ]
        ret = subprocess.call(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        if ret: return None
    else:
        # Create a new selfsigned certificate + key
        cmd = [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-config", confpath,
            "-nodes",
            "-days", "9999",
            "-out", certpath,
            "-newkey", "rsa:1024",
            "-keyout", certpath,
        ]
        ret = subprocess.call(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        if ret: return None
    time.sleep(CERT_SLEEP_TIME)
    return certpath


class LRUCache:
    """
        A decorator that implements a self-expiring LRU cache for class
        methods (not functions!).

        Cache data is tracked as attributes on the object itself. There is
        therefore a separate cache for each object instance.
    """
    def __init__(self, size=100):
        self.size = size

    def __call__(self, f):
        cacheName = "_cached_%s"%f.__name__
        cacheListName = "_cachelist_%s"%f.__name__
        size = self.size

        @functools.wraps(f)
        def wrap(self, *args):
            if not hasattr(self, cacheName):
                setattr(self, cacheName, {})
                setattr(self, cacheListName, [])
            cache = getattr(self, cacheName)
            cacheList = getattr(self, cacheListName)
            if cache.has_key(args):
                cacheList.remove(args)
                cacheList.insert(0, args)
                return cache[args]
            else:
                ret = f(self, *args)
                cacheList.insert(0, args)
                cache[args] = ret
                if len(cacheList) > size:
                    d = cacheList.pop()
                    cache.pop(d)
                return ret
        return wrap
