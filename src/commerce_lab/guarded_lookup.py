"""History only. No catalog, creation service, locks or writes."""

import hashlib
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from commerce_lab.contracts import Checkout, ExecutionContext
from commerce_lab.contracts.creation_lookup import (
    LOOKUP_SCHEMA,
    RESPONSE_PROFILE,
    CreationFound,
    canonical_original_response,
    original_response_sha256,
)
from commerce_lab.contracts.guarded_creation import SCHEMA, GuardedProof, GuardedRejectionRecord
from commerce_lab.contracts.guarded_lookup import (
    GuardProofFound,
    GuardProofLookupInput,
    GuardProofLookupResult,
    GuardProofNotFound,
    GuardProofRejected,
    GuardProofUnrecoverable,
)
from commerce_lab.db import database_url


class GuardHistoryInvalid(RuntimeError):
    pass


def _guard_fingerprint(proof: GuardedProof) -> str:
    # Same published preimage as GuardedInput.fingerprint(), without inventing
    # an original request body (its field-presence fingerprint is stored).
    value = {
        "schema_version": SCHEMA,
        "offer_id": proof.offer_id,
        "expected_offer_revision": proof.accepted_offer_revision,
        "offer_snapshot_profile": proof.offer_snapshot_profile,
        "offer_snapshot_sha256": proof.accepted_offer_snapshot_sha256,
        "acp_create_fingerprint": proof.creation.acp_create_fingerprint,
    }
    return hashlib.sha256(
        b"merchant-guarded-acp-attempt/v1\0" + canonical_original_response(value)
    ).hexdigest()


class GuardProofLookup:
    def __init__(self, context: ExecutionContext):
        self.context = context

    def lookup(self, request: GuardProofLookupInput) -> GuardProofLookupResult:
        request = GuardProofLookupInput.model_validate(request.model_dump())
        scope = (UUID(self.context.run_id), self.context.actor_id, request.idempotency_key_sha256)
        with (
            psycopg.connect(database_url()) as connection,
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as db,
        ):
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            accepted = db.execute(
                "SELECT run_id::text,actor_id,idempotency_sha256,checkout_id,"
                "guard_fingerprint,proof,proof_sha256 FROM guarded_checkout_creations "
                "WHERE run_id=%s AND actor_id=%s AND idempotency_sha256=%s",
                scope,
            ).fetchone()
            rejected = db.execute(
                "SELECT run_id::text,actor_id,idempotency_sha256,guard_fingerprint,record,"
                "record_sha256 FROM rejected_guarded_checkout_attempts "
                "WHERE run_id=%s AND actor_id=%s AND idempotency_sha256=%s",
                scope,
            ).fetchone()
            checkout = db.execute(
                "SELECT run_id::text,actor_id,idempotency_sha256,checkout_id,"
                "acp_create_fingerprint,acp_create_response,create_snapshot "
                "FROM checkout_sessions WHERE run_id=%s AND actor_id=%s "
                "AND idempotency_sha256=%s",
                scope,
            ).fetchone()
        base = dict(
            run_id=str(scope[0]),
            actor_id=scope[1],
            idempotency_key_sha256=scope[2],
            request_id=self.context.request_id,
        )
        try:
            for row in (accepted, rejected, checkout):
                if row is not None and (
                    row["run_id"],
                    row["actor_id"],
                    row["idempotency_sha256"],
                ) != (str(scope[0]), scope[1], scope[2]):
                    raise ValueError("Scope mismatch")
            if checkout is not None:
                snapshot = Checkout.model_validate(checkout["create_snapshot"])
                if snapshot.id != checkout["checkout_id"] or snapshot.status != "prepared":
                    raise ValueError("Invalid original checkout snapshot")
                if (
                    checkout["acp_create_fingerprint"] is not None
                    or checkout["acp_create_response"] is not None
                ):
                    CreationFound.model_validate(
                        {
                            **base,
                            "schema_version": LOOKUP_SCHEMA,
                            "result": "found",
                            "acp_api_version": "2026-04-17",
                            "acp_create_fingerprint": checkout["acp_create_fingerprint"],
                            "checkout_id": checkout["checkout_id"],
                            "original_response": checkout["acp_create_response"],
                            "original_response_profile": RESPONSE_PROFILE,
                            "original_response_sha256": original_response_sha256(
                                checkout["acp_create_response"]
                            ),
                        }
                    )
            if accepted is not None:
                if rejected is not None or checkout is None:
                    raise ValueError("Contradictory accepted history")
                proof = GuardedProof.model_validate(accepted["proof"])
                snapshot = Checkout.model_validate(checkout["create_snapshot"])
                if (
                    proof.guard_fingerprint != accepted["guard_fingerprint"]
                    or proof.guard_fingerprint != _guard_fingerprint(proof)
                    or proof.creation.checkout_id != accepted["checkout_id"]
                    or proof.creation.checkout_id != checkout["checkout_id"]
                    or proof.creation.acp_create_fingerprint != checkout["acp_create_fingerprint"]
                    or proof.creation.original_response != checkout["acp_create_response"]
                    or snapshot.id != checkout["checkout_id"]
                    or snapshot.status != "prepared"
                    or snapshot.offer_id != proof.offer_id
                    or snapshot.offer_revision != proof.accepted_offer_revision
                    or snapshot.quantity != 1
                    or proof.creation.original_response["line_items"][0]["item"]["unit_amount"]
                    != snapshot.pricing.items_total_minor
                    or [
                        (t["type"], t["amount"]) for t in proof.creation.original_response["totals"]
                    ]
                    != [
                        ("subtotal", snapshot.pricing.items_total_minor),
                        ("fulfillment", snapshot.pricing.shipping_total_minor),
                        ("total", snapshot.pricing.total_minor),
                    ]
                ):
                    raise ValueError("Original creation binding mismatch")
                return GuardProofFound.model_validate(
                    {**base, "proof": proof, "proof_sha256": accepted["proof_sha256"]}
                )
            if rejected is not None:
                record = GuardedRejectionRecord.model_validate(rejected["record"])
                result = GuardProofRejected.model_validate(
                    {**base, "rejection": record, "rejection_sha256": rejected["record_sha256"]}
                )
                if record.guard_fingerprint != rejected["guard_fingerprint"]:
                    raise ValueError("Rejection fingerprint mismatch")
                if record.code == "guard_history_unavailable":
                    if checkout is None:
                        raise ValueError("Missing ordinary history")
                    return GuardProofUnrecoverable.model_validate(base)
                if checkout is not None:
                    raise ValueError("Rejected attempt has commerce history")
                return result
            if checkout is not None:
                return GuardProofUnrecoverable.model_validate(base)
            return GuardProofNotFound.model_validate(base)
        except Exception:
            raise GuardHistoryInvalid("Historical guard proof cannot be verified") from None
