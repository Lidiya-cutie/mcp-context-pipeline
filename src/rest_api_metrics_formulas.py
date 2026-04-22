"""
Формулы и алгоритмы для метрик качества REST API
"""


def resource_orientation_formula(total_endpoints: int, noun_paths: int, http_method_compliance: int) -> float:
    """
    Метрика: Ресурсный подход

    Формула:
    score = (noun_paths / total_endpoints) * 0.6 + (http_method_compliance / total_endpoints) * 0.4

    Алгоритм:
    1. Для каждого эндпоинта определить, является ли путь ресурсно-ориентированным
       - Путь считается ресурсно-ориентированным, если ни одна часть пути
         не начинается с глагола (get, create, update, delete, list, find, search, add, remove, set, unset)
       - Пример хорошого пути: /api/v1/users, /api/v1/users/1
       - Пример плохого пути: /getUserList, /createUser, /searchUsers

    2. Проверить соответствие HTTP методов
       - GET для получения
       - POST для создания
       - PUT/PATCH для обновления
       - DELETE для удаления

    3. Вычислить score по формуле

    Целевое значение: >= 0.8
    """
    if total_endpoints == 0:
        return 0.0
    return (noun_paths / total_endpoints) * 0.6 + (http_method_compliance / total_endpoints) * 0.4


def pagination_formula(
    list_endpoints: int,
    endpoints_with_pagination: int,
    has_total_count: int,
    has_next_link: int,
    consistent_strategy: bool
) -> float:
    """
    Метрика: Пагинация

    Формула:
    score = (endpoints_with_pagination / list_endpoints) * 0.3 +
            (has_total_count / list_endpoints) * 0.2 +
            (has_next_link / list_endpoints) * 0.2 +
            consistent_strategy * 0.3

    Алгоритм:
    1. Определить list-эндпоинты (GET запросы, возвращающие коллекции)

    2. Для каждого list-эндпоинта проверить:
       - Наличие параметров пагинации:
         * limit, page_size, per_page, size
         * offset, skip, start
         * page, page_number
       - Наличие total/count в ответе
       - Наличие next/next_link/next_page в ответе

    3. Проверить согласованность стратегии пагинации:
       - offset_limit: limit + offset
       - page_size: page + size
       - cursor: cursor-based
       - Стратегия считается согласованной, если используется только одна

    4. Вычислить score по формуле

    Целевое значение: >= 0.7
    """
    if list_endpoints == 0:
        return 0.0
    consistent_value = 1.0 if consistent_strategy else 0.0
    return (
        (endpoints_with_pagination / list_endpoints) * 0.3 +
        (has_total_count / list_endpoints) * 0.2 +
        (has_next_link / list_endpoints) * 0.2 +
        consistent_value * 0.3
    )


def versioning_formula(
    total_endpoints: int,
    version_in_path: int,
    version_in_header: int,
    version_in_query: int,
    consistent_versioning: bool
) -> float:
    """
    Метрика: Версионность

    Формула:
    score = (version_in_path / total_endpoints) * 0.5 +
            (version_in_header / total_endpoints) * 0.3 +
            (version_in_query / total_endpoints) * 0.1 +
            consistent_versioning * 0.1

    Алгоритм:
    1. Определить способ версионирования для каждого эндпоинта:
       - В пути: /api/v1/users, /api/v2/users
       - В заголовке: Accept-Version: v1, X-API-Version: v1
       - В query параметре: ?version=v1, ?v=1

    2. Проверить согласованность версионирования:
       - Все эндпоинты используют одну и ту же версию
       - Версия указана одним способом (не смешивание)

    3. Вычислить score по формуле

    Целевое значение: >= 0.6
    """
    if total_endpoints == 0:
        return 0.0
    consistent_value = 1.0 if consistent_versioning else 0.0
    return (
        (version_in_path / total_endpoints) * 0.5 +
        (version_in_header / total_endpoints) * 0.3 +
        (version_in_query / total_endpoints) * 0.1 +
        consistent_value * 0.1
    )


def error_codes_formula(
    total_endpoints: int,
    appropriate_2xx: int,
    meaningful_4xx: int,
    has_500: int
) -> float:
    """
    Метрика: Коды ошибок

    Формула:
    score = (appropriate_2xx / total_endpoints) * 0.4 +
            (meaningful_4xx / total_endpoints) * 0.3 +
            (1 if has_500 == 0 else 0) * 0.3

    Алгоритм:
    1. Подсчитать количество кодов успеха:
       - 200 OK
       - 201 Created
       - 204 No Content

    2. Подсчитать количество осмысленных кодов ошибок клиента:
       - 400 Bad Request
       - 401 Unauthorized
       - 403 Forbidden
       - 404 Not Found
       - 409 Conflict
       - 422 Unprocessable Entity

    3. Проверить отсутствие кодов ошибок сервера:
       - 500 Internal Server Error (должен отсутствовать или быть минимальным)

    4. Вычислить score по формуле

    Целевое значение: >= 0.7
    """
    if total_endpoints == 0:
        return 0.0
    no_server_errors = 1.0 if has_500 == 0 else 0.0
    return (
        (appropriate_2xx / total_endpoints) * 0.4 +
        (meaningful_4xx / total_endpoints) * 0.3 +
        no_server_errors * 0.3
    )


def structural_redundancy_formula(
    total_endpoints: int,
    has_data_wrapper: int,
    has_meta_section: int,
    has_errors_section: int,
    consistent_structure: bool
) -> float:
    """
    Метрика: Структурная избыточность

    Формула:
    score = (has_data_wrapper / total_endpoints) * 0.3 +
            (has_meta_section / total_endpoints) * 0.2 +
            (has_errors_section / total_endpoints) * 0.2 +
            consistent_structure * 0.3

    Алгоритм:
    1. Для каждого эндпоинта проверить структуру ответа:
       - Наличие обертки данных: data, result, items
       - Наличие секции meta: метаинформация, пагинация
       - Наличие секции errors: информация об ошибках

    2. Проверить согласованность структуры:
       - Все ответы имеют одинаковый набор top-level ключей
       - Последовательность использования полей

    3. Вычислить score по формуле

    Целевое значение: >= 0.6
    """
    if total_endpoints == 0:
        return 0.0
    consistent_value = 1.0 if consistent_structure else 0.0
    return (
        (has_data_wrapper / total_endpoints) * 0.3 +
        (has_meta_section / total_endpoints) * 0.2 +
        (has_errors_section / total_endpoints) * 0.2 +
        consistent_value * 0.3
    )


def overall_score_formula(
    resource_score: float,
    pagination_score: float,
    versioning_score: float,
    error_codes_score: float,
    structural_score: float
) -> float:
    """
    Общая оценка качества REST API

    Формула:
    overall_score = resource_score * 0.2 +
                    pagination_score * 0.2 +
                    versioning_score * 0.15 +
                    error_codes_score * 0.25 +
                    structural_score * 0.2

    Веса:
    - Ресурсный подход: 20%
    - Пагинация: 20%
    - Версионность: 15%
    - Коды ошибок: 25% (наиболее важная метрика)
    - Структурная избыточность: 20%

    Целевое значение: >= 0.7
    """
    return (
        resource_score * 0.2 +
        pagination_score * 0.2 +
        versioning_score * 0.15 +
        error_codes_score * 0.25 +
        structural_score * 0.2
    )


def evaluate_rest_api_quality(
    total_endpoints: int,
    noun_paths: int,
    http_method_compliance: int,
    list_endpoints: int,
    endpoints_with_pagination: int,
    has_total_count: int,
    has_next_link: int,
    consistent_pagination_strategy: bool,
    version_in_path: int,
    version_in_header: int,
    version_in_query: int,
    consistent_versioning: bool,
    appropriate_2xx: int,
    meaningful_4xx: int,
    has_500: int,
    has_data_wrapper: int,
    has_meta_section: int,
    has_errors_section: int,
    consistent_response_structure: bool
) -> dict:
    """
    Полная оценка качества REST API

    Возвращает словарь с оценками по всем метрикам и общей оценкой
    """
    resource_score = resource_orientation_formula(total_endpoints, noun_paths, http_method_compliance)
    pagination_score = pagination_formula(
        list_endpoints, endpoints_with_pagination, has_total_count,
        has_next_link, consistent_pagination_strategy
    )
    versioning_score = versioning_formula(
        total_endpoints, version_in_path, version_in_header,
        version_in_query, consistent_versioning
    )
    error_codes_score = error_codes_formula(total_endpoints, appropriate_2xx, meaningful_4xx, has_500)
    structural_score = structural_redundancy_formula(
        total_endpoints, has_data_wrapper, has_meta_section,
        has_errors_section, consistent_response_structure
    )
    overall = overall_score_formula(
        resource_score, pagination_score, versioning_score,
        error_codes_score, structural_score
    )

    return {
        "resource_orientation": {"score": resource_score, "target": 0.8},
        "pagination": {"score": pagination_score, "target": 0.7},
        "versioning": {"score": versioning_score, "target": 0.6},
        "error_codes": {"score": error_codes_score, "target": 0.7},
        "structural_redundancy": {"score": structural_score, "target": 0.6},
        "overall_score": {"score": overall, "target": 0.7},
        "passed": overall >= 0.7
    }
