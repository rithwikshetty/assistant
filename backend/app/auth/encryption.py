"""
Encryption utilities for sensitive data storage.
"""
from cryptography.fernet import Fernet
from typing import Optional
import hashlib
import base64


def _get_fernet_key(secret: str) -> bytes:
    """
    Derive a Fernet-compatible key from the SECRET_KEY.
    Fernet requires a 32-byte base64-encoded key.
    """
    # Hash the secret to get a consistent 32-byte key
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_token(token: str, secret_key: str) -> str:
    """
    Encrypt a token using Fernet symmetric encryption.

    Args:
        token: The plaintext token to encrypt
        secret_key: The application's SECRET_KEY

    Returns:
        Base64-encoded encrypted token
    """
    if not token:
        return ""

    fernet = Fernet(_get_fernet_key(secret_key))
    encrypted = fernet.encrypt(token.encode())
    return encrypted.decode()


def decrypt_token(encrypted_token: str, secret_key: str) -> Optional[str]:
    """
    Decrypt a token encrypted with encrypt_token.

    Args:
        encrypted_token: The encrypted token string
        secret_key: The application's SECRET_KEY

    Returns:
        Decrypted plaintext token, or None if decryption fails
    """
    if not encrypted_token:
        return None

    try:
        fernet = Fernet(_get_fernet_key(secret_key))
        decrypted = fernet.decrypt(encrypted_token.encode())
        return decrypted.decode()
    except Exception:
        # Invalid token or wrong key
        return None
