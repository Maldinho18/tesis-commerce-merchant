from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from commerce_lab.catalog import CatalogReader
from commerce_lab.contracts import (
    CatalogSearchData,
    CatalogSearchInput,
    ExecutionContext,
    Failure,
    Offer,
    OfferGetInput,
    ScenarioClock,
    Success,
)
from commerce_lab.db import database_url


class PersistentCatalogReader:
    """Catalog reads scoped by a trusted execution context and recorded as evidence."""

    def __init__(self, context: ExecutionContext) -> None:
        self._context = context

    def search(self, raw: object) -> Success[CatalogSearchData]:
        payload = CatalogSearchInput.model_validate(raw)
        with psycopg.connect(database_url()) as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            reader, scenario_at = self._load_reader(connection)
            result = reader.search(payload)
            self._record(
                connection,
                event_type="catalog.searched",
                scenario_at=scenario_at,
                payload={
                    "request_id": self._context.request_id,
                    "actor_id": self._context.actor_id,
                    "received_at": self._context.received_at,
                    "offer_ids": [offer.id for offer in result.data.offers],
                    "next_offset": result.data.next_offset,
                },
            )
        return result

    def get(self, raw: object) -> Success[Offer] | Failure:
        payload = OfferGetInput.model_validate(raw)
        with psycopg.connect(database_url()) as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            reader, scenario_at = self._load_reader(connection)
            result = reader.get(payload)
            self._record(
                connection,
                event_type="offer.read",
                scenario_at=scenario_at,
                payload={
                    "request_id": self._context.request_id,
                    "actor_id": self._context.actor_id,
                    "received_at": self._context.received_at,
                    "offer_id": payload.offer_id,
                    "result": result.error.code if isinstance(result, Failure) else "ok",
                },
            )
        return result

    def _load_reader(self, connection: psycopg.Connection[Any]) -> tuple[CatalogReader, str]:
        run = connection.execute(
            """
            SELECT CASE WHEN variant = 'merchant' THEN date_trunc('second', now()) ELSE clock_at END
            FROM experiment_runs
            WHERE run_id = %s AND actor_id = %s
            """,
            (UUID(self._context.run_id), self._context.actor_id),
        ).fetchone()
        if run is None:
            raise PermissionError("Execution context does not own the episode")
        rows = connection.execute(
            """
            SELECT snapshot
            FROM catalog_offers
            WHERE run_id = %s
            ORDER BY offer_id
            """,
            (UUID(self._context.run_id),),
        ).fetchall()
        offers = [Offer.model_validate(row[0]) for row in rows]
        scenario_at = run[0].isoformat().replace("+00:00", "Z")
        return CatalogReader(offers, ScenarioClock(scenario_at)), scenario_at

    def _record(
        self,
        connection: psycopg.Connection[Any],
        *,
        event_type: str,
        scenario_at: str,
        payload: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO run_events (run_id, event_type, producer, scenario_at, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                UUID(self._context.run_id),
                event_type,
                "commerce_lab.persistent_catalog",
                scenario_at,
                Jsonb(payload),
            ),
        )
