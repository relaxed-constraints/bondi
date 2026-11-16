"""Pinned Hub dump loading against fixture-owned MongoDB and Couchbase deployments."""

from datetime import timedelta

import pytest
from bson import decode_file_iter
from bson.codec_options import CodecOptions
from huggingface_hub import hf_hub_download

from bondi.data import load_aptmql_dataset
from bondi.data._values import convert, document_key

pytestmark = pytest.mark.live
REVISION = "06ba1f0f29b1947e67a343c204e6a9b5eede6b17"
COUNTS = {
    "brands": 24,
    "customers": 554,
    "inventory": 118,
    "locations": 3,
    "reviews": 713,
    "transactions": 6312,
}


@pytest.mark.parametrize("backend", ["mongodb", "community"])
def test_pinned_beer_factory(backend, live_deployments):
    deployment = live_deployments(backend)
    kwargs = {} if backend == "mongodb" else {"bucket": deployment.bucket}
    results = load_aptmql_dataset(
        "beer_factory", target=deployment, revision=REVISION, batch_size=500, **kwargs
    )
    assert {key: sum(value.destinations.values()) for key, value in results.items()} == COUNTS
    if backend == "mongodb":
        from pymongo import MongoClient

        client = MongoClient(deployment.uri, tz_aware=True)
    else:
        from couchbase.auth import PasswordAuthenticator
        from couchbase.cluster import Cluster
        from couchbase.options import ClusterOptions

        from bondi.data._writers import CouchbaseWriter, connection

        client = Cluster(
            deployment.uri,
            ClusterOptions(PasswordAuthenticator(deployment.username, deployment.password)),
        )
        client.wait_until_ready(timedelta(seconds=30))
    try:
        for collection, count in COUNTS.items():
            path = hf_hub_download(
                "MongoDB/AptMQL-Bench",
                f"databases/train/beer_factory/dump/{collection}.bson",
                repo_type="dataset",
                revision=REVISION,
            )
            with open(path, "rb") as stream:
                originals = list(decode_file_iter(stream, CodecOptions(tz_aware=True)))
            assert len(originals) == count
            if backend == "mongodb":
                coll = client.beer_factory[collection]
                stored = {row["_id"]: row for row in coll.find()}
                assert stored == {row["_id"]: row for row in originals}
                assert list(coll.index_information()) == ["_id_"]
            else:
                writer = CouchbaseWriter(connection(deployment))
                try:
                    scan = writer._scan((deployment.bucket, "beer_factory", collection))
                    try:
                        assert {row.id for row in scan} == {
                            document_key(row["_id"]) for row in originals
                        }
                    finally:
                        scan.cancel_scan()
                finally:
                    writer.close()
                coll = client.bucket(deployment.bucket).scope("beer_factory").collection(collection)
                for row in (originals[0], originals[-1]):
                    expected = convert(row, "couchbase", results[collection].settings, {})
                    assert coll.get(document_key(row["_id"])).content_as[dict] == expected
    finally:
        client.close()
