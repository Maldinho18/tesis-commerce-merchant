import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, LiteralString, cast
from urllib.parse import urlparse
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from commerce_lab.contracts import Offer
from commerce_lab.fixtures import FIXTURE_NOW, fresh_p0_offers
from commerce_lab.settings import get_settings

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = (
    "001_preparation.sql",
    "002_snapshot_constraints.sql",
    "003_execution_context.sql",
    "004_checkout_sessions.sql",
    "007_checkout_mutations.sql",
    "008_checkout_payment_capability.sql",
)
FIXTURE_VERSION = "p0-catalog-v1"
PRODUCER = "preparation.db-seed"
ARTIFACT_PATH = ROOT / "artifacts" / "preparation" / "database-smoke.json"


class DatabaseNotReady(RuntimeError):
    pass


def database_url() -> str:
    value = get_settings().database_url
    parsed = urlparse(value)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Merchant requires a localhost database")
    if parsed.path != "/tesis_lab":
        raise ValueError("Merchant requires the tesis_lab database")
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fixture_snapshot() -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    offers = [offer.model_dump(mode="json") for offer in fresh_p0_offers()]
    offers.sort(key=lambda offer: str(offer["id"]))
    digest = hashlib.sha256(_canonical(offers).encode()).hexdigest()
    manifest = {
        "fixture_sha256": digest,
        "hash_format": "sorted-object-keys-json-v1",
        "offer_count": len(offers),
    }
    return offers, digest, manifest


def migrate() -> dict[str, object]:
    with psycopg.connect(database_url()) as connection, connection.transaction():
        for migration in MIGRATIONS:
            migration_sql = (ROOT / "migrations" / migration).read_text(encoding="utf-8")
            connection.execute(sql.SQL(cast(LiteralString, migration_sql)))
    return {"operation": "migrate", "migrations": list(MIGRATIONS), "status": "applied"}


def seed(actor_id: str = "preparation-fixture", variant: str = "preparation") -> dict[str, object]:
    run_id = uuid4()
    offers, fixture_hash, manifest = fixture_snapshot()
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute(
            """
                INSERT INTO experiment_runs
                  (run_id, scenario_id, variant, fixture_version, clock_at, manifest, actor_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
            (
                run_id,
                "PREP-01",
                variant,
                FIXTURE_VERSION,
                FIXTURE_NOW,
                Jsonb(manifest),
                actor_id,
            ),
        )
        for offer in offers:
            connection.execute(
                """
                    INSERT INTO catalog_offers (run_id, offer_id, revision, snapshot)
                    VALUES (%s, %s, %s, %s)
                    """,
                (run_id, offer["id"], offer["revision"], Jsonb(offer)),
            )
        connection.execute(
            """
                INSERT INTO run_events (run_id, event_type, producer, scenario_at, payload)
                VALUES (%s, %s, %s, %s, %s)
                """,
            (run_id, "fixture.loaded", PRODUCER, FIXTURE_NOW, Jsonb(manifest)),
        )

    artifact: dict[str, object] = {
        "scope": "Local synthetic database preparation; no checkout or payment",
        "run_id": str(run_id),
        "variant": variant,
        "fixture_version": FIXTURE_VERSION,
        "fixture_sha256": fixture_hash,
        "offer_count": len(offers),
        "seeded_at": datetime.now(UTC).isoformat(),
        "verifications": [],
        "persistence_across_restart_verified": False,
    }
    if variant == "preparation" and actor_id == "preparation-fixture":
        _save_artifact(artifact)
    return {
        "operation": "seed",
        "run_id": str(run_id),
        "offer_count": len(offers),
        "fixture_sha256": fixture_hash,
    }


def verify(run_id: str) -> dict[str, object]:
    parsed_run_id = UUID(run_id)
    expected_offers, fixture_hash, manifest = fixture_snapshot()
    with psycopg.connect(database_url()) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        run = connection.execute(
            """
                SELECT scenario_id, variant, fixture_version, clock_at, manifest
                FROM experiment_runs WHERE run_id = %s
                """,
            (parsed_run_id,),
        ).fetchone()
        if run is None:
            raise AssertionError("Run does not exist")
        scenario_id, variant, fixture_version, clock_at, stored_manifest = run
        if (
            scenario_id != "PREP-01"
            or variant != "preparation"
            or fixture_version != FIXTURE_VERSION
            or clock_at.isoformat().replace("+00:00", "Z") != FIXTURE_NOW
            or stored_manifest != manifest
        ):
            raise AssertionError("Run manifest or metadata differs from fixture")

        stored = connection.execute(
            """
                SELECT offer_id, revision, snapshot
                FROM catalog_offers WHERE run_id = %s ORDER BY offer_id
                """,
            (parsed_run_id,),
        ).fetchall()
        actual_offers: list[dict[str, Any]] = []
        for offer_id, revision, snapshot in stored:
            offer = Offer.model_validate(snapshot)
            if offer_id != offer.id or revision != offer.revision:
                raise AssertionError("Offer columns and snapshot disagree")
            actual_offers.append(offer.model_dump(mode="json"))
        if actual_offers != expected_offers:
            raise AssertionError("Persisted offer snapshots differ from fixtures")

        events = connection.execute(
            """
                SELECT event_id, producer, scenario_at, payload
                FROM run_events WHERE run_id = %s AND event_type = 'fixture.loaded'
                """,
            (parsed_run_id,),
        ).fetchall()
        if len(events) != 1:
            raise AssertionError("Exactly one fixture.loaded event is required")
        event_id, producer, scenario_at, event_payload = events[0]
        if (
            producer != PRODUCER
            or scenario_at.isoformat().replace("+00:00", "Z") != FIXTURE_NOW
            or event_payload != manifest
        ):
            raise AssertionError("Fixture event differs from expected evidence")
        server = connection.execute("SELECT pg_postmaster_start_time() AS started_at").fetchone()
        assert server is not None

    verification = {
        "verified_at": datetime.now(UTC).isoformat(),
        "server_started_at": server[0].isoformat(),
        "offer_count": len(stored),
        "fixture_sha256": fixture_hash,
        "fixture_event_id": str(event_id),
        "checks": {
            "snapshots_match": True,
            "run_matches": True,
            "fixture_event_matches": True,
        },
    }
    artifact = _load_compatible_artifact(run_id, fixture_hash, len(expected_offers))
    verifications = artifact["verifications"]
    assert isinstance(verifications, list)
    verifications.append(verification)
    starts = {item["server_started_at"] for item in verifications}
    artifact["persistence_across_restart_verified"] = len(starts) > 1
    _save_artifact(artifact)
    return {
        "operation": "verify",
        "run_id": run_id,
        "status": "passed",
        "persistence_across_restart_verified": artifact["persistence_across_restart_verified"],
        "artifact": str(ARTIFACT_PATH),
    }


def _load_compatible_artifact(run_id: str, fixture_hash: str, offer_count: int) -> dict[str, Any]:
    try:
        existing = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        if existing.get("run_id") == run_id and existing.get("fixture_sha256") == fixture_hash:
            return existing
    except FileNotFoundError:
        pass
    return {
        "scope": "Local synthetic database preparation; no checkout or payment",
        "run_id": run_id,
        "variant": "preparation",
        "fixture_version": FIXTURE_VERSION,
        "fixture_sha256": fixture_hash,
        "offer_count": offer_count,
        "verifications": [],
        "persistence_across_restart_verified": False,
    }


def _save_artifact(artifact: dict[str, object]) -> None:
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def check_database_ready() -> None:
    try:
        with psycopg.connect(database_url(), connect_timeout=2) as connection:
            row = connection.execute(
                """
                SELECT to_regclass('public.experiment_runs') IS NOT NULL AS runs,
                       to_regclass('public.catalog_offers') IS NOT NULL AS offers,
                       to_regclass('public.run_events') IS NOT NULL AS events,
                       to_regclass('public.lab_sessions') IS NOT NULL AS sessions,
                       to_regclass('public.checkout_sessions') IS NOT NULL AS checkouts,
                       to_regclass('public.checkout_mutations') IS NOT NULL AS checkout_mutations
                """
            ).fetchone()
            if row != (True, True, True, True, True, True):
                raise DatabaseNotReady("Required migrations are not applied")
    except (psycopg.Error, ValueError) as error:
        raise DatabaseNotReady("PostgreSQL is unavailable or not prepared") from error
