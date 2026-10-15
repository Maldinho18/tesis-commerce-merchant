"""Transaction-scoped serialization shared by internal and ACP creation paths."""

import hashlib
import json
from typing import Any
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus


def lock_creation(
    connection: psycopg.Connection[Any], run_id: UUID, actor_id: str, key_hash: str
) -> None:
    if connection.info.transaction_status != TransactionStatus.INTRANS:
        raise RuntimeError("Checkout creation requires a caller-owned transaction")
    scope = json.dumps(
        ["checkout-create/v1", str(run_id), actor_id, key_hash], separators=(",", ":")
    )
    lock_id = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], signed=True)
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
