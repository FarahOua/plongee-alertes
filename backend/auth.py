"""Connexion sans mot de passe : code à 6 chiffres envoyé par mail, puis jeton de session."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, request

from .db import get_db

CODE_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
MAX_ATTEMPTS = 5
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise ValueError("Adresse mail invalide.")
    return email


def create_login_code(email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO login_codes (email, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash, "
            "expires_at=excluded.expires_at, attempts=0",
            (email, _hash(code), (_now() + CODE_TTL).isoformat()),
        )
    return code


def verify_login_code(email: str, code: str) -> str:
    """Vérifie le code et renvoie un jeton de session. Lève ValueError sinon."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM login_codes WHERE email = ?", (email,)).fetchone()
        if row is None or row["expires_at"] < _now().isoformat():
            raise ValueError("Code expiré ou inconnu. Redemande un code.")
        if row["attempts"] >= MAX_ATTEMPTS:
            raise ValueError("Trop d'essais. Redemande un code.")
        if not hmac.compare_digest(row["code_hash"], _hash((code or "").strip())):
            conn.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE email = ?", (email,))
            raise ValueError("Code incorrect.")
        conn.execute("DELETE FROM login_codes WHERE email = ?", (email,))
        conn.execute("INSERT INTO users (email) VALUES (?) ON CONFLICT(email) DO NOTHING", (email,))
        user_id = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_hash(token), user_id, (_now() + SESSION_TTL).isoformat()),
        )
    return token


def user_from_token(token: str):
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (_hash(token), _now().isoformat()),
        ).fetchone()
    return dict(row) if row else None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        user = user_from_token(token)
        if user is None:
            return jsonify(error="Connexion requise."), 401
        g.user = user
        return view(*args, **kwargs)

    return wrapper
