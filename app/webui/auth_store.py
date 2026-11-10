"""Password based WebUI authentication with a bootstrap password.

The store keeps a single administrator credential in ``data/webui_auth.json``:

* ``password_hash`` / ``salt`` / ``iterations`` — PBKDF2-HMAC-SHA256.
* ``force_change`` — true until the operator replaces the bootstrap password.
* ``initial_password`` — the auto-generated bootstrap password, kept in
  plain text only while ``force_change`` is true so the operator can read
  it from the file or the startup log once.

On first start (no store file) a random 12 character password is generated;
the file is written with restrictive permissions. Sessions are random
bearer tokens hashed with SHA-256 before storage, so a stolen session file
cannot be replayed directly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import string
import time
from pathlib import Path
from typing import Any

PBKDF2_ITERATIONS = 240_000
SALT_BYTES = 16
SESSION_BYTES = 32
#: Sessions older than this are pruned whenever the store is touched.
SESSION_TTL_SECONDS = 7 * 24 * 3600

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 12

_PASSWORD_CLASSES = (
    ("数字", re.compile(r"[0-9]")),
    ("大写字母", re.compile(r"[A-Z]")),
    ("小写字母", re.compile(r"[a-z]")),
    ("符号", re.compile(r"[^0-9A-Za-z]")),
)


class PasswordPolicyError(ValueError):
    """The proposed password does not satisfy the complexity policy."""


def validate_password_strength(password: str) -> str:
    """Return the password when it satisfies the policy, else raise."""
    if not isinstance(password, str) or not password:
        raise PasswordPolicyError("密码不能为空")
    if not (PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH):
        raise PasswordPolicyError(
            f"密码长度必须为 {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} 位"
        )
    missing = [label for label, pattern in _PASSWORD_CLASSES if not pattern.search(password)]
    if missing:
        raise PasswordPolicyError("密码必须同时包含" + "、".join(missing))
    return password


def _hash_password(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def _generate_bootstrap_password(length: int = 12) -> str:
    """Random password that already satisfies the complexity policy."""
    alphabet_pool = [
        string.ascii_lowercase,
        string.ascii_uppercase,
        string.digits,
        string.punctuation,
    ]
    while True:
        # One character from each class, the rest from the union.
        chars = [secrets.choice(pool) for pool in alphabet_pool]
        all_chars = "".join(alphabet_pool)
        chars.extend(secrets.choice(all_chars) for _ in range(length - len(chars)))
        secrets.SystemRandom().shuffle(chars)
        candidate = "".join(chars)
        try:
            validate_password_strength(candidate)
        except PasswordPolicyError:
            continue
        return candidate


class AuthStore:
    """Persistent single-user credential and session registry."""

    def __init__(self, auth_path: os.PathLike[str] | str):
        self.path = Path(auth_path)
        self._sessions: dict[str, dict[str, Any]] = {}
        self._load_or_bootstrap()

    # -- persistence -----------------------------------------------------

    def _load_or_bootstrap(self) -> None:
        if self.path.is_file():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw
            self._sessions = raw.get("sessions", {})
        else:
            password = _generate_bootstrap_password()
            salt = secrets.token_bytes(SALT_BYTES)
            self._data = {
                "version": 1,
                "password_hash": _hash_password(password, salt, PBKDF2_ITERATIONS).hex(),
                "salt": salt.hex(),
                "iterations": PBKDF2_ITERATIONS,
                "force_change": True,
                "initial_password": password,
                "sessions": {},
            }
            self._save()
            print("=" * 60)
            print("[+] WebUI 首次启动：已自动生成管理密码")
            print(f"[+] 初始密码: {password}")
            print(f"[+] （也已写入 {self.path}，登录后请立即修改密码）")
            print("=" * 60)

    def _save(self) -> None:
        self._prune_sessions()
        self._data["sessions"] = self._sessions
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, ensure_ascii=False, indent=1)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, text.encode("utf-8"))
        finally:
            os.close(fd)

    def bootstrap_password(self) -> str | None:
        """The readable initial password, only while a change is pending."""
        if self._data.get("force_change"):
            return self._data.get("initial_password")
        return None

    @property
    def force_change(self) -> bool:
        return bool(self._data.get("force_change"))

    # -- verification ----------------------------------------------------

    def verify_credential(self, password: str) -> bool:
        salt = bytes.fromhex(self._data["salt"])
        iterations = int(self._data.get("iterations", PBKDF2_ITERATIONS))
        expected = bytes.fromhex(self._data["password_hash"])
        candidate = _hash_password(password, salt, iterations)
        return hmac.compare_digest(candidate, expected)

    def verify_bootstrap_or_password(self, password: str) -> bool:
        """Accept the current password; the env token stays a separate path."""
        return self.verify_credential(password)

    # -- password management ---------------------------------------------

    def change_password(self, old_password: str, new_password: str) -> str:
        if not self.verify_credential(old_password):
            raise PasswordPolicyError("原密码不正确")
        validate_password_strength(new_password)
        if hmac.compare_digest(old_password, new_password):
            raise PasswordPolicyError("新密码不能与原密码相同")
        salt = secrets.token_bytes(SALT_BYTES)
        self._data["password_hash"] = _hash_password(new_password, salt, PBKDF2_ITERATIONS).hex()
        self._data["salt"] = salt.hex()
        self._data["iterations"] = PBKDF2_ITERATIONS
        self._data["force_change"] = False
        self._data.pop("initial_password", None)
        # Every previous session dies with the old password.
        self._sessions.clear()
        session = self._issue_session()
        self._save()
        return session

    # -- sessions ---------------------------------------------------------

    def _issue_session(self) -> str:
        token = secrets.token_urlsafe(SESSION_BYTES)
        self._sessions[self._session_key(token)] = {
            "created": time.time(),
        }
        return token

    def issue_session(self) -> str:
        session = self._issue_session()
        self._save()
        return session

    @staticmethod
    def _session_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def session_is_valid(self, token: str) -> bool:
        if not token:
            return False
        entry = self._sessions.get(self._session_key(token))
        if entry is None:
            return False
        if time.time() - float(entry.get("created", 0)) > SESSION_TTL_SECONDS:
            self._sessions.pop(self._session_key(token), None)
            return False
        return True

    def revoke_session(self, token: str) -> None:
        self._sessions.pop(self._session_key(token), None)
        self._save()

    def _prune_sessions(self) -> None:
        now = time.time()
        stale = [
            key
            for key, entry in self._sessions.items()
            if now - float(entry.get("created", 0)) > SESSION_TTL_SECONDS
        ]
        for key in stale:
            self._sessions.pop(key, None)


__all__ = [
    "AuthStore",
    "PASSWORD_MAX_LENGTH",
    "PASSWORD_MIN_LENGTH",
    "PasswordPolicyError",
    "validate_password_strength",
]
