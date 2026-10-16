"""Opt-in standalone validation runner. Own new cluster; never use a developer DSN."""

import io
import json
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PG = Path("C:/Program Files/PostgreSQL/17/bin")


def main():
    if os.environ.get("RUN_MER07_REAL") != "1":
        raise RuntimeError("Explicit RUN_MER07_REAL=1 required")
    for key in list(os.environ):
        if key.startswith(
            ("OPENAI_", "PAYMENT_", "MERCHANT_", "PG", "LANGSMITH_", "RUN_")
        ) or key in {
            "DATABASE_URL",
            "WEBHOOK_RECEIVER_URL",
            "ACP_API_BASE_URL",
            "STOREFRONT_ORIGIN",
        }:
            os.environ.pop(key)
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    prefix = "mer07a2-" if "--guard-lookup" in sys.argv else "mer07-"
    root = ROOT / ".local" / (prefix + secrets.token_hex(6))
    root.mkdir(parents=True, exist_ok=False)
    data = root / "pgdata"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert port not in {55432, 55433, 62281, 4120}
    os.environ.update(
        DATABASE_URL=f"postgresql://mer07_app:{secrets.token_hex(20)}@127.0.0.1:{port}/tesis_lab",
        RECOVERY_TEST_CLUSTER=str(data),
        RUN_DB_INTEGRATION="1",
        PGCONNECT_TIMEOUT="10" if "--guard-lookup" in sys.argv else "2",
    )

    def command(name, *args):
        prefix = root / ("pg-" + secrets.token_hex(4))
        with (
            prefix.with_suffix(".out").open("wb") as out,
            prefix.with_suffix(".err").open("wb") as err,
        ):
            result = subprocess.run(
                [str(PG / name), *map(str, args)],
                stdout=out,
                stderr=err,
                timeout=40,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if result.returncode:
            raise RuntimeError("Owned PostgreSQL command failed")
        return prefix.with_suffix(".out").read_text(encoding="utf-8", errors="replace").strip()

    def psql(sql):
        return command(
            "psql.exe",
            "-X",
            "-qAt",
            "-h",
            "127.0.0.1",
            "-p",
            port,
            "-U",
            "mer07_admin",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        )

    evidence = {
        "root": str(root),
        "data_directory": str(data),
        "pg_port": port,
        "postgres": command("postgres.exe", "--version"),
        "python": sys.version.split()[0],
        "pg_connect_timeout_s": int(os.environ["PGCONNECT_TIMEOUT"]),
    }
    started = False
    try:
        command(
            "initdb.exe",
            "-D",
            data,
            "-U",
            "mer07_admin",
            "-A",
            "trust",
            "--encoding=UTF8",
            "--no-locale",
        )
        (data / "pg_hba.conf").write_text(
            "host all mer07_admin 127.0.0.1/32 trust\n"
            "host tesis_lab mer07_app 127.0.0.1/32 trust\n",
            encoding="utf-8",
        )
        with (data / "postgresql.conf").open("a", encoding="utf-8") as f:
            f.write("\ntimezone='UTC'\nlog_timezone='UTC'\n")
        started = True
        command(
            "pg_ctl.exe",
            "-D",
            data,
            "-l",
            root / "postgres.log",
            "-o",
            f"-h 127.0.0.1 -p {port}",
            "-w",
            "start",
        )
        metadata = json.loads(
            psql(
                "SELECT json_build_array(current_database(),current_user,"
                "host(inet_server_addr()),inet_server_port(),current_setting('data_directory'))"
            )
        )
        assert metadata[:4] == ["postgres", "mer07_admin", "127.0.0.1", port]
        assert Path(metadata[4]).resolve() == data.resolve()
        psql("CREATE ROLE mer07_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
        psql("CREATE DATABASE tesis_lab OWNER mer07_app")
        psql("GRANT pg_read_all_settings TO mer07_app")
        from commerce_lab.settings import Settings, get_settings

        Settings.model_config["env_file"] = None
        get_settings.cache_clear()
        import psycopg

        original_connect = psycopg.connect
        dsn = os.environ["DATABASE_URL"]

        def connect(*args, **kwargs):
            if not args or args[0] != dsn:
                raise RuntimeError("Refuse another DSN")
            db = original_connect(*args, **kwargs)
            row = db.execute(
                "SELECT current_database(),current_user,host(inet_server_addr()),"
                "inet_server_port(),current_setting('data_directory')"
            ).fetchone()
            if (
                row is None
                or tuple(row[:4]) != ("tesis_lab", "mer07_app", "127.0.0.1", port)
                or (Path(row[4]).resolve() != data.resolve())
            ):
                db.close()
                raise RuntimeError("Refuse another cluster identity")
            db.rollback()
            return db

        psycopg.connect = connect
        with psycopg.connect(dsn) as db:
            empty = db.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
            ).fetchone()
            assert empty is not None and empty[0] == 0
        # No repo writes, operational sockets or unowned listeners in the test process.
        bound = {port}
        real_bind = socket.socket.bind

        def bind(sock, address):
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
                raise RuntimeError("Refuse non-loopback bind")
            result = real_bind(sock, address)
            bound.add(sock.getsockname()[1])
            return result

        socket.socket.bind = bind

        def audit(event, args):
            if event == "socket.connect":
                address = args[1]
                if (
                    not isinstance(address, tuple)
                    or address[0] not in {"127.0.0.1", "localhost", "::1"}
                    or address[1] not in bound
                ):
                    raise RuntimeError("Refuse operational/external socket")
            if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
                mode, flags = args[1:3]
                writing = (isinstance(mode, str) and any(x in mode for x in "wax+")) or (
                    isinstance(flags, int)
                    and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
                )
                path = Path(os.fsdecode(args[0])).resolve()
                if (
                    writing
                    and (
                        path.is_relative_to(ROOT)
                        or path.is_relative_to(ROOT.parent / "tesis-commerce-agent")
                    )
                    and not path.is_relative_to(root)
                ):
                    raise RuntimeError("Refuse historical repository write")

        sys.addaudithook(audit)
        from importlib.metadata import version

        import pytest

        evidence["versions"] = {
            p: version(p) for p in ["psycopg", "fastapi", "httpx", "pydantic", "pytest"]
        }
        evidence["phases"] = []

        class Counts:
            def __init__(self):
                self.summary: dict[str, Any] = {
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "warnings": [],
                    "failures": [],
                }

            def pytest_runtest_logreport(self, report):
                if report.failed:
                    self.summary["failed"] += 1
                    crash = getattr(report.longrepr, "reprcrash", None)
                    self.summary["failures"].append(
                        {
                            "nodeid": report.nodeid,
                            "line": getattr(crash, "lineno", None),
                            "type": str(getattr(crash, "message", "unknown")).split(":", 1)[0],
                        }
                    )
                elif report.skipped:
                    self.summary["skipped"] += 1
                elif report.when == "call" and report.passed:
                    self.summary["passed"] += 1

            def pytest_warning_recorded(self, warning_message, when, nodeid, location):
                self.summary["warnings"].append(
                    {
                        "category": warning_message.category.__name__,
                        "file": Path(warning_message.filename).name,
                        "line": warning_message.lineno,
                    }
                )

        import time

        plan = [
            ("fresh_migrations", ["tests/integration/test_migration_tracking.py"]),
            (
                "new_and_acp_regressions",
                [
                    "tests/test_guarded_contract.py",
                    "tests/integration/test_guarded_creation.py",
                    "tests/test_acp_creation.py",
                    "tests/test_creation_lookup.py",
                    "tests/integration/test_acp_creation_recovery.py",
                    "tests/integration/test_acp_creation_lookup.py",
                ],
            ),
            ("full", []),
        ]
        if "--guard-lookup" in sys.argv:
            if "--full-only" in sys.argv:
                plan = [plan[0], plan[-1]]
            else:
                plan.insert(
                    1,
                    (
                        "guard_lookup_new",
                        [
                            "tests/test_guarded_lookup_contract.py",
                            "tests/integration/test_guarded_lookup.py",
                        ],
                    ),
                )
        elif "--key-audit" in sys.argv:
            plan = [
                plan[0],
                (
                    "rejected_key_identity",
                    [
                        "tests/integration/test_guarded_creation.py",
                        "-k",
                        "rejected_attempt_cannot_change_condition_under_same_key",
                    ],
                ),
            ]
        elif "--focused" in sys.argv:
            plan = [
                plan[0],
                (
                    "final_new_tests",
                    [
                        "tests/test_guarded_contract.py",
                        "tests/integration/test_guarded_creation.py",
                    ],
                ),
            ]
        elif "--full-only" in sys.argv:
            plan = [plan[0], plan[-1]]
        for label, paths in plan:
            counts = Counts()
            stamp = time.perf_counter()
            with (
                __import__("contextlib").redirect_stdout(io.StringIO()),
                __import__("contextlib").redirect_stderr(io.StringIO()),
            ):
                code = pytest.main(
                    [
                        *paths,
                        "-q",
                        "--assert=plain",
                        "--tb=short",
                        "-p",
                        "no:cacheprovider",
                        "--basetemp=" + str(root / ("pytest-" + label)),
                    ],
                    plugins=[counts],
                )
            record = {
                "phase": label,
                **counts.summary,
                "duration_s": time.perf_counter() - stamp,
                "exit_code": int(code),
            }
            evidence["phases"].append(record)
            (root / "validation.json").write_text(json.dumps(evidence), encoding="utf-8")
            print(json.dumps(record), flush=True)
            if code:
                raise RuntimeError("Validation phase failed")
        with psycopg.connect(dsn) as db:
            rows = db.execute(
                "SELECT version,sha256 FROM schema_migrations ORDER BY version"
            ).fetchall()
            evidence["migrations"] = rows
    finally:
        if started:
            command("pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop")
        with socket.socket() as probe:
            probe.settimeout(0.2)
            evidence["postgres_port_closed"] = probe.connect_ex(("127.0.0.1", port)) != 0
        (root / "validation.json").write_text(json.dumps(evidence), encoding="utf-8")
        print("Evidence: " + str(root), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("MER07_RUNNER_FAILED:" + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
