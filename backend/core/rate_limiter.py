"""Shared slowapi rate limiter keyed by client address."""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Default limits can be applied per-route with `@limiter.limit(...)`.
limiter = Limiter(key_func=get_remote_address)
