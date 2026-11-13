"""Use only fixture-owned databases for loader integration tests."""

from uuid import uuid4

import pytest

from bondi.couchbase import CouchbaseCollectionRef
from bondi.data import LoadDataError, load_documents
from bondi.mongodb import MongoCollectionRef

pytestmark = pytest.mark.live


@pytest.mark.parametrize("backend", ["mongodb", "community"])
def test_loader_live(backend, live_deployments):
    deployment = live_deployments(backend)
    unique = "load_" + uuid4().hex[:10]
    ref = (
        MongoCollectionRef(unique, "items")
        if backend == "mongodb"
        else CouchbaseCollectionRef(deployment.bucket, unique, "items")
    )
    # Fixture cleanup removes the entire isolated deployment.
    result = load_documents([{"_id": "a", "v": 1}], target=deployment, collection=ref)
    expected = f"{unique}.items" if backend == "mongodb" else f"{deployment.bucket}.{unique}.items"
    assert result.destinations == {expected: 1}
    with pytest.raises(LoadDataError, match="empty"):
        load_documents([{"_id": "b"}], target=deployment, collection=ref)
    result = load_documents([{"_id": "b"}], target=deployment, collection=ref, mode="replace")
    assert sum(result.destinations.values()) == 1
    result = load_documents(
        [{"_id": "b", "v": 2}], target=deployment, collection=ref, mode="upsert"
    )
    assert sum(result.destinations.values()) == 1

    load_documents(
        [{"_id": "replacement"}],
        target=deployment,
        collection=ref,
        mode="replace",
        namespace="different-dataset",
    )
    if backend == "mongodb":
        from pymongo import MongoClient

        with MongoClient(deployment.uri) as client:
            assert client[unique].list_collection_names() == ["items"]
            assert list(client[unique].items.find({})) == [{"_id": "replacement"}]
    else:
        from bondi.data._values import document_key
        from bondi.data._writers import CouchbaseWriter, connection

        writer = CouchbaseWriter(connection(deployment))
        try:
            scopes = writer._bucket(deployment.bucket).collections().get_all_scopes()
            scope = next(scope for scope in scopes if scope.name == unique)
            assert [collection.name for collection in scope.collections] == ["items"]
            dest = (deployment.bucket, unique, "items")
            scan = writer._scan(dest)
            try:
                assert [row.id for row in scan] == [document_key("replacement")]
            finally:
                scan.cancel_scan()
        finally:
            writer.close()


def test_couchbase_new_bucket(live_deployments):
    from datetime import timedelta

    from couchbase.auth import PasswordAuthenticator
    from couchbase.cluster import Cluster
    from couchbase.options import ClusterOptions

    from bondi.data import CouchbaseConnection
    from bondi.data._values import document_key

    deployment = live_deployments("community")
    bucket = "load_" + uuid4().hex[:10]
    target = CouchbaseConnection(deployment.uri, deployment.username, deployment.password)
    ref = CouchbaseCollectionRef(bucket, "_default", "items")
    rows = [{"_id": "x", "field": "value"}]
    with pytest.raises(LoadDataError, match="bucket_memory_mb"):
        load_documents(rows, target=target, collection=ref)
    result = load_documents(rows, target=target, collection=ref, bucket_memory_mb=100)
    assert sum(result.destinations.values()) == 1
    load_documents(rows, target=target, collection=ref, mode="replace")
    cluster = Cluster(
        deployment.uri,
        ClusterOptions(PasswordAuthenticator(deployment.username, deployment.password)),
    )
    try:
        cluster.wait_until_ready(timedelta(seconds=30))
        collection = cluster.bucket(bucket).default_scope().collection("items")
        assert collection.get(document_key("x")).content_as[dict]["field"] == "value"
        assert cluster.buckets().get_bucket(bucket).ram_quota_mb == 100
    finally:
        cluster.close()


def test_mongo_explicit_credentials_live(live_deployments):
    from pymongo import MongoClient

    from bondi.data import MongoConnection

    deployment = live_deployments("mongodb")
    database = "auth_" + uuid4().hex[:10]
    password = "test@password:/%"
    with MongoClient(deployment.uri) as admin:
        admin[database].command(
            "createUser", "loader", pwd=password, roles=[{"role": "readWrite", "db": database}]
        )
    # Explicit fields override URI credentials. The password is not URI-encoded.
    uri = deployment.uri.replace("mongodb://", "mongodb://ignored:ignored@")
    uri = uri.rstrip("/") + ("&" if "?" in uri else "/?") + f"authSource={database}"
    target = MongoConnection(uri, username="loader", password=password)
    result = load_documents(
        [{"_id": "a"}], target=target, collection=MongoCollectionRef(database, "items")
    )
    assert result.destinations == {f"{database}.items": 1}
    with MongoClient(deployment.uri) as admin:
        assert admin[database].items.count_documents({}) == 1
