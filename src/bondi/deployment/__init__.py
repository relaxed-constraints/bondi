"""Manage named local research databases with Docker Compose.

Supports MongoDB and single-node Couchbase Community/Enterprise deployments.
Requires Docker and Compose v2 on the machine running Python. Deployment state
is stored in ~/.bondi/deployments, overridable with BONDI_DEPLOYMENT_DIR.
"""

from ._deployment import (
    Deployment,
    deploy_couchbase,
    deploy_mongodb,
    get_deployment,
    list_deployments,
)

__all__ = ["Deployment", "deploy_couchbase", "deploy_mongodb", "get_deployment", "list_deployments"]
