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

def shift(text:str,password:str):
    rnd = get_random_string(6)
    password = rnd + password
    password = urlsafe_b64encode(password.encode()).decode()

    text=urlsafe_b64encode(text.encode()).decode()
    text = pad(text, len(password))
    lp=[]
    ls=[]
    for p in password:
        lp.append(ord(p))
    ii = 0
    def nx(ii):
        if len(lp)<ii+2:
            return 0
        return ii+1

    for t in text:
        ls.append(chr(ord(t) + lp[ii]))
        ii = nx(ii)

    text=rnd+''.join(ls)
    text=urlsafe_b64encode(text.encode()).decode()
    return remove_pad64(text)

def unshift(text: str, password: str):
    try:
        text=add_pad64(text)
        text = urlsafe_b64decode(text).decode()
        rnd = text[:6]
        text = text[6:]
        password = rnd + password
        password = urlsafe_b64encode(password.encode()).decode()
        lp = []
        ls = []
        for p in password:
            lp.append(ord(p))
        ii = 0

        def nx(ii):
            if len(lp) < ii + 2:
                return 0
            return ii + 1

        for t in text:
            ls.append(chr(ord(t) - lp[ii]))
            ii = nx(ii)

        if len(ls)<len(lp):
            raise RuntimeError('Invalid Token Format')

        text=''.join(ls).rstrip()
        return urlsafe_b64decode(text).decode()
    except:
        sys.exit('Invalid Token Format')