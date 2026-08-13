from app.config import settings
from app.core.crypto import decrypt, encrypt


def encrypt_token(plain: str) -> str:
    return encrypt(plain, settings.CURSOR_TOKEN_ENCRYPT_KEY)


def decrypt_token(cipher: str) -> str:
    return decrypt(cipher, settings.CURSOR_TOKEN_ENCRYPT_KEY)
