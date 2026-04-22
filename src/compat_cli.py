#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from api_compatibility import calculate_backwards_compatibility, load_openapi_spec


def print_report(report, v1_path: str, v2_path: str, detailed: bool = False):
    print(f"\nСравнение OpenAPI спецификаций:")
    print(f"  v1: {v1_path}")
    print(f"  v2: {v2_path}")
    print(f"\nСтатистика:")
    print(f"  Эндпоинтов v1: {report.total_endpoints_v1}")
    print(f"  Эндпоинтов v2: {report.total_endpoints_v2}")
    print(f"  Удалено эндпоинтов: {report.removed_endpoints}")
    print(f"  Добавлено эндпоинтов: {report.added_endpoints}")
    print(f"\nМетрики:")
    print(f"  Скор риска: {report.risk_score:.2f}")
    print(f"  Скор совместимости: {report.compatibility_score:.2f}")
    
    if detailed:
        print(f"\nИзменения ({len(report.changes)}):")
        for change in report.changes:
            print(f"  [{change.change_type.value}] {change.location}")
            print(f"    {change.description}")
            print(f"    Severity: {change.severity}")
    
    if report.compatibility_score < 0.5:
        print(f"\nВНИМАНИЕ: Высокий риск breaking changes!")
        sys.exit(1)
    elif report.compatibility_score < 0.8:
        print(f"\nПРЕДУПРЕЖДЕНИЕ: Обнаружены breaking changes.")
        sys.exit(2)
    else:
        print(f"\nОК: Совместимость на хорошем уровне.")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Инструмент для оценки обратной совместимости API"
    )
    parser.add_argument(
        "v1",
        help="Путь к OpenAPI спецификации v1"
    )
    parser.add_argument(
        "v2",
        help="Путь к OpenAPI спецификации v2"
    )
    parser.add_argument(
        "--detailed", "-d",
        action="store_true",
        help="Показать детальную информацию об изменениях"
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=0.8,
        help="Порог совместимости (default: 0.8)"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Вывести результат в JSON формате"
    )
    
    args = parser.parse_args()
    
    if not Path(args.v1).exists():
        print(f"Ошибка: файл {args.v1} не найден", file=sys.stderr)
        sys.exit(1)
    
    if not Path(args.v2).exists():
        print(f"Ошибка: файл {args.v2} не найден", file=sys.stderr)
        sys.exit(1)
    
    try:
        report = calculate_backwards_compatibility(args.v1, args.v2)
        
        if args.json:
            result = {
                "v1": args.v1,
                "v2": args.v2,
                "total_endpoints_v1": report.total_endpoints_v1,
                "total_endpoints_v2": report.total_endpoints_v2,
                "removed_endpoints": report.removed_endpoints,
                "added_endpoints": report.added_endpoints,
                "risk_score": report.risk_score,
                "compatibility_score": report.compatibility_score,
                "changes": [
                    {
                        "change_type": c.change_type.value,
                        "location": c.location,
                        "description": c.description,
                        "severity": c.severity
                    }
                    for c in report.changes
                ]
            }
            print(json.dumps(result, indent=2))
            
            if report.compatibility_score < args.threshold:
                sys.exit(1)
            else:
                sys.exit(0)
        else:
            print_report(report, args.v1, args.v2, args.detailed)
            
    except Exception as e:
        print(f"Ошибка при анализе: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
