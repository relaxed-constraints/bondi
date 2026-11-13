"""Dataset command group."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import click

from bondi._terminal import table

from . import CouchbaseConnection, MongoConnection, dataset_info, list_datasets, load_data


@click.group(no_args_is_help=False)
def datasets():
    """List, inspect or load datasets."""


@datasets.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output catalogue metadata as JSON.")
def listing(as_json):
    """Show available datasets."""
    return _dispatch(dataset_command="list", json=as_json)


@datasets.command("info")
@click.argument("name")
def info(name):
    """Show dataset metadata as JSON."""
    return _dispatch(dataset_command="info", name=name)


@datasets.command("load")
@click.argument("source", required=False)
@click.option("--manifest", help="Dataset manifest file.")
@click.option("--deployment", help="Saved deployment name.")
@click.option("--connection", help="JSON connection file. Use password_env for credentials.")
@click.option("--database")
@click.option("--bucket")
@click.option("--scope")
@click.option("--collection")
@click.option("--id-field")
@click.option("--namespace")
@click.option("--indexes")
@click.option("--bucket-memory-mb", type=int)
@click.option("--batch-size", type=int, default=1000, show_default=True)
@click.option(
    "--mode",
    type=click.Choice(["create", "replace", "upsert"]),
    default="create",
    show_default=True,
)
@click.option("--allow-unowned", is_flag=True)
@click.option("--split", multiple=True, help="Select a split. Repeat to select several.")
@click.option(
    "--splits", type=click.Choice(["preserve", "merge"]), default="preserve", show_default=True
)
@click.option(
    "--json-mode", type=click.Choice(["plain", "extended"]), default="plain", show_default=True
)
@click.option(
    "--naive-datetimes", type=click.Choice(["error", "utc"]), default="error", show_default=True
)
@click.option(
    "--decimal-mode", type=click.Choice(["error", "string"]), default="error", show_default=True
)
def load(**options):
    """Load documents and output the result as JSON."""
    if (options["deployment"] is None) == (options["connection"] is None):
        raise click.UsageError("Specify exactly one of --deployment or --connection.")
    options["split"] = list(options["split"]) or None
    return _dispatch(dataset_command="load", **options)


def _dispatch(**options):
    from bondi._cli import _run

    return _run(SimpleNamespace(command="datasets", **options))


def run(args):
    if args.dataset_command == "list":
        datasets = list_datasets()
        if args.json:
            print(json.dumps(datasets, indent=2))
        elif not datasets:
            print("No datasets available.")
        else:
            table(
                "Available datasets",
                ("Dataset", "Source", "Description"),
                [
                    (name, info.get("repo_id", "Packaged with BONDI"), info["description"])
                    for name, info in datasets.items()
                ],
            )
        return 0
    if args.dataset_command == "info":
        print(json.dumps(dataset_info(args.name), indent=2))
        return 0
    if args.deployment:
        from bondi.deployment import get_deployment

        target = get_deployment(args.deployment)
    else:
        config = json.loads(Path(args.connection).read_text())
        if not isinstance(config, dict) or not config.get("uri"):
            raise ValueError("Connection file requires a uri")
        if config.get("backend") == "mongodb":
            password = None
            if "password_env" in config:
                variable = config["password_env"]
                if not isinstance(variable, str) or variable not in os.environ:
                    raise ValueError("MongoDB password_env must name a set environment variable")
                password = os.environ[variable]
            target = MongoConnection(config["uri"], config.get("username"), password)
        elif config.get("backend") == "couchbase":
            if not config.get("username") or config.get("password_env") not in os.environ:
                raise ValueError("Couchbase connection requires username and a set password_env")
            target = CouchbaseConnection(
                config["uri"], config["username"], os.environ[config["password_env"]]
            )
        else:
            raise ValueError("Unsupported connection backend")
    options = {
        key: getattr(args, key)
        for key in (
            "manifest",
            "database",
            "bucket",
            "collection",
            "id_field",
            "namespace",
            "indexes",
            "bucket_memory_mb",
            "batch_size",
            "mode",
            "allow_unowned",
            "split",
            "splits",
            "json_mode",
            "naive_datetimes",
            "decimal_mode",
        )
    }
    options["scope"] = args.scope or "_default"
    result = load_data(args.source, target=target, **options)
    print(json.dumps(asdict(result), indent=2))
    return 0
