# handles encrypting and decrypting tokens
import os
from cryptography.fernet import Fernet

# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Then set it as an env var called ENCRYPTION_KEY (on Render + locally). Never commit it.
ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"]
_fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    if value is None:
        return None
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if value is None:
        return None
    return _fernet.decrypt(value.encode()).decode()