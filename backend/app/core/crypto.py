import base64
import hashlib
import os

from Crypto.Cipher import DES
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_AES_PREFIX = "v2:"


def _aes_key(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


def encrypt(text: str, key: str) -> str:
    nonce = os.urandom(12)
    cipher = AESGCM(_aes_key(key))
    payload = nonce + cipher.encrypt(nonce, text.encode("utf-8"), None)
    return _AES_PREFIX + base64.b64encode(payload).decode("utf-8")


def decrypt(encrypted_text: str, key: str) -> str:
    if encrypted_text.startswith(_AES_PREFIX):
        raw = base64.b64decode(encrypted_text[len(_AES_PREFIX) :])
        nonce, blob = raw[:12], raw[12:]
        return AESGCM(_aes_key(key)).decrypt(nonce, blob, None).decode("utf-8")
    return _decrypt_legacy_des(encrypted_text, key)


def _decrypt_legacy_des(encrypted_text: str, key: str) -> str:
    """Read tokens encrypted by the previous DES-CBC scheme."""
    key_b = key[:8].ljust(8, "\0").encode("utf-8")
    iv = bytes([0x12, 0x34, 0x56, 0x78, 0x90, 0xAB, 0xCD, 0xEF])
    raw = base64.b64decode(encrypted_text)
    cipher = DES.new(key_b, DES.MODE_CBC, iv)
    decrypted_text = cipher.decrypt(raw).decode("utf-8")
    pad = ord(decrypted_text[-1])
    return decrypted_text[:-pad]
