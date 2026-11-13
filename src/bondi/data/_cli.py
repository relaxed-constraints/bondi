"""Dataset command group."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import click

from bondi._terminal import table
from bondi.couchbase.collection import CouchbaseCollectionRef
from bondi.mongodb import MongoCollectionRef

from . import (
    CouchbaseConnection,
    MongoConnection,
    dataset_info,
    list_datasets,
    load_file,
    load_hf_dataset,
    load_hf_repository,
)
from ._writers import connection


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


def _load_options(function):
    """Common destination and write options for the three source commands."""
    decorators = [
        click.option("--deployment", help="Saved deployment name."),
        click.option("--connection", help="JSON connection file, with optional password_env."),
        click.option("--database", help="MongoDB destination database."),
        click.option("--bucket", help="Couchbase destination bucket."),
        click.option("--scope", default="_default", show_default=True),
        click.option("--id-field"),
        click.option("--namespace"),
        click.option("--bucket-memory-mb", type=int),
        click.option("--batch-size", type=int, default=1000, show_default=True),
        click.option(
            "--mode",
            type=click.Choice(["create", "replace", "upsert"]),
            default="create",
            show_default=True,
        ),
        click.option("--json-mode", type=click.Choice(["plain", "extended"]), default="plain"),
        click.option("--naive-datetimes", type=click.Choice(["error", "utc"]), default="error"),
        click.option("--decimal-mode", type=click.Choice(["error", "string"]), default="error"),
    ]
    for decorate in reversed(decorators):
        function = decorate(function)
    return function


@datasets.command("load-file")
@click.argument("source", type=click.Path(path_type=Path))
@click.option("--collection", required=True, help="Exact destination collection name.")
@_load_options
def file_command(**options):
    """Load one CSV, JSON, JSONL or Parquet file."""
    return _load_dispatch("load-file", options)


@datasets.command("load-hf")
@click.argument("source")
@click.option("--dataset", help="HF configuration name. Required for multi-config repositories.")
@click.option("--split", multiple=True, help="Select splits. Default: combine all splits.")
@click.option("--revision", help="Hub branch, tag or commit.")
@click.option("--collection", required=True, help="Exact collection name. No suffix is added.")
@_load_options
def hf_command(**options):
    """Load one Hugging Face dataset into one collection."""
    return _load_dispatch("load-hf", options)


@datasets.command("load-hf-repository")
@click.argument("source")
@click.option("--split", multiple=True, help="Select splits in every dataset. Default: all.")
@click.option("--revision", help="Hub branch, tag or commit.")
@_load_options
def repository_command(**options):
    """Load all HF configurations, using their names as collection names."""
    return _load_dispatch("load-hf-repository", options)


def _load_dispatch(command, options):
    if (options["deployment"] is None) == (options["connection"] is None):
        raise click.UsageError("Specify exactly one of --deployment or --connection.")
    if "split" in options:
        options["split"] = list(options["split"]) or None
    return _dispatch(dataset_command=command, **options)


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
            "id_field",
            "namespace",
            "bucket_memory_mb",
            "batch_size",
            "mode",
            "json_mode",
            "naive_datetimes",
            "decimal_mode",
        )
    }
    conn = connection(target)
    if isinstance(conn, MongoConnection):
        if not args.database:
            raise ValueError("MongoDB requires a destination database. Specify --database NAME.")
        if args.bucket is not None or args.scope != "_default":
            raise ValueError("MongoDB does not accept --bucket or --scope")
    else:
        if not args.bucket:
            raise ValueError("Couchbase requires a destination bucket. Specify --bucket NAME.")
        if args.database is not None:
            raise ValueError("Couchbase does not accept --database")
    if args.dataset_command == "load-hf-repository":
        result = load_hf_repository(
            args.source,
            target=target,
            database=args.database,
            bucket=args.bucket,
            scope=args.scope,
            split=args.split,
            revision=args.revision,
            **options,
        )
        payload = {key: asdict(value) for key, value in result.items()}
    else:
        ref = (
            MongoCollectionRef(args.database, args.collection)
            if isinstance(conn, MongoConnection)
            else CouchbaseCollectionRef(args.bucket, args.scope, args.collection)
        )
        if args.dataset_command == "load-file":
            result = load_file(args.source, target=target, collection=ref, **options)
        else:
            result = load_hf_dataset(
                args.source,
                target=target,
                collection=ref,
                dataset=args.dataset,
                split=args.split,
                revision=args.revision,
                **options,
            )
        payload = asdict(result)
    print(json.dumps(payload, indent=2))
    return 0
