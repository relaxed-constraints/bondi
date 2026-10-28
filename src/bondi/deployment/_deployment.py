"""Persistent local deployment configuration and a small Compose adapter."""

import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

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
    """A saved MongoDB deployment; obtaining a handle does not start Docker.

    Use deploy_mongodb() or get_deployment() to obtain a handle. Connections use
    localhost, so Python and Docker must run on the same machine. Lifecycle
    methods never stop or remove unrelated Compose projects.

    Attributes:
        name: User-chosen deployment name.
        port: Localhost port exposed by MongoDB.
        image: Pinned MongoDB Docker image.
    """

    name: str
    port: int
    image: str
    _path: Path
    _project: str

    @property
    def uri(self) -> str:
        """MongoDB connection URI on the local machine."""
        return f"mongodb://127.0.0.1:{self.port}/"

    def _run(self, *arguments: str, timeout: float = 120) -> str:
        _timeout(timeout)
        if not (self._path / "deployment.json").exists():
            raise RuntimeError("Deployment was deleted; call deploy_mongodb() again")
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
        """Create/start the container and wait for MongoDB health readiness.

        Args:
            timeout: Maximum seconds for startup, including image download.
                Increase this for a first deployment on a slow connection.
        """
        _timeout(timeout)
        self._run(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            str(math.ceil(timeout)),
            "mongodb",
            timeout=timeout,
        )

    def stop(self, *, timeout: float = 120) -> None:
        """Stop MongoDB, retaining its container, configuration and data volume."""
        self._run("stop", "mongodb", timeout=timeout)

    def status(self) -> Status:
        """Return observed container state; Docker access errors raise RuntimeError.

        Returns:
            running, starting, unhealthy, stopped, or removed. Removed means
            no container exists; a retained data volume may still exist.
        """
        output = self._run("ps", "--all", "--format", "json", "mongodb")
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
        return "running" if row.get("Health") == "healthy" else "starting"

    def logs(self, *, tail: int = 50) -> str:
        """Return recent MongoDB logs to help diagnose startup failures."""
        if type(tail) is not int or tail < 1:
            raise ValueError("tail must be a positive integer")
        return self._run("logs", "--no-color", "--tail", str(tail), "mongodb")

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
    if config.get("format_version") != 1 or config.get("backend") != "mongodb":
        raise ValueError("Unsupported deployment configuration")
    return Deployment(name, config["port"], config["image"], path, config["project"])


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
    path = _directory(name)
    _timeout(timeout)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    if path.exists():
        deployment = get_deployment(name)
        if deployment.port != port:
            raise ValueError(
                f"Deployment {name!r} already uses port {deployment.port}. "
                f"Inspect it with 'bondi status {name}'. Use a different --name to keep it; "
                f"only if its data is disposable, run 'bondi remove {name}' "
                "before deploying again."
            )
        try:
            deployment.start(timeout=timeout)
        except (RuntimeError, OSError) as exc:
            raise RuntimeError(
                f"{exc}\nExisting deployment {name!r} was retained. "
                f"Inspect 'bondi logs {name}' and retry 'bondi start {name}'."
            ) from exc
        return deployment
    else:
        _check_port(port)
        template = json.loads(
            files("bondi.deployment").joinpath("mongodb.compose.json").read_text()
        )
        project = "bondi-" + name + "-" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
        service = template["services"]["mongodb"]
        service["ports"] = [f"127.0.0.1:{port}:27017"]
        config = {
            "format_version": 1,
            "backend": "mongodb",
            "port": port,
            "image": service["image"],
            "project": project,
        }
        path.mkdir(parents=True, exist_ok=False)
        try:
            (path / "compose.json").write_text(json.dumps(template, indent=2) + "\n")
            (path / "deployment.json").write_text(json.dumps(config, indent=2) + "\n")
            deployment = get_deployment(name)
        except BaseException:
            # Docker has not been called, so only these newly written files exist.
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
                f"Restore Docker access and run 'bondi remove {name}' "
                "to finish cleanup."
            ) from startup_error
        if isinstance(startup_error, (KeyboardInterrupt, SystemExit)):
            raise
        raise RuntimeError(
            f"Startup failed for {name!r}: {startup_error}\n"
            "The new deployment and its data were removed. Retry with a free port."
        ) from startup_error
    return deployment
