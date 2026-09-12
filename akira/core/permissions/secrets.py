"""Credentials, encrypted by the operating system to this Windows account.

The rule this module exists to enforce: **a secret never reaches a model.** Not
in a prompt, not in a tool argument, not in the audit log. Tools ask for a
credential *by name*; the transport layer fetches the value and attaches it to
the request. The agent handles a handle, never the thing itself.

Encryption is DPAPI, which binds the ciphertext to the current Windows user
account. Copying the files to another machine or another account yields
nothing. That is weaker than a hardware keystore and much stronger than a file
of plaintext tokens, which is the realistic alternative.

Where DPAPI is unavailable the store refuses to save rather than falling back
to something weaker. A secret store that silently degrades to obfuscation is
worse than one that says it cannot help.
"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from pathlib import Path

from akira.core.config import config_dir

#: Names are used as filenames, so they are validated rather than sanitised.
_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

#: Mixed into every encryption. Ciphertext from this application cannot be
#: decrypted by another program running as the same user unless it knows this.
#: It keeps the name the application had before it was Akira: every saved
#: secret was sealed with it, so changing it would make each one unreadable.
_ENTROPY = b"protege.secrets.v1"

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretError(RuntimeError):
    """A secret could not be stored or retrieved."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]

    @classmethod
    def of(cls, data: bytes) -> "_Blob":
        buffer = ctypes.create_string_buffer(data, len(data))
        return cls(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))

    def value(self) -> bytes:
        return ctypes.string_at(self.pbData, self.cbData)


def _dpapi():
    """The two DPAPI entry points, or None where they do not exist."""
    try:
        crypt32 = ctypes.WinDLL("crypt32.dll")
        kernel32 = ctypes.WinDLL("kernel32.dll")
    except (OSError, AttributeError):
        return None
    return crypt32, kernel32


def available() -> bool:
    """Whether secrets can be stored at all on this machine."""
    return _dpapi() is not None


def _protect(plaintext: bytes) -> bytes:
    api = _dpapi()
    if api is None:
        raise SecretError(
            "No OS credential store is available here, so Akira will not "
            "store secrets. It will not fall back to obfuscating them."
        )
    crypt32, kernel32 = api
    out = _Blob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(_Blob.of(plaintext)), None,
        ctypes.byref(_Blob.of(_ENTROPY)), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise SecretError("the operating system refused to encrypt the secret")
    try:
        return out.value()
    finally:
        kernel32.LocalFree(out.pbData)


def _unprotect(ciphertext: bytes) -> bytes:
    api = _dpapi()
    if api is None:
        raise SecretError("no OS credential store is available here")
    crypt32, kernel32 = api
    out = _Blob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(_Blob.of(ciphertext)), None,
        ctypes.byref(_Blob.of(_ENTROPY)), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise SecretError(
            "the secret could not be decrypted. DPAPI ties it to the Windows "
            "account that saved it, so this usually means it was written by a "
            "different user or copied from another machine."
        )
    try:
        return out.value()
    finally:
        kernel32.LocalFree(out.pbData)


class SecretStore:
    """Named credentials, one encrypted file each."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory if directory is not None else config_dir() / "secrets"

    @property
    def directory(self) -> Path:
        return self._dir

    def _path(self, name: str) -> Path:
        if not _NAME.match(name):
            raise SecretError(
                f"not a usable secret name: {name!r}. Letters, digits, dot, "
                "dash and underscore only."
            )
        return self._dir / f"{name}.dpapi"

    # -- the operations ------------------------------------------------------

    def put(self, name: str, value: str) -> None:
        path = self._path(name)
        blob = _protect(value.encode("utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written directly rather than through a temp file: a partially written
        # secret is useless anyway, and a temp copy is one more place the
        # plaintext-adjacent ciphertext could be left behind.
        path.write_bytes(blob)

    def get(self, name: str) -> str:
        path = self._path(name)
        if not path.is_file():
            raise SecretError(f"no secret named {name!r} has been saved")
        return _unprotect(path.read_bytes()).decode("utf-8")

    def has(self, name: str) -> bool:
        try:
            return self._path(name).is_file()
        except SecretError:
            return False

    def delete(self, name: str) -> None:
        try:
            self._path(name).unlink(missing_ok=True)
        except SecretError:
            return

    def names(self) -> list[str]:
        """Which secrets exist. Never their values.

        This is what the settings screen lists, and what an agent may be told:
        knowing that a credential named `canvas_token` exists is not sensitive,
        and is enough for a tool to ask for it by name.
        """
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.dpapi"))
