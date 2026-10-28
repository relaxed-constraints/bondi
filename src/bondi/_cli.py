"""Command-line adapter for the deployment API (no extra CLI dependencies)."""

import argparse
import os
import sys

from bondi.deployment import deploy_couchbase, deploy_mongodb, get_deployment, list_deployments


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bondi", description="Manage local research databases with Docker Compose."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    deploy = commands.add_parser("deploy", help="Create/start a database and wait for readiness")
    backends = deploy.add_subparsers(dest="backend", required=True)
    mongo = backends.add_parser("mongodb", help="Deploy MongoDB")
    mongo.add_argument("--name", default="mongodb")
    mongo.add_argument("--port", type=int, default=27017)
    mongo.add_argument("--timeout", type=float, default=120)
    couchbase = backends.add_parser("couchbase", help="Deploy and initialize Couchbase")
    couchbase.add_argument("--name", default="couchbase")
    couchbase.add_argument("--management-port", type=int, default=8091)
    couchbase.add_argument("--query-port", type=int, default=8093)
    couchbase.add_argument("--kv-port", type=int, default=11210)
    couchbase.add_argument("--edition", choices=["community", "enterprise"], default="community")
    couchbase.add_argument("--username", default="Administrator")
    couchbase.add_argument("--password-env", help="Read password from this environment variable")
    couchbase.add_argument("--bucket", default="demo")
    couchbase.add_argument("--timeout", type=float, default=300)
    for name, help_text in (
        ("start", "Start a saved deployment and wait for readiness"),
        ("stop", "Stop a deployment, retaining data"),
        ("remove", "Remove a deployment and its data (asks for confirmation)"),
        ("status", "Show a deployment's current state and URI"),
        ("logs", "Show recent database logs"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("name", help="Saved deployment name")
        if name in {"start", "stop", "remove"}:
            command.add_argument(
                "--timeout",
                type=float,
                default=120,
                help="Operation deadline in seconds (default: 120)",
            )
        if name == "remove":
            command.add_argument(
                "--keep-data",
                action="store_true",
                help="Retain data volume and configuration for a later start",
            )
            command.add_argument(
                "-y", "--yes", action="store_true", help="Skip the removal confirmation"
            )
        if name == "logs":
            command.add_argument("--tail", type=int, default=50, help="Number of log lines")
    commands.add_parser("list", help="List saved deployments with current status")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI, returning 0 on success, 1 on operation failure, or 130 on Ctrl-C.

    Argparse exits with code 2 for invalid command syntax. Removal requires
    confirmation unless -y is supplied; declined/EOF confirmation returns 1.
    """
    args = _parser().parse_args(argv)
    try:
        if args.command == "deploy":
            if args.backend == "mongodb":
                db = deploy_mongodb(args.name, port=args.port, timeout=args.timeout)
            else:
                password = "bondi-local"
                if args.password_env:
                    if args.password_env not in os.environ:
                        raise ValueError(
                            f"Password environment variable {args.password_env!r} is unset"
                        )
                    password = os.environ[args.password_env]
                db = deploy_couchbase(
                    args.name,
                    management_port=args.management_port,
                    query_port=args.query_port,
                    kv_port=args.kv_port,
                    edition=args.edition,
                    username=args.username,
                    password=password,
                    bucket=args.bucket,
                    timeout=args.timeout,
                )

            print(f"{db.name}: running — {db.uri}")
            if args.backend == "mongodb":
                print(f'Connect: mongosh "{db.uri}"')
                print("Install mongosh: https://www.mongodb.com/docs/mongodb-shell/install/")
                print("Install mongoimport, mongoexport, mongodump, mongorestore:")
                print("  https://www.mongodb.com/docs/database-tools/installation/")
            else:
                print(f"Console: {db.console_url}")
                print(f"Username: {db.username}")
                if args.password_env:
                    print(f"Password: from {args.password_env} (value not displayed)")
                else:
                    print("Password: bondi-local (local demo default)")
                print(f"Bucket: {db.bucket} (default scope and collection)")
        elif args.command == "list":
            deployments = list_deployments()
            if not deployments:
                print("No saved deployments. Create one with: bondi deploy mongodb")
            for db in deployments:
                print(f"{db.name}: {db.status()} — {db.uri}")
        else:
            db = get_deployment(args.name)
            if args.command == "status":
                print(f"{db.name}: {db.status()} — {db.uri}")
            elif args.command == "logs":
                print(db.logs(tail=args.tail), end="")
            elif args.command == "remove":
                if not args.yes:
                    action = (
                        "remove the container, keeping its data and configuration"
                        if args.keep_data
                        else "permanently delete the container, data and saved configuration"
                    )
                    try:
                        answer = input(f"{db.name}: {action}? [y/N] ")
                    except EOFError:
                        print(
                            "bondi: removal cancelled; use -y for unattended removal.",
                            file=sys.stderr,
                        )
                        return 1
                    if answer.strip().lower() not in {"y", "yes"}:
                        print("Removal cancelled; nothing was changed.")
                        return 1
                db.remove(delete_data=not args.keep_data, timeout=args.timeout)
                detail = "data retained" if args.keep_data else "data and configuration deleted"
                print(f"{db.name}: removed ({detail})")
            elif args.command == "start":
                db.start(timeout=args.timeout)
                print(f"{db.name}: running — {db.uri}")
            elif args.command == "stop":
                db.stop(timeout=args.timeout)
                print(f"{db.name}: stopped (data retained)")
    except FileNotFoundError as exc:
        print(f"bondi: saved deployment files not found: {exc.filename or exc}", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"bondi: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("bondi: interrupted; inspect deployment status before retrying.", file=sys.stderr)
        return 130
    return 0
