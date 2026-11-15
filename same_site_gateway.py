"""Same-host integration gateway for RAJ Enterprise + an existing FastAPI printing app.

Intended for a FUTURE deployment only after the original source has been
copied into this repository and audited. Never overwrites or modifies
the legacy application.

Public routing:
- /                -> existing printing application
- /api/...          -> existing printing application
- /enterprise/      -> new enterprise application
- /enterprise/api/  -> new enterprise APIs (including its isolated Cashfree webhook)
- /enterprise/s/... -> partner shop pages and QR

Do not enable on Render until the legacy application import target is available
and the route / database / payment smoke tests have passed.
"""
from __future__ import annotations

import importlib
import os
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount


RESERVED_PREFIX = "/enterprise"


def resolve_asgi(target: str) -> Any:
    """Import a named ASGI application, e.g. 'original_printing.main:app'."""
    if ":" not in target:
        raise ValueError("ASGI target must be 'python_module:attribute'")
    module_name, attribute = target.rsplit(":", 1)
    if not module_name or not attribute or attribute.startswith("_"):
        raise ValueError("Invalid ASGI import target")
    module = importlib.import_module(module_name)
    app = getattr(module, attribute)
    if not callable(app):
        raise TypeError("ASGI target is not callable")
    return app


def check_legacy_route_conflicts(legacy_app: Any):
    """Refuse to silently intercept any legacy route using /enterprise."""
    routes = getattr(legacy_app, "routes", None)
    if routes is None:
        raise TypeError("Legacy application must expose a FastAPI/Starlette route list")
    conflicting = []
    for route in routes:
        path = getattr(route, "path", "")
        if path == RESERVED_PREFIX or path.startswith(RESERVED_PREFIX + "/"):
            conflicting.append(path)
    if conflicting:
        raise ValueError("Existing app already uses reserved /enterprise routes: " + ", ".join(sorted(conflicting)))
    return True


def build_gateway(legacy_app: Any, enterprise_app: Any) -> Starlette:
    """Prioritize enterprise prefix; everything else passes to legacy ASGI."""
    if legacy_app is enterprise_app:
        raise ValueError("Legacy and enterprise apps must be different instances")
    check_legacy_route_conflicts(legacy_app)
    return Starlette(routes=[
        Mount(RESERVED_PREFIX, app=enterprise_app, name="enterprise"),
        Mount("/", app=legacy_app, name="legacy"),
    ])


def load_gateway_from_environment() -> Starlette:
    legacy = os.getenv("RAJ_LEGACY_ASGI", "").strip()
    enterprise = os.getenv("RAJ_ENTERPRISE_ASGI", "main:app").strip()
    if not legacy:
        raise RuntimeError(
            "RAJ_LEGACY_ASGI is required. Do not deploy the gateway until "
            "the ORIGINAL PRINTING APPLICATION SOURCE is available."
        )
    if legacy == enterprise:
        raise RuntimeError("RAJ_LEGACY_ASGI and RAJ_ENTERPRISE_ASGI cannot match")
    return build_gateway(resolve_asgi(legacy), resolve_asgi(enterprise))


# The ASGI entrypoint is deliberately fail-closed without an audited legacy app.
app = load_gateway_from_environment()
