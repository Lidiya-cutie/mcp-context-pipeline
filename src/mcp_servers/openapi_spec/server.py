#!/usr/bin/env python3
"""OpenAPI/Swagger spec parser and explorer MCP server."""

import sys
import json
import copy
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# --- In-memory spec storage ---
SPECS = {}  # name -> {raw, endpoints, schemas, security_schemes}


def make_response(req_id, result):
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n"


def make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": err}) + "\n"


def resolve_ref(spec, ref_str):
    """Resolve a $ref pointer like '#/components/schemas/Pet' within spec."""
    if not ref_str.startswith("#/"):
        return None
    parts = ref_str[2:].split("/")
    node = spec
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        else:
            return None
    return node


def resolve_refs_deep(spec, obj, depth=0):
    """Recursively resolve $ref in an object, with cycle guard."""
    if depth > 10:
        return obj
    if isinstance(obj, dict):
        if "$ref" in obj and isinstance(obj["$ref"], str):
            resolved = resolve_ref(spec, obj["$ref"])
            if resolved is not None:
                return resolve_refs_deep(spec, copy.deepcopy(resolved), depth + 1)
            return obj
        return {k: resolve_refs_deep(spec, v, depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_refs_deep(spec, v, depth) for v in obj]
    return obj


def extract_endpoints(spec):
    """Extract all endpoints from paths."""
    endpoints = []
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, details in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete", "head", "options", "trace"):
                continue
            if not isinstance(details, dict):
                continue
            endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "tags": details.get("tags", []),
                "deprecated": details.get("deprecated", False),
                "operationId": details.get("operationId", ""),
            })
    return endpoints


def extract_schemas(spec):
    """Extract schema definitions from components/schemas or definitions."""
    schemas = {}
    # OpenAPI 3.x
    comps = spec.get("components", {})
    for name, schema in comps.get("schemas", {}).items():
        schemas[name] = schema
    # Swagger 2.x
    for name, schema in spec.get("definitions", {}).items():
        schemas[name] = schema
    return schemas


def extract_security_schemes(spec):
    """Extract security scheme definitions."""
    schemes = {}
    # OpenAPI 3.x
    comps = spec.get("components", {})
    for name, scheme in comps.get("securitySchemes", {}).items():
        schemes[name] = scheme
    # Swagger 2.x
    for name, scheme in spec.get("securityDefinitions", {}).items():
        schemes[name] = scheme
    return schemes


def find_endpoint_details(spec, method, path):
    """Get full details for a specific endpoint."""
    methods = spec.get("paths", {}).get(path, {})
    details = methods.get(method.lower(), {})
    if not details:
        return None
    # Resolve $ref in parameters
    params = resolve_refs_deep(spec, details.get("parameters", []))
    # Request body
    req_body = details.get("requestBody")
    if req_body:
        req_body = resolve_refs_deep(spec, req_body)
    # Responses
    responses = resolve_refs_deep(spec, details.get("responses", {}))
    return {
        "method": method.upper(),
        "path": path,
        "summary": details.get("summary", ""),
        "description": details.get("description", ""),
        "tags": details.get("tags", []),
        "deprecated": details.get("deprecated", False),
        "operationId": details.get("operationId", ""),
        "parameters": params,
        "requestBody": req_body,
        "responses": responses,
        "security": details.get("security", []),
    }


def generate_example_from_schema(spec, schema, depth=0):
    """Generate an example value from a schema definition."""
    if depth > 8:
        return None
    if not isinstance(schema, dict):
        return None

    if "example" in schema:
        return schema["example"]

    if "$ref" in schema:
        resolved = resolve_ref(spec, schema["$ref"])
        if resolved:
            return generate_example_from_schema(spec, resolved, depth + 1)
        return None

    schema_type = schema.get("type", "")
    if "oneOf" in schema:
        return generate_example_from_schema(spec, schema["oneOf"][0], depth + 1)
    if "anyOf" in schema:
        return generate_example_from_schema(spec, schema["anyOf"][0], depth + 1)
    if "allOf" in schema:
        merged = {}
        for sub in schema["allOf"]:
            sub_example = generate_example_from_schema(spec, sub, depth + 1)
            if isinstance(sub_example, dict):
                merged.update(sub_example)
        return merged if merged else None

    if schema_type == "object":
        props = schema.get("properties", {})
        obj = {}
        for pname, pschema in props.items():
            val = generate_example_from_schema(spec, pschema, depth + 1)
            if val is not None:
                obj[pname] = val
        return obj

    if schema_type == "array":
        items = schema.get("items", {})
        val = generate_example_from_schema(spec, items, depth + 1)
        return [val] if val is not None else []

    if schema_type == "string":
        enum = schema.get("enum")
        if enum:
            return enum[0]
        fmt = schema.get("format", "")
        if fmt == "date-time":
            return "2025-01-01T00:00:00Z"
        if fmt == "date":
            return "2025-01-01"
        if fmt == "email":
            return "user@example.com"
        if fmt == "uri":
            return "https://example.com"
        if fmt == "uuid":
            return "550e8400-e29b-41d4-a716-446655440000"
        return "string"

    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return True
    if schema_type == "null":
        return None

    return None


def generate_request_example(spec, method, path):
    """Generate example request body for an endpoint."""
    details = find_endpoint_details(spec, method, path)
    if not details:
        return None

    req_body = details.get("requestBody")
    if not req_body:
        return {"body": None, "parameters": details.get("parameters", [])}

    content = req_body.get("content", {})
    example_data = {}
    for ct, media in content.items():
        schema = media.get("schema", {})
        example = generate_example_from_schema(spec, schema)
        if "example" in media:
            example = media["example"]
        example_data[ct] = example

    return {"contentTypes": example_data, "required": req_body.get("required", False)}


# --- Tool definitions ---

TOOLS = [
    {
        "name": "load_spec",
        "description": "Load an OpenAPI spec from a URL or JSON string. Parse and index it in memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "URL to fetch spec from, or raw JSON string of the spec",
                },
                "name": {
                    "type": "string",
                    "description": "Name to reference this spec by (default: 'default')",
                    "default": "default",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "list_endpoints",
        "description": "List all endpoints in a loaded spec: method, path, summary, tags, deprecated flag.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Spec name (default: 'default')",
                    "default": "default",
                },
                "tag": {
                    "type": "string",
                    "description": "Filter by tag (optional)",
                },
                "deprecated": {
                    "type": "boolean",
                    "description": "Include deprecated endpoints (default: true)",
                    "default": True,
                },
            },
        },
    },
    {
        "name": "get_endpoint",
        "description": "Get detailed endpoint info: parameters, request body, responses, examples.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Spec name (default: 'default')",
                    "default": "default",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET, POST, PUT, PATCH, DELETE)",
                },
                "path": {
                    "type": "string",
                    "description": "Endpoint path (e.g. /pets)",
                },
            },
            "required": ["method", "path"],
        },
    },
    {
        "name": "find_endpoint",
        "description": "Search endpoints by keyword in path, summary, or description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Spec name (default: 'default')",
                    "default": "default",
                },
                "keyword": {
                    "type": "string",
                    "description": "Search keyword",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "list_schemas",
        "description": "List all schema definitions with properties and types.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Spec name (default: 'default')",
                    "default": "default",
                },
            },
        },
    },
    {
        "name": "get_schema",
        "description": "Get detailed schema: properties, required, enums, nested refs (resolve $ref).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Spec name (default: 'default')",
                    "default": "default",
                },
                "schema_name": {
                    "type": "string",
                    "description": "Schema name (e.g. 'Pet')",
                },
            },
            "required": ["schema_name"],
        },
    },
    {
        "name": "generate_request_example",
        "description": "Generate example request body for an endpoint based on its schema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Spec name (default: 'default')",
                    "default": "default",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method",
                },
                "path": {
                    "type": "string",
                    "description": "Endpoint path",
                },
            },
            "required": ["method", "path"],
        },
    },
    {
        "name": "get_auth_requirements",
        "description": "Get security schemes defined in spec (API key, OAuth2, Bearer, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Spec name (default: 'default')",
                    "default": "default",
                },
            },
        },
    },
    {
        "name": "check_health",
        "description": "Status of loaded spec(s): loaded names, endpoint counts, schema counts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_load_spec(params):
    source = params.get("source", "")
    spec_name = params.get("name", "default")

    if source.strip().startswith(("http://", "https://")):
        try:
            req = Request(source, headers={"Accept": "application/json"})
            with urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            return {"content": [{"type": "text", "text": f"Failed to load spec from URL: {e}"}]}
    else:
        try:
            raw = json.loads(source)
        except json.JSONDecodeError as e:
            return {"content": [{"type": "text", "text": f"Invalid JSON: {e}"}]}

    endpoints = extract_endpoints(raw)
    schemas = extract_schemas(raw)
    security = extract_security_schemes(raw)

    SPECS[spec_name] = {
        "raw": raw,
        "endpoints": endpoints,
        "schemas": schemas,
        "security_schemes": security,
    }

    info = raw.get("info", {})
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "loaded": spec_name,
                    "title": info.get("title", "Unknown"),
                    "version": info.get("version", "Unknown"),
                    "openapi": raw.get("openapi") or raw.get("swagger", "Unknown"),
                    "endpoints": len(endpoints),
                    "schemas": len(schemas),
                    "securitySchemes": len(security),
                }, indent=2),
            }
        ]
    }


def handle_list_endpoints(params):
    spec_name = params.get("name", "default")
    if spec_name not in SPECS:
        return {"content": [{"type": "text", "text": f"Spec '{spec_name}' not loaded. Use load_spec first."}]}

    spec_data = SPECS[spec_name]
    endpoints = spec_data["endpoints"]

    tag_filter = params.get("tag")
    include_deprecated = params.get("deprecated", True)

    filtered = endpoints
    if tag_filter:
        filtered = [e for e in filtered if tag_filter in e.get("tags", [])]
    if not include_deprecated:
        filtered = [e for e in filtered if not e.get("deprecated")]

    lines = [f"Endpoints ({len(filtered)}):"]
    for ep in filtered:
        dep = " [DEPRECATED]" if ep.get("deprecated") else ""
        tags = f" ({', '.join(ep.get('tags', []))})" if ep.get("tags") else ""
        lines.append(f"  {ep['method']:7s} {ep['path']}{tags}{dep}")
        if ep.get("summary"):
            lines.append(f"           {ep['summary']}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def handle_get_endpoint(params):
    spec_name = params.get("name", "default")
    method = params.get("method", "").upper()
    path = params.get("path", "")

    if spec_name not in SPECS:
        return {"content": [{"type": "text", "text": f"Spec '{spec_name}' not loaded."}]}

    raw = SPECS[spec_name]["raw"]
    details = find_endpoint_details(raw, method, path)
    if not details:
        return {"content": [{"type": "text", "text": f"Endpoint {method} {path} not found."}]}

    return {"content": [{"type": "text", "text": json.dumps(details, indent=2, ensure_ascii=False)}]}


def handle_find_endpoint(params):
    spec_name = params.get("name", "default")
    keyword = params.get("keyword", "").lower()

    if spec_name not in SPECS:
        return {"content": [{"type": "text", "text": f"Spec '{spec_name}' not loaded."}]}

    endpoints = SPECS[spec_name]["endpoints"]
    matches = [
        e for e in endpoints
        if keyword in e["path"].lower()
        or keyword in (e.get("summary") or "").lower()
        or keyword in (e.get("description") or "").lower()
    ]

    if not matches:
        return {"content": [{"type": "text", "text": f"No endpoints matching '{keyword}'."}]}

    lines = [f"Found {len(matches)} endpoint(s):"]
    for ep in matches:
        tags = f" ({', '.join(ep.get('tags', []))})" if ep.get("tags") else ""
        lines.append(f"  {ep['method']:7s} {ep['path']}{tags}")
        if ep.get("summary"):
            lines.append(f"           {ep['summary']}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def handle_list_schemas(params):
    spec_name = params.get("name", "default")
    if spec_name not in SPECS:
        return {"content": [{"type": "text", "text": f"Spec '{spec_name}' not loaded."}]}

    schemas = SPECS[spec_name]["schemas"]
    if not schemas:
        return {"content": [{"type": "text", "text": "No schemas found."}]}

    lines = [f"Schemas ({len(schemas)}):"]
    for name, schema in schemas.items():
        props = schema.get("properties", {})
        prop_summary = ", ".join(f"{k}: {v.get('type', 'object')}" for k, v in props.items())
        req = schema.get("required", [])
        req_str = f" [required: {', '.join(req)}]" if req else ""
        lines.append(f"  {name}: {{{prop_summary}}}{req_str}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def handle_get_schema(params):
    spec_name = params.get("name", "default")
    schema_name = params.get("schema_name", "")

    if spec_name not in SPECS:
        return {"content": [{"type": "text", "text": f"Spec '{spec_name}' not loaded."}]}

    raw = SPECS[spec_name]["raw"]
    schemas = SPECS[spec_name]["schemas"]
    if schema_name not in schemas:
        return {"content": [{"type": "text", "text": f"Schema '{schema_name}' not found."}]}

    resolved = resolve_refs_deep(raw, copy.deepcopy(schemas[schema_name]))
    return {"content": [{"type": "text", "text": json.dumps(resolved, indent=2, ensure_ascii=False)}]}


def handle_generate_request_example(params):
    spec_name = params.get("name", "default")
    method = params.get("method", "").upper()
    path = params.get("path", "")

    if spec_name not in SPECS:
        return {"content": [{"type": "text", "text": f"Spec '{spec_name}' not loaded."}]}

    raw = SPECS[spec_name]["raw"]
    result = generate_request_example(raw, method, path)
    if result is None:
        return {"content": [{"type": "text", "text": f"Endpoint {method} {path} not found."}]}

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]}


def handle_get_auth_requirements(params):
    spec_name = params.get("name", "default")
    if spec_name not in SPECS:
        return {"content": [{"type": "text", "text": f"Spec '{spec_name}' not loaded."}]}

    security = SPECS[spec_name]["security_schemes"]
    global_sec = SPECS[spec_name]["raw"].get("security", [])

    if not security:
        return {"content": [{"type": "text", "text": "No security schemes defined."}]}

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"securitySchemes": security, "globalSecurity": global_sec},
                    indent=2,
                    ensure_ascii=False,
                ),
            }
        ]
    }


def handle_check_health(params):
    if not SPECS:
        return {"content": [{"type": "text", "text": "No specs loaded."}]}

    status = []
    for name, data in SPECS.items():
        info = data["raw"].get("info", {})
        status.append({
            "name": name,
            "title": info.get("title", "Unknown"),
            "version": info.get("version", "Unknown"),
            "endpoints": len(data["endpoints"]),
            "schemas": len(data["schemas"]),
            "securitySchemes": len(data["security_schemes"]),
        })

    return {"content": [{"type": "text", "text": json.dumps(status, indent=2)}]}


TOOL_HANDLERS = {
    "load_spec": handle_load_spec,
    "list_endpoints": handle_list_endpoints,
    "get_endpoint": handle_get_endpoint,
    "find_endpoint": handle_find_endpoint,
    "list_schemas": handle_list_schemas,
    "get_schema": handle_get_schema,
    "generate_request_example": handle_generate_request_example,
    "get_auth_requirements": handle_get_auth_requirements,
    "check_health": handle_check_health,
}


def handle_request(msg):
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "openapi_spec", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_params = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return make_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = handler(tool_params)
            return make_response(req_id, result)
        except Exception as e:
            return make_error(req_id, -32603, f"Tool error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    # notification without response
    if method.startswith("notifications/"):
        return None

    return make_error(req_id, -32601, f"Method not found: {method}")


def main():
    """Main loop: read JSON-RPC lines from stdin, write responses to stdout."""
    # Flush every write to avoid buffering issues with subprocess pipes
    sys.stdout.reconfigure(line_buffering=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(msg)
        if response is not None:
            sys.stdout.write(response)
            sys.stdout.flush()


if __name__ == "__main__":
    main()
