# Workload generation

Generate MongoDB find queries for one collection using observed schema values.
A pattern fixes fields, operators, types and query options; instances vary the
filter values. The generator is synchronous and can be used directly in notebooks.

## Generate patterns from observed values

```python
from bondi.mongodb import MongoCollectionRef, MongoGenerationConfig, MongoWorkloadGenerator
from bondi.schema import Schema

schema = Schema.from_documents(
    [{"city": "Sydney", "stars": 4}, {"city": "Melbourne", "stars": 3}],
    values="distinct",
)
generator = MongoWorkloadGenerator(
    target=MongoCollectionRef("demo", "business"),
    schema=schema,
    config=MongoGenerationConfig(min_predicates=1, max_predicates=2),
)
workload, patterns = generator.generate(
    num_patterns=10, instances_per_pattern=50, seed=42, return_patterns=True,
)
workload.save("workload.jsonl")
assert len(workload) == 500
assert patterns[workload[0].pattern_id].matches(workload[0].query)
```

Omit `return_patterns=True` to receive only the workload. Set
`instances_per_pattern=1` for one instance per distinct pattern. Full query instances
can repeat; pattern shapes are distinct. Pattern IDs index the returned pattern list.
`values="full"` schemas also work: both modes sample uniformly from distinct values.

## Inspect a pattern

`print(pattern)` shows the collection, typed filter slots and any query options:

```python
from bondi.mongodb import MongoFindQuery, MongoQueryPattern

pattern = MongoQueryPattern.from_query(MongoFindQuery(
    MongoCollectionRef("demo", "business"),
    {"city": {"$in": ["Sydney", "Melbourne"]}, "stars": {"$gte": 4}},
    sort=(("stars", -1),), limit=20,
))
print(pattern)
# demo.business: city $in <2 × str> AND stars $gte <int> | sort={'stars': -1} | limit=20
```

Placeholders describe sampled value types; `$exists` and `$type` show their fixed
literals. Sort order is preserved, and unset options are omitted. This display is
for inspection and logs; use `Workload.save()` for persistence. `repr(pattern)`
retains the detailed dataclass representation.

## Add selectivity constraints

Supply a prepared `MongoSampleEstimator` as `estimator=` to the generator, then pass
`min_selectivity` and `max_selectivity` to `generate()`. Every accepted instance must
meet those bounds on the estimator's sample. The generator does not prepare or close
the estimator. See the [end-to-end tutorial](tutorials.md#generate-and-evaluate-a-workload).

## Configure the experiment

Use one `MongoGenerationConfig` for predicate counts, included/excluded fields,
field/operator weights, and sort/projection/skip/limit settings. For example:

```python
config = MongoGenerationConfig(
    min_predicates=1,
    max_predicates=3,
    exclude_fields=["_id", "business_id"],
    sort_probability=0.5,
    projection_probability=0.5,
    limit_probability=0.5,
    limit_min=5,
    limit_max=100,
)
```

These are proposal settings, not promises about exact output frequencies. A
`validate_pattern` callback can enforce project-specific diversity constraints.
Generation returns all requested groups or raises `WorkloadGenerationError`; it does
not silently return a partial workload. Inspect `generator.last_stats` for rejection
counts. Attempt budgets and `timeout_seconds` bound search, but the deadline cannot
interrupt a running estimator call; configure executor timeouts too.

## Research boundaries

This generator supports flat find filters, not logical combinations, `$elemMatch`,
joins or aggregation generation. A fixed seed requires fixed schema values and
estimator responses for reproducibility. Save the generated workload as the durable
experiment input. Sample constraints are not full-population guarantees.

See the [generation reference](reference/mongodb/generation.md) for all options,
pattern fields, supported paths and failure diagnostics.

## Save and restore patterns

Patterns provide `to_dict()` / `from_dict()` for embedding in experiment summaries,
and `to_json()` / `from_json()` for standalone JSON:

```python
saved = pattern.to_dict()
restored = MongoQueryPattern.from_dict(saved)
assert restored == pattern
print(restored)

text = pattern.to_json()
assert MongoQueryPattern.from_json(text) == pattern
```

BONDI owns the versioned envelope and reconstructs collection references, predicate
objects and ordered sort tuples. Patterns store operand type labels and fixed
boolean/string values, so ordinary JSON suffices. Sampled query values remain in
workload files. Missing/unknown fields, unsupported versions and invalid patterns
are rejected. Dictionary results are independent of the original pattern.

With Yanex, embed `pattern.to_dict()` in a summary saved via `save_artifact()`.
After loading the summary, use `MongoQueryPattern.from_dict(summary["pattern"])`
to recover its readable string and `matches()` behavior. For a standalone artifact,
use `to_json()` and `from_json()` in Yanex's custom saver/loader hooks.
