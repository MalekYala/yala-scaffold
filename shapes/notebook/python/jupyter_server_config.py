"""Jupyter server configuration for the notebook container."""

from __future__ import annotations

import os
from typing import Any

c: Any = get_config()  # type: ignore[name-defined]  # noqa: F821

c.ServerApp.ip = "0.0.0.0"
c.ServerApp.port = int(os.environ["PORT"])
c.ServerApp.open_browser = False
c.IdentityProvider.token = os.environ.get("JUPYTER_TOKEN", "")
c.PasswordIdentityProvider.hashed_password = ""
