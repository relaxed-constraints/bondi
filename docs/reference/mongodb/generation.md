# MongoDB workload generation

::: dbrtoolkit.mongodb.MongoGenerationConfig
    options:
      show_root_heading: true
      heading_level: 2

::: dbrtoolkit.mongodb.MongoPredicateTemplate
    options:
      show_root_heading: true
      heading_level: 2

::: dbrtoolkit.mongodb.MongoQueryPattern
    options:
      show_root_heading: true
      heading_level: 2

::: dbrtoolkit.mongodb.MongoWorkloadGenerator
    options:
      show_root_heading: true
      heading_level: 2

::: dbrtoolkit.mongodb.WorkloadGenerationError
    options:
      show_root_heading: true
      heading_level: 2

## Paths and supported values


Generation supports strings, booleans, BSON-range integers, finite floats,
datetimes, ObjectIds and null. Large Python integers normalize to Int64; dates
normalize to BSON UTC millisecond precision. Retention of other Python types by
Schema does not imply support for generating MongoDB predicates from them; exclude
those fields or explicitly transform source data first.

Array traversal markers are removed when generating MongoDB dot paths. Values
remain in their chosen typed source pool throughout a pattern. Mixed scalar and
array sources can map to the same Mongo path, but only one predicate is selected
per path. Missingness used for exists proposals comes from schema observations;
MongoDB/your estimator evaluates the actual semantics.

Literal dotted keys, empty/dollar-prefixed path segments, positional numeric
segments and literal `[]` segments are rejected rather than reinterpreted. Use
schema display paths in exclusions for literal dotted keys, e.g. `r"literal\.dot"`.
Container-only paths without primitive value pools are not candidates. Generated
queries still obey native MongoDB execution restrictions; for example, sorting
on parallel arrays is not generally valid. Use field inclusion to restrict an
experiment to suitable sortable fields.

## Custom constraints, budgets and diagnostics

```python
def accept_pattern(candidate, accepted_patterns):
    fields = {predicate.field for predicate in candidate.predicates}
    return not {"start_station", "end_station"} <= fields


workload = generator.generate(
    num_patterns=5,
    instances_per_pattern=20,
    validate_pattern=accept_pattern,
    max_candidate_attempts=10_000,
    max_instance_attempts=1_000,
    timeout_seconds=60,
    seed=42,
)
print(dict(generator.last_stats))
```

The callback runs before estimation, receives only fully completed prior patterns
as a tuple, and must return bool. The candidate budget is global; the instance
budget applies to each additional instance. Failed groups are discarded completely.
Deadline checks occur between operations; they cannot interrupt a running estimator
or callback. Configure the estimator's executor timeout separately.

On budget exhaustion, `WorkloadGenerationError.stats` reports progress. There is
no partial workload result. `generator.last_stats` is a read-only snapshot with
attempts, rejection counts, estimator calls, discarded groups, completed patterns,
elapsed seconds and, when unfinished, the pending slot targets. Exceptions and
interruptions also update diagnostics after generation starts. Input-validation
failures clear the previous snapshot. Calls on one generator must not overlap.

## Reproducibility and persistence

Fixed schema contents, config, seed and estimator responses give reproducible
queries without changing Python's global random state. Value pools are canonically
ordered, independent of hash seed and value frequencies. Generator seeds do not
control database sampling or elapsed timings. Do not mutate inputs during a call.

```python
from dbrtoolkit.workload import Workload
from dbrtoolkit.mongodb import MongoQueryPattern

workload.save("workload.jsonl")
loaded = Workload.load("workload.jsonl")
pattern = MongoQueryPattern.from_query(loaded[0].query)
```

Existing JSONL preserves queries and integer pattern IDs. Patterns can be extracted
from saved queries; generation statistics are separate and are not added to the
workload file. Queries remain mutable, so edits can invalidate their original shape
or selectivity. The returned patterns are immutable snapshots.

See `notebooks/workload_generation.ipynb` for a toy example and optional live
selectivity checks against the Docker MongoDB demo collection.

## One configuration

`MongoGenerationConfig` contains all settings. Change only what your experiment needs:

```python
config = MongoGenerationConfig(
    min_predicates=2,
    max_predicates=4,
    exclude_fields=["_id", "name", "address"],
    field_weights={"default": 1.0, "overrides": {"attributes.*": 0.05}},
    sort_probability=0.3,
    limit_probability=1.0,
    limit_min=10,
    limit_max=100,
    projection_probability=0.2,
)
```

| Settings | Defaults and meaning |
| --- | --- |
| `min_predicates`, `max_predicates` | 1, 8; maximum capped by available fields, minimum never relaxed |
| `include_fields`, `exclude_fields` | None, `["_id"]`; exact normalized paths, include takes precedence |
| `field_weights` | Default 1; positive weights with case-sensitive glob overrides, last match wins |
| `sort_probability` | 0.3 |
| `sort_on_filter_field_ratio` | 0.7 |
| `sort_two_field_ratio`, `sort_ascending_ratio` | 0.3, 0.8 |
| `skip_probability`, `limit_probability` | 0.0, 0.2 |
| `skip_min`, `skip_max` | 0, 1000, inclusive |
| `limit_min`, `limit_max` | 1, 100, inclusive |
| `skip_requires_limit` | True |
| `projection_probability` | 0.0; inclusion projections |
| `projection_filter_overlap_ratio` | 0.5 |
| `projection_min_fields`, `projection_max_fields` | 1, 5 requested fields |
| `projection_exclude_id_ratio` | 0.5; adds `_id: 0` unless an `_id` path is projected |

Field weights apply to filters, sorts and projections, with weighted selection
without replacement. Exclusions apply to all three (except explicit `_id: 0`).
Requested sort/projection counts may shrink when suitable fields are scarce.
Projection paths that collide with parent/child paths are not selected together.
Probabilities describe proposed pattern slots; rejection changes final frequencies.
For each slot, predicate count and option-presence flags stay fixed through retries.

Operator configuration retains the existing explicit per-type weights:

```python
config = MongoGenerationConfig(
    operator_config={
        "types": {
            "int": {"operators": ["eq", "gte", "in"], "weights": [1, 1, 0.5]},
            "str": {"operators": ["eq", "ne"], "weights": [1, 0.2]},
        },
        "operators": {
            "$exists": {"enabled": True, "chance": 0.3},
            "$type": {"enabled": False, "chance": 0},
            "$size": {"enabled": False, "chance": 0},
        },
    },
)
```

This **replaces**, rather than merges with, defaults. Omitted scalar types are
not proposed; omitted special operators are disabled. Ordinary operators are
`eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `in`, `nin`. Zero operator weights disable
individual operators; at least one weight per configured type must be positive.

Default integer operators are comparisons plus equality (weights 1,1,1,1,0.5);
floats use four comparisons; strings use eq/ne/in/nin/gte/lte with weights
1/0.2/0.4/0.2/0.3/0.3. Booleans and ObjectIds use eq/ne (1/0.3), datetimes use
comparisons/equality equally, and null uses eq/ne (1/0.3). Int64 follows integers.

`$in` uses 2–10 distinct values, `$nin` 1–10, and `$size` 0–5. Special operators
conditionally replace an ordinary predicate, in exists/type/size order. Defaults
are enabled with chances 0.3/0.2/0.1: exists requires observed missingness, type
requires multiple observed types, and size requires an observed array.
These probabilities are conditional, not independent final proportions.

