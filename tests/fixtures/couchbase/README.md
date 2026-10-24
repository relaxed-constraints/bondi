# Couchbase summary fixtures

Captured on 2026-10-24 with the toolkit executor against the local Community and
Enterprise 7.6.2 ARM64 containers, using SDK 4.6.3 and the eight synthetic documents
in `dev/business.json`. These timings demonstrate response structure, not performance.

Each file records its edition, versions, exact SQL++ statement, and three raw
responses: `explain`, `run`, and `profile`. Credentials are not recorded. All queries
were read-only with `QueryScanConsistency.REQUEST_PLUS`; no indexes or data changed.

To reproduce a file, initialize the corresponding local Docker environment, create
`CouchbaseQuery(record["statement"])`, and call each executor method with
`query_kwargs={"read_only": True, "scan_consistency": QueryScanConsistency.REQUEST_PLUS}`.
Save each result's `.raw`. Use SDK ports 11210 (Community) or 11211 (Enterprise)
and `?network=external`. Request IDs and times will change.

Tests assert known row counts, named indexes and structural behavior without
comparing timing values between editions. The scalar query uses no collection;
the covering query has no Fetch. The empty query distinguishes zero from missing.
