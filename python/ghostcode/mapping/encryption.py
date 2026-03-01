"""Map encryption using Fernet (symmetric AES-128-CBC).

The map file IS the rosetta stone. If someone gets the ghost code AND the
map, they have everything. The map must be protected at rest.

Key derivation:
    - From passphrase: PBKDF2-HMAC-SHA256 with random salt (100k iterations)
    - From system keychain: auto-generated key stored in OS keychain

Encrypted format:
    - First 16 bytes: salt (for key derivation)
    - Remaining bytes: Fernet-encrypted JSON
    - File extension: .ghost (encrypted) vs .json (plaintext)
"""

import base64
import getpass
import json
import os

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    _CRYPTOGRAPHY_AVAILABLE = False


def _require_cryptography() -> None:
    if not _CRYPTOGRAPHY_AVAILABLE:
        raise RuntimeError(
            "Map encryption requires the 'cryptography' package. "
            "Install it with: pip install cryptography"
        )

SALT_SIZE = 16
KDF_ITERATIONS = 100_000


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet key from a passphrase using PBKDF2."""
    _require_cryptography()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return key


def encrypt_map(data: dict, passphrase: str) -> bytes:
    """Encrypt a map dictionary with a passphrase.

    Args:
        data: The map dictionary to encrypt.
        passphrase: User-provided passphrase.

    Returns:
        Encrypted bytes (salt + ciphertext).
    """
    salt = os.urandom(SALT_SIZE)
    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)

    plaintext = json.dumps(data, indent=2).encode()
    ciphertext = fernet.encrypt(plaintext)

    return salt + ciphertext


def decrypt_map(encrypted_data: bytes, passphrase: str) -> dict:
    """Decrypt an encrypted map file.

    Args:
        encrypted_data: Raw bytes from encrypted file (salt + ciphertext).
        passphrase: User-provided passphrase.

    Returns:
        Decrypted map dictionary.

    Raises:
        ValueError: If passphrase is wrong or data is corrupted.
    """
    if len(encrypted_data) < SALT_SIZE + 1:
        raise ValueError("Encrypted data is too short — file may be corrupted")

    salt = encrypted_data[:SALT_SIZE]
    ciphertext = encrypted_data[SALT_SIZE:]

    key = _derive_key(passphrase, salt)
    fernet = Fernet(key)

    try:
        plaintext = fernet.decrypt(ciphertext)
    except InvalidToken:
        raise ValueError("Decryption failed — wrong passphrase or corrupted file")

    return json.loads(plaintext.decode())


def save_encrypted(data: dict, filepath: str, passphrase: str):
    """Encrypt and save map to file.

    Args:
        data: Map dictionary.
        filepath: Output path (should end in .ghost).
        passphrase: Encryption passphrase.
    """
    encrypted = encrypt_map(data, passphrase)
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(encrypted)


def load_encrypted(filepath: str, passphrase: str) -> dict:
    """Load and decrypt a map file.

    Args:
        filepath: Path to encrypted .ghost file.
        passphrase: Decryption passphrase.

    Returns:
        Decrypted map dictionary.
    """
    with open(filepath, "rb") as f:
        encrypted = f.read()
    return decrypt_map(encrypted, passphrase)


def prompt_passphrase(confirm: bool = False) -> str:
    """Prompt user for a passphrase interactively.

    Args:
        confirm: If True, ask for confirmation (for encryption).

    Returns:
        The passphrase string.
    """
    passphrase = getpass.getpass("GhostCode passphrase: ")
    if not passphrase:
        raise ValueError("Passphrase cannot be empty")

    if confirm:
        confirm_pass = getpass.getpass("Confirm passphrase: ")
        if passphrase != confirm_pass:
            raise ValueError("Passphrases do not match")

    return passphrase


def is_encrypted(filepath: str) -> bool:
    """Check if a file is an encrypted ghost map (.ghost extension)."""
    return filepath.endswith(".ghost")
