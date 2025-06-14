from base64 import urlsafe_b64encode, urlsafe_b64decode
from hashlib import sha3_512
from json import dumps as json_dump, loads as json_loads
from random import choice as random_choice

from renus.core.serialize import jsonEncoder


def hash_new_password(password: str, salt: str = 'renus') -> str:
    p = password.encode("utf-8")
    s = salt.encode("utf-8")
    r = sha3_512(s + p)
    return sha3_512(p + r.digest()).hexdigest()


def is_correct_password(pw_hash: bytes, password: str, salt: str = 'renus') -> bool:
    p = password.encode("utf-8")
    s = salt.encode("utf-8")
    r = sha3_512(s + p)
    return sha3_512(p + r.digest()).hexdigest() == pw_hash


def get_random_string(length):
    letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return ''.join(random_choice(letters) for i in range(length))


def encode64(value):
    base_bytes = urlsafe_b64encode(json_dump(value,
                                             ensure_ascii=False,
                                             allow_nan=True,
                                             indent=4,
                                             separators=(",", ":"),
                                             cls=jsonEncoder).encode('utf-8'))
    return remove_pad64(base_bytes.decode())


def decode64(value: str, decoder=None):
    try:
        value = add_pad64(value)
        message_bytes = urlsafe_b64decode(value)
        if decoder is None:
            return json_loads(message_bytes)
        return json_loads(message_bytes, object_hook=decoder)
    except:
        raise RuntimeError('Invalid encode64 Format:' + str(value))



def remove_pad64(text):
    return text.replace('=', '')


def add_pad64(text):
    s = 4 - len(text) % 4
    if s == 4:
        return text
    return text + s * '='
