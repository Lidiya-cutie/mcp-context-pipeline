from __future__ import annotations

import json
import argparse
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class ChangeType(Enum):
    REMOVED_ENDPOINT = "removed_endpoint"
    REMOVED_FIELD = "removed_field"
    CHANGED_FIELD_TYPE = "changed_field_type"
    REMOVED_REQUIRED_FIELD = "removed_required_field"
    ADDED_REQUIRED_FIELD = "added_required_field"
    CHANGED_HTTP_METHOD = "changed_http_method"
    CHANGED_PATH_PATTERN = "changed_path_pattern"


@dataclass
class APIChange:
    change_type: ChangeType
    location: str
    description: str
    severity: float = 1.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompatibilityReport:
    total_endpoints_v1: int = 0
    total_endpoints_v2: int = 0
    removed_endpoints: int = 0
    added_endpoints: int = 0
    changes: List[APIChange] = field(default_factory=list)
    risk_score: float = 0.0
    compatibility_score: float = 1.0


class OpenAPISpec:
    def __init__(self, spec_data: Dict[str, Any]):
        self.spec = spec_data
        self.paths = spec_data.get("paths", {})

    def get_endpoints(self) -> Dict[str, Dict[str, Any]]:
        return {path: methods for path, methods in self.paths.items()}

    def get_schema_for_path(self, path: str, method: str) -> Optional[Dict[str, Any]]:
        if path not in self.paths:
            return None
        if method not in self.paths[path]:
            return None
        method_data = self.paths[path][method]
        if method_data.get("requestBody"):
            content = method_data["requestBody"].get("content", {})
            for content_type, content_data in content.items():
                if "schema" in content_data:
                    return content_data["schema"]
        return {}

    def get_response_schema(self, path: str, method: str, status_code: str = "200") -> Optional[Dict[str, Any]]:
        if path not in self.paths:
            return None
        if method not in self.paths[path]:
            return None
        method_data = self.paths[path][method]
        responses = method_data.get("responses", {})
        if status_code not in responses:
            return None
        response_data = responses[status_code]
        content = response_data.get("content", {})
        for content_type, content_data in content.items():
            if "schema" in content_data:
                return content_data["schema"]
        return {}

    def get_all_schemas(self) -> Dict[str, Dict[str, Any]]:
        schemas = self.spec.get("components", {}).get("schemas", {})
        return {name: schema for name, schema in schemas.items()}


def _get_type_from_schema(schema: Dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "type" in schema:
        return schema["type"]
    if "oneOf" in schema:
        return "oneOf"
    if "anyOf" in schema:
        return "anyOf"
    if "allOf" in schema:
        return "allOf"
    if "enum" in schema:
        return "enum"
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return "unknown"


def _extract_properties(schema: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    properties = {}
    if "properties" in schema:
        for prop_name, prop_schema in schema["properties"].items():
            full_name = f"{prefix}.{prop_name}" if prefix else prop_name
            properties[full_name] = _get_type_from_schema(prop_schema)
            if prop_schema.get("type") == "object":
                nested = _extract_properties(prop_schema, full_name)
                properties.update(nested)
            elif prop_schema.get("type") == "array" and "items" in prop_schema:
                if isinstance(prop_schema["items"], dict):
                    nested = _extract_properties(prop_schema["items"], full_name + "[]")
                    properties.update(nested)
    return properties


def _get_required_fields(schema: Dict[str, Any], prefix: str = "") -> Set[str]:
    required = set()
    if "required" in schema:
        for field in schema["required"]:
            full_name = f"{prefix}.{field}" if prefix else field
            required.add(full_name)
    if "properties" in schema:
        for prop_name, prop_schema in schema["properties"].items():
            full_name = f"{prefix}.{prop_name}" if prefix else prop_name
            if prop_schema.get("type") == "object":
                nested = _get_required_fields(prop_schema, full_name)
                required.update(nested)
    return required


def _compare_schemas(schema_v1: Dict[str, Any], schema_v2: Dict[str, Any], location: str) -> List[APIChange]:
    changes: List[APIChange] = []

    props_v1 = _extract_properties(schema_v1)
    props_v2 = _extract_properties(schema_v2)

    required_v1 = _get_required_fields(schema_v1)
    required_v2 = _get_required_fields(schema_v2)

    for prop, type_v1 in props_v1.items():
        if prop not in props_v2:
            changes.append(APIChange(
                change_type=ChangeType.REMOVED_FIELD,
                location=location,
                description=f"Removed field: {prop} (was: {type_v1})",
                severity=1.0,
                details={"field": prop, "old_type": type_v1}
            ))

    for prop, type_v1 in props_v1.items():
        if prop in props_v2:
            type_v2 = props_v2[prop]
            if type_v1 != type_v2:
                changes.append(APIChange(
                    change_type=ChangeType.CHANGED_FIELD_TYPE,
                    location=location,
                    description=f"Changed type of {prop}: {type_v1} -> {type_v2}",
                    severity=0.5,
                    details={"field": prop, "old_type": type_v1, "new_type": type_v2}
                ))

    for field in required_v1:
        if field not in required_v2:
            changes.append(APIChange(
                change_type=ChangeType.REMOVED_REQUIRED_FIELD,
                location=location,
                description=f"Removed required field: {field}",
                severity=0.8,
                details={"field": field}
            ))

    for field in required_v2:
        if field not in required_v1:
            changes.append(APIChange(
                change_type=ChangeType.ADDED_REQUIRED_FIELD,
                location=location,
                description=f"Added required field: {field} (breaking change)",
                severity=0.3,
                details={"field": field}
            ))

    return changes


def compare_openapi_specs(spec_v1: Dict[str, Any], spec_v2: Dict[str, Any]) -> CompatibilityReport:
    report = CompatibilityReport()

    api_v1 = OpenAPISpec(spec_v1)
    api_v2 = OpenAPISpec(spec_v2)

    endpoints_v1 = api_v1.get_endpoints()
    endpoints_v2 = api_v2.get_endpoints()

    report.total_endpoints_v1 = len(endpoints_v1)
    report.total_endpoints_v2 = len(endpoints_v2)

    for path, methods_v1 in endpoints_v1.items():
        for method, method_data_v1 in methods_v1.items():
            location = f"{method.upper()} {path}"

            if path not in endpoints_v2:
                report.changes.append(APIChange(
                    change_type=ChangeType.REMOVED_ENDPOINT,
                    location=location,
                    description=f"Removed endpoint: {location}",
                    severity=2.0,
                    details={"path": path, "method": method}
                ))
                report.removed_endpoints += 1
            elif method not in endpoints_v2[path]:
                report.changes.append(APIChange(
                    change_type=ChangeType.CHANGED_HTTP_METHOD,
                    location=location,
                    description=f"Changed HTTP method: {method.upper()} removed from {path}",
                    severity=1.5,
                    details={"path": path, "old_method": method, "new_methods": list(endpoints_v2[path].keys())}
                ))
            else:
                request_schema_v1 = api_v1.get_schema_for_path(path, method)
                request_schema_v2 = api_v2.get_schema_for_path(path, method)

                if request_schema_v1 and request_schema_v2:
                    changes = _compare_schemas(request_schema_v1, request_schema_v2, location)
                    report.changes.extend(changes)

                response_schema_v1 = api_v1.get_response_schema(path, method)
                response_schema_v2 = api_v2.get_response_schema(path, method)

                if response_schema_v1 and response_schema_v2:
                    changes = _compare_schemas(response_schema_v1, response_schema_v2, f"{location} response")
                    report.changes.extend(changes)

    for path in endpoints_v2:
        if path not in endpoints_v1:
            report.added_endpoints += 1

    report.risk_score = _calculate_risk_score(report)
    report.compatibility_score = _calculate_compatibility_score(report)

    return report


def _calculate_risk_score(report: CompatibilityReport) -> float:
    return float(sum(change.severity for change in report.changes))


def _calculate_compatibility_score(report: CompatibilityReport) -> float:
    if report.total_endpoints_v1 == 0:
        return 1.0
    # Legacy compatibility score preserved for backward compatibility:
    # 1.0 means no breaking changes, 0.0 means maximal normalized risk.
    normalized_risk = report.risk_score / max(1.0, float(report.total_endpoints_v1))
    return max(0.0, 1.0 - min(1.0, normalized_risk))


def load_openapi_spec(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_backwards_compatibility(spec_v1_path: str, spec_v2_path: str) -> CompatibilityReport:
    spec_v1 = load_openapi_spec(spec_v1_path)
    spec_v2 = load_openapi_spec(spec_v2_path)
    return compare_openapi_specs(spec_v1, spec_v2)


def _risk_level(risk_score: float) -> str:
    if risk_score >= 5.0:
        return "CRITICAL"
    if risk_score >= 3.0:
        return "HIGH"
    if risk_score >= 1.5:
        return "MEDIUM"
    return "LOW"


def format_risk_summary(report: CompatibilityReport) -> str:
    level = _risk_level(report.risk_score)
    return (
        f"BACKWARD_COMPATIBILITY_RISK={report.risk_score:.2f} "
        f"LEVEL={level} "
        f"BREAKING_CHANGES={len(report.changes)} "
        f"REMOVED_ENDPOINTS={report.removed_endpoints}"
    )


def format_compatibility_report(report: CompatibilityReport) -> str:
    lines = [
        format_risk_summary(report),
        f"endpoints_v1={report.total_endpoints_v1} endpoints_v2={report.total_endpoints_v2} "
        f"added_endpoints={report.added_endpoints} compatibility_score={report.compatibility_score:.3f}",
    ]
    if report.changes:
        lines.append("top_changes:")
        for change in report.changes[:5]:
            lines.append(
                f"- {change.change_type.value} | severity={change.severity:.1f} | "
                f"{change.location} | {change.description}"
            )
    else:
        lines.append("top_changes: none")
    return "\n".join(lines)


def _main() -> int:
    parser = argparse.ArgumentParser(description="OpenAPI backwards compatibility risk report")
    parser.add_argument("spec_v1", help="Path to baseline OpenAPI spec (v1)")
    parser.add_argument("spec_v2", help="Path to new OpenAPI spec (v2)")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only one-line risk summary for CI/pipeline logs",
    )
    args = parser.parse_args()
    report = calculate_backwards_compatibility(args.spec_v1, args.spec_v2)
    if args.summary_only:
        print(format_risk_summary(report))
    else:
        print(format_compatibility_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
