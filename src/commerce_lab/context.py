import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg

from commerce_lab.contracts import ExecutionContext
from commerce_lab.db import database_url


class InvalidLabSession(ValueError):
    """Raised when a synthetic lab credential is absent, expired, or revoked."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue_lab_session(run_id: str, actor_id: str, ttl_seconds: int = 3600) -> str:
    """Issue a synthetic bearer credential; only its hash is persisted."""

    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise ValueError("Session TTL must be a positive integer")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    with psycopg.connect(database_url()) as connection, connection.transaction():
        inserted = connection.execute(
            """
            INSERT INTO lab_sessions (session_sha256, run_id, actor_id, expires_at)
            SELECT %s, run_id, actor_id, %s
            FROM experiment_runs
            WHERE run_id = %s AND actor_id = %s
            RETURNING session_sha256
            """,
            (_sha256(token), expires_at, UUID(run_id), actor_id),
        ).fetchone()
    if inserted is None:
        raise ValueError("Run and actor do not identify an existing lab episode")
    return token


def authenticate_lab_session(token: str) -> ExecutionContext:
    """Resolve server-controlled identity and episode context from a bearer credential."""

    if not token or len(token) > 512:
        raise InvalidLabSession("Invalid lab session")
    with psycopg.connect(database_url()) as connection, connection.transaction():
        row = connection.execute(
            """
            SELECT session.run_id, session.actor_id
            FROM lab_sessions AS session
            JOIN experiment_runs AS run
              ON run.run_id = session.run_id AND run.actor_id = session.actor_id
            WHERE session.session_sha256 = %s
              AND session.revoked_at IS NULL
              AND session.expires_at > now()
            """,
            (_sha256(token),),
        ).fetchone()
    if row is None:
        raise InvalidLabSession("Invalid lab session")
    run_id, actor_id = row
    return ExecutionContext(
        actor_id=actor_id,
        run_id=str(run_id),
        request_id=str(uuid4()),
        received_at=_timestamp(datetime.now(UTC)),
    )
