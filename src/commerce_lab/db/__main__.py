import argparse
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from commerce_lab.checkout import CheckoutService
from commerce_lab.context import issue_lab_session
from commerce_lab.contracts import ExecutionContext
from commerce_lab.db import migrate, seed, verify
from commerce_lab.webhook_delivery import WebhookDispatcher


def _jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[attr-defined]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m commerce_lab.db")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("--actor-id", default="preparation-fixture")
    seed_parser.add_argument(
        "--variant", choices=("preparation", "B0", "B1", "B2"), default="preparation"
    )
    session_parser = subparsers.add_parser("issue-session")
    session_parser.add_argument("run_id")
    session_parser.add_argument("actor_id")
    session_parser.add_argument("--ttl-seconds", type=int, default=3600)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("run_id")
    update_parser = subparsers.add_parser("order-update")
    update_parser.add_argument("run_id")
    update_parser.add_argument("actor_id")
    update_parser.add_argument("order_id")
    dispatch_parser = subparsers.add_parser("webhook-dispatch")
    dispatch_parser.add_argument("--limit", type=int, default=1)
    arguments = parser.parse_args()
    if arguments.command == "migrate":
        result = migrate()
    elif arguments.command == "seed":
        result = seed(actor_id=arguments.actor_id, variant=arguments.variant)
    elif arguments.command == "issue-session":
        result = {
            "operation": "issue-session",
            "run_id": arguments.run_id,
            "actor_id": arguments.actor_id,
            "session_token": issue_lab_session(
                arguments.run_id, arguments.actor_id, arguments.ttl_seconds
            ),
            "warning": "Synthetic local credential; do not commit or copy to artifacts.",
        }
    elif arguments.command == "order-update":
        context = ExecutionContext(
            run_id=arguments.run_id,
            actor_id=arguments.actor_id,
            request_id=str(uuid4()),
            received_at=datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        result = CheckoutService(context).update_order_status(arguments.order_id)
    elif arguments.command == "webhook-dispatch":
        result = WebhookDispatcher().dispatch_due(limit=arguments.limit)
    else:
        result = verify(arguments.run_id)
    print(json.dumps(_jsonable(result), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = re.sub(r"postgres(?:ql)?://[^\s]+", "[database URL redacted]", str(error))
        raise SystemExit(message) from None
