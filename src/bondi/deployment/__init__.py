"""Manage named local research databases with Docker Compose.

Requires Docker and Compose v2 on the machine running Python. Deployment state
is stored in ~/.bondi/deployments, overridable with BONDI_DEPLOYMENT_DIR.
"""

from ._deployment import Deployment, deploy_mongodb, get_deployment, list_deployments

__all__ = ["Deployment", "deploy_mongodb", "get_deployment", "list_deployments"]
