import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.security import create_token, decode_token, hash_password, verify_password


def test_password_roundtrip():
    hashed = hash_password("abc123")
    assert verify_password("abc123", hashed)
    assert not verify_password("wrong", hashed)


def test_token_roundtrip():
    settings = Settings()
    token = create_token("demo", "user", settings)
    payload = decode_token(token, settings)
    assert payload["sub"] == "demo"
    assert payload["role"] == "user"
