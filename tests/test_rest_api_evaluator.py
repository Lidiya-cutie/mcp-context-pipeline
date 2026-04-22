import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rest_api_evaluator import RESTAPIEvaluator, load_rest_api_records


async def test_rest_api_evaluator():
    print("=== Тест REST API Evaluator ===")
    print()

    good_dataset = "/mldata/mcp_context_pipeline/data/rest_api_eval_good.jsonl"
    poor_dataset = "/mldata/mcp_context_pipeline/data/rest_api_eval_poor.jsonl"

    print("1. Загрузка записей хорошего API:")
    good_records = load_rest_api_records(good_dataset)
    print(f"   Загружено {len(good_records)} записей")
    print(f"   Пример записи: {good_records[0].__dict__}")
    print()

    print("2. Загрузка записей плохого API:")
    poor_records = load_rest_api_records(poor_dataset)
    print(f"   Загружено {len(poor_records)} записей")
    print(f"   Пример записи: {poor_records[0].__dict__}")
    print()

    print("3. Оценка хорошего API:")
    good_evaluator = RESTAPIEvaluator(dataset_path=good_dataset)
    good_report = await good_evaluator.run()
    print(f"   Статус: {good_report['status']}")
    print(f"   Overall Score: {good_report['quality']['overall_score']:.2f}")
    print()
    print("   Gate checks:")
    for check in good_report["gates"]["checks"]:
        status_icon = "PASS" if check["status"] == "pass" else "FAIL"
        print(f"   - {check['name']}: {check['value']:.2f} (target: {check['threshold']}) [{status_icon}]")
    print()

    print("4. Оценка плохого API:")
    poor_evaluator = RESTAPIEvaluator(dataset_path=poor_dataset)
    poor_report = await poor_evaluator.run()
    print(f"   Статус: {poor_report['status']}")
    print(f"   Overall Score: {poor_report['quality']['overall_score']:.2f}")
    print()
    print("   Gate checks:")
    for check in poor_report["gates"]["checks"]:
        status_icon = "PASS" if check["status"] == "pass" else "FAIL"
        print(f"   - {check['name']}: {check['value']:.2f} (target: {check['threshold']}) [{status_icon}]")
    print()

    print("5. Экспорт артефактов:")
    good_artifacts = await good_evaluator.run_and_export("artifacts/rest_api_eval")
    print(f"   Хороший API артефакты:")
    for artifact_type, path in good_artifacts.get("artifacts", {}).items():
        print(f"   - {artifact_type}: {path}")
    print()

    print("6. Сравнение:")
    print(f"   Хороший API:")
    print(f"     - Overall Score: {good_report['quality']['overall_score']:.2f}")
    print(f"     - Resource Orientation: {good_report['quality']['resource_orientation']['score']:.2f}")
    print(f"     - Pagination: {good_report['quality']['pagination']['score']:.2f}")
    print(f"     - Versioning: {good_report['quality']['versioning']['score']:.2f}")
    print(f"     - Error Codes: {good_report['quality']['error_codes']['score']:.2f}")
    print(f"     - Structural Redundancy: {good_report['quality']['structural_redundancy']['score']:.2f}")
    print()
    print(f"   Плохой API:")
    print(f"     - Overall Score: {poor_report['quality']['overall_score']:.2f}")
    print(f"     - Resource Orientation: {poor_report['quality']['resource_orientation']['score']:.2f}")
    print(f"     - Pagination: {poor_report['quality']['pagination']['score']:.2f}")
    print(f"     - Versioning: {poor_report['quality']['versioning']['score']:.2f}")
    print(f"     - Error Codes: {poor_report['quality']['error_codes']['score']:.2f}")
    print(f"     - Structural Redundancy: {poor_report['quality']['structural_redundancy']['score']:.2f}")


if __name__ == "__main__":
    asyncio.run(test_rest_api_evaluator())
