"""Shared test utilities for embedding tests."""

import random
import struct


def to_blob(vec: list[float]) -> bytes:
    """Serialize a float vector to little-endian float32 BLOB."""
    return struct.pack(f"<{len(vec)}f", *vec)


def random_vec(dim: int, seed: int = 42) -> list[float]:
    """Generate a deterministic pseudo-random vector."""
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(dim)]
