# Your first collection reference

A `MongoCollectionRef` identifies a logical MongoDB collection using a database
name and collection name. It contains no client, host or credentials. You can use
it without installing PyMongo or running MongoDB.

```python
from dbrtoolkit.mongodb import MongoCollectionRef

target = MongoCollectionRef(database="research", collection="businesses")
print(target.database)  # research
print(target.collection)  # businesses
```

## Understand the implementation

The class is a `dataclass`: Python generates its constructor, readable
representation and value equality from the two annotated fields. `frozen=True`
prevents field reassignment and, with these string fields, makes references
hashable. To change the target, construct another reference.

```python
same_target = MongoCollectionRef("research", "businesses")
assert target == same_target
assert len({target, same_target}) == 1
```

The generated constructor calls `__post_init__`, which checks each name. Non-string
values raise `TypeError`; empty strings and null characters raise `ValueError`.
Names are never stripped or case-normalized. Even whitespace-only names pass this
minimal validation; passing it does not guarantee acceptance by MongoDB.

References with the same names compare equal across deployments. A future executor
will supply the deployment, and execution records will identify that environment.
This class does not perform existence checks or create a collection.

See the [generated API reference](api.md) for the signature, arguments, exceptions
and executable docstring examples.
