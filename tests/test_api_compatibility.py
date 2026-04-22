import pytest
from src.api_compatibility import (
    calculate_backwards_compatibility,
    ChangeType,
    compare_openapi_specs,
    load_openapi_spec
)


class TestAPICompatibility:
    def test_example_1_products_api_backward_compatible(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_1_v1.json",
            "data/compat_example_1_v2.json"
        )
        assert report.total_endpoints_v1 == 2
        assert report.total_endpoints_v2 == 2
        assert report.removed_endpoints == 0
        assert report.compatibility_score == 1.0
        assert len(report.changes) == 0

    def test_example_2_orders_api_field_removed(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_2_v1.json",
            "data/compat_example_2_v2.json"
        )
        assert report.total_endpoints_v1 == 2
        assert report.removed_endpoints == 0
        assert report.compatibility_score < 1.0
        created_at_removed = any("created_at" in c.description for c in report.changes)
        assert created_at_removed

    def test_example_3_comments_api_backward_compatible(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_3_v1.json",
            "data/compat_example_3_v2.json"
        )
        assert report.total_endpoints_v1 == 1
        assert report.removed_endpoints == 0
        assert report.compatibility_score == 1.0
        assert len(report.changes) == 0

    def test_example_4_blog_api_method_removed(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_4_v1.json",
            "data/compat_example_4_v2.json"
        )
        assert report.total_endpoints_v1 == 2
        assert report.total_endpoints_v2 == 3
        assert report.removed_endpoints == 0
        assert report.compatibility_score < 1.0
        method_changed = any(c.change_type == ChangeType.CHANGED_HTTP_METHOD for c in report.changes)
        assert method_changed

    def test_example_5_notifications_api_multiple_changes(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_5_v1.json",
            "data/compat_example_5_v2.json"
        )
        assert report.total_endpoints_v1 == 2
        assert report.total_endpoints_v2 == 2
        assert report.compatibility_score < 1.0
        type_changes = [c for c in report.changes if c.change_type == ChangeType.CHANGED_FIELD_TYPE]
        assert len(type_changes) > 0

    def test_example_6_users_api_field_removal(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_6_v1.json",
            "data/compat_example_6_v2.json"
        )
        assert report.total_endpoints_v1 == 2
        assert report.total_endpoints_v2 == 2
        assert report.compatibility_score < 1.0
        active_removed = any(c.change_type == ChangeType.REMOVED_FIELD and "active" in c.description for c in report.changes)
        assert active_removed

    def test_example_7_payments_api_type_change_and_method_removed(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_7_v1.json",
            "data/compat_example_7_v2.json"
        )
        assert report.total_endpoints_v1 == 2
        assert report.total_endpoints_v2 == 2
        assert report.compatibility_score < 1.0
        type_changes = [c for c in report.changes if c.change_type == ChangeType.CHANGED_FIELD_TYPE]
        assert len(type_changes) > 0
        amount_change = any("amount" in c.description for c in type_changes)
        assert amount_change

    def test_example_8_inventory_api_nested_changes(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_8_v1.json",
            "data/compat_example_8_v2.json"
        )
        assert report.total_endpoints_v1 == 1
        assert report.total_endpoints_v2 == 1
        assert report.compatibility_score < 1.0
        removed_fields = [c for c in report.changes if c.change_type == ChangeType.REMOVED_FIELD]
        assert len(removed_fields) > 0

    def test_removed_required_field_severity(self):
        spec_v1 = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                                            "required": ["id", "name"]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        spec_v2 = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                                            "required": ["id"]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        report = compare_openapi_specs(spec_v1, spec_v2)
        required_removed = [c for c in report.changes if c.change_type == ChangeType.REMOVED_REQUIRED_FIELD]
        assert len(required_removed) == 1
        assert required_removed[0].severity == 0.8

    def test_added_required_field_severity(self):
        spec_v1 = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                        "required": ["name"]
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        spec_v2 = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                                        "required": ["name", "age"]
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        report = compare_openapi_specs(spec_v1, spec_v2)
        required_added = [c for c in report.changes if c.change_type == ChangeType.ADDED_REQUIRED_FIELD]
        assert len(required_added) == 1
        assert required_added[0].severity == 0.3

    def test_no_changes_compatibility_score(self):
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"id": {"type": "integer"}}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        report = compare_openapi_specs(spec, spec)
        assert report.compatibility_score == 1.0
        assert report.risk_score == 0.0
        assert len(report.changes) == 0

    def test_removed_endpoint_severity(self):
        spec_v1 = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        spec_v2 = {
            "openapi": "3.0.0",
            "paths": {}
        }
        report = compare_openapi_specs(spec_v1, spec_v2)
        removed = [c for c in report.changes if c.change_type == ChangeType.REMOVED_ENDPOINT]
        assert len(removed) == 1
        assert removed[0].severity == 2.0

    def test_field_type_change_severity(self):
        spec_v1 = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"count": {"type": "integer"}}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        spec_v2 = {
            "openapi": "3.0.0",
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"count": {"type": "string"}}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        report = compare_openapi_specs(spec_v1, spec_v2)
        type_changes = [c for c in report.changes if c.change_type == ChangeType.CHANGED_FIELD_TYPE]
        assert len(type_changes) == 1
        assert type_changes[0].severity == 0.5

    def test_compatibility_score_bounds(self):
        report = calculate_backwards_compatibility(
            "data/compat_example_4_v1.json",
            "data/compat_example_4_v2.json"
        )
        assert 0.0 <= report.compatibility_score <= 1.0
        assert report.risk_score >= 0.0

    def test_all_examples_exist(self):
        examples = [
            ("data/compat_example_1_v1.json", "data/compat_example_1_v2.json"),
            ("data/compat_example_2_v1.json", "data/compat_example_2_v2.json"),
            ("data/compat_example_3_v1.json", "data/compat_example_3_v2.json"),
            ("data/compat_example_4_v1.json", "data/compat_example_4_v2.json"),
            ("data/compat_example_5_v1.json", "data/compat_example_5_v2.json"),
            ("data/compat_example_6_v1.json", "data/compat_example_6_v2.json"),
            ("data/compat_example_7_v1.json", "data/compat_example_7_v2.json"),
            ("data/compat_example_8_v1.json", "data/compat_example_8_v2.json"),
        ]
        for v1, v2 in examples:
            load_openapi_spec(v1)
            load_openapi_spec(v2)
