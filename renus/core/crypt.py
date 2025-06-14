import base64
import os
import random


class Cryptor:
    """A cryptographic utility for encrypting and decrypting text using a matrix-based transformation.

    The Cryptor uses a combination of shuffling, mixing, and matrix operations to obscure the
    original text. It supports configurable matrix sizes for the transformation process.
    """

    def __init__(self):
        """Creates a new Cryptor instance with default matrix size (32)."""
        self.matrix = 32

    def encrypt(self, data: bytes, key: str) -> bytes:
        """Encrypts raw bytes using the provided key.

        Args:
            data: The bytes to encrypt
            key: The encryption key

        Returns:
            The encrypted bytes

        Raises:
            ValueError: If encryption fails
        """
        matrix_size = self.matrix
        key_bytes = self._generate_password(matrix_size, key.encode())
        data_size = len(data).to_bytes(4, byteorder='big')
        random_prefix = self._get_random_bytes(6)
        seed_random = sum(b for b in random_prefix)

        padded_text = bytearray()
        padded_text.extend(data_size)
        padded_text.extend(random_prefix)
        padded_text.extend(data)

        seed_sum = sum(b for b in key_bytes)
        self._shuffle(padded_text, seed_sum + seed_random, 5)

        # Split into matrix chunks
        matrix = [padded_text[i:i + matrix_size] for i in range(0, len(padded_text), matrix_size)]

        for i in range(len(matrix)):
            seed = matrix[i + 1][0] if i + 1 < len(matrix) else key_bytes[0]
            self._shuffle(matrix[i], seed + seed_random, 2)

        # Flatten the matrix back to bytes
        padded_text = bytearray().join(matrix)
        self._mix(matrix_size, padded_text, key_bytes)

        padded_text.extend(seed_random.to_bytes(2, byteorder='big'))
        return bytes(padded_text)

    def encrypt_text(self, text: str, key: str) -> str:
        """Encrypts text using the provided key and returns a URL-safe base64 string.

        Args:
            text: The plaintext to encrypt
            key: The encryption key

        Returns:
            URL-safe base64 encoded encrypted string without padding
        """
        encrypted = self.encrypt(text.encode(), key)
        return base64.urlsafe_b64encode(encrypted).decode().rstrip('=')

    def decrypt(self, encoded: bytes, key: str) -> bytes:
        """Decrypts bytes using the provided key.

        Args:
            encoded: The encrypted bytes to decrypt
            key: The decryption key

        Returns:
            The decrypted bytes

        Raises:
            ValueError: If decryption fails
        """
        if len(encoded) < 6:
            raise ValueError("Invalid Token Matrix Length")

        seed_random = int.from_bytes(encoded[-2:], byteorder='big')
        decoded = bytearray(encoded[:-2])
        matrix_size = self.matrix

        key_bytes = self._generate_password(matrix_size, key.encode())
        self._unmix(matrix_size, decoded, key_bytes)

        # Split into matrix chunks
        matrix = [decoded[i:i + matrix_size] for i in range(0, len(decoded), matrix_size)]

        for i in reversed(range(len(matrix))):
            seed = matrix[i + 1][0] if i + 1 < len(matrix) else key_bytes[0]
            self._unshuffle(matrix[i], seed + seed_random, 2)

        # Flatten the matrix back to bytes
        decoded = bytearray().join(matrix)
        seed_sum = sum(b for b in key_bytes)
        self._unshuffle(decoded, seed_sum + seed_random, 5)

        data_size = int.from_bytes(decoded[:4], byteorder='big')
        if len(decoded) < data_size + 10:
            raise ValueError("Invalid Token Matrix Length")

        return bytes(decoded[10:data_size + 10])

    def decrypt_text(self, encoded: str, key: str) -> str:
        """Decrypts a URL-safe base64 encoded string using the provided key.

        Args:
            encoded: URL-safe base64 encoded string to decrypt
            key: The decryption key

        Returns:
            The decrypted string

        Raises:
            ValueError: If decryption fails
        """
        # Add padding if needed
        padding = len(encoded) % 4
        if padding != 0:
            encoded += '=' * (4 - padding)

        data = base64.urlsafe_b64decode(encoded)
        return self.decrypt(data, key).decode()

    def set_matrix(self, size: int):
        """Sets the matrix size used for cryptographic operations.

        The matrix size determines how data is chunked and processed during encryption/decryption.
        Must be a positive non-zero value.
        """
        if size > 0:
            self.matrix = size

    # Utility methods
    def _generate_password(self, matrix: int, password: bytes) -> bytes:
        """Generates a key of specified length by repeating the password."""
        if not password:
            return bytes(matrix)

        password_len = len(password)
        repeats = matrix // password_len
        remainder = matrix % password_len

        result = bytearray()
        for _ in range(repeats):
            result.extend(password)
        if remainder > 0:
            result.extend(password[:remainder])

        return bytes(result)

    def _shuffle(self, data: bytearray, seed: int, step: int):
        """Shuffles the data using the given seed."""
        random.seed(seed)
        length = len(data)

        for i in reversed(range(1, length, step)):
            j = random.randint(0, i)
            data[i], data[j] = data[j], data[i]

    def _unshuffle(self, data: bytearray, seed: int, step: int):
        """Reverses the shuffling operation."""
        random.seed(seed)
        length = len(data)
        swaps = []

        for i in reversed(range(1, length, step)):
            j = random.randint(0, i)
            swaps.append((i, j))

        for i, j in reversed(swaps):
            data[i], data[j] = data[j], data[i]

    def _mix(self, block_size: int, buf: bytearray, key: bytes):
        """Mixes the data blocks with XOR operations."""
        prev_block = key

        for i in range(0, len(buf), block_size):
            block = buf[i:i + block_size]
            for j in range(len(block)):
                block[j] ^= prev_block[j]
            prev_block = block

    def _unmix(self, block_size: int, buf: bytearray, key: bytes):
        """Reverses the mixing operation."""
        chunks = [buf[i:i + block_size] for i in range(0, len(buf), block_size)]

        for i in reversed(range(len(chunks))):
            if i == 0:
                for j in range(len(chunks[i])):
                    chunks[i][j] ^= key[j]
            else:
                for j in range(len(chunks[i])):
                    chunks[i][j] ^= chunks[i - 1][j]

    def _get_random_bytes(self, length: int) -> bytes:
        """Generates cryptographically secure random bytes."""
        return os.urandom(length)
