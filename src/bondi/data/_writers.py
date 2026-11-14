"""Native database writers. Only explicitly selected collections are cleared."""

import re
from contextlib import contextmanager, suppress
from datetime import timedelta

from pymongo import MongoClient

from ._types import CouchbaseConnection, MongoConnection


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,62}", value):
        raise ValueError("Destination names require 1-63 letters, digits, underscores or hyphens")
    return value


def connection(target):
    if isinstance(target, (MongoConnection, CouchbaseConnection)):
        return target
    from bondi.deployment import Deployment

    if not isinstance(target, Deployment):
        raise TypeError("target must be a Deployment, MongoConnection or CouchbaseConnection")
    if target.backend == "mongodb":
        return MongoConnection(target.uri)
    return CouchbaseConnection(target.uri, target.username, target.password)


class MongoWriter:
    backend = "mongodb"

    def __init__(self, target):
        credentials = {
            key: value
            for key, value in (("username", target.username), ("password", target.password))
            if value is not None
        }
        self.client = MongoClient(target.uri, timeoutMS=30000, **credentials)

    def preflight(self, dest, quota):
        database, _, collection = dest
        db = self.client[database]
        existing = db[collection].find_one({}, {"_id": 1}) is not None
        return existing

    def prepare(self, dest, mode):
        database, _, collection = dest
        db = self.client[database]
        if collection not in db.list_collection_names():
            db.create_collection(collection)
        if mode == "replace":
            db[collection].delete_many({})

    def write_one(self, dest, key, document, mode):
        collection = self.client[dest[0]][dest[2]]
        if mode == "upsert":
            result = collection.replace_one({"_id": document["_id"]}, document, upsert=True)
        else:
            result = collection.insert_one(document)
        if not result.acknowledged:
            raise RuntimeError("MongoDB did not acknowledge the write")

    def close(self):
        self.client.close()


class CouchbaseWriter:
    backend = "couchbase"

    def __init__(self, target):
        from couchbase.auth import PasswordAuthenticator
        from couchbase.cluster import Cluster
        from couchbase.options import ClusterOptions

        self.cluster = Cluster(
            target.uri, ClusterOptions(PasswordAuthenticator(target.username, target.password))
        )
        self.cluster.wait_until_ready(timedelta(seconds=30))
        self.buckets = {}

    def _bucket(self, bucket):
        if bucket not in self.buckets:
            self.buckets[bucket] = self.cluster.bucket(bucket)
            self.cluster.wait_until_ready(timedelta(seconds=30))
        return self.buckets[bucket]

    def _collection(self, dest):
        return self._bucket(dest[0]).scope(dest[1]).collection(dest[2])

    def _scan(self, dest):
        from couchbase.kv_range_scan import RangeScan
        from couchbase.options import ScanOptions

        return self._collection(dest).scan(
            RangeScan(), ScanOptions(ids_only=True, timeout=timedelta(seconds=30))
        )

    @contextmanager
    def _managed_scan(self, dest):
        scan = self._scan(dest)
        try:
            yield scan
        except BaseException:
            # SDK cancellation can fail if the scan never started. Keep the
            # original scan or deletion error, including interruption.
            with suppress(Exception):
                scan.cancel_scan()
            raise
        else:
            scan.cancel_scan()

    def preflight(self, dest, quota):
        from couchbase.exceptions import (
            BucketDoesNotExistException,
            BucketNotFoundException,
        )

        try:
            self.cluster.buckets().get_bucket(dest[0])
        except (BucketNotFoundException, BucketDoesNotExistException):
            if type(quota) is not int or quota < 100:
                raise ValueError(
                    "A missing Couchbase bucket requires bucket_memory_mb >= 100"
                ) from None
            return False
        scopes = self._bucket(dest[0]).collections().get_all_scopes()
        scope = next((s for s in scopes if s.name == dest[1]), None)
        exists = scope is not None and any(c.name == dest[2] for c in scope.collections)
        if not exists:
            return False
        with self._managed_scan(dest) as scan:
            return next(iter(scan), None) is not None

    def prepare(self, dest, mode, quota=None):
        from couchbase.exceptions import BucketDoesNotExistException, BucketNotFoundException
        from couchbase.management.buckets import CreateBucketSettings

        try:
            self.cluster.buckets().get_bucket(dest[0])
        except (BucketNotFoundException, BucketDoesNotExistException):
            self.cluster.buckets().create_bucket(
                CreateBucketSettings(name=dest[0], ram_quota_mb=quota, num_replicas=0)
            )
        bucket = self._bucket(dest[0])
        manager = bucket.collections()
        scopes = manager.get_all_scopes()
        current = next((s for s in scopes if s.name == dest[1]), None)
        if current is None:
            manager.create_scope(dest[1])
        names = {c.name for c in current.collections} if current else set()
        created = dest[2] not in names
        if created:
            # A creation conflict must fail, not be treated as an empty collection.
            manager.create_collection(dest[1], dest[2])
        # New collections have no old documents to delete. SDK writes retry
        # collection-map refresh; do not start a range scan immediately after creation.
        if mode == "replace" and not created:
            with self._managed_scan(dest) as scan:
                for item in scan:
                    self._collection(dest).remove(item.id)

    def write_one(self, dest, key, document, mode):
        collection = self._collection(dest)
        if mode == "upsert":
            collection.upsert(key, document)
        else:
            collection.insert(key, document)

    def close(self):
        self.cluster.close()
