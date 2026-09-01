"""Shared slowapi rate limiter keyed by client address.

``SlowAPIMiddleware`` in ``main.py`` runs this limiter on every request, so the
configured default applies to the whole API without per-route decorators.
Tighter caps on a single route still go on with ``@limiter.limit(...)``.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from core.config import get_settings


def default_limits(configured: str) -> list[str]:
    """Turn the configured limit expression into slowapi's default limits.

    An empty setting yields no limits at all, which leaves the middleware
    mounted but enforcing nothing — the escape hatch for deployments that
    already throttle at the gateway.
    """
    expression = configured.strip()
    return [expression] if expression else []


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=default_limits(get_settings().RATE_LIMIT_DEFAULT),
)
