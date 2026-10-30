"""Persistent local deployment configuration and a small Compose adapter."""

import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Literal

from ._demo import DemoDataResult

Status = Literal["running", "starting", "unhealthy", "stopped", "removed"]


def _directory(name: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
        raise ValueError(
            "name must start with a lowercase letter; use 1–48 lowercase letters/digits/hyphens"
        )
    root = Path(os.environ.get("BONDI_DEPLOYMENT_DIR", Path.home() / ".bondi" / "deployments"))
    return root.expanduser().resolve() / name


def _check_port(port: int) -> None:
    # Advisory only: another process can acquire the port before Docker binds it.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError(
            f"Cannot bind localhost port {port}: {exc.strerror or exc}. "
            "Choose another --port (or port= in Python). No deployment was created."
        ) from exc


def _timeout(timeout: float) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a positive finite number of seconds")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number of seconds")


@dataclass(frozen=True)
class Deployment:
    """A saved database deployment; obtaining a handle does not start Docker.

    Use deploy_mongodb(), deploy_couchbase() or get_deployment() to obtain a handle. Connections use
    localhost, so Python and Docker must run on the same machine. Lifecycle
    methods never stop or remove unrelated Compose projects.

    Attributes:
        name: User-chosen deployment name.
        port: MongoDB port, or Couchbase management port.
        backend: mongodb or couchbase.
        query_port: Couchbase SQL++ port; None for MongoDB.
        kv_port: Couchbase key/value port; None for MongoDB.
        username: Couchbase administrator username.
        password: Couchbase password, excluded from repr.
        bucket: Default Couchbase bucket.
        edition: Couchbase community or enterprise.
        image: Pinned database Docker image.
    """

    name: str
    port: int
    image: str
    _path: Path
    _project: str
    backend: str = "mongodb"
    query_port: int | None = None
    kv_port: int | None = None
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    bucket: str | None = None
    edition: str | None = None

    @property
    def uri(self) -> str:
        """Database connection URI on the local machine (without credentials)."""
        if self.backend == "couchbase":
            return f"couchbase://127.0.0.1:{self.kv_port}?network=external"
        return f"mongodb://127.0.0.1:{self.port}/"

    @property
    def console_url(self) -> str | None:
        """Couchbase browser console URL, or None for MongoDB."""
        return f"http://127.0.0.1:{self.port}/" if self.backend == "couchbase" else None

    def _run(self, *arguments: str, timeout: float = 120) -> str:
        _timeout(timeout)
        if not (self._path / "deployment.json").exists():
            raise RuntimeError("Deployment was deleted; deploy it again")
        command = [
            "docker",
            "compose",
            "--project-name",
            self._project,
            "--file",
            str(self._path / "compose.json"),
            *arguments,
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=True, timeout=timeout
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Docker was not found. Install Docker with Compose v2.") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Docker operation timed out after {timeout}s.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Docker Compose failed: {detail}\nCheck Docker is running, Compose v2 is "
                "installed, and the configured port is free. Inspect logs() for startup failures."
            ) from exc
        return result.stdout

    def start(self, *, timeout: float = 120) -> None:
        """Create/start the container, initialize it and wait for database readiness.

        Args:
            timeout: Maximum seconds for startup, including image download.
                Increase this for a first deployment on a slow connection.
        """
        _timeout(timeout)
        deadline = time.monotonic() + timeout
        self._run(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            str(math.ceil(timeout)),
            self.backend,
            timeout=timeout,
        )
        if self.backend == "couchbase":
            from ._couchbase import initialize

            initialize(self, deadline=deadline)

    def stop(self, *, timeout: float = 120) -> None:
        """Stop the database, retaining its container, configuration and data volume."""
        self._run("stop", self.backend, timeout=timeout)

    def status(self) -> Status:
        """Return observed container state; Docker access errors raise RuntimeError.

        Returns:
            running, starting, unhealthy, stopped, or removed. Removed means
            no container exists; a retained data volume may still exist.
        """
        output = self._run("ps", "--all", "--format", "json", self.backend)
        # Compose versions emit either a JSON array or newline-delimited objects.
        if not output.strip():
            return "removed"
        rows = (
            json.loads(output)
            if output.lstrip().startswith("[")
            else [json.loads(line) for line in output.splitlines() if line.strip()]
        )
        if not rows:
            return "removed"
        row = rows[0]
        if row.get("State") != "running":
            return "stopped"
        if row.get("Health") == "unhealthy":
            return "unhealthy"
        if row.get("Health") != "healthy":
            return "starting"
        if self.backend == "couchbase":
            from ._couchbase import ready

            try:
                ready(self)
            except (RuntimeError, ValueError):
                return "starting"
        return "running"

    def logs(self, *, tail: int = 50) -> str:
        """Return recent database logs to help diagnose startup failures."""
        if type(tail) is not int or tail < 1:
            raise ValueError("tail must be a positive integer")
        return self._run("logs", "--no-color", "--tail", str(tail), self.backend)

    def load_demo_data(
        self,
        *,
        database: str | None = None,
        scope: str | None = None,
        collection: str = "business",
        create_primary_index: bool = False,
    ) -> "DemoDataResult":
        """Upsert eight packaged fictional businesses into this running deployment.

        Matching demo IDs are replaced; unrelated documents are preserved. Repeating
        the call creates no duplicates. Failures may leave partial writes; retrying
        is safe. Lifecycle operations and concurrent loads must be serialized.

        Args:
            database: MongoDB database (default demo); invalid for Couchbase.
            scope: Couchbase scope (default _default); invalid for MongoDB.
            collection: Collection to create if missing (default business).
            create_primary_index: Explicitly create a Couchbase primary index.
                Invalid for MongoDB. Defaults to False.

        Returns:
            Destination and number of documents loaded, including replacements.

        Raises:
            ValueError: Invalid or backend-inappropriate options.
            RuntimeError: Deployment is not running or loading failed.
        """
        from ._demo import load_demo_data

        return load_demo_data(
            self,
            database=database,
            scope=scope,
            collection=collection,
            create_primary_index=create_primary_index,
        )

    def remove(self, *, delete_data: bool = False, timeout: float = 120) -> None:
        """Remove the container/network, retaining data by default.

        With delete_data=False, configuration is retained so start() recreates
        the container using the same volume. With True, also delete the volume
        and saved configuration. Existing handles must then be discarded.
        """
        if type(delete_data) is not bool:
            raise ValueError("delete_data must be a boolean")
        args = ("down", "--volumes") if delete_data else ("down",)
        self._run(*args, timeout=timeout)
        if delete_data:
            shutil.rmtree(self._path)


def get_deployment(name: str) -> Deployment:
    """Load a saved deployment by name without contacting Docker.

    Raises:
        FileNotFoundError: No configuration exists for this name.
        ValueError: Configuration is incompatible or malformed.
    """
    path = _directory(name)
    config = json.loads((path / "deployment.json").read_text())
    if config.get("format_version") != 1 or config.get("backend") not in {"mongodb", "couchbase"}:
        raise ValueError("Unsupported deployment configuration")
    extra = {
        key: config[key]
        for key in ("backend", "query_port", "kv_port", "username", "password", "bucket", "edition")
        if key in config
    }
    return Deployment(name, config["port"], config["image"], path, config["project"], **extra)


def list_deployments() -> list[Deployment]:
    """List saved deployment handles (including stopped/removed containers)."""
    root = _directory("mongodb").parent
    return [get_deployment(path.parent.name) for path in sorted(root.glob("*/deployment.json"))]


def deploy_mongodb(
    name: str = "mongodb",
    *,
    port: int = 27017,
    timeout: float = 120,
) -> Deployment:
    """Create and start a named local MongoDB database, or reuse a matching one.

    Args:
        name: Deployment identity, default mongodb.
        port: Localhost port (1–65535); each simultaneous deployment needs its own.
        timeout: Startup deadline in seconds, including image download.

    Returns:
        A ready Deployment, usable with MongoExecutor.from_uri(deployment.uri).

    Raises:
        ValueError: Invalid arguments or a saved port conflicts with this request.
        RuntimeError: Port unavailable or startup failed. New deployments are cleaned
            up on failure; existing deployments retain their data and configuration.
            If cleanup fails, metadata is retained with recovery instructions.

    Saved deployments retain their original image and assets across BONDI upgrades.
    Calls managing the same deployment must be serialized by the caller.
    """
    return _deploy(name, {"backend": "mongodb", "port": port}, timeout=timeout)


def deploy_couchbase(
    name: str = "couchbase",
    *,
    management_port: int = 8091,
    query_port: int = 8093,
    kv_port: int = 11210,
    edition: Literal["community", "enterprise"] = "community",
    username: str = "Administrator",
    password: str = "bondi-local",
    bucket: str = "demo",
    timeout: float = 300,
) -> Deployment:
    """Deploy a local Couchbase node with Data, Query and Index services.

    Creates a 256 MiB bucket with its default scope/collection; no data or indexes
    are added. Community is the default. All three distinct ports bind localhost.
    Credentials are saved in owner-only metadata and never printed by the CLI.

    Args:
        name: Saved deployment identity.
        management_port: Console/REST port.
        query_port: SQL++ service port.
        kv_port: SDK bootstrap/key-value port.
        edition: community or enterprise (both pinned to 7.6.2).
        username: Local administrator username.
        password: Local password, at least six characters.
        bucket: Bucket name, default demo.
        timeout: Total startup and initialization deadline in seconds.

    Returns:
        A ready deployment with uri, console_url and credentials.
    """
    if edition not in {"community", "enterprise"}:
        raise ValueError("edition must be community or enterprise")
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", username):
        raise ValueError("username must use letters, digits, underscores or hyphens")
    if not isinstance(password, str) or len(password) < 6 or any(ord(c) < 32 for c in password):
        raise ValueError("password must have at least six characters and no control characters")
    if not isinstance(bucket, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", bucket):
        raise ValueError("bucket must use letters, digits, underscores or hyphens")
    return _deploy(
        name,
        {
            "backend": "couchbase",
            "port": management_port,
            "query_port": query_port,
            "kv_port": kv_port,
            "edition": edition,
            "username": username,
            "password": password,
            "bucket": bucket,
        },
        timeout=timeout,
    )


def _deploy(name: str, settings: dict, *, timeout: float) -> Deployment:
    path = _directory(name)
    _timeout(timeout)
    backend = settings["backend"]
    ports = [settings[key] for key in ("port", "query_port", "kv_port") if key in settings]
    if any(type(port) is not int or not 1 <= port <= 65535 for port in ports):
        raise ValueError("ports must be integers between 1 and 65535")
    if len(set(ports)) != len(ports):
        raise ValueError("Couchbase service ports must be distinct")
    if path.exists():
        deployment = get_deployment(name)
        differences = [key for key, value in settings.items() if getattr(deployment, key) != value]
        if differences:
            raise ValueError(
                f"Deployment {name!r} already uses saved configuration; conflicting fields: "
                f"{', '.join(differences)}. Inspect 'bondi status {name}'. "
                "Use another name to keep it, or remove it only if its data is disposable."
            )
        try:
            deployment.start(timeout=timeout)
        except (RuntimeError, OSError, ValueError) as exc:
            raise RuntimeError(
                f"{exc}\nExisting deployment {name!r} was retained. "
                f"Inspect 'bondi logs {name}' and retry 'bondi start {name}'."
            ) from exc
        return deployment
    for port in ports:
        _check_port(port)
    template = json.loads(files("bondi.deployment").joinpath(f"{backend}.compose.json").read_text())
    project = "bondi-" + name + "-" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
    service = template["services"][backend]
    internal_ports = [27017] if backend == "mongodb" else [8091, 8093, 11210]
    service["ports"] = [
        f"127.0.0.1:{host}:{internal}" for host, internal in zip(ports, internal_ports)
    ]
    if backend == "couchbase":
        service["image"] = f"couchbase:{settings['edition']}-7.6.2"
    config = {"format_version": 1, **settings, "image": service["image"], "project": project}
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        (path / "compose.json").write_text(json.dumps(template, indent=2) + "\n")
        metadata = path / "deployment.json"
        with open(metadata, "x", opener=lambda file, flags: os.open(file, flags, 0o600)) as stream:
            stream.write(json.dumps(config, indent=2) + "\n")
        deployment = get_deployment(name)
    except BaseException:
        shutil.rmtree(path)
        raise
    try:
        deployment.start(timeout=timeout)
    except BaseException as startup_error:
        try:
            deployment.remove(delete_data=True)
        except BaseException as cleanup_error:
            raise RuntimeError(
                f"Startup failed for {name!r}: {startup_error}. "
                f"Cleanup also failed: {cleanup_error}. Metadata retained at {path}. "
                f"Restore Docker access and run 'bondi remove {name}' to finish cleanup."
            ) from startup_error
        if isinstance(startup_error, (KeyboardInterrupt, SystemExit)):
            raise
        raise RuntimeError(
            f"Startup failed for {name!r}: {startup_error}\n"
            "The new deployment and its data were removed. Check the error and retry."
        ) from startup_error
    return deployment
