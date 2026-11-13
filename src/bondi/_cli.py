"""Click commands for database deployments and datasets."""

import os
import sys
from types import SimpleNamespace

import click

from bondi._terminal import message, table
from bondi._terminal import status as status_line
from bondi.data._cli import dataset
from bondi.deployment import deploy_couchbase, deploy_mongodb, get_deployment, list_deployments


@click.group(no_args_is_help=False)
def cli():
    """Manage research databases and load datasets."""


@cli.result_callback()
@click.pass_context
def _exit_with_result(ctx, result, **options):
    ctx.exit(result or 0)


@cli.group(no_args_is_help=False)
def deployment():
    """Create and manage local database deployments."""


@deployment.group(no_args_is_help=False)
def create():
    """Create a database deployment and wait for readiness."""


@create.command("mongodb")
@click.option("--name", default="mongodb", show_default=True)
@click.option("--port", type=int, default=27017, show_default=True)
@click.option(
    "--memory-limit-mb", type=int, help="Container cap in MiB. Omission reuses saved settings."
)
@click.option(
    "--wiredtiger-cache-size-gb", type=float, help="WiredTiger cache in GiB (0.25–10000)."
)
@click.option("--timeout", type=float, default=120, show_default=True)
@click.option(
    "--version",
    help="Database major.minor.patch version. Omission reuses the saved image or pinned default.",
)
def mongodb(**options):
    """Deploy MongoDB."""
    return _run(SimpleNamespace(command="create", backend="mongodb", **options))


@create.command("couchbase")
@click.option("--name", default="couchbase", show_default=True)
@click.option("--management-port", type=int, default=8091, show_default=True)
@click.option("--query-port", type=int, default=8093, show_default=True)
@click.option("--kv-port", type=int, default=11210, show_default=True)
@click.option(
    "--edition",
    type=click.Choice(["community", "enterprise"]),
    default="community",
    show_default=True,
)
@click.option("--username", default="Administrator", show_default=True)
@click.option("--password-env", help="Read the password from this environment variable.")
@click.option("--bucket", default="demo", show_default=True)
@click.option(
    "--memory-limit-mb",
    type=int,
    default=4096,
    show_default=True,
    help="Container cap in MiB, separate from service quotas.",
)
@click.option("--timeout", type=float, default=300, show_default=True)
@click.option(
    "--version",
    help="Database major.minor.patch version. Omission reuses the saved image or pinned default.",
)
def couchbase(**options):
    """Deploy and initialize Couchbase."""
    return _run(SimpleNamespace(command="create", backend="couchbase", **options))


@deployment.command("start")
@click.argument("name")
@click.option("--timeout", type=float, default=120, show_default=True)
def start(**options):
    """Start a saved deployment and wait for readiness."""
    return _run(SimpleNamespace(command="start", **options))


@deployment.command("stop")
@click.argument("name")
@click.option("--timeout", type=float, default=120, show_default=True)
def stop(**options):
    """Stop a deployment and retain its data."""
    return _run(SimpleNamespace(command="stop", **options))


@deployment.command("remove")
@click.argument("name")
@click.option("--timeout", type=float, default=120, show_default=True)
@click.option("--keep-data", is_flag=True, help="Retain data and configuration for a later start.")
@click.option("-y", "--yes", is_flag=True, help="Skip the removal confirmation.")
def remove(**options):
    """Remove a deployment and its data. Ask for confirmation first."""
    return _run(SimpleNamespace(command="remove", **options))


@deployment.command("status")
@click.argument("name")
def status(**options):
    """Show a deployment's current state, URI and saved memory settings."""
    return _run(SimpleNamespace(command="status", **options))


@deployment.command("logs")
@click.argument("name")
@click.option("--tail", type=int, default=50, show_default=True, help="Number of log lines.")
def logs(**options):
    """Show recent database logs without extra formatting."""
    return _run(SimpleNamespace(command="logs", **options))


@deployment.command("list")
def list_saved():
    """List saved deployments and their current status."""
    return _run(SimpleNamespace(command="list"))


def _display_status(db):
    state = db.status()
    if state == "removed" and db._data_volume_exists():
        return "removed (data retained)"
    return state


def _run(args):
    try:
        if args.command == "dataset":
            from bondi.data._cli import run

            return run(args)
        if args.command == "create":
            if args.backend == "mongodb":
                db = deploy_mongodb(
                    args.name,
                    port=args.port,
                    version=args.version,
                    timeout=args.timeout,
                    memory_limit_mb=args.memory_limit_mb,
                    wiredtiger_cache_size_gb=args.wiredtiger_cache_size_gb,
                )
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
                    version=args.version,
                    username=args.username,
                    password=password,
                    bucket=args.bucket,
                    memory_limit_mb=args.memory_limit_mb,
                    timeout=args.timeout,
                )

            status_line(db.name, "running", db.uri)
            if args.backend == "mongodb":
                message(f'Connect: mongosh "{db.uri}"')
                message("Install mongosh: https://www.mongodb.com/docs/mongodb-shell/install/")
                message("Install mongoimport, mongoexport, mongodump, mongorestore:")
                message("  https://www.mongodb.com/docs/database-tools/installation/")
            else:
                message(f"Console: {db.console_url}")
                message(f"Username: {db.username}")
                if args.password_env:
                    message(f"Password: from {args.password_env} (value not displayed)")
                else:
                    message("Password: bondi-local (local demo default)")
                message(f"Bucket: {db.bucket} (default scope and collection)")
        elif args.command == "list":
            deployments = list_deployments()
            if not deployments:
                message("No saved deployments. Create one with: bondi deployment create mongodb")
            else:
                table(
                    "Saved deployments",
                    ("Name", "Status", "URI"),
                    [(db.name, _display_status(db), db.uri) for db in deployments],
                )
        else:
            db = get_deployment(args.name)
            if args.command == "status":
                status_line(db.name, _display_status(db), db.uri)
                memory = (
                    "not explicitly saved"
                    if db.memory_limit_mb is None
                    else f"{db.memory_limit_mb} MiB"
                )
                message(f"Saved container memory limit: {memory}")
                if db.backend == "mongodb":
                    cache = (
                        "not explicitly saved"
                        if db.wiredtiger_cache_size_gb is None
                        else f"{db.wiredtiger_cache_size_gb} GiB"
                    )
                    message(f"Saved WiredTiger cache size: {cache}")
            elif args.command == "logs":
                sys.stdout.write(db.logs(tail=args.tail))
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
                        message(
                            "bondi: removal cancelled; use -y for unattended removal.",
                            error=True,
                        )
                        return 1
                    if answer.strip().lower() not in {"y", "yes"}:
                        message("Removal cancelled; nothing was changed.")
                        return 1
                db.remove(keep_data=args.keep_data, timeout=args.timeout)
                detail = "data retained" if args.keep_data else "data and configuration deleted"
                message(f"{db.name}: removed ({detail})")
            elif args.command == "start":
                db.start(timeout=args.timeout)
                status_line(db.name, "running", db.uri)
            elif args.command == "stop":
                db.stop(timeout=args.timeout)
                message(f"{db.name}: stopped (data retained)")
    except FileNotFoundError as exc:
        message(f"bondi: saved deployment files not found: {exc.filename or exc}", error=True)
        return 1
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        message(f"bondi: {exc}", error=True)
        return 1
    except KeyboardInterrupt:
        message("bondi: interrupted; inspect deployment status before retrying.", error=True)
        return 130
    return 0


cli.add_command(dataset)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Operations return 0 on success, 1 on failure, or 130 on interruption.
    Invalid syntax raises SystemExit(2). Help returns 0.
    """
    try:
        result = cli.main(args=argv, prog_name="bondi", standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        raise SystemExit(exc.exit_code) from None
    except click.Abort:
        message("bondi: interrupted; inspect deployment status before retrying.", error=True)
        return 130
    return result or 0
