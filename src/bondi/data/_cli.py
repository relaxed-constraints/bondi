"""Dataset command group."""

import json
import os
from dataclasses import asdict
from pathlib import Path

from . import CouchbaseConnection, MongoConnection, dataset_info, list_datasets, load_data


def add_parser(commands):
    parser = commands.add_parser("datasets", help="List, inspect or load datasets")
    sub = parser.add_subparsers(dest="dataset_command", required=True)
    sub.add_parser("list")
    info = sub.add_parser("info")
    info.add_argument("name")
    load = sub.add_parser("load")
    load.add_argument("source", nargs="?")
    load.add_argument("--manifest")
    target = load.add_mutually_exclusive_group(required=True)
    target.add_argument("--deployment")
    target.add_argument(
        "--connection", help="JSON connection file, with password_env for Couchbase"
    )
    for option in ("database", "bucket", "scope", "collection", "id-field", "namespace", "indexes"):
        load.add_argument("--" + option)
    load.add_argument("--bucket-memory-mb", type=int)
    load.add_argument("--batch-size", type=int, default=1000)
    load.add_argument("--mode", choices=("create", "replace", "upsert"), default="create")
    load.add_argument("--allow-unowned", action="store_true")
    load.add_argument("--split", action="append")
    load.add_argument("--splits", choices=("preserve", "merge"), default="preserve")
    load.add_argument("--json-mode", choices=("plain", "extended"), default="plain")
    load.add_argument("--naive-datetimes", choices=("error", "utc"), default="error")
    load.add_argument("--decimal-mode", choices=("error", "string"), default="error")


def run(args):
    if args.dataset_command == "list":
        print(json.dumps(list_datasets(), indent=2))
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
