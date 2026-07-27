"""n8n MCP Server - Model Context Protocol server for n8n workflow automation.

Provides AI assistants with comprehensive access to n8n's workflow automation platform:
- Workflow CRUD operations
- Execution monitoring and management
- Credential management
- Pipeline building and validation
- Variable management
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")

# ---------------------------------------------------------------------------
# HTTP client helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if N8N_API_KEY:
        h["X-N8N-API-KEY"] = N8N_API_KEY
    return h


def _url(path: str) -> str:
    base = N8N_BASE_URL.rstrip("/")
    return f"{base}/api/v1{path}"


async def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    """Make an async HTTP request to the n8n API and return parsed JSON."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, _url(path), headers=_headers(), **kwargs)
        resp.raise_for_status()
        data = resp.json()
        # n8n wraps responses in {"data": ...}
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    name: str = Field(..., description="Workflow name")
    nodes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of workflow nodes. Each node needs: id, name, type, typeVersion, position, parameters"
    )
    connections: dict[str, Any] = Field(
        default_factory=dict,
        description="Node connections map"
    )
    settings: dict[str, Any] = Field(
        default_factory=lambda: {"executionOrder": "v1"},
        description="Workflow settings"
    )
    static_data: Any = Field(default=None, description="Static workflow data")
    tags: list[str] = Field(default_factory=list, description="Workflow tags")


class WorkflowUpdate(BaseModel):
    name: str | None = None
    nodes: list[dict[str, Any]] | None = None
    connections: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    static_data: Any = None
    tags: list[str] | None = None


class ExecutionListParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    cursor: str | None = Field(default=None, description="Pagination cursor")
    status: str | None = Field(
        default=None,
        description="Filter by status: 'error', 'success', 'waiting', 'running', 'canceled', 'new', 'crashed'"
    )
    workflow_id: str | None = Field(default=None, description="Filter by workflow ID")
    project_id: str | None = Field(default=None, description="Filter by project ID")


class CredentialCreate(BaseModel):
    name: str = Field(..., description="Credential name")
    type: str = Field(..., description="Credential type (e.g., 'httpHeaderAuth', 'oAuth2Api', 'googleApi')")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Credential data (type-specific)"
    )
    nodes_to_access: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Nodes that can use this credential"
    )


class VariableCreate(BaseModel):
    key: str = Field(..., description="Variable name/key")
    value: str = Field(..., description="Variable value")


class NodeSearchParams(BaseModel):
    query: str = Field(..., description="Search query for node types (e.g., 'http', 'slack', 'trigger')")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="n8n-mcp-server",
    version="1.0.0",
)


# ---- Server info & diagnostics ---------------------------------------------

@mcp.tool(description="Get n8n server status and version info")
async def n8n_status() -> dict[str, Any]:
    """Check n8n server health and return version information."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Try the root endpoint for version info
            resp = await client.get(N8N_BASE_URL.rstrip("/") + "/", headers=_headers())
            health = await client.get(N8N_BASE_URL.rstrip("/") + "/healthz", headers=_headers())
            return {
                "status": "ok" if health.status_code == 200 else "degraded",
                "health": health.json() if health.status_code == 200 else None,
                "api_configured": bool(N8N_API_KEY),
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool(description="List all available n8n API endpoints (OpenAPI schema)")
async def n8n_api_schema() -> dict[str, Any]:
    """Get the OpenAPI schema for the n8n REST API."""
    try:
        result = await _request("GET", "/schema")
        return {"schema": result}
    except Exception as e:
        return {"error": str(e)}


# ---- Workflow management ---------------------------------------------------

@mcp.tool(description="List all workflows with optional filters")
async def list_workflows(
    active: bool | None = None,
    tags: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List workflows from n8n instance.

    Args:
        active: Filter by active status
        tags: Comma-separated tag names
        project_id: Filter by project ID
        limit: Max results (1-200)
        cursor: Pagination cursor from previous response
    """
    params: dict[str, Any] = {"limit": limit}
    if active is not None:
        params["active"] = str(active).lower()
    if tags:
        params["tags"] = tags
    if project_id:
        params["projectId"] = project_id
    if cursor:
        params["cursor"] = cursor

    try:
        result = await _request("GET", "/workflows", params=params)
        return {"workflows": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Get a single workflow by ID with full node and connection details")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Get detailed information about a specific workflow.

    Args:
        workflow_id: The workflow ID
    """
    try:
        result = await _request("GET", f"/workflows/{workflow_id}")
        return {"workflow": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Create a new workflow with nodes and connections")
async def create_workflow(
    name: str,
    nodes: str = "[]",
    connections: str = "{}",
    settings: str = '{"executionOrder":"v1"}',
    tags: str = "[]",
) -> dict[str, Any]:
    """Create a new workflow.

    Args:
        name: Workflow name
        nodes: JSON array of node objects (as string)
        connections: JSON object of connections (as string)
        settings: JSON object of settings (as string)
        tags: JSON array of tag names (as string)

    Each node object should have:
        - id: unique string ID
        - name: display name
        - type: node type (e.g. 'n8n-nodes-base.httpRequest')
        - typeVersion: number (e.g. 4.2)
        - position: [x, y] coordinates
        - parameters: object with node-specific config

    Example node:
    {
        "id": "abc123",
        "name": "HTTP Request",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [450, 300],
        "parameters": {
            "method": "GET",
            "url": "https://api.example.com/data"
        }
    }
    """
    import json as _json
    try:
        payload = {
            "name": name,
            "nodes": _json.loads(nodes) if isinstance(nodes, str) else nodes,
            "connections": _json.loads(connections) if isinstance(connections, str) else connections,
            "settings": _json.loads(settings) if isinstance(settings, str) else settings,
            "staticData": None,
            
        }
        result = await _request("POST", "/workflows", json=payload)
        return {"workflow": result, "message": f"Workflow '{name}' created successfully"}
    except ValueError as e:
        return {"error": f"Invalid JSON in parameters: {e}"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Update an existing workflow - full or partial update")
async def update_workflow(
    workflow_id: str,
    name: str | None = None,
    active: bool | None = None,
    nodes: str | None = None,
    connections: str | None = None,
    settings: str | None = None,
    tags: str | None = None,
) -> dict[str, Any]:
    """Update an existing workflow.

    Args:
        workflow_id: Workflow ID to update
        name: New workflow name
        active: Activate/deactivate the workflow
        nodes: JSON array of nodes (full replacement)
        connections: JSON object of connections
        settings: JSON object of settings
        tags: JSON array of tag names
    """
    import json as _json
    try:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if active is not None:
            payload["active"] = active
        if nodes is not None:
            payload["nodes"] = _json.loads(nodes)
        if connections is not None:
            payload["connections"] = _json.loads(connections)
        if settings is not None:
            payload["settings"] = _json.loads(settings)
        if tags is not None:
            payload["tags"] = _json.loads(tags)

        result = await _request("PUT", f"/workflows/{workflow_id}", json=payload)
        return {"workflow": result, "message": f"Workflow {workflow_id} updated"}
    except ValueError as e:
        return {"error": f"Invalid JSON in parameters: {e}"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Delete a workflow by ID")
async def delete_workflow(workflow_id: str) -> dict[str, Any]:
    """Delete a workflow.

    Args:
        workflow_id: Workflow ID to delete
    """
    try:
        await _request("DELETE", f"/workflows/{workflow_id}")
        return {"message": f"Workflow {workflow_id} deleted successfully"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Activate a workflow to start processing triggers")
async def activate_workflow(workflow_id: str) -> dict[str, Any]:
    """Activate a workflow.

    Args:
        workflow_id: Workflow ID to activate
    """
    try:
        result = await _request("POST", f"/workflows/{workflow_id}/activate")
        return {"workflow": result, "message": f"Workflow {workflow_id} activated"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Deactivate a workflow to stop processing triggers")
async def deactivate_workflow(workflow_id: str) -> dict[str, Any]:
    """Deactivate a workflow.

    Args:
        workflow_id: Workflow ID to deactivate
    """
    try:
        result = await _request("POST", f"/workflows/{workflow_id}/deactivate")
        return {"workflow": result, "message": f"Workflow {workflow_id} deactivated"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Duplicate/create a copy of an existing workflow")
async def duplicate_workflow(workflow_id: str, name: str | None = None) -> dict[str, Any]:
    """Duplicate an existing workflow.

    Args:
        workflow_id: Source workflow ID
        name: Name for the new workflow (default: "Copy of <original>")
    """
    try:
        # Get the original workflow
        original = await _request("GET", f"/workflows/{workflow_id}")
        # Create a copy
        payload = {
            "name": name or f"Copy of {original.get('name', 'workflow')}",
            "nodes": original.get("nodes", []),
            "connections": original.get("connections", {}),
            "settings": original.get("settings", {"executionOrder": "v1"}),
            "staticData": original.get("staticData"),
            "tags": original.get("tags", []),
        }
        result = await _request("POST", "/workflows", json=payload)
        return {"workflow": result, "message": f"Workflow duplicated from {workflow_id}"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: (e.response.text)"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Export a workflow as JSON (portable format for backup/transfer)")
async def export_workflow(workflow_id: str) -> dict[str, Any]:
    """Export workflow as a portable JSON object.

    Args:
        workflow_id: Workflow ID to export
    """
    try:
        result = await _request("GET", f"/workflows/{workflow_id}")
        return {"workflow": result, "format": "n8n-workflow-json"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Import a workflow from JSON (backup/transfer)")
async def import_workflow(workflow_json: str) -> dict[str, Any]:
    """Import a workflow from its JSON export.

    Args:
        workflow_json: JSON string of the exported workflow
    """
    import json as _json
    try:
        data = _json.loads(workflow_json)
        result = await _request("POST", "/workflows", json=data)
        return {"workflow": result, "message": f"Workflow '{result.get('name')}' imported"}
    except ValueError as e:
        return {"error": f"Invalid JSON: {e}"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="List workflow versions/history")
async def list_workflow_history(workflow_id: str, limit: int = 20) -> dict[str, Any]:
    """List version history of a workflow.

    Args:
        workflow_id: Workflow ID
        limit: Max versions to return
    """
    try:
        result = await _request("GET", f"/workflows/{workflow_id}/versions", params={"limit": limit})
        return {"versions": result}
    except httpx.HTTPStatusError as e:
        # This endpoint might not exist in all n8n versions
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}. Note: workflow history requires n8n enterprise."}
    except Exception as e:
        return {"error": str(e)}


# ---- Execution management ---------------------------------------------------

@mcp.tool(description="List workflow executions with filtering")
async def list_executions(
    limit: int = 20,
    status: str | None = None,
    workflow_id: str | None = None,
    project_id: str | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List workflow executions with optional filters.

    Args:
        limit: Max results (1-200)
        status: Filter by status - 'error', 'success', 'waiting', 'running', 'canceled', 'new', 'crashed'
        workflow_id: Filter by workflow ID
        project_id: Filter by project ID
        cursor: Pagination cursor
    """
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    if workflow_id:
        params["workflowId"] = workflow_id
    if project_id:
        params["projectId"] = project_id
    if cursor:
        params["cursor"] = cursor

    try:
        result = await _request("GET", "/executions", params=params)
        return {"executions": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Get detailed information about a specific execution")
async def get_execution(execution_id: str, include_data: bool = False) -> dict[str, Any]:
    """Get execution details.

    Args:
        execution_id: Execution ID
        include_data: Include full node output data (can be large)
    """
    try:
        params = {"includeData": str(include_data).lower()}
        result = await _request("GET", f"/executions/{execution_id}", params=params)
        return {"execution": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Delete an execution record")
async def delete_execution(execution_id: str) -> dict[str, Any]:
    """Delete an execution.

    Args:
        execution_id: Execution ID to delete
    """
    try:
        await _request("DELETE", f"/executions/{execution_id}")
        return {"message": f"Execution {execution_id} deleted"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Retry a failed execution")
async def retry_execution(execution_id: str, load_data: bool = False) -> dict[str, Any]:
    """Retry a failed execution.

    Args:
        execution_id: Execution ID to retry
        load_data: Reload execution data before retry
    """
    try:
        result = await _request("POST", f"/executions/{execution_id}/retry",
                                json={"loadWorkflow": load_data})
        return {"execution": result, "message": f"Execution {execution_id} retry initiated"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Stop a running execution")
async def stop_execution(execution_id: str) -> dict[str, Any]:
    """Stop a running execution.

    Args:
        execution_id: Execution ID to stop
    """
    try:
        result = await _request("POST", f"/executions/{execution_id}/stop")
        return {"execution": result, "message": f"Execution {execution_id} stopped"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Manually trigger a workflow execution (equivalent to clicking 'Execute Workflow' in UI)")
async def execute_workflow(workflow_id: str) -> dict[str, Any]:
    """Manually trigger a workflow execution.

    Args:
        workflow_id: Workflow ID to execute
    """
    try:
        # First activate if not active
        wf = await _request("GET", f"/workflows/{workflow_id}")
        if not wf.get("active"):
            return {"error": f"Workflow {workflow_id} is not active. Activate it first using activate_workflow."}

        result = await _request("POST", f"/workflows/{workflow_id}/execute")
        return {"execution": result, "message": f"Workflow {workflow_id} execution started"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Get execution statistics for a workflow (success/failure counts)")
async def get_execution_stats(workflow_id: str | None = None) -> dict[str, Any]:
    """Get execution statistics.

    Args:
        workflow_id: Optional workflow ID to filter stats
    """
    try:
        params = {}
        if workflow_id:
            params["workflowId"] = workflow_id
        result = await _request("GET", "/executions", params={**params, "limit": 1})
        # n8n returns total count in the response
        return {"stats": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


# ---- Credential management --------------------------------------------------

@mcp.tool(description="List all credentials (names and types only, no secret data)")
async def list_credentials(
    credential_type: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List credentials. Does NOT return sensitive credential data.

    Args:
        credential_type: Filter by credential type
        project_id: Filter by project ID
        limit: Max results
    """
    params: dict[str, Any] = {"limit": limit}
    if credential_type:
        params["credentialType"] = credential_type
    if project_id:
        params["projectId"] = project_id

    try:
        result = await _request("GET", "/credentials", params=params)
        # Remove sensitive data from response
        safe = []
        for cred in (result if isinstance(result, list) else []):
            safe.append({
                "id": cred.get("id"),
                "name": cred.get("name"),
                "type": cred.get("type"),
                "nodes_to_access": cred.get("nodesToAccess", []),
                "is_managed": cred.get("isManaged", False),
            })
        return {"credentials": safe}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Get a credential by ID (includes type-specific data)")
async def get_credential(credential_id: str) -> dict[str, Any]:
    """Get credential details by ID.

    Args:
        credential_id: Credential ID
    """
    try:
        result = await _request("GET", f"/credentials/{credential_id}")
        return {"credential": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Create a new credential")
async def create_credential(
    name: str,
    credential_type: str,
    data: str,
) -> dict[str, Any]:
    """Create a new credential.

    Args:
        name: Credential name
        credential_type: Type ID (e.g., 'httpHeaderAuth', 'oAuth2Api', 'googleApi', 'slackApi')
        data: JSON string with credential data (type-specific)

    Examples:
        HTTP Header Auth: {"name": "X-API-KEY", "value": "your-api-key"}
        OAuth2: {"clientId": "...", "clientSecret": "...", "accessTokenUrl": "..."}
        Google API: {"email": "...", "privateKey": "..."}
    """
    import json as _json
    try:
        payload = {
            "name": name,
            "type": credential_type,
            "data": _json.loads(data),
        }
        result = await _request("POST", "/credentials", json=payload)
        return {"credential": {"id": result.get("id"), "name": name, "type": credential_type},
                "message": f"Credential '{name}' created"}
    except ValueError as e:
        return {"error": f"Invalid JSON data: {e}"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Delete a credential")
async def delete_credential(credential_id: str) -> dict[str, Any]:
    """Delete a credential.

    Args:
        credential_id: Credential ID to delete
    """
    try:
        await _request("DELETE", f"/credentials/{credential_id}")
        return {"message": f"Credential {credential_id} deleted"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


# ---- Variables management ---------------------------------------------------

@mcp.tool(description="List all environment variables defined in n8n")
async def list_variables() -> dict[str, Any]:
    """List all n8n variables (environment-level, not workflow-level)."""
    try:
        result = await _request("GET", "/variables")
        return {"variables": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Create a new variable in n8n")
async def create_variable(key: str, value: str) -> dict[str, Any]:
    """Create a new n8n variable.

    Args:
        key: Variable name
        value: Variable value
    """
    try:
        payload = {"key": key, "value": value}
        result = await _request("POST", "/variables", json=payload)
        return {"variable": result, "message": f"Variable '{key}' created"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Delete a variable")
async def delete_variable(variable_id: str) -> dict[str, Any]:
    """Delete an n8n variable.

    Args:
        variable_id: Variable ID to delete
    """
    try:
        await _request("DELETE", f"/variables/{variable_id}")
        return {"message": f"Variable {variable_id} deleted"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


# ---- Tags management -------------------------------------------------------

@mcp.tool(description="List all workflow tags")
async def list_tags() -> dict[str, Any]:
    """List all workflow tags."""
    try:
        result = await _request("GET", "/tags")
        return {"tags": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


# ---- Project management ----------------------------------------------------

@mcp.tool(description="List all projects")
async def list_projects() -> dict[str, Any]:
    """List all projects (n8n enterprise feature)."""
    try:
        result = await _request("GET", "/projects")
        return {"projects": result}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}


# ---- Pipeline building helpers ---------------------------------------------

@mcp.tool(description="Get a minimal workflow template with a trigger + one action node to start building a pipeline")
async def get_workflow_template(
    trigger_type: str = "manualTrigger",
    action_type: str = "n8n-nodes-base.set",
) -> dict[str, Any]:
    """Get a minimal workflow template for building a pipeline.

    Args:
        trigger_type: Trigger node type (e.g., 'manualTrigger', 'webhook', 'scheduleTrigger', 'cron')
        action_type: First action node type (e.g., 'n8n-nodes-base.httpRequest', 'n8n-nodes-base.set')

    Returns a workflow JSON that can be passed to create_workflow.
    """
    import json as _json

    trigger_id = "trigger-1"
    action_id = "action-1"

    trigger_nodes = {
        "manualTrigger": {
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "parameters": {},
        },
        "webhook": {
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "parameters": {
                "httpMethod": "POST",
                "path": "webhook",
                "responseMode": "onReceived",
            },
        },
        "scheduleTrigger": {
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "parameters": {
                "rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]},
            },
        },
    }

    trigger_config = trigger_nodes.get(trigger_type, trigger_nodes["manualTrigger"])
    trigger_name = trigger_type if trigger_type in trigger_nodes else "Manual Trigger"

    template = {
        "name": f"New Pipeline ({trigger_name})",
        "nodes": [
            {
                "id": trigger_id,
                "name": trigger_name,
                "position": [250, 300],
                **trigger_config,
            },
            {
                "id": action_id,
                "name": action_type.split(".")[-1],
                "type": action_type,
                "typeVersion": 3.4,
                "position": [500, 300],
                "parameters": {},
            },
        ],
        "connections": {
            trigger_name: {
                "main": [[{"node": action_type.split(".")[-1], "type": "main", "index": 0}]],
            },
        },
        "settings": {"executionOrder": "v1"},
        "tags": [],
    }

    return {
        "template": template,
        "json": _json.dumps(template, indent=2),
        "instructions": "Modify the template nodes/parameters and pass to create_workflow. "
                        "Add more nodes and update connections as needed.",
    }


@mcp.tool(description="Validate a workflow structure (nodes, connections, required parameters)")
async def validate_workflow_structure(workflow_json: str) -> dict[str, Any]:
    """Validate a workflow JSON structure before creating it in n8n.

    Args:
        workflow_json: JSON string of the workflow to validate
    """
    import json as _json

    errors = []
    warnings = []

    try:
        wf = _json.loads(workflow_json)
    except ValueError as e:
        return {"valid": False, "errors": [f"Invalid JSON: {e}"]}

    # Check required fields
    if "name" not in wf:
        errors.append("Missing 'name' field")
    if "nodes" not in wf:
        errors.append("Missing 'nodes' field")
    elif not isinstance(wf["nodes"], list):
        errors.append("'nodes' must be an array")
    elif len(wf["nodes"]) == 0:
        errors.append("Workflow must have at least one node")

    # Validate nodes
    node_ids = set()
    node_names = set()
    for i, node in enumerate(wf.get("nodes", [])):
        prefix = f"Node {i}"
        if "id" not in node:
            errors.append(f"{prefix}: missing 'id'")
        elif node["id"] in node_ids:
            errors.append(f"{prefix}: duplicate id '{node['id']}'")
        else:
            node_ids.add(node["id"])

        if "name" not in node:
            errors.append(f"{prefix}: missing 'name'")
        elif node["name"] in node_names:
            warnings.append(f"{prefix}: duplicate name '{node['name']}'")
        else:
            node_names.add(node["name"])

        if "type" not in node:
            errors.append(f"{prefix}: missing 'type'")
        if "typeVersion" not in node:
            warnings.append(f"{prefix}: missing 'typeVersion'")
        if "position" not in node:
            warnings.append(f"{prefix}: missing 'position'")
        elif not isinstance(node["position"], list) or len(node["position"]) != 2:
            errors.append(f"{prefix}: 'position' must be [x, y]")

    # Validate connections
    connections = wf.get("connections", {})
    for source_name, outputs in connections.items():
        if source_name not in node_names:
            warnings.append(f"Connection source '{source_name}' not found in nodes")
        if isinstance(outputs, dict):
            for output_key, targets in outputs.items():
                if isinstance(targets, list):
                    for target_list in targets:
                        if isinstance(target_list, list):
                            for target in target_list:
                                if isinstance(target, dict):
                                    target_name = target.get("node", "")
                                    if target_name and target_name not in node_names:
                                        warnings.append(
                                            f"Connection target '{target_name}' not found in nodes"
                                        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(wf.get("nodes", [])),
        "connection_count": len(connections),
    }


@mcp.tool(description="Get common n8n node types and their descriptions for building workflows")
async def list_common_node_types() -> dict[str, Any]:
    """List commonly used n8n node types organized by category."""
    return {
        "triggers": [
            {"type": "n8n-nodes-base.manualTrigger", "description": "Manual trigger - execute workflow on demand"},
            {"type": "n8n-nodes-base.webhook", "description": "Webhook trigger - receive HTTP requests"},
            {"type": "n8n-nodes-base.scheduleTrigger", "description": "Schedule trigger - run on a timer"},
            {"type": "n8n-nodes-base.cron", "description": "Cron trigger - advanced scheduling"},
            {"type": "n8n-nodes-base.emailTrigger", "description": "Email trigger - react to incoming emails"},
            {"type": "n8n-nodes-base.formTrigger", "description": "Form trigger - react to form submissions"},
        ],
        "actions": [
            {"type": "n8n-nodes-base.httpRequest", "description": "HTTP Request - call any API endpoint"},
            {"type": "n8n-nodes-base.set", "description": "Set - set/modify data fields"},
            {"type": "n8n-nodes-base.code", "description": "Code - run JavaScript/Python code"},
            {"type": "n8n-nodes-base.if", "description": "IF - conditional branching (true/false)"},
            {"type": "n8n-nodes-base.switch", "description": "Switch - multi-branch routing"},
            {"type": "n8n-nodes-base.merge", "description": "Merge - combine data from multiple branches"},
            {"type": "n8n-nodes-base.splitInBatches", "description": "Split In Batches - process data in chunks"},
            {"type": "n8n-nodes-base.filter", "description": "Filter - filter data by conditions"},
            {"type": "n8n-nodes-base.aggregate", "description": "Aggregate - group and summarize data"},
            {"type": "n8n-nodes-base.splitOut", "description": "Split Out - split arrays into individual items"},
            {"type": "n8n-nodes-base.wait", "description": "Wait - pause execution"},
            {"type": "n8n-nodes-base.respondToWebhook", "description": "Respond to Webhook - send webhook response"},
            {"type": "n8n-nodes-base.executeWorkflow", "description": "Execute Workflow - call another workflow"},
            {"type": "n8n-nodes-base.stopAndError", "description": "Stop and Error - halt with error message"},
        ],
        "data_transform": [
            {"type": "n8n-nodes-base.moveDataKeys", "description": "Move Data Keys - rename fields"},
            {"type": "n8n-nodes-base.removeDuplicates", "description": "Remove Duplicates - deduplicate data"},
            {"type": "n8n-nodes-base.sort", "description": "Sort - sort data by field"},
            {"type": "n8n-nodes-base.limit", "description": "Limit - limit number of items"},
            {"type": "n8n-nodes-base.dateTime", "description": "Date & Time - parse/format dates"},
        ],
        "ai": [
            {"type": "@n8n/n8n-nodes-langchain.agent", "description": "AI Agent - autonomous AI agent"},
            {"type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "description": "OpenAI Chat Model"},
            {"type": "@n8n/n8n-nodes-langchain.lmChatAnthropic", "description": "Anthropic Chat Model"},
            {"type": "@n8n/n8n-nodes-langchain.toolHttpRequest", "description": "HTTP Request Tool for AI agents"},
            {"type": "@n8n/n8n-nodes-langchain.memoryBufferWindow", "description": "Window Buffer Memory for AI agents"},
        ],
        "popular_integrations": [
            {"type": "n8n-nodes-base.slack", "description": "Slack - send messages, react to events"},
            {"type": "n8n-nodes-base.telegram", "description": "Telegram - bot messaging"},
            {"type": "n8n-nodes-base.discord", "description": "Discord - bot messaging"},
            {"type": "n8n-nodes-base.gmail", "description": "Gmail - send/receive emails"},
            {"type": "n8n-nodes-base.googleSheets", "description": "Google Sheets - read/write spreadsheets"},
            {"type": "n8n-nodes-base.googleDrive", "description": "Google Drive - file management"},
            {"type": "n8n-nodes-base.github", "description": "GitHub - issues, PRs, repos"},
            {"type": "n8n-nodes-base.gitlab", "description": "GitLab - issues, MRs, repos"},
            {"type": "n8n-nodes-base.postgres", "description": "PostgreSQL - database operations"},
            {"type": "n8n-nodes-base.mySql", "description": "MySQL - database operations"},
            {"type": "n8n-nodes-base.mongoDb", "description": "MongoDB - database operations"},
            {"type": "n8n-nodes-base.redis", "description": "Redis - cache operations"},
            {"type": "n8n-nodes-base.awsS3", "description": "AWS S3 - file storage"},
            {"type": "n8n-nodes-base.notion", "description": "Notion - pages and databases"},
            {"type": "n8n-nodes-base.airtable", "description": "Airtable - spreadsheet-database hybrid"},
            {"type": "n8n-nodes-base.hubspot", "description": "HubSpot - CRM"},
            {"type": "n8n-nodes-base.salesforce", "description": "Salesforce - CRM"},
            {"type": "n8n-nodes-base.stripe", "description": "Stripe - payments"},
            {"type": "n8n-nodes-base.shopify", "description": "Shopify - e-commerce"},
        ],
    }


# ---- Entry point -----------------------------------------------------------

def main() -> None:
    """Run the MCP server (stdio transport for Claude Desktop / MCP clients)."""
    if not N8N_API_KEY:
        logger.warning(
            "N8N_API_KEY is not set. Set it via environment variable:\n"
            "  export N8N_API_KEY=your-api-key\n"
            "Get your API key from n8n UI: Settings > API > Create API Key"
        )
    logger.info("Starting n8n MCP server (stdio)")
    logger.info(f"n8n URL: {N8N_BASE_URL}")
    mcp.run()


if __name__ == "__main__":
    main()
