"""The demo uses the general loader and its public CLI contract."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bondi._cli import cli
from bondi.couchbase import CouchbaseCollectionRef
from bondi.data import CouchbaseConnection, LoadDataResult, MongoConnection, load_demo_data
from bondi.deployment import Deployment
from bondi.mongodb import MongoCollectionRef


@pytest.mark.parametrize(
    "target,ref",
    [
        (MongoConnection("mongodb://unused"), MongoCollectionRef("demo", "business")),
        (
            CouchbaseConnection("couchbase://unused", "user", "password"),
            CouchbaseCollectionRef("demo", "_default", "business"),
        ),
    ],
)
def test_packaged_documents_and_loader_options(target, ref, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def callback(result):
        return None

    with patch("bondi.data._demo.load_documents") as load:
        result = load_demo_data(
            target=target, collection=ref, mode="upsert", on_progress=callback, batch_size=2
        )
    assert result is load.return_value
    rows = load.call_args.args[0]
    assert len(rows) == 8
    assert len({row["business_id"] for row in rows}) == 8
    assert rows[0]["name"] == "Harbour Cafe"
    assert load.call_args.kwargs == {
        "target": target,
        "collection": ref,
        "id_field": "business_id",
        "mode": "upsert",
        "on_progress": callback,
        "batch_size": 2,
    }


def test_demo_uses_loader_defaults():
    with patch("bondi.data._demo.load_documents") as load:
        load_demo_data(
            target=MongoConnection("mongodb://unused"),
            collection=MongoCollectionRef("demo", "business"),
        )
    assert "mode" not in load.call_args.kwargs
    assert load.call_args.kwargs["id_field"] == "business_id"


def test_removed_deployment_api():
    import bondi.deployment

    assert not hasattr(Deployment, "load_demo_data")
    assert not hasattr(bondi.deployment, "DemoDataResult")
    assert CliRunner().invoke(cli, ["deployment", "load-demo-data"]).exit_code == 2


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_demo_cli(backend):
    target = (
        MongoConnection("mongodb://unused")
        if backend == "mongodb"
        else CouchbaseConnection("couchbase://unused", "user", "password")
    )
    destination = ["--database", "demo"] if backend == "mongodb" else ["--bucket", "demo"]
    with (
        patch("bondi.deployment.get_deployment", return_value=target),
        patch("bondi.data._cli.load_demo_data", return_value=LoadDataResult(backend)) as load,
    ):
        result = CliRunner().invoke(
            cli,
            [
                "dataset",
                "load-demo",
                "--deployment",
                "example",
                *destination,
                "--collection",
                "business",
                "--mode",
                "upsert",
            ],
        )
    assert result.exit_code == 0, result.output
    assert load.call_args.kwargs["target"] is target
    assert load.call_args.kwargs["mode"] == "upsert"
    assert load.call_args.kwargs["id_field"] == "business_id"
    assert load.call_args.kwargs["collection"].collection == "business"
