"""DynamoDB single-table repository. See docs/ARCHITECTURE.md section 8."""

from jalsakshi.store.errors import ConflictError, NotFoundError, StoreError
from jalsakshi.store.records import ActivityEntry, CallSession
from jalsakshi.store.repo import Repository
from jalsakshi.store.table import TABLE_SPEC, create_table, create_table_kwargs

__all__ = [
    "TABLE_SPEC",
    "ActivityEntry",
    "CallSession",
    "ConflictError",
    "NotFoundError",
    "Repository",
    "StoreError",
    "create_table",
    "create_table_kwargs",
]
