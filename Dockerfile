FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uvicorn starlette

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src/ src/
COPY tests/ tests/

EXPOSE 3000

# Run MCP server in HTTP mode for standalone service
CMD ["python", "-m", "src.server_http"]
