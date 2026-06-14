"""Business logic layer.

Logic that is neither a thin handler nor pure data access lives here. Services
orchestrate one or more repositories and may be called by handlers. They take an
``AsyncSession`` and never open their own session, so the test rollback works.

This package is an intentional placeholder for the ``items`` skeleton, which is
simple enough to need no service layer.
"""
