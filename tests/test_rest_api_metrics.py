import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rest_api_metrics import RESTAPIMetrics, Endpoint


def test_good_rest_api():
    metrics = RESTAPIMetrics()

    metrics.add_endpoint(Endpoint(
        method="GET",
        path="/api/v1/users",
        version="v1",
        params={"limit": 10, "offset": 0},
        response={
            "data": [{"id": 1, "name": "User 1"}],
            "meta": {"total": 100, "page": 1, "limit": 10},
        },
        status_code=200,
        headers={"Accept-Version": "v1"}
    ))

    metrics.add_endpoint(Endpoint(
        method="POST",
        path="/api/v1/users",
        version="v1",
        params={},
        response={
            "data": {"id": 2, "name": "User 2"},
        },
        status_code=201,
        headers={"Accept-Version": "v1"}
    ))

    metrics.add_endpoint(Endpoint(
        method="GET",
        path="/api/v1/users/1",
        version="v1",
        params={},
        response={
            "data": {"id": 1, "name": "User 1"},
        },
        status_code=200,
        headers={"Accept-Version": "v1"}
    ))

    metrics.add_endpoint(Endpoint(
        method="PUT",
        path="/api/v1/users/1",
        version="v1",
        params={},
        response={
            "data": {"id": 1, "name": "Updated User"},
        },
        status_code=200,
        headers={"Accept-Version": "v1"}
    ))

    metrics.add_endpoint(Endpoint(
        method="DELETE",
        path="/api/v1/users/1",
        version="v1",
        params={},
        response=None,
        status_code=204,
        headers={"Accept-Version": "v1"}
    ))

    metrics.add_endpoint(Endpoint(
        method="GET",
        path="/api/v1/users/999",
        version="v1",
        params={},
        response={
            "errors": [{"code": "NOT_FOUND", "message": "User not found"}],
        },
        status_code=404,
        headers={"Accept-Version": "v1"}
    ))

    all_metrics = metrics.compute_all_metrics()
    overall_score = metrics.compute_overall_score()

    print("=== Good REST API Metrics ===")
    print(f"Overall Score: {overall_score:.2f}")
    print()
    for metric_name, metric_data in all_metrics.items():
        print(f"{metric_name}:")
        print(f"  Score: {metric_data['score']:.2f}")
        print(f"  Details: {metric_data['details']}")
        print()


def test_poor_rest_api():
    metrics = RESTAPIMetrics()

    metrics.add_endpoint(Endpoint(
        method="GET",
        path="/getUserList",
        version=None,
        params={},
        response=[
            {"id": 1, "name": "User 1"},
            {"id": 2, "name": "User 2"},
        ],
        status_code=200,
        headers={}
    ))

    metrics.add_endpoint(Endpoint(
        method="POST",
        path="/createUser",
        version=None,
        params={},
        response={"success": True, "user_id": 3},
        status_code=200,
        headers={}
    ))

    metrics.add_endpoint(Endpoint(
        method="GET",
        path="/searchUsers",
        version=None,
        params={},
        response={"results": [{"id": 1, "name": "User 1"}]},
        status_code=200,
        headers={}
    ))

    metrics.add_endpoint(Endpoint(
        method="GET",
        path="/deleteUser",
        version=None,
        params={"id": 1},
        response={"status": "ok"},
        status_code=500,
        headers={}
    ))

    all_metrics = metrics.compute_all_metrics()
    overall_score = metrics.compute_overall_score()

    print("=== Poor REST API Metrics ===")
    print(f"Overall Score: {overall_score:.2f}")
    print()
    for metric_name, metric_data in all_metrics.items():
        print(f"{metric_name}:")
        print(f"  Score: {metric_data['score']:.2f}")
        print(f"  Details: {metric_data['details']}")
        print()


if __name__ == "__main__":
    test_good_rest_api()
    print()
    test_poor_rest_api()
