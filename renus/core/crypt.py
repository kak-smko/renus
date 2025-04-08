import random
from base64 import urlsafe_b64encode, urlsafe_b64decode
from hashlib import sha3_256
from typing import List

from renus.util.helper import get_random_string


class FastEncryptor:
    def __init__(self, length=32):
        self._matrix = length

    def _pad_list(self, s: List[int]) -> List[int]:
        """Pads the input list with zeros until its length is a multiple of n."""
        block_size = self._matrix
        remainder = len(s) % block_size
        padding_needed = block_size - remainder
        return s + [0] * padding_needed

    def _generate_password(self, password: bytes) -> List[int]:
        """Generates a list of matrix bytes from the hashed password."""
        p = sha3_256()
        r = []
        while len(r) < self._matrix:
            p.update(password)
            r.extend(p.digest())
        return r[:self._matrix]

    def _to_matrix(self, text: List[int]) -> List[List[int]]:
        """Converts a flat list into a matrix of size matrix."""
        return [text[i * self._matrix:(i + 1) * self._matrix] for i in range(len(text) // self._matrix)]

    def _from_matrix(self, text: List[List[int]]) -> List[int]:
        """Flattens a matrix back into a single list."""
        return [item for sublist in text for item in sublist]

    def _getperm(self, l, seed):
        perm = list(range(len(l)))
        random.Random(seed).shuffle(perm)
        return perm

    def _shuffle(self, l, seed):
        perm = self._getperm(l, seed)
        l[:] = [l[j] for j in perm]

    def _unshuffle(self, l, seed):
        perm = self._getperm(l, seed)
        res = [None] * len(l)
        for i, j in enumerate(perm):
            res[j] = l[i]
        l[:] = res

    def _sum_matrix(self, l: List[List[int]], key: List[int]) -> None:
        """Applies XOR operation to the matrix with the key."""
        for i in range(len(l)):
            for j in range(len(l[i])):
                l[i][j] ^= l[i - 1][j] if i > 0 else key[j]

    def _minus_matrix(self, l: List[List[int]], key: List[int]) -> None:
        """Reverses the sum_matrix operation."""
        ln = len(l)
        for k in range(ln):
            i = ln - k - 1
            for j in range(len(l[i])):
                l[i][j] ^= l[i - 1][j] if i > 0 else key[j]

    def _decode(self, enc):
        return urlsafe_b64encode(bytearray(enc)).decode()

    def _encode(self, dec):
        return list(urlsafe_b64decode(dec.encode()))

    def shift(self, text: str, key: str):
        key = self._generate_password(key.encode("utf-8"))
        text = get_random_string(self._matrix) + text
        text = self._pad_list(list(text.encode("utf-8")))
        text = self._to_matrix(text)
        self._shuffle(text, sum(key))
        for i in range(len(text)):
            if i > len(text) - 2:
                self._shuffle(text[i], key[0])
            else:
                self._shuffle(text[i], text[i + 1][0])

        self._sum_matrix(text, key)
        return self._decode(self._from_matrix(text))

    def unshift(self, text, key):
        text = self._encode(text)
        remainder = len(text) % self._matrix
        if remainder != 0:
            raise RuntimeError('Invalid Token Matrix Length')
        key = self._generate_password(key.encode("utf-8"))
        text = self._to_matrix(text)
        self._minus_matrix(text, key)
        for k in range(len(text)):
            i = len(text) - k - 1
            if i == len(text) - 1:
                self._unshuffle(text[i], key[0])
            else:
                self._unshuffle(text[i], text[i + 1][0])

        self._unshuffle(text, sum(key))
        text = self._from_matrix(text)
        if len(text) <= self._matrix:
            raise RuntimeError('Invalid Token Matrix Length')
        return bytearray(text[self._matrix:]).decode("utf-8").rstrip(chr(0))
