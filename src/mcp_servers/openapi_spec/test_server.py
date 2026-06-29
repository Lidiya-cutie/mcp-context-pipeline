#!/usr/bin/env python3
"""Test harness for openapi_spec MCP server."""
import subprocess
import json
import sys

SERVER = [sys.executable, "/tmp/skills_deploy/mcp-servers/openapi_spec/server.py"]

SAMPLE_SPEC = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "components": {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        },
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "id": {"type": "integer", "format": "int64"},
                    "name": {"type": "string", "example": "Buddy"},
                    "tag": {"type": "string"},
                    "status": {"type": "string", "enum": ["available", "sold"]}
                }
            },
            "NewPet": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "tag": {"type": "string"}
                }
            },
            "Error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "integer"},
                    "message": {"type": "string"}
                }
            }
        }
    },
    "paths": {
        "/pets": {
            "get": {
                "summary": "List all pets",
                "tags": ["pets"],
                "operationId": "listPets",
                "parameters": [
                    {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
                    {"name": "offset", "in": "query", "required": False, "schema": {"type": "integer"}}
                ],
                "responses": {
                    "200": {"description": "A list of pets", "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}}}},
                    "default": {"description": "unexpected error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                }
            },
            "post": {
                "summary": "Create a pet",
                "tags": ["pets"],
                "operationId": "createPet",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/NewPet"}}}
                },
                "responses": {
                    "201": {"description": "Created", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}},
                    "default": {"description": "error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                }
            }
        },
        "/pets/{petId}": {
            "get": {
                "summary": "Get a pet by ID",
                "tags": ["pets"],
                "operationId": "getPet",
                "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "responses": {
                    "200": {"description": "Expected response", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}},
                    "404": {"description": "Not found", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                }
            },
            "delete": {
                "summary": "Delete a pet",
                "tags": ["pets"],
                "deprecated": True,
                "operationId": "deletePet",
                "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "responses": {"204": {"description": "Deleted"}}
            }
        },
        "/users": {
            "get": {
                "summary": "List users",
                "tags": ["users"],
                "operationId": "listUsers",
                "responses": {"200": {"description": "User list"}}
            }
        }
    },
    "security": [{"bearerAuth": []}]
})


def send(proc, msg):
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode())
    proc.stdin.flush()


def recv(proc):
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line)


def test():
    errors = []
    proc = subprocess.Popen(
        SERVER,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 1. Initialize
    send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    resp = recv(proc)
    if not resp or resp.get("result", {}).get("protocolVersion") != "2024-11-05":
        errors.append(f"initialize failed: {resp}")
    else:
        print("PASS: initialize")

    # Send initialized notification
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    # 2. tools/list
    send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    resp = recv(proc)
    tools = resp.get("result", {}).get("tools", [])
    tool_names = [t["name"] for t in tools]
    expected = ["load_spec", "list_endpoints", "get_endpoint", "find_endpoint",
                "list_schemas", "get_schema", "generate_request_example",
                "get_auth_requirements", "check_health"]
    if set(tool_names) != set(expected):
        errors.append(f"tools/list mismatch: got {tool_names}")
    else:
        print(f"PASS: tools/list ({len(tools)} tools)")

    # 3. load_spec
    send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "load_spec", "arguments": {"source": SAMPLE_SPEC}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if '"endpoints": 5' not in text or '"schemas": 3' not in text:
        errors.append(f"load_spec unexpected: {text}")
    else:
        print(f"PASS: load_spec -> {text.strip()}")

    # 4. list_endpoints
    send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "list_endpoints", "arguments": {}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if "Endpoints (5)" not in text:
        errors.append(f"list_endpoints unexpected: {text}")
    else:
        print(f"PASS: list_endpoints")

    # 5. check_health
    send(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "check_health", "arguments": {}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if '"endpoints": 5' not in text:
        errors.append(f"check_health unexpected: {text}")
    else:
        print(f"PASS: check_health")

    # 6. find_endpoint
    send(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "find_endpoint", "arguments": {"keyword": "pet"}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if "Found 4 endpoint" not in text:
        errors.append(f"find_endpoint unexpected: {text}")
    else:
        print(f"PASS: find_endpoint (pet -> 3)")

    # 7. get_endpoint
    send(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "get_endpoint", "arguments": {"method": "POST", "path": "/pets"}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if "requestBody" not in text:
        errors.append(f"get_endpoint unexpected: {text[:200]}")
    else:
        print(f"PASS: get_endpoint (POST /pets)")

    # 8. list_schemas
    send(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                "params": {"name": "list_schemas", "arguments": {}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if "Schemas (3)" not in text:
        errors.append(f"list_schemas unexpected: {text}")
    else:
        print(f"PASS: list_schemas")

    # 9. get_schema
    send(proc, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                "params": {"name": "get_schema", "arguments": {"schema_name": "Pet"}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if '"Buddy"' not in text:
        errors.append(f"get_schema unexpected: {text[:200]}")
    else:
        print(f"PASS: get_schema (Pet)")

    # 10. generate_request_example
    send(proc, {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                "params": {"name": "generate_request_example", "arguments": {"method": "POST", "path": "/pets"}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if "name" not in text:
        errors.append(f"generate_request_example unexpected: {text[:200]}")
    else:
        print(f"PASS: generate_request_example")

    # 11. get_auth_requirements
    send(proc, {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                "params": {"name": "get_auth_requirements", "arguments": {}}})
    resp = recv(proc)
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    if "bearerAuth" not in text or "apiKey" not in text:
        errors.append(f"get_auth_requirements unexpected: {text[:200]}")
    else:
        print(f"PASS: get_auth_requirements")

    proc.stdin.close()
    proc.wait(timeout=5)

    if errors:
        print(f"\nFAILED ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"\nAll 11 tests passed.")


if __name__ == "__main__":
    test()
