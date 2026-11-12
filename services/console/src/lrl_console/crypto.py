"""Authenticated encryption for stored passwords."""

from cryptography.fernet import Fernet


class PasswordCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, password: str) -> bytes:
        return self._fernet.encrypt(password.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return self._fernet.decrypt(ciphertext).decode()
