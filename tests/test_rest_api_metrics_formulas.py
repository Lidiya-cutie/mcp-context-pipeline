import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rest_api_metrics_formulas import (
    resource_orientation_formula,
    pagination_formula,
    versioning_formula,
    error_codes_formula,
    structural_redundancy_formula,
    overall_score_formula,
    evaluate_rest_api_quality
)


def test_formulas():
    print("=== Тест формул REST API метрик ===")
    print()

    print("1. Ресурсный подход:")
    print(f"   Хорошее API (6/6 noun paths, 6/6 HTTP compliance): {resource_orientation_formula(6, 6, 6):.2f}")
    print(f"   Плохое API (0/4 noun paths, 4/4 HTTP compliance): {resource_orientation_formula(4, 0, 4):.2f}")
    print(f"   Среднее API (3/5 noun paths, 4/5 HTTP compliance): {resource_orientation_formula(5, 3, 4):.2f}")
    print()

    print("2. Пагинация:")
    print(f"   Хорошее API (3/3 пагинация, 3/3 total, 3/3 next, True стратегия): {pagination_formula(3, 3, 3, 3, True):.2f}")
    print(f"   Плохое API (0/3 пагинация, 0/3 total, 0/3 next, False стратегия): {pagination_formula(3, 0, 0, 0, False):.2f}")
    print(f"   Среднее API (2/3 пагинация, 2/3 total, 1/3 next, True стратегия): {pagination_formula(3, 2, 2, 1, True):.2f}")
    print()

    print("3. Версионность:")
    print(f"   Хорошее API (6/6 path, 6/6 header, 0/6 query, True консистентность): {versioning_formula(6, 6, 6, 0, True):.2f}")
    print(f"   Плохое API (0/4 path, 0/4 header, 0/4 query, False консистентность): {versioning_formula(4, 0, 0, 0, False):.2f}")
    print(f"   Среднее API (3/5 path, 2/5 header, 1/5 query, False консистентность): {versioning_formula(5, 3, 2, 1, False):.2f}")
    print()

    print("4. Коды ошибок:")
    print(f"   Хорошее API (7/6 2xx, 2/6 4xx, 0 500): {error_codes_formula(6, 7, 2, 0):.2f}")
    print(f"   Плохое API (3/4 2xx, 0/4 4xx, 1 500): {error_codes_formula(4, 3, 0, 1):.2f}")
    print(f"   Среднее API (5/5 2xx, 1/5 4xx, 0 500): {error_codes_formula(5, 5, 1, 0):.2f}")
    print()

    print("5. Структурная избыточность:")
    print(f"   Хорошее API (6/6 data, 6/6 meta, 6/6 errors, True структура): {structural_redundancy_formula(6, 6, 6, 6, True):.2f}")
    print(f"   Плохое API (0/4 data, 0/4 meta, 0/4 errors, False структура): {structural_redundancy_formula(4, 0, 0, 0, False):.2f}")
    print(f"   Среднее API (3/5 data, 2/5 meta, 1/5 errors, False структура): {structural_redundancy_formula(5, 3, 2, 1, False):.2f}")
    print()

    print("6. Общая оценка:")
    print(f"   Хорошее API: {overall_score_formula(1.0, 0.8, 0.9, 0.9, 0.8):.2f}")
    print(f"   Плохое API: {overall_score_formula(0.4, 0.0, 0.0, 0.3, 0.0):.2f}")
    print(f"   Среднее API: {overall_score_formula(0.7, 0.6, 0.5, 0.7, 0.4):.2f}")
    print()

    print("=== Полная оценка хорошего API ===")
    good_api = evaluate_rest_api_quality(
        total_endpoints=6,
        noun_paths=6,
        http_method_compliance=6,
        list_endpoints=3,
        endpoints_with_pagination=3,
        has_total_count=3,
        has_next_link=3,
        consistent_pagination_strategy=True,
        version_in_path=6,
        version_in_header=6,
        version_in_query=0,
        consistent_versioning=True,
        appropriate_2xx=7,
        meaningful_4xx=2,
        has_500=0,
        has_data_wrapper=6,
        has_meta_section=6,
        has_errors_section=6,
        consistent_response_structure=True
    )
    for metric, data in good_api.items():
        if metric != "passed":
            status = "PASS" if data["score"] >= data["target"] else "FAIL"
            print(f"   {metric}: {data['score']:.2f} (target: {data['target']}) [{status}]")
    print(f"   Overall: {good_api['overall_score']['score']:.2f} (target: {good_api['overall_score']['target']}) [{'PASS' if good_api['passed'] else 'FAIL'}]")
    print()

    print("=== Полная оценка плохого API ===")
    bad_api = evaluate_rest_api_quality(
        total_endpoints=4,
        noun_paths=0,
        http_method_compliance=4,
        list_endpoints=3,
        endpoints_with_pagination=0,
        has_total_count=0,
        has_next_link=0,
        consistent_pagination_strategy=False,
        version_in_path=0,
        version_in_header=0,
        version_in_query=0,
        consistent_versioning=False,
        appropriate_2xx=3,
        meaningful_4xx=0,
        has_500=1,
        has_data_wrapper=0,
        has_meta_section=0,
        has_errors_section=0,
        consistent_response_structure=False
    )
    for metric, data in bad_api.items():
        if metric != "passed":
            status = "PASS" if data["score"] >= data["target"] else "FAIL"
            print(f"   {metric}: {data['score']:.2f} (target: {data['target']}) [{status}]")
    print(f"   Overall: {bad_api['overall_score']['score']:.2f} (target: {bad_api['overall_score']['target']}) [{'PASS' if bad_api['passed'] else 'FAIL'}]")


if __name__ == "__main__":
    test_formulas()
