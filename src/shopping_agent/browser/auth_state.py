"""Keep session cookies across Chromium restarts without exposing them in APIs.

Chromium's persistent profile handles origin storage and persistent cookies.
Session cookies need an explicit handoff; on Windows the handoff is encrypted
with DPAPI for the current OS user, inside the same local browser profile.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path


STATE_NAME = "shopping-session.dpapi"


def _protect(payload: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Encrypted browser session persistence requires Windows.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    source_buffer = ctypes.create_string_buffer(payload)
    source = Blob(len(payload), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    operation.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError("Unable to protect or restore the local browser session.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


async def save_session_cookies(context, profile_dir: Path) -> None:
    # Other platforms retain their previous profile-only behavior.
    if os.name != "nt":
        return
    cookies = [cookie for cookie in await context.cookies() if cookie.get("expires", -1) == -1]
    encrypted = _protect(json.dumps(cookies, separators=(",", ":")).encode("utf-8"))
    target = profile_dir / STATE_NAME
    pending = target.with_suffix(".tmp")
    pending.write_bytes(encrypted)
    pending.replace(target)


async def restore_session_cookies(context, profile_dir: Path) -> None:
    target = profile_dir / STATE_NAME
    if os.name != "nt" or not target.exists():
        return
    try:
        cookies = json.loads(_protect(target.read_bytes(), decrypt=True))
    except (OSError, ValueError):
        # A damaged file or profile copied from a different Windows user cannot
        # authenticate. Leave it intact and allow normal manual login instead.
        return
    if not isinstance(cookies, list) or not all(isinstance(cookie, dict) for cookie in cookies):
        return
    if cookies:
        await context.add_cookies(cookies)
