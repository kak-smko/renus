import os
from datetime import datetime, timedelta
import pickle
from hashlib import sha3_256

from renus.core.log import Log
from renus.util.helper import encode64

from renus.core.config import Config

try:
    import redis
    rds = redis.Redis()
except ImportError:
    rds=None

class Cache:
    depth = 1
    typ=Config('app').get('cacheDriver','file')
    if typ=='redis':
        assert rds is not None, "'redis' must be installed for Cache"
        rd=rds
    else:
        rd=None
    def __init__(self, prefix: str = '', use_hash=False) -> None:
        self._prefix = prefix
        self._use_hash = use_hash

    def put(self, key: str, value, expire: int = 60):
        """
        add value by key to cache system
        :param key: key for value
        :param value: value that save by key
        :param expire: seconds to expire from now
        """
        if self.rd:
            v=pickle.dumps(value,pickle.HIGHEST_PROTOCOL)
            self.rd.set(self._prefix+key,v,expire)
            return
        expire = datetime.utcnow() + timedelta(seconds=expire)
        path = self._build_name(key, self.depth)
        self._create_if_not_exist(path, value, expire)

    def get(self, key: str, default=None):
        if self.rd:
            r=self.rd.get(self._prefix+key)
            return default if r is None else pickle.loads(r)
        path = self._build_name(key, self.depth)
        return self._read_key(path, default)['value']

    def expire(self, key, default=None):
        if self.rd:
            return max(-1,self.rd.ttl(self._prefix+key))
        path = self._build_name(key, self.depth)
        t= self._read_key(path, default)['expire']
        if t==-1:
            return -1
        return max(-1,int(t.timestamp()-datetime.utcnow().timestamp()))

    def delete(self, key):
        if self.rd:
            return self.rd.delete(self._prefix+key)

        path = self._build_name(key, self.depth)
        return self._delete_file("storage/cache" + path)

    def delete_expired(self):
        filename = './storage/cache/'
        n = 0
        for dirname, subdirs, files in os.walk(filename):
            for file in files:
                p=f'{dirname}/{file}'.replace(filename,'')
                r=self._read_key(p)
                if r['expire']==-1:
                    t= self._delete_file("storage/cache/"+p)
                    if t:
                        n+=1

        Log().info(f'delete_expired success: {n} files')

    def _delete_file(self, path, n=0):
        path = path.strip(' \n')
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            if n < 3:
                return self._delete_file(path, n + 1)
            Log().info(f'cache delete_file: {exc}')
        return True

    def _check_pass(self, line):
        res = line.split('<=>', 1)
        if len(res) < 2:
            return True
        expired, path = res
        if (datetime.strptime(expired, '%Y-%m-%d %H:%M:%S').timestamp() < datetime.utcnow().timestamp()):
            self._delete_file('storage/cache' + path)
            return False
        return True


    def _create_if_not_exist(self, path, value, expire, n=0):
        filename = 'storage/cache' + path
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'wb') as output:
                pickle.dump(expire, output, pickle.HIGHEST_PROTOCOL)
                pickle.dump(value, output, pickle.HIGHEST_PROTOCOL)
        except:
            if n < 3:
                self._create_if_not_exist(path, value, expire, n + 1)

    def _read_key(self, path, default=None, n=0):
        filename = 'storage/cache' + path
        if not os.path.exists(filename):
            return {'value': default, 'expire': -1}

        try:
            with open(filename, 'rb') as input:
                expire = pickle.load(input)
                value = pickle.load(input)
        except Exception:
            if n < 3:
                return self._read_key(path, default, n + 1)
            else:
                return {'value': default, 'expire': -1}

        if expire.timestamp() < datetime.utcnow().timestamp():
            self._delete_file(filename)
            return {'value': default, 'expire': -1}
        return {'value': value, 'expire': expire}

    def _build_name(self, key: str, depth):
        h_key = hash_key(key, self._use_hash)
        res = self._prefix.strip('/')
        d = 1
        s = 0
        e = 2
        while d < depth + 1:
            d += 1
            res += '/' + h_key[s:e]
            s = e
            e += 2
        res += '/' + h_key[s:]
        return '/' + res


def hash_key(key, use_hash=False):
    k = str(key)
    if use_hash:
        return sha3_256(k.encode("utf-8")).hexdigest()

    if len(k) < 10:
        k += '123456789'
    return encode64(k)


def cache_func(time: int, prefix=''):
    def dec(func):
        name = func.__name__
        file = func.__code__.co_filename

        def wrapper(*args, **kw):
            k = prefix + file + name
            for i in args:
                if type(i) in [str, int, float, list, dict, tuple, set]:
                    k = k + hash_key(i,True)

            has = Cache(use_hash=True).get(k, 'no_cached')
            if has != 'no_cached':
                return has

            f = func(*args, **kw)
            Cache(use_hash=True).put(k, f, time)
            return f

        return wrapper

    return dec