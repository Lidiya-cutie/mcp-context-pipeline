from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


class HTTPStatusCode(Enum):
    SUCCESS = (200, 299)
    REDIRECT = (300, 399)
    CLIENT_ERROR = (400, 499)
    SERVER_ERROR = (500, 599)

    @classmethod
    def get_category(cls, status_code: int) -> str:
        for category, (min_code, max_code) in {
            "success": cls.SUCCESS.value,
            "redirect": cls.REDIRECT.value,
            "client_error": cls.CLIENT_ERROR.value,
            "server_error": cls.SERVER_ERROR.value,
        }.items():
            if min_code <= status_code <= max_code:
                return category
        return "unknown"


@dataclass
class Endpoint:
    method: str
    path: str
    version: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    response: Optional[Dict[str, Any]] = None
    status_code: Optional[int] = None
    headers: Optional[Dict[str, str]] = None


@dataclass
class RESTAPIMetrics:
    endpoints: List[Endpoint] = field(default_factory=list)

    def add_endpoint(self, endpoint: Endpoint) -> None:
        self.endpoints.append(endpoint)

    def _analyze_resource_orientation(self) -> Dict[str, Any]:
        total = len(self.endpoints)
        if total == 0:
            return {"score": 0.0, "details": {}}

        noun_paths = 0
        verb_paths = 0
        http_method_compliance = 0

        verbs = {"get", "post", "put", "patch", "delete", "options", "head"}

        for endpoint in self.endpoints:
            path_parts = [p for p in endpoint.path.split("/") if p]

            if not path_parts:
                continue

            is_noun = all(
                not re.search(r"^(get|create|update|delete|list|find|search|add|remove|set|unset)", part.lower())
                for part in path_parts
            )

            if is_noun:
                noun_paths += 1
            else:
                verb_paths += 1

            if endpoint.method.lower() in verbs:
                http_method_compliance += 1

        score = (noun_paths / total) * 0.6 + (http_method_compliance / total) * 0.4

        return {
            "score": score,
            "details": {
                "total_endpoints": total,
                "noun_oriented_paths": noun_paths,
                "verb_oriented_paths": verb_paths,
                "http_method_compliance": http_method_compliance,
                "noun_path_ratio": noun_paths / total,
            },
        }

    def _analyze_pagination(self) -> Dict[str, Any]:
        total = len(self.endpoints)
        if total == 0:
            return {"score": 0.0, "details": {}}

        list_endpoints = [
            e for e in self.endpoints
            if e.method.lower() == "get" and e.response
        ]

        if not list_endpoints:
            return {"score": 0.0, "details": {"reason": "no_list_endpoints"}}

        has_pagination = 0
        has_limit_param = 0
        has_offset_param = 0
        has_page_param = 0
        has_total_count = 0
        has_next_link = 0
        consistent_strategy = 0

        pagination_strategies: Dict[str, Set[str]] = {
            "offset_limit": set(),
            "page_size": set(),
            "cursor": set(),
        }

        for endpoint in list_endpoints:
            params = endpoint.params or {}

            limit_present = any(
                k.lower() in {"limit", "page_size", "per_page", "size"}
                for k in params.keys()
            )

            offset_present = any(
                k.lower() in {"offset", "skip", "start"}
                for k in params.keys()
            )

            page_present = any(
                k.lower() in {"page", "page_number"}
                for k in params.keys()
            )

            response = endpoint.response or {}
            if not isinstance(response, dict):
                response = {}

            meta_section = response.get("meta", {})
            if not isinstance(meta_section, dict):
                meta_section = {}

            total_present = any(
                k.lower() in {"total", "count", "total_count"}
                for k in set(response.keys()) | set(meta_section.keys())
            )

            next_link_present = any(
                k.lower() in {"next", "next_link", "next_page"}
                for k in set(response.keys()) | set(meta_section.keys())
            )

            if limit_present:
                has_limit_param += 1

            if offset_present:
                has_offset_param += 1

            if page_present:
                has_page_param += 1

            if total_present:
                has_total_count += 1

            if next_link_present:
                has_next_link += 1

            if limit_present or page_present:
                has_pagination += 1

            if limit_present and offset_present:
                pagination_strategies["offset_limit"].add(endpoint.path)
            elif page_present:
                pagination_strategies["page_size"].add(endpoint.path)
            elif "cursor" in [k.lower() for k in params.keys()]:
                pagination_strategies["cursor"].add(endpoint.path)

        strategy_diversity = sum(1 for s in pagination_strategies.values() if s)
        consistent_strategy = 1 if strategy_diversity == 1 else 0

        score = (
            (has_pagination / len(list_endpoints)) * 0.3 +
            (has_total_count / len(list_endpoints)) * 0.2 +
            (has_next_link / len(list_endpoints)) * 0.2 +
            consistent_strategy * 0.3
        )

        return {
            "score": score,
            "details": {
                "total_list_endpoints": len(list_endpoints),
                "endpoints_with_pagination": has_pagination,
                "has_limit_param": has_limit_param,
                "has_offset_param": has_offset_param,
                "has_page_param": has_page_param,
                "has_total_count": has_total_count,
                "has_next_link": has_next_link,
                "pagination_strategies": {k: len(v) for k, v in pagination_strategies.items()},
                "consistent_strategy": consistent_strategy,
            },
        }

    def _analyze_versioning(self) -> Dict[str, Any]:
        total = len(self.endpoints)
        if total == 0:
            return {"score": 0.0, "details": {}}

        version_in_path = 0
        version_in_header = 0
        version_in_query = 0
        consistent_versioning = 0

        path_versions: Set[str] = set()
        header_versions: Set[str] = set()

        for endpoint in self.endpoints:
            path = endpoint.path

            path_version_match = re.search(r"/v\d+/", path)
            if path_version_match:
                version_in_path += 1
                path_versions.add(path_version_match.group())

            headers = endpoint.headers or {}
            if any(k.lower() in {"api-version", "accept-version", "x-api-version"} for k in headers.keys()):
                version_in_header += 1
                for k, v in headers.items():
                    if k.lower() in {"api-version", "accept-version", "x-api-version"}:
                        header_versions.add(v)

            params = endpoint.params or {}
            if any(k.lower() in {"version", "v", "api_version"} for k in params.keys()):
                version_in_query += 1

        if path_versions and len(path_versions) == 1:
            consistent_versioning = 1
        elif header_versions and len(header_versions) == 1:
            consistent_versioning = 1

        score = (
            (version_in_path / total) * 0.5 +
            (version_in_header / total) * 0.3 +
            (version_in_query / total) * 0.1 +
            consistent_versioning * 0.1
        )

        return {
            "score": score,
            "details": {
                "total_endpoints": total,
                "version_in_path": version_in_path,
                "version_in_header": version_in_header,
                "version_in_query": version_in_query,
                "path_versions": list(path_versions),
                "header_versions": list(header_versions),
                "consistent_versioning": consistent_versioning,
            },
        }

    def _analyze_error_codes(self) -> Dict[str, Any]:
        total = len(self.endpoints)
        if total == 0:
            return {"score": 0.0, "details": {}}

        status_codes: List[int] = [e.status_code for e in self.endpoints if e.status_code is not None]

        if not status_codes:
            return {"score": 0.0, "details": {"reason": "no_status_codes"}}

        has_200 = sum(1 for code in status_codes if 200 <= code <= 299)
        has_201 = sum(1 for code in status_codes if code == 201)
        has_204 = sum(1 for code in status_codes if code == 204)
        has_400 = sum(1 for code in status_codes if 400 <= code <= 499)
        has_401 = sum(1 for code in status_codes if code == 401)
        has_403 = sum(1 for code in status_codes if code == 403)
        has_404 = sum(1 for code in status_codes if code == 404)
        has_409 = sum(1 for code in status_codes if code == 409)
        has_422 = sum(1 for code in status_codes if code == 422)
        has_500 = sum(1 for code in status_codes if 500 <= code <= 599)

        appropriate_2xx = has_200 + has_201 + has_204
        meaningful_4xx = has_400 + has_401 + has_403 + has_404 + has_409 + has_422

        score = (
            (appropriate_2xx / total) * 0.4 +
            (meaningful_4xx / total) * 0.3 +
            (1 if has_500 == 0 else 0) * 0.3
        )

        return {
            "score": score,
            "details": {
                "total_endpoints": total,
                "has_200": has_200,
                "has_201": has_201,
                "has_204": has_204,
                "has_400": has_400,
                "has_401": has_401,
                "has_403": has_403,
                "has_404": has_404,
                "has_409": has_409,
                "has_422": has_422,
                "has_500": has_500,
                "appropriate_2xx": appropriate_2xx,
                "meaningful_4xx": meaningful_4xx,
            },
        }

    def _analyze_structural_redundancy(self) -> Dict[str, Any]:
        total = len(self.endpoints)
        if total == 0:
            return {"score": 0.0, "details": {}}

        has_data_wrapper = 0
        has_meta_section = 0
        has_errors_section = 0
        consistent_response_structure = 0
        has_pagination_meta = 0

        response_structures: List[Dict[str, Any]] = []

        for endpoint in self.endpoints:
            if not endpoint.response:
                continue

            response = endpoint.response
            if not isinstance(response, dict):
                continue

            has_data = "data" in response
            has_result = "result" in response
            has_items = "items" in response

            if has_data or has_result or has_items:
                has_data_wrapper += 1

            if "meta" in response:
                has_meta_section += 1

            if "errors" in response or "error" in response:
                has_errors_section += 1

            response_structure = {
                "has_data_wrapper": has_data or has_result or has_items,
                "has_meta": "meta" in response,
                "has_errors": "errors" in response or "error" in response,
                "top_level_keys": set(response.keys()),
            }
            response_structures.append(response_structure)

            if "meta" in response and any(
                k in response.get("meta", {})
                for k in {"total", "page", "limit", "offset"}
            ):
                has_pagination_meta += 1

        if response_structures:
            structures = [s["top_level_keys"] for s in response_structures]
            if structures and all(s == structures[0] for s in structures):
                consistent_response_structure = 1

        score = (
            (has_data_wrapper / total) * 0.3 +
            (has_meta_section / total) * 0.2 +
            (has_errors_section / total) * 0.2 +
            consistent_response_structure * 0.3
        )

        return {
            "score": score,
            "details": {
                "total_endpoints": total,
                "has_data_wrapper": has_data_wrapper,
                "has_meta_section": has_meta_section,
                "has_errors_section": has_errors_section,
                "consistent_response_structure": consistent_response_structure,
                "has_pagination_meta": has_pagination_meta,
            },
        }

    def compute_all_metrics(self) -> Dict[str, Any]:
        return {
            "resource_orientation": self._analyze_resource_orientation(),
            "pagination": self._analyze_pagination(),
            "versioning": self._analyze_versioning(),
            "error_codes": self._analyze_error_codes(),
            "structural_redundancy": self._analyze_structural_redundancy(),
        }

    def compute_overall_score(self) -> float:
        metrics = self.compute_all_metrics()
        weights = {
            "resource_orientation": 0.2,
            "pagination": 0.2,
            "versioning": 0.15,
            "error_codes": 0.25,
            "structural_redundancy": 0.2,
        }

        total_score = 0.0
        for metric_name, weight in weights.items():
            score = metrics.get(metric_name, {}).get("score", 0.0)
            total_score += score * weight

        return total_score
