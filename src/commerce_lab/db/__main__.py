import argparse
import json
import re

from commerce_lab.context import issue_lab_session
from commerce_lab.db import migrate, seed, verify


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
    else:
        result = verify(arguments.run_id)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = re.sub(r"postgres(?:ql)?://[^\s]+", "[database URL redacted]", str(error))
        raise SystemExit(message) from None
