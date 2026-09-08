"""HTTP hardening helpers."""
from __future__ import annotations

import os
from flask import request

ESPN_EXTENSION_ID = os.getenv("ESPN_EXTENSION_ID", "").strip()

def extension_identity_ok():
    """Require the packaged extension identity when configured on Render.

    The header is not a secret; rate limiting remains the abuse-control boundary.
    Its purpose is to reject accidental/non-extension traffic and make origin policy explicit.
    """
    if not ESPN_EXTENSION_ID:
        return True
    return request.headers.get("X-FCC-Extension-ID", "").strip() == ESPN_EXTENSION_ID
