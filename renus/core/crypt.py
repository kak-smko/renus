from base64 import urlsafe_b64encode, urlsafe_b64decode
import sys

from renus.util.helper import get_random_string, remove_pad64, add_pad64

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

def pad(s,n=16):
    block_size = n
    remainder = len(s) % block_size
    padding_needed = block_size - remainder
    return s + padding_needed * ' '


def __generate_key(password):
    salt = b'dfkTGG536fdfkTGG536fkdfijdkdfijd'
    kdf = PBKDF2HMAC(algorithm = hashes.SHA256(),length = 32,salt = salt,iterations = 100000)
    return urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt(text:str,password:str)->str:
    assert Fernet is not None, "'cryptography' must be installed to use encrypt"
    key = __generate_key(password)
    f = Fernet(key)
    d= f.encrypt(text.encode())
    return d.decode()



def decrypt(enc_dict:str, password:str)->str:
    assert Fernet is not None, "'cryptography' must be installed to use decrypt"
    key = __generate_key(password)
    f = Fernet(key)
    d = f.decrypt(enc_dict.encode())
    return d.decode()


def shift(clear, key):
    clear += key
    rnd = get_random_string(6)
    clear = rnd + clear
    clear = urlsafe_b64encode(clear.encode()).decode()
    enc = []
    lnk=len(key)
    for i in range(len(clear)):
        key_c = key[i % lnk]
        enc_c = chr((ord(clear[i]) + ord(key_c)) % 256)
        enc.append(enc_c)

    return remove_pad64(urlsafe_b64encode("".join(enc).encode()).decode())


def unshift(enc, key):
    try:
        enc = urlsafe_b64decode(add_pad64(enc)).decode()
        ln = len(key)
        dec = []
        for i in range(len(enc)):
            key_c = key[i % ln]
            dec_c = chr((256 + ord(enc[i]) - ord(key_c)) % 256)
            dec.append(dec_c)
        return urlsafe_b64decode("".join(dec)).decode()[6:-ln]
    except:
        raise RuntimeError('Invalid Token Format')