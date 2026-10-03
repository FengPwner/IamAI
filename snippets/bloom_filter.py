"""A minimal Bloom filter — probabilistic membership, zero false negatives."""

import hashlib
import math


class BloomFilter:
    """A space-efficient set membership test with no false negatives.

    >>> bf = BloomFilter(capacity=100, error_rate=0.01)
    >>> bf.add("hello")
    >>> "hello" in bf
    True
    >>> "world" in bf
    False
    >>> bf.add("world")
    >>> "world" in bf
    True
    """

    def __init__(self, capacity: int = 1000, error_rate: float = 0.01):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if not (0 < error_rate < 1):
            raise ValueError("error_rate must be in (0, 1)")

        # optimal bit count: m = -(n * ln(p)) / (ln(2))^2
        self.size = int(-capacity * math.log(error_rate) / (math.log(2) ** 2))
        # optimal hash count: k = (m / n) * ln(2)
        self.hash_count = max(1, int((self.size / capacity) * math.log(2)))
        self._bits = bytearray(math.ceil(self.size / 8))
        self._count = 0

    def _hashes(self, item: str) -> list[int]:
        """Generate `hash_count` bit positions from two base hashes (double hashing)."""
        h1 = int(hashlib.md5(item.encode()).hexdigest(), 16)
        h2 = int(hashlib.sha1(item.encode()).hexdigest(), 16)
        return [(h1 + i * h2) % self.size for i in range(self.hash_count)]

    def add(self, item: str) -> None:
        """Insert `item` into the filter."""
        for pos in self._hashes(item):
            byte_idx, bit_idx = divmod(pos, 8)
            self._bits[byte_idx] |= 1 << bit_idx
        self._count += 1

    def __contains__(self, item: str) -> bool:
        """Check if `item` is (probably) in the set. Never false-negative."""
        for pos in self._hashes(item):
            byte_idx, bit_idx = divmod(pos, 8)
            if not (self._bits[byte_idx] & (1 << bit_idx)):
                return False
        return True

    def __len__(self) -> int:
        """Number of items added (not unique count — we don't track duplicates)."""
        return self._count

    @property
    def fill_ratio(self) -> float:
        """Fraction of bits set to 1.

        >>> bf = BloomFilter(capacity=100, error_rate=0.01)
        >>> bf.fill_ratio
        0.0
        >>> bf.add("test")
        >>> bf.fill_ratio > 0
        True
        """
        set_bits = sum(bin(b).count("1") for b in self._bits)
        return set_bits / self.size if self.size else 0.0
