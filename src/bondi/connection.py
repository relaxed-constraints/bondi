"""Connection settings shared by dataset loading and index administration."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MongoConnection:
    """Connect to MongoDB without a managed deployment.

    Args:
        uri: MongoDB connection string. Can include authSource and URI credentials.
        username: Optional username passed directly to PyMongo, without URI encoding.
        password: Optional password passed directly to PyMongo, without URI encoding.

    Supplied fields override the corresponding URI credentials. Omitted fields
    retain URI settings. Credentials are excluded from repr and load reports.
    """

    uri: str = field(repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value in (self.username, self.password):
            if value is not None and not isinstance(value, str):
                raise ValueError("MongoDB username and password must be strings or None")


@dataclass(frozen=True)
class CouchbaseConnection:
    """Connect to Couchbase without a managed deployment.

    Args:
        uri: SDK connection string, including custom port mappings if needed.
        username: Account with permissions for the requested load operations.
        password: Account password. Excluded from repr and load reports.
    """

    uri: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)


def normalize_connection(target):
    """Resolve connection settings without opening a client."""
    if isinstance(target, (MongoConnection, CouchbaseConnection)):
        return target
    from bondi.deployment import Deployment

    if not isinstance(target, Deployment):
        raise TypeError("Expected Deployment, MongoConnection or CouchbaseConnection")
    if target.backend == "mongodb":
        return MongoConnection(target.uri, target.username, target.password)
    if target.backend == "couchbase":
        return CouchbaseConnection(target.uri, target.username, target.password)
    raise ValueError(f"Unsupported deployment backend: {target.backend}")
