"""Command-line adapter for the deployment API (no extra CLI dependencies)."""

import argparse
import sys

from bondi.deployment import deploy_mongodb, get_deployment, list_deployments


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bondi", description="Manage local research databases with Docker Compose."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    deploy = commands.add_parser("deploy", help="Create/start a database and wait for readiness")
    deploy.add_argument("backend", choices=["mongodb"])
    deploy.add_argument("--name", default="mongodb", help="Deployment name (default: mongodb)")
    deploy.add_argument("--port", type=int, default=27017, help="Localhost port (default: 27017)")
    deploy.add_argument("--timeout", type=float, default=120, help="Startup deadline in seconds")
    for name, help_text in (
        ("start", "Start a saved deployment and wait for readiness"),
        ("stop", "Stop a deployment, retaining data"),
        ("remove", "Remove a container/network, retaining data by default"),
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
                "--delete-data",
                action="store_true",
                help="Permanently delete data volume and saved configuration",
            )
        if name == "logs":
            command.add_argument("--tail", type=int, default=50, help="Number of log lines")
    commands.add_parser("list", help="List saved deployments with current status")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI, returning 0 on success, 1 on operation failure, or 130 on Ctrl-C.

    Argparse exits with code 2 for invalid command syntax. The explicit
    --delete-data flag authorizes deletion without an interactive prompt.
    """
    args = _parser().parse_args(argv)
    try:
        if args.command == "deploy":
            db = deploy_mongodb(args.name, port=args.port, timeout=args.timeout)
            print(f"{db.name}: running — {db.uri}")
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
                db.remove(delete_data=args.delete_data, timeout=args.timeout)
                detail = "data and configuration deleted" if args.delete_data else "data retained"
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
