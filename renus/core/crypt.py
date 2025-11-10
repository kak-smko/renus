import base64
import math
import struct
import time


class SimpleRng:
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    @classmethod
    def new_with_time_seed(cls):
        return cls(int(time.time() * 1000))

    def next_u32(self) -> int:
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return (self.state >> 32) & 0xFFFFFFFF

    def next_u64(self) -> int:
        high = self.next_u32()
        low = self.next_u32()
        return (high << 32) | low

    def next_f64(self) -> float:
        val = self.next_u32()
        return val / 4294967295.0

    def gen_range(self, low: float, high: float) -> float:
        return low + (high - low) * self.next_f64()

    def get_random_bytes(self, length: int) -> bytes:
        byte_array = bytearray(length)
        chunks = length // 4
        remainder = length % 4

        for i in range(chunks):
            random = self.next_u32()
            byte_array[i * 4] = random & 0xFF
            byte_array[i * 4 + 1] = (random >> 8) & 0xFF
            byte_array[i * 4 + 2] = (random >> 16) & 0xFF
            byte_array[i * 4 + 3] = (random >> 24) & 0xFF

        if remainder > 0:
            random = self.next_u32()
            for i in range(remainder):
                byte_array[chunks * 4 + i] = (random >> (i * 8)) & 0xFF

        return bytes(byte_array)


class Cryptor:
    def __init__(self):
        self.matrix = 32

    def encrypt(self, data: bytes, key: str) -> bytes:
        matrix_size = self.matrix
        pad = (matrix_size - ((10 + len(data)) % matrix_size)) % matrix_size
        key_bytes = self.generate_password(matrix_size, key.encode('utf-8'))

        # Pack data length into 4 bytes (big-endian)
        data_size = struct.pack('>I', len(data))

        random_prefix = self.get_random_bytes(6)
        seed_random = sum(random_prefix)

        padded_text = bytearray(10 + len(data) + pad)
        padded_text[0:4] = data_size
        padded_text[4:10] = random_prefix
        padded_text[10:10 + len(data)] = data

        if pad > 0:
            padded_text[10 + len(data):10 + len(data) + pad] = [1] * pad

        seed_sum = sum(b for b in key_bytes)
        self.shuffle(padded_text, seed_sum + seed_random, 5)

        for i in range(0, len(padded_text), matrix_size):
            end = min(i + matrix_size, len(padded_text))
            chunk = padded_text[i:end]  # This creates a slice (view) of the bytearray
            seed = (padded_text[i + matrix_size] if (i + matrix_size) < len(padded_text) else key_bytes[0])
            # Need to work on a copy and then put it back since shuffle works in-place
            chunk_copy = bytearray(chunk)  # Create a mutable copy
            self.shuffle(chunk_copy, seed + seed_random, 2)
            padded_text[i:end] = chunk_copy  # Put the shuffled copy back

        self.mix(matrix_size, padded_text, key_bytes)

        # Append seedRandom as 2 bytes (big-endian)
        result = bytearray(len(padded_text) + 2)
        result[0:len(padded_text)] = padded_text
        result[len(padded_text)] = (seed_random >> 8) & 0xFF
        result[len(padded_text) + 1] = seed_random & 0xFF

        return bytes(result)

    def encrypt_text(self, text: str, key: str) -> str:
        data = text.encode('utf-8')
        encrypted = self.encrypt(data, key)
        return self.base64_url_encode(encrypted)

    def encrypt(self, data: bytes, key: str) -> bytes:
        matrix_size = self.matrix
        pad = (matrix_size - ((10 + len(data)) % matrix_size)) % matrix_size
        key_bytes = self.generate_password(matrix_size, key.encode('utf-8'))

        data_size = struct.pack('>I', len(data))

        random_prefix = self.get_random_bytes(6)
        seed_random = sum(random_prefix)

        padded_text = bytearray(10 + len(data) + pad)
        padded_text[0:4] = data_size
        padded_text[4:10] = random_prefix
        padded_text[10:10 + len(data)] = data

        if pad > 0:
            padded_text[10 + len(data):10 + len(data) + pad] = [1] * pad

        seed_sum = sum(b for b in key_bytes)
        self.shuffle(padded_text, seed_sum + seed_random, 5)

        for i in range(0, len(padded_text), matrix_size):
            end = min(i + matrix_size, len(padded_text))
            chunk = padded_text[i:end]
            seed = (padded_text[i + matrix_size] if (i + matrix_size) < len(padded_text) else key_bytes[0])
            chunk_copy = bytearray(chunk)
            self.shuffle(chunk_copy, seed + seed_random, 2)
            padded_text[i:end] = chunk_copy

        self.mix(matrix_size, padded_text, key_bytes)

        result = bytearray(len(padded_text) + 2)
        result[0:len(padded_text)] = padded_text
        result[len(padded_text)] = (seed_random >> 8) & 0xFF
        result[len(padded_text) + 1] = seed_random & 0xFF

        return bytes(result)

    def decrypt(self, encoded: bytes, key: str) -> bytes:
        if len(encoded) < 8:
            raise ValueError('Invalid Token Matrix Length.')

        seed_random = (encoded[-2] << 8) | encoded[-1]
        decoded = bytearray(encoded[:-2])
        matrix_size = self.matrix

        key_bytes = self.generate_password(matrix_size, key.encode('utf-8'))
        self.unmix(matrix_size, decoded, key_bytes)

        for i in range((len(decoded) // matrix_size) * matrix_size, -1, -matrix_size):
            end = min(i + matrix_size, len(decoded))
            chunk = decoded[i:end]
            seed = (decoded[i + matrix_size] if (i + matrix_size) < len(decoded) else key_bytes[0])
            chunk_copy = bytearray(chunk)
            self.unshuffle(chunk_copy, seed + seed_random, 2)
            decoded[i:end] = chunk_copy

        seed_sum = sum(b for b in key_bytes)
        self.unshuffle(decoded, seed_sum + seed_random, 5)

        data_size = struct.unpack('>I', decoded[0:4])[0]

        if len(decoded) < data_size + 10:
            raise ValueError('Invalid Token Matrix Length')

        return bytes(decoded[10:10 + data_size])

    def decrypt_text(self, encoded: str, key: str) -> str:
        padding = len(encoded) % 4
        padded_input = encoded if padding == 0 else encoded + '=' * (4 - padding)

        data = self.base64_url_decode(padded_input)
        decrypted = self.decrypt(data, key)
        return decrypted.decode('utf-8')

    def set_matrix(self, size: int):
        if size > 0:
            self.matrix = size

    def generate_password(self, matrix: int, password: bytes) -> bytes:
        result = bytearray(matrix)
        password_len = len(password)

        if password_len == 0:
            return bytes(result)

        repeats = matrix // password_len
        remainder = matrix % password_len

        for i in range(repeats):
            start = i * password_len
            result[start:start + password_len] = password

        if remainder > 0:
            start = repeats * password_len
            result[start:start + remainder] = password[:remainder]

        return bytes(result)

    def shuffle(self, data: bytearray, seed: int, step: int):
        rng = SimpleRng(seed)
        length = len(data)

        for i in range(length - 1, 0, -step):
            j = math.floor(rng.gen_range(0, i))
            data[i], data[j] = data[j], data[i]

    def unshuffle(self, data: bytearray, seed: int, step: int):
        rng = SimpleRng(seed)
        length = len(data)
        swaps = []

        for i in range(length - 1, 0, -step):
            j = math.floor(rng.gen_range(0, i))
            swaps.append((i, j))

        for i, j in reversed(swaps):
            data[i], data[j] = data[j], data[i]

    def mix(self, block_size: int, buf: bytearray, key: bytes):
        """Mix blocks with previous blocks or key."""
        prev_block = bytearray(key)

        for i in range(0, len(buf), block_size):
            block = buf[i:i + block_size]
            for j in range(min(len(block), len(prev_block))):
                buf[i + j] ^= prev_block[j]
            prev_block = bytearray(buf[i:i + block_size])

    def unmix(self, block_size: int, buf: bytearray, key: bytes):
        """Reverse the mix operation."""
        # First create a list of all blocks
        blocks = []
        for i in range(0, len(buf), block_size):
            blocks.append(bytearray(buf[i:i + block_size]))

        # Process in reverse order
        for i in range(len(blocks) - 1, -1, -1):
            if i == 0:
                # First block uses the key
                for j in range(min(len(blocks[i]), len(key))):
                    blocks[i][j] ^= key[j]
            else:
                # Other blocks use previous block
                for j in range(min(len(blocks[i]), len(blocks[i - 1]))):
                    blocks[i][j] ^= blocks[i - 1][j]

        # Reconstruct the buffer
        buf.clear()
        for block in blocks:
            buf.extend(block)

    def get_random_bytes(self, length: int) -> bytes:
        rng = SimpleRng(int(time.time() * 1000))
        return rng.get_random_bytes(length)

    def base64_url_encode(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

    def base64_url_decode(self, encoded: str) -> bytes:
        padding = len(encoded) % 4
        if padding != 0:
            encoded += '=' * (4 - padding)

        return base64.urlsafe_b64decode(encoded)
