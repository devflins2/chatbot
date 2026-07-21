"""
Encryption utilities for secure API key storage.
Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
Keys are encrypted before storage and decrypted only when needed for API calls.
"""

import os
import base64
import secrets
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)

# Path to store the encryption key file (never commit this file)
KEY_FILE_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "database",
    ".encryption_key",
)


def _get_or_create_key() -> bytes:
    """
    Load or generate the Fernet encryption key.
    In production, this should come from a secure key management service
    (e.g., AWS KMS, HashiCorp Vault) or an environment variable.
    """
    # Priority 1: Environment variable
    env_key = os.environ.get("ENCRYPTION_KEY")
    if env_key:
        try:
            key = base64.urlsafe_b64decode(env_key.encode())
            if len(key) == 32:
                return base64.urlsafe_b64encode(key)
            return env_key.encode()
        except Exception:
            pass

    # Priority 2: Key file on disk
    os.makedirs(os.path.dirname(KEY_FILE_PATH), exist_ok=True)
    if os.path.exists(KEY_FILE_PATH):
        with open(KEY_FILE_PATH, "rb") as f:
            return f.read().strip()

    # Generate a new key
    key = Fernet.generate_key()
    with open(KEY_FILE_PATH, "wb") as f:
        f.write(key)
    # Restrict file permissions on Unix systems
    try:
        os.chmod(KEY_FILE_PATH, 0o600)
    except AttributeError:
        pass  # Windows doesn't support chmod
    logger.info("Generated new encryption key and saved to disk.")
    return key


# Module-level cipher instance
_fernet: Fernet = None


def get_cipher() -> Fernet:
    """Get the Fernet cipher instance (lazy initialization)."""
    global _fernet
    if _fernet is None:
        key = _get_or_create_key()
        _fernet = Fernet(key)
    return _fernet


def encrypt_api_key(raw_key: str) -> str:
    """
    Encrypt an API key for storage.
    Returns base64-encoded ciphertext as a string.
    """
    if not raw_key:
        raise ValueError("API key cannot be empty")
    cipher = get_cipher()
    encrypted = cipher.encrypt(raw_key.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt a stored API key for use in API calls.
    This should only be called server-side; never return the result to the frontend.
    """
    if not encrypted_key:
        raise ValueError("Encrypted key cannot be empty")
    cipher = get_cipher()
    decrypted = cipher.decrypt(encrypted_key.encode("utf-8"))
    return decrypted.decode("utf-8")


def make_key_preview(raw_key: str) -> str:
    """
    Create a safe preview of an API key for display.
    Shows first 8 characters, masked middle, last 4 characters.
    Example: "sk-abc12..." → "sk-abc12••••••1234"
    """
    if not raw_key or len(raw_key) < 12:
        return "••••••••"
    return f"{raw_key[:8]}••••••{raw_key[-4:]}"