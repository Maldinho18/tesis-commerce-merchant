"""Conditional admission in the same transaction as the original ACP creation."""

import hashlib
from datetime import UTC
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from commerce_lab.acp import ACPCheckoutAdapter
from commerce_lab.checkout_creation import lock_creation
from commerce_lab.contracts import ExecutionContext, Failure, Offer, parse_timestamp
from commerce_lab.contracts.creation_lookup import (
    LOOKUP_SCHEMA,
    RESPONSE_PROFILE,
    CreationFound,
    original_response_sha256,
)
from commerce_lab.contracts.guarded_creation import (
    SNAPSHOT_PROFILE,
    GuardedInput,
    GuardedProof,
    GuardedRejectionRecord,
    GuardedResult,
    offer_snapshot_sha256,
)
from commerce_lab.db import database_url


class GuardRejected(Exception):
    def __init__(self, code: str, *, historical: bool = False):
        self.code = code
        self.historical = historical
        super().__init__("Conditional creation rejected")


class GuardedCreation:
    def __init__(self, context: ExecutionContext):
        self.context = context

    def create(self, request: GuardedInput, key: str) -> GuardedResult:
        request = GuardedInput.model_validate(request.model_dump(mode="json", exclude_unset=True))
        if not 1 <= len(key) <= 255:
            raise GuardRejected("invalid_request")
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        run = UUID(self.context.run_id)
        with psycopg.connect(database_url()) as connection, connection.transaction():
            # Hold the episode clock stable in synthetic runs. Compatible shared
            # locks allow other creators, but not clock/catalog episode replacement.
            owned = connection.execute(
                "SELECT 1 FROM experiment_runs WHERE run_id=%s AND actor_id=%s FOR SHARE",
                (run, self.context.actor_id),
            ).fetchone()
            if owned is None:
                raise GuardRejected("offer_invalid")
            lock_creation(connection, run, self.context.actor_id, key_hash)
            rejected = connection.execute(
                "SELECT guard_fingerprint,record,record_sha256 "
                "FROM rejected_guarded_checkout_attempts "
                "WHERE run_id=%s AND actor_id=%s AND idempotency_sha256=%s",
                (run, self.context.actor_id, key_hash),
            ).fetchone()
            failure = None
            result = None
            if rejected is not None:
                record = GuardedRejectionRecord.model_validate(rejected[1])
                if (
                    record.digest() != rejected[2]
                    or record.guard_fingerprint != rejected[0]
                    or record.run_id != str(run)
                    or record.actor_id != self.context.actor_id
                    or record.idempotency_sha256 != key_hash
                ):
                    raise RuntimeError("Rejected attempt integrity failure")
                failure = (
                    GuardRejected(record.code, historical=True)
                    if request.fingerprint() == rejected[0]
                    else GuardRejected("idempotency_conflict")
                )
            else:
                try:
                    # A known rejection commits only its immutable attempt identity;
                    # every provisional checkout/evidence write is rolled back.
                    with connection.transaction():
                        result = self._execute(request, key, key_hash, run, connection)
                except GuardRejected as error:
                    failure = error
                    accepted = connection.execute(
                        "SELECT 1 FROM guarded_checkout_creations WHERE run_id=%s AND actor_id=%s "
                        "AND idempotency_sha256=%s",
                        (run, self.context.actor_id, key_hash),
                    ).fetchone()
                    if accepted is None and error.code != "idempotency_conflict":
                        record = GuardedRejectionRecord.model_validate(
                            {
                                "run_id": str(run),
                                "actor_id": self.context.actor_id,
                                "idempotency_sha256": key_hash,
                                "guard_fingerprint": request.fingerprint(),
                                "code": error.code,
                            }
                        )
                        connection.execute(
                            "INSERT INTO rejected_guarded_checkout_attempts "
                            "(run_id,actor_id,idempotency_sha256,guard_fingerprint,"
                            "record,record_sha256) "
                            "VALUES (%s,%s,%s,%s,%s,%s)",
                            (
                                run,
                                self.context.actor_id,
                                key_hash,
                                record.guard_fingerprint,
                                Jsonb(record.model_dump(mode="json")),
                                record.digest(),
                            ),
                        )
        if failure is not None:
            raise failure
        assert result is not None
        return result

    def _execute(self, request, key, key_hash, run, connection):
        adapter = ACPCheckoutAdapter(self.context)
        old = connection.execute(
            "SELECT guard_fingerprint,proof,proof_sha256 FROM guarded_checkout_creations "
            "WHERE run_id=%s AND actor_id=%s AND idempotency_sha256=%s FOR UPDATE",
            (run, self.context.actor_id, key_hash),
        ).fetchone()
        if old is not None:
            if old[0] != request.fingerprint():
                raise GuardRejected("idempotency_conflict")
            proof = GuardedProof.model_validate(old[1])
            if (
                proof.digest() != old[2]
                or proof.guard_fingerprint != old[0]
                or proof.offer_id != request.offer_id
                or proof.accepted_offer_revision != request.expected_offer_revision
                or proof.accepted_offer_snapshot_sha256 != request.offer_snapshot_sha256
                or proof.creation.run_id != str(run)
                or proof.creation.actor_id != self.context.actor_id
                or proof.creation.idempotency_key_sha256 != key_hash
                or proof.creation.acp_create_fingerprint != request.acp_fingerprint()
            ):
                raise RuntimeError("Historical proof integrity failure")
            original = adapter._existing_creation(connection, key_hash, request.acp_fingerprint())
            if original != proof.creation.original_response:
                raise RuntimeError("Historical ACP binding failure")
            return GuardedResult(result="replayed", request_id=self.context.request_id, proof=proof)
        # An existing unguarded or internal operation cannot acquire a guard retroactively.
        existing = connection.execute(
            "SELECT 1 FROM checkout_sessions WHERE run_id=%s AND actor_id=%s "
            "AND idempotency_sha256=%s",
            (run, self.context.actor_id, key_hash),
        ).fetchone()
        if existing is not None:
            raise GuardRejected("guard_history_unavailable")
        accepted: Offer | None = None

        def commercial_now():
            row = connection.execute(
                "SELECT CASE WHEN variant='merchant' THEN clock_timestamp() ELSE clock_at END "
                "FROM experiment_runs WHERE run_id=%s AND actor_id=%s",
                (run, self.context.actor_id),
            ).fetchone()
            if row is None:
                raise GuardRejected("offer_invalid")
            return row[0].astimezone(UTC)

        def time_check(offer: Offer):
            now = commercial_now()
            if parse_timestamp(offer.observed_at) > now:
                raise GuardRejected("offer_invalid")
            if now >= parse_timestamp(offer.expires_at):
                raise GuardRejected("offer_expired")
            return now.strftime("%Y-%m-%dT%H:%M:%SZ")

        def check(offer: Offer) -> None:
            nonlocal accepted
            if offer.id != request.offer_id:
                raise GuardRejected("offer_invalid")
            if offer.revision != request.expected_offer_revision:
                raise GuardRejected("offer_revision_mismatch")
            if offer_snapshot_sha256(offer) != request.offer_snapshot_sha256:
                raise GuardRejected("offer_snapshot_mismatch")
            if offer.product_status != "active":
                raise GuardRejected("product_inactive")
            if offer.availability != "in_stock" or offer.available_quantity < 1:
                raise GuardRejected("out_of_stock")
            time_check(offer)
            accepted = offer

        original = adapter.create_in_transaction(
            request.acp_request,
            key,
            connection=connection,
            check_offer=check,
        )
        if isinstance(original, Failure):
            code = {
                "OFFER_NOT_FOUND": "offer_not_found",
                "OFFER_EXPIRED": "offer_expired",
                "OUT_OF_STOCK": "out_of_stock",
                "OFFER_REVISION_MISMATCH": "offer_revision_mismatch",
            }.get(original.error.code, "offer_invalid")
            raise GuardRejected(code)
        if accepted is None:
            raise RuntimeError("Guard did not run before creation")
        creation = CreationFound(
            schema_version=LOOKUP_SCHEMA,
            result="found",
            run_id=str(run),
            actor_id=self.context.actor_id,
            request_id=self.context.request_id,
            idempotency_key_sha256=key_hash,
            acp_api_version="2026-04-17",
            acp_create_fingerprint=request.acp_fingerprint(),
            checkout_id=original["id"],
            original_response=original,
            original_response_profile=RESPONSE_PROFILE,
            original_response_sha256=original_response_sha256(original),
        )
        proof = GuardedProof(
            offer_id=accepted.id,
            accepted_offer_revision=accepted.revision,
            offer_snapshot_profile=SNAPSHOT_PROFILE,
            accepted_offer_snapshot_sha256=offer_snapshot_sha256(accepted),
            guard_fingerprint=request.fingerprint(),
            checked_at=time_check(accepted),
            creation=creation,
        )
        self._persist(connection, run, key_hash, proof)
        # Avoid PostgreSQL now()'s transaction-start time after a lock wait.
        # This is validation time, not a promise about wall time after commit.
        time_check(accepted)
        return GuardedResult(result="created", request_id=self.context.request_id, proof=proof)

    def _persist(
        self, connection: psycopg.Connection[Any], run: UUID, key_hash: str, proof: GuardedProof
    ) -> None:
        connection.execute(
            "INSERT INTO guarded_checkout_creations "
            "(run_id,actor_id,idempotency_sha256,checkout_id,guard_fingerprint,proof,proof_sha256) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                run,
                self.context.actor_id,
                key_hash,
                proof.creation.checkout_id,
                proof.guard_fingerprint,
                Jsonb(proof.model_dump(mode="json")),
                proof.digest(),
            ),
        )
