# n8n MCP Server

MCP (Model Context Protocol) server for [n8n](https://n8n.io/) workflow automation platform.
Provides AI assistants with full access to manage workflows, monitor executions, handle credentials, and build pipelines.

## Features

- **Workflow Management**: Create, read, update, delete, activate/deactivate, duplicate, export/import workflows
- **Execution Monitoring**: List, get details, retry, stop executions
- **Credential Management**: List, create, delete credentials (no secret data exposure)
- **Variables**: Manage n8n environment variables (requires n8n license)
- **Pipeline Building**: Templates, validation, common node type reference
- **Tags & Projects**: List tags and projects

## Quick Start

### 1. Set up n8n

If you don't have n8n running yet, use the included docker-compose:

```bash
cd /opt/projects/n8n-mcp
docker compose -f docker-compose.n8n.yml up -d
```

This creates an n8n instance. On first run, n8n will show the setup screen where you create your owner account:
- **URL**: http://localhost:5678

### 2. Create an API Key

Open n8n in your browser and create an API key:

1. Complete the initial owner setup (create your admin account)
2. Go to **Settings → API**
3. Click **Create API Key**
4. Copy the key

Or use the API directly (replace `your-email` and `your-password` with your actual credentials):

```bash
# Login
curl -X POST http://localhost:5678/rest/login \
  -H "Content-Type: application/json" \
  -d '{"emailOrLdapLoginId":"your-email","password":"your-password"}'

# Create API key (use the cookie from login)
curl -X POST http://localhost:5678/rest/api-keys \
  -H "Content-Type: application/json" \
  -H "Cookie: n8n-auth=<cookie>" \
  -d '{
    "label": "MCP Server",
    "scopes": ["workflow:create","workflow:read","workflow:update","workflow:delete","workflow:list","workflow:export","workflow:import","workflow:activate","workflow:deactivate","execution:read","execution:list","execution:delete","execution:retry","execution:stop","credential:create","credential:read","credential:list","credential:update","credential:delete","tag:create","tag:read","tag:list","tag:update","tag:delete","project:list"],
    "expiresAt": 1813151338246
  }'
```

### 3. Install

```bash
cd /opt/projects/n8n-mcp
pip install -e .
```

Or with Docker:

```bash
docker compose build
```

### 4. Configure

Set environment variables:

```bash
export N8N_BASE_URL=http://localhost:5678
export N8N_API_KEY=your-a...
```

Or create a `.env` file:

```env
N8N_BASE_URL=http://localhost:5678
N8N_API_KEY=your-a...
```

### 5. Run

**For Claude Desktop / MCP clients (stdio):**

```bash
n8n-mcp-server
```

**Direct Python:**

```bash
python -m src.server
```

**HTTP mode (standalone service):**

```bash
python -m src.server_http
# or
docker compose up -d
```

### 6. Configure Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "n8n": {
      "command": "n8n-mcp-server",
      "env": {
        "N8N_BASE_URL": "http://localhost:5678",
        "N8N_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

Or with a virtual environment:

```json
{
  "mcpServers": {
    "n8n": {
      "command": "/opt/projects/n8n-mcp/.venv/bin/n8n-mcp-server",
      "env": {
        "N8N_BASE_URL": "http://localhost:5678",
        "N8N_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

## Available Tools

### Workflows (10 tools)
| Tool | Description |
|------|-------------|
| `list_workflows` | List all workflows (filter by active, tags, project) |
| `get_workflow` | Get workflow details with full node config |
| `create_workflow` | Create a new workflow with nodes and connections |
| `update_workflow` | Update an existing workflow |
| `delete_workflow` | Delete a workflow |
| `activate_workflow` | Activate a workflow |
| `deactivate_workflow` | Deactivate a workflow |
| `duplicate_workflow` | Duplicate an existing workflow |
| `export_workflow` | Export workflow as JSON |
| `import_workflow` | Import workflow from JSON |

### Executions (7 tools)
| Tool | Description |
|------|-------------|
| `list_executions` | List executions (filter by status, workflow) |
| `get_execution` | Get execution details with node output data |
| `delete_execution` | Delete an execution record |
| `retry_execution` | Retry a failed execution |
| `stop_execution` | Stop a running execution |
| `execute_workflow` | Manually trigger a workflow |
| `get_execution_stats` | Get execution statistics |

### Credentials (4 tools)
| Tool | Description |
|------|-------------|
| `list_credentials` | List credentials (names/types only, no secrets) |
| `get_credential` | Get credential details |
| `create_credential` | Create a new credential |
| `delete_credential` | Delete a credential |

### Building Pipelines (3 tools)
| Tool | Description |
|------|-------------|
| `get_workflow_template` | Get a starter template with trigger + action |
| `validate_workflow_structure` | Validate workflow JSON before creating |
| `list_common_node_types` | Browse available node types by category |

### Other (5 tools)
| Tool | Description |
|------|-------------|
| `n8n_status` | Check n8n server health |
| `list_variables` | List environment variables |
| `create_variable` | Create a variable |
| `delete_variable` | Delete a variable |
| `list_tags` | List workflow tags |
| `list_projects` | List projects |

## Example: Building a Pipeline

```
User: "Create a workflow that fetches data from a webhook and stores it in Google Sheets"

AI: 1. Gets template: get_workflow_template(trigger_type="webhook", action_type="n8n-nodes-base.googleSheets")
   2. Adds Sheets configuration to the action node
   3. Validates: validate_workflow_structure(...)
   4. Creates: create_workflow(...)
   5. Activates: activate_workflow(...)
   6. Tests: execute_workflow(...)
   7. Checks: get_execution(...)
```

## Architecture

```
┌─────────────┐     MCP (stdio/HTTP)      ┌──────────────┐     HTTP/REST     ┌─────────┐
│   Claude /  │ ◄───────────────────────► │  n8n MCP     │ ◄──────────────► │   n8n   │
│   AI Agent  │                           │  Server      │                   │ Instance│
└─────────────┘                           └──────────────┘                   └─────────┘
```

## Development

```bash
# Install
pip install -e .

# Run tests
pytest tests/ -v

# Run with debug logging
N8N_BASE_URL=http://localhost:5678 N8N_API_KEY=*** python -m src.server
```

## License

MIT
