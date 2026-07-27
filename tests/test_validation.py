"""Tests for n8n MCP Server - workflow validation and structure."""

import json
import pytest

from src.server import validate_workflow_structure


@pytest.mark.asyncio
async def test_validate_empty_workflow():
    """Empty workflow should have errors."""
    result = await validate_workflow_structure("{}")
    assert result["valid"] is False
    assert any("name" in e for e in result["errors"])
    assert any("nodes" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_validate_minimal_workflow():
    """Minimal valid workflow should pass."""
    wf = json.dumps({
        "name": "Test",
        "nodes": [
            {
                "id": "n1",
                "name": "Start",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [250, 300],
                "parameters": {},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    })
    result = await validate_workflow_structure(wf)
    assert result["valid"] is True
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_validate_workflow_with_connections():
    """Workflow with connections should validate node references."""
    wf = json.dumps({
        "name": "Connected",
        "nodes": [
            {
                "id": "n1",
                "name": "Trigger",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [250, 300],
                "parameters": {},
            },
            {
                "id": "n2",
                "name": "Action",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "position": [500, 300],
                "parameters": {},
            },
        ],
        "connections": {
            "Trigger": {
                "main": [[{"node": "Action", "type": "main", "index": 0}]],
            },
        },
        "settings": {"executionOrder": "v1"},
    })
    result = await validate_workflow_structure(wf)
    assert result["valid"] is True
    assert result["node_count"] == 2


@pytest.mark.asyncio
async def test_validate_invalid_json():
    """Invalid JSON should return error."""
    result = await validate_workflow_structure("not json{{{")
    assert result["valid"] is False
    assert "Invalid JSON" in result["errors"][0]


@pytest.mark.asyncio
async def test_validate_duplicate_node_ids():
    """Duplicate node IDs should be flagged."""
    wf = json.dumps({
        "name": "Dupes",
        "nodes": [
            {"id": "same", "name": "A", "type": "x", "position": [0, 0]},
            {"id": "same", "name": "B", "type": "x", "position": [100, 0]},
        ],
        "connections": {},
    })
    result = await validate_workflow_structure(wf)
    assert result["valid"] is False
    assert any("duplicate" in e.lower() for e in result["errors"])
