"""One scoped SELECT in a PostgreSQL read-only transaction; no commerce adapter."""

from uuid import UUID

import psycopg

from commerce_lab.contracts import ExecutionContext
from commerce_lab.contracts.creation_lookup import (
    LOOKUP_SCHEMA,
    RESPONSE_PROFILE,
    CreationFound,
    CreationLookupInput,
    CreationLookupResult,
    CreationNotFound,
    CreationUnrecoverable,
    original_response_sha256,
)
from commerce_lab.db import database_url


class LookupIntegrityError(RuntimeError):
    pass


class CheckoutCreationLookup:
    def __init__(self, context: ExecutionContext):
        self.context = context

    def lookup(self, request: CreationLookupInput) -> CreationLookupResult:
        request = CreationLookupInput.model_validate(request.model_dump())
        run_id = UUID(self.context.run_id)
        with psycopg.connect(database_url()) as connection, connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            row = connection.execute(
                "SELECT run_id,actor_id,idempotency_sha256,checkout_id,"
                "acp_create_fingerprint,acp_create_response FROM checkout_sessions "
                "WHERE run_id=%s AND actor_id=%s AND idempotency_sha256=%s",
                (run_id, self.context.actor_id, request.idempotency_key_sha256),
            ).fetchone()
        base = dict(
            schema_version=LOOKUP_SCHEMA,
            run_id=str(run_id),
            actor_id=self.context.actor_id,
            idempotency_key_sha256=request.idempotency_key_sha256,
            request_id=self.context.request_id,
        )
        if row is None:
            return CreationNotFound.model_validate({**base, "result": "not_found"})
        try:
            if tuple(row[:3]) != (run_id, self.context.actor_id, request.idempotency_key_sha256):
                raise ValueError("Scope mismatch")
            if row[4] is None and row[5] is None:
                return CreationUnrecoverable.model_validate({**base, "result": "unrecoverable"})
            return CreationFound.model_validate(
                {
                    **base,
                    "result": "found",
                    "acp_api_version": "2026-04-17",
                    "acp_create_fingerprint": row[4],
                    "checkout_id": row[3],
                    "original_response": row[5],
                    "original_response_profile": RESPONSE_PROFILE,
                    "original_response_sha256": original_response_sha256(row[5]),
                }
            )
        except Exception:
            raise LookupIntegrityError("Historical creation cannot be verified") from None
