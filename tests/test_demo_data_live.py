"""Demo loads use the same create, upsert and replace rules on both databases."""

from datetime import timedelta

import pytest
from pymongo import MongoClient

from bondi._cli import main
from bondi.couchbase import CouchbaseCollectionRef
from bondi.data import LoadDataError, load_demo_data, load_documents
from bondi.data._values import document_key
from bondi.mongodb import MongoCollectionRef

pytestmark = pytest.mark.live


@pytest.mark.parametrize("backend", ["mongodb", "community"])
def test_demo_modes_and_cli(live_deployments, backend, monkeypatch):
    db = live_deployments(backend)
    collection = "demo_loader_test"
    ref = (
        MongoCollectionRef("demo", collection)
        if backend == "mongodb"
        else CouchbaseCollectionRef("demo", "_default", collection)
    )
    label = "demo." + collection if backend == "mongodb" else "demo._default." + collection
    assert load_demo_data(target=db, collection=ref).destinations == {label: 8}
    with pytest.raises(LoadDataError, match="empty"):
        load_demo_data(target=db, collection=ref)
    load_documents(
        [{"_id": "keep", "value": 42}, {"_id": "demo-001", "name": "changed"}],
        target=db,
        collection=ref,
        mode="upsert",
    )
    monkeypatch.setattr("bondi.deployment.get_deployment", lambda name: db)
    destination = ["--database", "demo"] if backend == "mongodb" else ["--bucket", "demo"]
    args = [
        "dataset",
        "load-demo",
        "--deployment",
        db.name,
        *destination,
        "--collection",
        collection,
        "--mode",
        "upsert",
    ]
    assert main(args) == 0
    assert main(args) == 0

    if backend == "mongodb":
        with MongoClient(db.uri) as client:
            stored = client.demo[collection]
            assert stored.count_documents({}) == 9
            assert stored.find_one({"_id": "keep"})["value"] == 42
            assert stored.find_one({"_id": "demo-001"})["name"] == "Harbour Cafe"
            load_demo_data(target=db, collection=ref, mode="replace")
            assert stored.count_documents({}) == 8
    else:
        from couchbase.auth import PasswordAuthenticator
        from couchbase.cluster import Cluster
        from couchbase.exceptions import DocumentNotFoundException
        from couchbase.options import ClusterOptions

        cluster = Cluster(db.uri, ClusterOptions(PasswordAuthenticator(db.username, db.password)))
        try:
            cluster.wait_until_ready(timedelta(seconds=30))
            stored = cluster.bucket("demo").default_scope().collection(collection)
            assert stored.get(document_key("keep")).content_as[dict]["value"] == 42
            assert stored.get(document_key("demo-001")).content_as[dict]["name"] == "Harbour Cafe"
            load_demo_data(target=db, collection=ref, mode="replace")
            with pytest.raises(DocumentNotFoundException):
                stored.get(document_key("keep"))
        finally:
            cluster.close()
