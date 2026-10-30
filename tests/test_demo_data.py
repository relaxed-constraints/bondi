"""Demo loader contracts, failures, and CLI delegation without Docker."""

import json
from importlib.resources import files
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import OperationFailure

from bondi._cli import main
from bondi.deployment import DemoDataResult, Deployment


@pytest.fixture
def db(tmp_path):
    return Deployment("demo", 27017, "image", tmp_path, "project")


def test_packaged_data_matches_source():
    from pathlib import Path

    documents = json.loads(files("bondi.deployment").joinpath("business.json").read_text())
    assert documents == json.loads(Path("dev/business.json").read_text())
    assert len(documents) == len({d["business_id"] for d in documents}) == 8


@pytest.mark.parametrize(
    "options",
    [
        {"scope": "x"},
        {"create_primary_index": True},
        {"collection": ""},
        {"database": "x.y"},
        {"collection": "x`"},
        {"create_primary_index": 1},
    ],
)
def test_invalid_options_do_not_contact_database(db, options):
    with patch.object(Deployment, "status") as status:
        with pytest.raises(ValueError):
            db.load_demo_data(**options)
        status.assert_not_called()


def test_stopped_deployment(db):
    with patch.object(Deployment, "status", return_value="stopped"):
        with pytest.raises(RuntimeError, match="must be running"):
            db.load_demo_data()


def test_mongo_upserts_and_closes_client(db):
    with (
        patch.object(Deployment, "status", return_value="running"),
        patch("bondi.deployment._demo.MongoClient") as client,
    ):
        collection = client.return_value.__enter__.return_value["research"]["businesses"]
        collection.bulk_write.return_value.matched_count = 3
        collection.bulk_write.return_value.upserted_count = 5
        result = db.load_demo_data(database="research", collection="businesses")
        assert result == DemoDataResult("mongodb", "research", None, "businesses", 8)
        operations = collection.bulk_write.call_args.args[0]
        assert len(operations) == 8
        assert all(
            op._upsert and op._filter == {"_id": op._doc["business_id"]} for op in operations
        )
        client.return_value.__exit__.assert_called_once()


def test_mongo_partial_failure(db):
    with (
        patch.object(Deployment, "status", return_value="running"),
        patch("bondi.deployment._demo.MongoClient") as client,
    ):
        collection = client.return_value.__enter__.return_value["demo"]["business"]
        collection.bulk_write.side_effect = OperationFailure("sensitive server text")
        with pytest.raises(RuntimeError, match="some writes may have succeeded") as error:
            db.load_demo_data()
        assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("create_index", [False, True])
def test_couchbase_creation_parameters_and_index(tmp_path, create_index):
    db = Deployment("cb", 8091, "image", tmp_path, "project", backend="couchbase", bucket="demo")
    responses = [
        {"scopes": []},
        None,
        None,
        {"status": "success", "results": [f"demo-{n:03}" for n in range(1, 9)]},
        {"status": "success"},
    ]
    with (
        patch.object(Deployment, "status", return_value="running"),
        patch("bondi.deployment._couchbase.request", side_effect=responses) as request,
    ):
        result = db.load_demo_data(scope="research", create_primary_index=create_index)
        assert result == DemoDataResult("couchbase", "demo", "research", "business", 8)
        calls = request.call_args_list
        assert calls[1].args[2] == {"name": "research"}
        assert calls[2].args[2] == {"name": "business"}
        assert len(json.loads(calls[3].args[2]["$documents"])) == 8
        assert "`demo`.`research`.`business`" in calls[3].args[2]["statement"]
        assert len(calls) == (5 if create_index else 4)


@pytest.mark.parametrize("response", [{"status": "errors"}, {"status": "success", "results": []}])
def test_couchbase_failed_or_incomplete_load(tmp_path, response):
    db = Deployment("cb", 8091, "image", tmp_path, "project", backend="couchbase", bucket="demo")
    existing = {"scopes": [{"name": "_default", "collections": [{"name": "business"}]}]}
    with (
        patch.object(Deployment, "status", return_value="running"),
        patch("bondi.deployment._couchbase.request", side_effect=[existing, response]) as request,
    ):
        with pytest.raises(RuntimeError):
            db.load_demo_data(create_primary_index=True)
        assert request.call_count == 2  # No index after a failed load; no collection recreated.


def test_cli_options_and_error(capsys):
    db = MagicMock()
    db.name = "cb"
    db.load_demo_data.return_value = DemoDataResult(
        "couchbase", "demo", "research", "businesses", 8
    )
    with patch("bondi._cli.get_deployment", return_value=db):
        assert (
            main(
                [
                    "load-demo-data",
                    "cb",
                    "--scope",
                    "research",
                    "--collection",
                    "businesses",
                    "--create-primary-index",
                ]
            )
            == 0
        )
        db.load_demo_data.assert_called_once_with(
            database=None, scope="research", collection="businesses", create_primary_index=True
        )
        assert "loaded 8 demo documents into demo.research.businesses" in capsys.readouterr().out
        db.load_demo_data.side_effect = RuntimeError("not running")
        assert main(["load-demo-data", "cb"]) == 1
        assert "not running" in capsys.readouterr().err


def test_couchbase_new_collection_retries_manifest_delay(tmp_path):
    from bondi.deployment._couchbase import CouchbaseHTTPError

    db = Deployment("cb", 8091, "image", tmp_path, "project", backend="couchbase", bucket="demo")
    responses = [
        {"scopes": []},
        None,
        None,
        CouchbaseHTTPError(424, "/query/service"),
        {"status": "success", "results": [f"demo-{n:03}" for n in range(1, 9)]},
    ]
    with (
        patch.object(Deployment, "status", return_value="running"),
        patch("bondi.deployment._couchbase.request", side_effect=responses),
        patch("bondi.deployment._demo.time.sleep") as sleep,
    ):
        assert db.load_demo_data().document_count == 8
        sleep.assert_called_once_with(0.5)


def test_couchbase_rejects_database_before_contact(tmp_path):
    db = Deployment("cb", 8091, "image", tmp_path, "project", backend="couchbase", bucket="demo")
    with patch.object(Deployment, "status") as status:
        with pytest.raises(ValueError, match="only supported for MongoDB"):
            db.load_demo_data(database="other")
        status.assert_not_called()


def test_mongo_incomplete_acknowledgement(db):
    with (
        patch.object(Deployment, "status", return_value="running"),
        patch("bondi.deployment._demo.MongoClient") as client,
    ):
        result = client.return_value.__enter__.return_value["demo"][
            "business"
        ].bulk_write.return_value
        result.matched_count = 0
        result.upserted_count = 7
        with pytest.raises(RuntimeError, match="did not acknowledge all"):
            db.load_demo_data()
