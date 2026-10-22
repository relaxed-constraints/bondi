# MongoDB explain fixtures

Captured from MongoDB 8.0.4 on 2026-10-23 against `yelp.business`, using
`executionStats` and a 10-second server deadline. Only `explainVersion`,
`queryPlanner`, `executionStats`, `stages` and `ok` were retained; server metadata
and echoed command were omitted. Timing and counters are observations, not benchmarks.
The existing `_id_` index was used; no documents or indexes were changed.

- `find_collscan`: state AZ, limit 5, natural hint.
- `find_index`: `_id` exists, limit 5, `_id_` hint.
- `aggregate_group`: match state AZ, group by city and count.
- `aggregate_sort`: match state AZ, sort stars descending, limit 5.
- `aggregate_facet`: match state AZ, limit 100, facet grouping cities.
- `aggregate_lookup`: limit 2, lookup business by `_id`, foreign pipeline limit 1.

Tests load these files without connecting to MongoDB. Synthetic cases additionally
exercise unavailable fields, malformed input, rejected plans and branching trees.
