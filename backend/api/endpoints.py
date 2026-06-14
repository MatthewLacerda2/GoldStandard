"""Compose the versioned API router.

Auth is attached per-router: the ``auth`` router is public, while ``users`` and
``items`` require a valid bearer token via ``get_current_user``.
"""

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from api.v1 import auth, items, users

api_router = APIRouter()

# Public.
api_router.include_router(auth.router)

# Protected.
api_router.include_router(users.router, dependencies=[Depends(get_current_user)])
api_router.include_router(items.router, dependencies=[Depends(get_current_user)])
