# API reference

::: dbrtoolkit.mongodb.MongoCollectionRef
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true
      members: []

::: dbrtoolkit.mongodb.MongoFindQuery
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true
      members: [validate, to_json, from_json, fingerprint]

::: dbrtoolkit.mongodb.MongoAggregateQuery
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true
      members: [validate, to_json, from_json, fingerprint]

::: dbrtoolkit.couchbase.CouchbaseQuery
    options:
      show_root_heading: true
      heading_level: 2
      show_signature_annotations: true
      members: [validate, to_json, from_json, fingerprint]

::: dbrtoolkit.query.Query
    options:
      show_root_heading: true
      heading_level: 2
      members: [backend, validate, to_json, fingerprint]

::: dbrtoolkit.workload.WorkloadEntry
    options:
      show_root_heading: true
      heading_level: 2
      members: [validate]

::: dbrtoolkit.workload.Workload
    options:
      show_root_heading: true
      heading_level: 2
      members: [validate, save, load, __len__, __iter__, __getitem__]

::: dbrtoolkit.execution.ExecutionResult
    options:
      show_root_heading: true
      heading_level: 2
      members: [status]

::: dbrtoolkit.mongodb.AsyncMongoDBExecutor
    options:
      show_root_heading: true
      heading_level: 2
      members: [from_uri, close, run, run_workload, explain, explain_workload]
