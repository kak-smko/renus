import base64
import struct
import time


class SimpleRng:
    """A simple random number generator"""

    def __init__(self, seed: int = None):
        if seed is None:
            seed = int(time.time())
        self.state = seed

    def next_u32(self) -> int:
        """Generates a random 32-bit unsigned integer"""
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return (self.state >> 32) & 0xFFFFFFFF

    def next_u64(self) -> int:
        """Generates a random 64-bit unsigned integer"""
        high = self.next_u32()
        low = self.next_u32()
        return (high << 32) | low

    def next_f64(self) -> float:
        """Generates a random float between 0 and 1"""
        val = self.next_u32()
        return val / 4294967295.0

    def gen_range(self, low: float, high: float) -> float:
        """Generates a random float in the given range"""
        return low + (high - low) * self.next_f64()

    def get_random_bytes(self, length: int) -> bytes:
        """Generates random bytes of specified length"""
        result = bytearray()
        chunks = length // 4
        remainder = length % 4

        for _ in range(chunks):
            random = self.next_u32()
            result.extend(struct.pack('<I', random))

        if remainder > 0:
            random = self.next_u32()
            result.extend(struct.pack('<I', random)[:remainder])

        return bytes(result)


def generate_password(matrix_size: int, password: bytes) -> bytes:
    """Generates a key of specified length by repeating the password"""
    if not password:
        return bytes([0] * matrix_size)

    repeats = matrix_size // len(password)
    remainder = matrix_size % len(password)

    result = password * repeats
    if remainder > 0:
        result += password[:remainder]

    return result


def shuffle(data: bytearray, seed: int, step: int) -> None:
    """Shuffles the data using the given seed"""
    rng = SimpleRng(seed)
    length = len(data)

    for i in range(length - 1, 0, -step):
        j = int(rng.gen_range(0, i))
        data[i], data[j] = data[j], data[i]


def unshuffle(data: bytearray, seed: int, step: int) -> None:
    """Reverses the shuffle operation"""
    rng = SimpleRng(seed)
    length = len(data)
    swaps = []

    for i in range(length - 1, 0, -step):
        j = int(rng.gen_range(0, i))
        swaps.append((i, j))

    for i, j in reversed(swaps):
        data[i], data[j] = data[j], data[i]


def mix(block_size: int, buf: bytearray, key: bytes) -> None:
    """Mixes the data with the key using XOR operations"""
    prev_block = key

    for i in range(0, len(buf), block_size):
        block = buf[i:i + block_size]
        for j in range(len(block)):
            block[j] ^= prev_block[j]
        prev_block = block


def unmix(block_size: int, buf: bytearray, key: bytes) -> None:
    """Reverses the mix operation"""
    blocks = [buf[i:i + block_size] for i in range(0, len(buf), block_size)]

    for i in range(len(blocks) - 1, -1, -1):
        if i == 0:
            for j in range(len(blocks[i])):
                blocks[i][j] ^= key[j]
        else:
            for j in range(len(blocks[i])):
                blocks[i][j] ^= blocks[i - 1][j]


class Cryptor:
    """A cryptographic utility for encrypting and decrypting data using matrix-based transformations"""

    def __init__(self):
        self.matrix = 32

    def encrypt(self, data: bytes, key: str) -> bytes:
        """Encrypts raw bytes using the provided key"""
        matrix_size = self.matrix
        key_bytes = generate_password(matrix_size, key.encode())

        # Prepare data with size prefix and random prefix
        data_size = struct.pack('>I', len(data))
        random_prefix = SimpleRng().get_random_bytes(6)
        seed_random = sum(b for b in random_prefix)

        padded_text = bytearray()
        padded_text.extend(data_size)
        padded_text.extend(random_prefix)
        padded_text.extend(data)

        # First shuffle
        seed_sum = sum(b for b in key_bytes)
        shuffle(padded_text, seed_sum + seed_random, 5)

        # Matrix operations
        matrix = [padded_text[i:i + matrix_size] for i in range(0, len(padded_text), matrix_size)]
        matrix_len = len(matrix)

        for i in range(matrix_len):
            seed = matrix[i + 1][0] if i + 1 < matrix_len else key_bytes[0]
            shuffle(matrix[i], seed + seed_random, 2)

        # Final mix and add seed
        mix(matrix_size, padded_text, key_bytes)
        padded_text.extend(struct.pack('>H', seed_random & 0xFFFF))

        return bytes(padded_text)

    def encrypt_text(self, text: str, key: str) -> str:
        """Encrypts text and returns a URL-safe base64 string"""
        encrypted = self.encrypt(text.encode(), key)
        return base64.urlsafe_b64encode(encrypted).decode().rstrip('=')

    def decrypt(self, encoded: bytes, key: str) -> bytes:
        """Decrypts bytes using the provided key"""
        if len(encoded) < 6:
            raise ValueError("Invalid Token Matrix Length")

        # Extract seed and prepare data
        seed_random = struct.unpack('>H', encoded[-2:])[0]
        decoded = bytearray(encoded[:-2])
        matrix_size = self.matrix
        key_bytes = generate_password(matrix_size, key.encode())

        # Reverse operations
        unmix(matrix_size, decoded, key_bytes)

        matrix = [decoded[i:i + matrix_size] for i in range(0, len(decoded), matrix_size)]
        matrix_len = len(matrix)

        for i in range(matrix_len - 1, -1, -1):
            seed = matrix[i + 1][0] if i + 1 < matrix_len else key_bytes[0]
            unshuffle(matrix[i], seed + seed_random, 2)

        seed_sum = sum(b for b in key_bytes)
        unshuffle(decoded, seed_sum + seed_random, 5)

        # Extract original data
        data_size = struct.unpack('>I', decoded[:4])[0]
        if len(decoded) < data_size + 10:
            raise ValueError("Invalid Token Matrix Length")

        return bytes(decoded[10:10 + data_size])

    def decrypt_text(self, encoded: str, key: str) -> str:
        """Decrypts a URL-safe base64 encoded string"""
        # Add padding if needed
        padding = len(encoded) % 4
        if padding != 0:
            encoded += '=' * (4 - padding)

        data = base64.urlsafe_b64decode(encoded)
        decrypted = self.decrypt(data, key)
        return decrypted.decode()

    def set_matrix(self, size: int) -> None:
        """Sets the matrix size used for cryptographic operations"""
        if size > 0:
            self.matrix = size