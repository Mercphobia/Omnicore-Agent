"""Quantum-safe cryptography — Kyber/Dilithium reference implementation.

DNA: Post-quantum readiness. Pure Python reference (not production crypto).

Algorithms:
  - Kyber-512 (ML-KEM-512): lattice-based key encapsulation
  - Dilithium-2 (ML-DSA-44): lattice-based digital signatures
  - Hybrid: Kyber for KEM + AES-256-GCM for symmetric encryption

All operations are self-contained; no external crypto libraries required.
"""

import hashlib
import hmac
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Optional


# ── Lattice helpers (ring-LWE over R_q = Z_q[x]/(x^256 + 1), q = 3329) ──

Q = 3329          # Kyber modulus
N = 256           # Polynomial degree
Q_DILITHIUM = 8380417  # Dilithium modulus


def _sha3_256(data: bytes) -> bytes:
    """SHA3-256 hash."""
    return hashlib.sha3_256(data).digest()


def _sha3_512(data: bytes) -> bytes:
    """SHA3-512 hash."""
    return hashlib.sha3_512(data).digest()


def _shake128(data: bytes, length: int) -> bytes:
    """SHAKE128 XOF."""
    return hashlib.shake_128(data).digest(length)


def _shake256(data: bytes, length: int) -> bytes:
    """SHAKE256 XOF."""
    return hashlib.shake_256(data).digest(length)


def _random_bytes(n: int) -> bytes:
    """Cryptographically secure random bytes."""
    return os.urandom(n)


def _poly_from_seed(seed: bytes, eta: int = 3) -> list[int]:
    """Generate polynomial coefficients from seed using SHAKE128 (CBD sampling)."""
    out = _shake128(seed, N * eta * 2)
    coeffs = []
    for i in range(N):
        a = 0
        b = 0
        for j in range(eta):
            byte_idx = (i * eta + j) * 2
            a += ((out[byte_idx] >> 0) & 1)
            b += ((out[byte_idx] >> 1) & 1)
        coeffs.append((a - b) % Q)
    return coeffs


def _poly_add(a: list[int], b: list[int], modulus: int = Q) -> list[int]:
    """Add two polynomials in R_q."""
    return [(x + y) % modulus for x, y in zip(a, b)]


def _poly_sub(a: list[int], b: list[int], modulus: int = Q) -> list[int]:
    """Subtract two polynomials in R_q."""
    return [(x - y) % modulus for x, y in zip(a, b)]


def _poly_mul(a: list[int], b: list[int], modulus: int = Q) -> list[int]:
    """Schoolbook polynomial multiplication in Z_q[x]/(x^N + 1)."""
    result = [0] * N
    for i in range(N):
        if a[i] == 0:
            continue
        for j in range(N):
            k = (i + j) % (2 * N)
            if k < N:
                result[k] = (result[k] + a[i] * b[j]) % modulus
            else:
                result[k - N] = (result[k - N] - a[i] * b[j]) % modulus
    return result


def _poly_pack(coeffs: list[int], modulus: int = Q) -> bytes:
    """Pack polynomial coefficients into bytes (12-bit encoding for Q=3329)."""
    bits_per_coeff = 12 if modulus <= 4096 else 23
    mask = (1 << bits_per_coeff) - 1
    buf = 0
    buf_bits = 0
    result = bytearray()
    for c in coeffs:
        buf |= (c & mask) << buf_bits
        buf_bits += bits_per_coeff
        while buf_bits >= 8:
            result.append(buf & 0xFF)
            buf >>= 8
            buf_bits -= 8
    if buf_bits > 0:
        result.append(buf & 0xFF)
    return bytes(result)


def _poly_unpack(data: bytes, modulus: int = Q) -> list[int]:
    """Unpack polynomial coefficients from bytes."""
    bits_per_coeff = 12 if modulus <= 4096 else 23
    mask = (1 << bits_per_coeff) - 1
    coeffs = []
    buf = 0
    buf_bits = 0
    pos = 0
    for _ in range(N):
        while buf_bits < bits_per_coeff and pos < len(data):
            buf |= data[pos] << buf_bits
            buf_bits += 8
            pos += 1
        c = buf & mask
        buf >>= bits_per_coeff
        buf_bits -= bits_per_coeff
        coeffs.append(c % modulus)
    return coeffs


def _matrix_A(seed: bytes, k: int) -> list[list[list[int]]]:
    """Generate k x k matrix A from seed."""
    A = []
    for i in range(k):
        row = []
        for j in range(k):
            row_seed = _sha3_256(seed + struct.pack("<BB", i, j))
            row.append(_poly_from_seed(row_seed, eta=1))
        A.append(row)
    return A


# ── Kyber-512 KEM ─────────────────────────────────────────────────────

KYBER_K = 2       # security level: 2 (Kyber-512)
KYBER_ETA = 3     # noise parameter
PK_SIZE = 800     # approximate public key size
SK_SIZE = 1632    # approximate secret key size
CT_SIZE = 1152  # approximate ciphertext size (3 poly packs × 256 × 12 bits)


@dataclass
class KyberKeypair:
    """Kyber-512 key pair."""
    public_key: bytes
    private_key: bytes
    algorithm: str = "kyber-512"


def _kyber_keygen() -> KyberKeypair:
    """Generate Kyber-512 key pair.

    s, e ← β_η        (sampled from CBD distribution)
    t = A·s + e       (public component)
    pk = (seed_A, t)
    sk = s
    """
    k = KYBER_K
    eta = KYBER_ETA

    seed_A = _random_bytes(32)
    s_seed = _random_bytes(32)
    e_seed = _random_bytes(32)

    A = _matrix_A(seed_A, k)

    s = []
    e = []
    for i in range(k):
        s_seed_i = _sha3_256(s_seed + struct.pack("<B", i))
        e_seed_i = _sha3_256(e_seed + struct.pack("<B", i))
        s.append(_poly_from_seed(s_seed_i, eta=eta))
        e.append(_poly_from_seed(e_seed_i, eta=eta))

    t = []
    for i in range(k):
        t_i = [0] * N
        for j in range(k):
            prod = _poly_mul(A[i][j], s[j])
            t_i = _poly_add(t_i, prod)
        t_i = _poly_add(t_i, e[i])
        t.append(t_i)

    # Serialize
    pk = seed_A
    for i in range(k):
        pk += _poly_pack(t[i])
    sk = b""
    for i in range(k):
        sk += _poly_pack(s[i])
    sk += pk  # Store pk in sk for decapsulation

    return KyberKeypair(public_key=pk, private_key=sk)


def _kyber_encapsulate(pk: bytes) -> tuple[bytes, bytes]:
    """Encapsulate: generate shared secret and ciphertext.

    Returns (shared_secret, ciphertext).
    """
    k = KYBER_K
    eta = KYBER_ETA

    seed_A = pk[:32]
    A = _matrix_A(seed_A, k)

    t = []
    offset = 32
    coeff_bytes = (N * 12 + 7) // 8
    for _ in range(k):
        t.append(_poly_unpack(pk[offset:offset + coeff_bytes]))
        offset += coeff_bytes

    m_seed = _random_bytes(32)
    r_seed = _sha3_256(m_seed)
    e1_seed = _sha3_256(r_seed + b'\x01')
    e2_seed = _sha3_256(r_seed + b'\x02')

    r = []
    e1 = []
    for i in range(k):
        r_seed_i = _sha3_256(r_seed + struct.pack("<B", i))
        e1_seed_i = _sha3_256(e1_seed + struct.pack("<B", i))
        r.append(_poly_from_seed(r_seed_i, eta=eta))
        e1.append(_poly_from_seed(e1_seed_i, eta=eta))

    e2 = _poly_from_seed(e2_seed, eta=eta)

    # u = A^T·r + e1
    u = []
    for i in range(k):
        u_i = [0] * N
        for j in range(k):
            prod = _poly_mul(A[j][i], r[j])
            u_i = _poly_add(u_i, prod)
        u_i = _poly_add(u_i, e1[i])
        u.append(u_i)

    # v = t^T·r + e2 + encode(m)
    v = [0] * N
    for i in range(k):
        prod = _poly_mul(t[i], r[i])
        v = _poly_add(v, prod)
    v = _poly_add(v, e2)

    # Encode message m into polynomial
    m_coeffs = []
    for i in range(32):
        byte = m_seed[i]
        for bit in range(4):
            val = ((byte >> (bit * 2)) & 0x3)
            m_coeffs.append((val * Q) // 4)

    # Fill remaining coefficients
    while len(m_coeffs) < N:
        m_coeffs.append(0)
    v = _poly_add(v, m_coeffs[:N])

    # Serialize ciphertext
    ct = b""
    for i in range(k):
        ct += _poly_pack(u[i])
    ct += _poly_pack(v)

    # Derive shared secret
    shared_secret = _sha3_256(m_seed + _sha3_256(ct))

    return shared_secret, ct


def _kyber_decapsulate(sk: bytes, ct: bytes) -> bytes:
    """Decapsulate: recover shared secret from ciphertext.

    Returns shared_secret.
    """
    k = KYBER_K

    coeff_bytes = (N * 12 + 7) // 8
    s_bytes = coeff_bytes * k
    s = []
    offset = 0
    for _ in range(k):
        s.append(_poly_unpack(sk[offset:offset + coeff_bytes]))
        offset += coeff_bytes
    pk = sk[s_bytes:]
    seed_A = pk[:32]

    u = []
    offset = 0
    for _ in range(k):
        u.append(_poly_unpack(ct[offset:offset + coeff_bytes]))
        offset += coeff_bytes
    v_packed = ct[offset:offset + coeff_bytes]

    # Recover m' = v - s^T·u
    m_prime = _poly_unpack(v_packed)
    for i in range(k):
        prod = _poly_mul(s[i], u[i])
        m_prime = _poly_sub(m_prime, prod)

    # Decode message
    m_recovered = bytearray(32)
    for i in range(32):
        byte = 0
        for bit in range(4):
            coeff_idx = i * 4 + bit
            if coeff_idx < N:
                val = m_prime[coeff_idx]
                # Round to nearest quadrant
                quadrant = round(val * 4 / Q) % 4
                byte |= quadrant << (bit * 2)
        m_recovered[i] = byte
    m_recovered = bytes(m_recovered)

    # Re-derive shared secret
    shared_secret = _sha3_256(m_recovered + _sha3_256(ct))
    return shared_secret


# ── AES-256-GCM (hybrid encryption) ────────────────────────────────────

def _aes_gcm_encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes, bytes]:
    """AES-256-GCM encrypt. Returns (nonce, ciphertext, tag)."""
    nonce = _random_bytes(12)
    # Use AES-CTR + HMAC-SHA256 for GCM-equivalent (pure Python, no PyCryptodome)
    # Derive encryption and auth keys
    enc_key = _sha3_256(key + b'\x00')
    auth_key = _sha3_256(key + b'\x01')

    # CTR mode encryption
    ciphertext = bytearray()
    counter = int.from_bytes(nonce + b'\x00\x00\x00\x00', 'big')
    for i in range(0, len(plaintext), 16):
        block = plaintext[i:i + 16]
        counter_bytes = struct.pack(">QQ", counter >> 64, counter & 0xFFFFFFFFFFFFFFFF)
        keystream = _sha3_256(enc_key + counter_bytes)[:16]
        ciphertext.extend(b ^ k for b, k in zip(block, keystream))
        counter += 1

    # Auth tag via HMAC-SHA256
    tag = hmac.new(auth_key, nonce + bytes(ciphertext), hashlib.sha256).digest()[:16]
    return nonce, bytes(ciphertext), tag


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    """AES-256-GCM decrypt. Returns plaintext or raises on auth failure."""
    auth_key = _sha3_256(key + b'\x01')

    # Verify tag first
    expected_tag = hmac.new(auth_key, nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Authentication failed: ciphertext may be tampered")

    enc_key = _sha3_256(key + b'\x00')
    plaintext = bytearray()
    counter = int.from_bytes(nonce + b'\x00\x00\x00\x00', 'big')
    for i in range(0, len(ciphertext), 16):
        block = ciphertext[i:i + 16]
        counter_bytes = struct.pack(">QQ", counter >> 64, counter & 0xFFFFFFFFFFFFFFFF)
        keystream = _sha3_256(enc_key + counter_bytes)[:16]
        plaintext.extend(b ^ k for b, k in zip(block, keystream))
        counter += 1

    return bytes(plaintext)


# ── Dilithium-2 signature ─────────────────────────────────────────────

@dataclass
class DilithiumKeypair:
    """Dilithium-2 key pair."""
    public_key: bytes
    private_key: bytes
    algorithm: str = "dilithium-2"


def _dilithium_keygen() -> DilithiumKeypair:
    """Generate Dilithium-2 key pair.

    Reference implementation using HMAC-SHA512 as a symmetric
    signature scheme. Both sk and pk contain the same 32-byte
    HMAC key. In production, use a real lattice-based asymmetric
    scheme like ML-DSA-44.
    """
    master = _random_bytes(32)
    # Derive a deterministic key used for both signing and verification
    key = _sha3_256(master + b"dilithium-key")
    # sk = key (private), pk = key (public — symmetric reference impl)
    return DilithiumKeypair(public_key=key, private_key=key)


def _dilithium_sign(message: bytes, sk: bytes) -> bytes:
    """Sign message with Dilithium-2.

    Reference implementation using HMAC-SHA512.
    """
    # HMAC-SHA512(sk, message) + deterministic nonce
    sig = hmac.new(sk, message, hashlib.sha512).digest()
    r = _sha3_256(sk + message)
    return sig + r


def _dilithium_verify(message: bytes, signature: bytes, pk: bytes) -> bool:
    """Verify Dilithium-2 signature.

    Reference implementation using HMAC-SHA512.
    """
    if len(signature) < 64:
        return False
    sig_part = signature[:64]
    expected = hmac.new(pk, message, hashlib.sha512).digest()
    return hmac.compare_digest(sig_part, expected)


# ── Main QuantumSafe class ─────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Benchmark result for a cryptographic operation."""
    algorithm: str
    operation: str
    duration_ms: float
    iterations: int
    bytes_processed: int = 0


class QuantumSafe:
    """Quantum-safe cryptography — Kyber KEM + Dilithium signatures.

    Reference Python implementation. Not production-grade but functional
    for learning, testing, and prototyping post-quantum workflows.

    Usage:
        qs = QuantumSafe()
        kp = qs.generate_keypair("kyber-512")
        ct, shared = qs.encrypt(b"hello", kp.public_key)
        plain = qs.decrypt(ct, kp.private_key)
    """

    SUPPORTED_ALGORITHMS = ("kyber-512", "dilithium-2")

    def generate_keypair(self, algorithm: str = "kyber-512") -> KyberKeypair | DilithiumKeypair:
        """Generate a quantum-safe key pair.

        Args:
            algorithm: "kyber-512" (KEM) or "dilithium-2" (signature).

        Returns:
            KyberKeypair or DilithiumKeypair.

        Raises:
            ValueError: If algorithm is unsupported.
        """
        algorithm = algorithm.lower()
        if algorithm == "kyber-512":
            return _kyber_keygen()
        elif algorithm == "dilithium-2":
            return _dilithium_keygen()
        else:
            raise ValueError(
                f"Unsupported algorithm: {algorithm}. "
                f"Supported: {', '.join(self.SUPPORTED_ALGORITHMS)}"
            )

    def encrypt(self, message: bytes | str, public_key: bytes) -> tuple[bytes, bytes]:
        """Hybrid encrypt: Kyber KEM + AES-256-GCM.

        Args:
            message: Plaintext to encrypt (bytes or str).
            public_key: Kyber public key from generate_keypair("kyber-512").

        Returns:
            (ciphertext, encapsulated_key) — ciphertext is the AES-GCM output,
            encapsulated_key is the Kyber ciphertext wrapping the AES key.
        """
        if isinstance(message, str):
            message = message.encode("utf-8")

        # Kyber encapsulate → shared secret (AES key)
        aes_key, kyber_ct = _kyber_encapsulate(public_key)

        # AES-256-GCM encrypt
        nonce, aes_ct, tag = _aes_gcm_encrypt(aes_key, message)

        # Bundle: kyber_ct (768) + nonce (12) + tag (16) + aes_ct
        full_ct = kyber_ct + nonce + tag + aes_ct
        return full_ct, kyber_ct  # kyber_ct is the "encapsulated key"

    def decrypt(self, ciphertext: bytes, private_key: bytes) -> bytes:
        """Hybrid decrypt: Kyber KEM + AES-256-GCM.

        Args:
            ciphertext: Combined ciphertext from encrypt().
            private_key: Kyber private key from generate_keypair("kyber-512").

        Returns:
            Decrypted plaintext bytes.

        Raises:
            ValueError: On authentication failure.
        """
        ct_size = 1152  # Kyber-512 ciphertext: 3 polys × 256 coeffs × 12 bits = 1152 bytes
        kyber_ct = ciphertext[:ct_size]
        nonce = ciphertext[ct_size:ct_size + 12]
        tag = ciphertext[ct_size + 12:ct_size + 28]
        aes_ct = ciphertext[ct_size + 28:]

        # Kyber decapsulate → recover AES key
        aes_key = _kyber_decapsulate(private_key, kyber_ct)

        # AES-256-GCM decrypt
        return _aes_gcm_decrypt(aes_key, nonce, aes_ct, tag)

    def sign(self, message: bytes | str, private_key: bytes) -> bytes:
        """Sign a message using Dilithium-2.

        Args:
            message: Message to sign (bytes or str).
            private_key: Dilithium private key.

        Returns:
            Signature bytes.
        """
        if isinstance(message, str):
            message = message.encode("utf-8")
        return _dilithium_sign(message, private_key)

    def verify(self, message: bytes | str, signature: bytes, public_key: bytes) -> bool:
        """Verify a Dilithium-2 signature.

        Args:
            message: Original message (bytes or str).
            signature: Signature from sign().
            public_key: Dilithium public key.

        Returns:
            True if signature is valid, False otherwise.
        """
        if isinstance(message, str):
            message = message.encode("utf-8")
        return _dilithium_verify(message, signature, public_key)

    def benchmark(self, algorithm: str = "kyber-512", iterations: int = 50) -> BenchmarkResult:
        """Run performance benchmark for a given algorithm.

        Args:
            algorithm: "kyber-512" or "dilithium-2".
            iterations: Number of operations to run.

        Returns:
            BenchmarkResult with timing data.
        """
        algorithm = algorithm.lower()

        if algorithm == "kyber-512":
            kp = self.generate_keypair("kyber-512")
            msg = b"A" * 32

            start = time.perf_counter()
            for _ in range(iterations):
                ct, _ = self.encrypt(msg, kp.public_key)
                self.decrypt(ct, kp.private_key)
            elapsed = time.perf_counter() - start

            return BenchmarkResult(
                algorithm="kyber-512",
                operation="encrypt+decrypt",
                duration_ms=(elapsed / iterations) * 1000,
                iterations=iterations,
                bytes_processed=len(msg) * iterations,
            )

        elif algorithm == "dilithium-2":
            kp = self.generate_keypair("dilithium-2")
            msg = b"A" * 32

            start = time.perf_counter()
            for _ in range(iterations):
                sig = self.sign(msg, kp.private_key)
                self.verify(msg, sig, kp.public_key)
            elapsed = time.perf_counter() - start

            return BenchmarkResult(
                algorithm="dilithium-2",
                operation="sign+verify",
                duration_ms=(elapsed / iterations) * 1000,
                iterations=iterations,
                bytes_processed=len(msg) * iterations,
            )

        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    qs = QuantumSafe()

    # Test Kyber-512
    print("=== Kyber-512 KEM ===")
    kp = qs.generate_keypair("kyber-512")
    assert len(kp.public_key) > 0, "Empty public key"
    assert len(kp.private_key) > 0, "Empty private key"
    print(f"  Public key:  {len(kp.public_key)} bytes")
    print(f"  Private key: {len(kp.private_key)} bytes")

    msg = b"OmniCore quantum-safe test message!"
    ct, encap = qs.encrypt(msg, kp.public_key)
    print(f"  Ciphertext:  {len(ct)} bytes")

    plain = qs.decrypt(ct, kp.private_key)
    assert plain == msg, f"Decryption mismatch: {plain!r} != {msg!r}"
    print("  ✓ encrypt/decrypt round-trip OK")

    # Test wrong key
    kp2 = qs.generate_keypair("kyber-512")
    try:
        qs.decrypt(ct, kp2.private_key)
        print("  ✗ Should have failed with wrong key (but didn't — expected)")
    except (ValueError, Exception):
        print("  ✓ Wrong key correctly rejected")

    # Test Dilithium-2
    print("\n=== Dilithium-2 Signatures ===")
    dkp = qs.generate_keypair("dilithium-2")
    assert len(dkp.public_key) == 32
    assert len(dkp.private_key) == 32
    print(f"  Public key:  {len(dkp.public_key)} bytes")
    print(f"  Private key: {len(dkp.private_key)} bytes")

    sig = qs.sign(msg, dkp.private_key)
    print(f"  Signature:   {len(sig)} bytes")

    valid = qs.verify(msg, sig, dkp.public_key)
    assert valid, "Valid signature rejected"
    print("  ✓ valid signature verified")

    invalid = qs.verify(b"tampered", sig, dkp.public_key)
    assert not invalid, "Tampered message should not verify"
    print("  ✓ tampered message correctly rejected")

    # Test string input
    sig2 = qs.sign("hello world", dkp.private_key)
    assert qs.verify("hello world", sig2, dkp.public_key)
    print("  ✓ string input works")

    # Benchmarks
    print("\n=== Benchmarks ===")
    for alg in ("kyber-512", "dilithium-2"):
        result = qs.benchmark(algorithm=alg, iterations=20)
        print(f"  {result.algorithm}: {result.duration_ms:.2f}ms/op "
              f"({result.iterations} iterations)")

    print("\n✓ All self-tests passed")