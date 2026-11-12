"""Use only fixture-owned databases for loader integration tests."""

from uuid import uuid4

import pytest

from bondi.data import LoadDataError, load_data

pytestmark = pytest.mark.live


@pytest.mark.parametrize("backend", ["mongodb", "community"])
def test_loader_live(backend, live_deployments):
    deployment = live_deployments(backend)
    unique = "load_" + uuid4().hex[:10]
    options = (
        {"database": unique}
        if backend == "mongodb"
        else {"bucket": deployment.bucket, "scope": unique}
    )
    # Fixture cleanup removes the entire isolated deployment.
    result = load_data([{"_id": "a", "v": 1}], target=deployment, collection="items", **options)
    assert sum(result.destinations.values()) == 1
    with pytest.raises(LoadDataError, match="empty"):
        load_data([{"_id": "b"}], target=deployment, collection="items", **options)
    result = load_data(
        [{"_id": "b"}], target=deployment, collection="items", mode="replace", **options
    )
    assert sum(result.destinations.values()) == 1
    result = load_data(
        [{"_id": "b", "v": 2}], target=deployment, collection="items", mode="upsert", **options
    )
    assert sum(result.destinations.values()) == 1


def test_couchbase_new_bucket_and_native_indexes(live_deployments):
    from datetime import timedelta

    from couchbase.auth import PasswordAuthenticator
    from couchbase.cluster import Cluster
    from couchbase.options import ClusterOptions

    from bondi.data import CouchbaseConnection
    from bondi.data._values import document_key

    deployment = live_deployments("community")
    bucket = "load_" + uuid4().hex[:10]
    target = CouchbaseConnection(deployment.uri, deployment.username, deployment.password)
    manifest = {
        "version": 1,
        "namespace": "live-bucket",
        "collections": {"items": {"source": [{"_id": "x", "field": "value"}]}},
        "index_profiles": {
            "baseline": {
                "couchbase": [{"collection": "items", "name": "field_idx", "keys": ["field"]}]
            }
        },
    }
    with pytest.raises(LoadDataError, match="bucket_memory_mb"):
        load_data(manifest=manifest, target=target, bucket=bucket)
    result = load_data(
        manifest=manifest, target=target, bucket=bucket, bucket_memory_mb=100, indexes="baseline"
    )
    assert sum(result.destinations.values()) == 1
    # Reusing a matching index must not make a repeated load fail.
    load_data(
        manifest=manifest,
        target=target,
        bucket=bucket,
        bucket_memory_mb=100,
        indexes="baseline",
        mode="replace",
    )
    cluster = Cluster(
        deployment.uri,
        ClusterOptions(PasswordAuthenticator(deployment.username, deployment.password)),
    )
    try:
        cluster.wait_until_ready(timedelta(seconds=30))
        collection = cluster.bucket(bucket).default_scope().collection("items")
        assert collection.get(document_key("x")).content_as[dict]["field"] == "value"
        assert cluster.buckets().get_bucket(bucket).ram_quota_mb == 100
        assert any(i.name == "field_idx" for i in cluster.query_indexes().get_all_indexes(bucket))
    finally:
        cluster.close()
