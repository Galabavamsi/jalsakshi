"""Errors raised by the DynamoDB repository."""

from __future__ import annotations


class StoreError(Exception):
    """Base class for repository errors."""


class ConflictError(StoreError):
    """A conditional write lost a race: the caller's copy is stale. Reload and retry."""


class NotFoundError(StoreError, LookupError):
    """The item to update does not exist."""
