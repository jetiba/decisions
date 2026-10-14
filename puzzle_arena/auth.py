"""Shared Azure token cache so that authentication never lands inside a timed model call.

`DefaultAzureCredential` (az CLI) spawns a subprocess on every `get_token` (~330 ms), so tokens are
fetched once, refreshed ahead of expiry, and always off the event loop.
"""
import threading
import time

from azure.identity import DefaultAzureCredential

import config

_cred = DefaultAzureCredential()
_lock = threading.Lock()
_tok = None
_MARGIN_S = 600


def fresh() -> bool:
    return _tok is not None and _tok.expires_on - time.time() > _MARGIN_S


def token() -> str:
    """Blocking: call via asyncio.to_thread unless `fresh()` is true."""
    global _tok
    with _lock:
        if not fresh():
            _tok = _cred.get_token(config.TOKEN_SCOPE)
        return _tok.token
