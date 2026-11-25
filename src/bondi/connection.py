"""Immutable connection settings shared by database operations."""

from dataclasses import dataclass, field

__all__ = ["MongoConnection", "CouchbaseConnection", "PostgresConnection"]


@dataclass(frozen=True)
class MongoConnection:
    """MongoDB connection settings; construction does not open a client.

    Args:
        uri: MongoDB connection string. Can include authSource and URI credentials.
        username: Optional username passed directly to PyMongo, without URI encoding.
        password: Optional password passed directly to PyMongo, without URI encoding.

    Supplied fields override the corresponding URI credentials. Omitted fields
    retain URI settings. URI and credentials are excluded from repr and operation reports.

    Raises:
        TypeError: URI is not a string, or credentials are neither strings nor None.
    """

    uri: str = field(repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str):
            raise TypeError("uri must be a string")
        for value in (self.username, self.password):
            if value is not None and not isinstance(value, str):
                raise TypeError("MongoDB username and password must be strings or None")


@dataclass(frozen=True)
class CouchbaseConnection:
    """Couchbase connection settings; construction does not open a client.

    Args:
        uri: SDK connection string, including custom port mappings if needed.
        username: Account with permissions for the requested operations.
        password: Account password.

    URI and credentials are excluded from repr and operation reports.

    Raises:
        TypeError: URI, username or password is not a string.
    """

    uri: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str):
            raise TypeError("uri must be a string")
        if not isinstance(self.username, str) or not isinstance(self.password, str):
            raise TypeError("Couchbase username and password must be strings")


@dataclass(frozen=True)
class PostgresConnection:
    """PostgreSQL connection settings; construction does not open a client.

    Args:
        uri: PostgreSQL connection string. Selects the target database and may include credentials.
        username: Optional username passed directly to the driver, without URI encoding.
        password: Optional password passed directly to the driver, without URI encoding.

    Supplied fields override the corresponding URI credentials. Omitted fields
    retain URI settings. URI and credentials are excluded from repr and operation reports.

    Raises:
        TypeError: URI is not a string, or credentials are neither strings nor None.
    """

    uri: str = field(repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str):
            raise TypeError("uri must be a string")
        for value in (self.username, self.password):
            if value is not None and not isinstance(value, str):
                raise TypeError("PostgreSQL username and password must be strings or None")


def _validate_connection(
    connection: MongoConnection | CouchbaseConnection,
) -> MongoConnection | CouchbaseConnection:
    """Validate settings without opening a client."""
    if not isinstance(connection, (MongoConnection, CouchbaseConnection)):
        raise TypeError("Expected MongoConnection or CouchbaseConnection")
    return connection
