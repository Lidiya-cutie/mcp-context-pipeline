"""
Knowledge Bridge MCP Server - Integration with Context 7.

Provides tools and resources for accessing external knowledge base.
Implements Context 7 integration for retrieving company standards and specifications.

Tools:
- search_standard: Search for specific standards in Context 7
- list_domains: List available knowledge domains

Resources:
- kb://architecture/principles: Architectural principles
- kb://tech_stack: Technology stack information
"""

from mcp.server.fastmcp import FastMCP
from typing import List, Dict, Optional
import json
import re

mcp = FastMCP("Knowledge-Bridge-Server")

CONTEXT_7_KNOWLEDGE = {
    "api": {
        "pagination": "Standard: Use cursor-based pagination for all list endpoints. Parameters: 'cursor' (string), 'limit' (int, max 100). Do not use offset/limit.",
        "error_handling": "Standard: Return 4xx for client errors, 5xx for server. Always include JSON body with 'code', 'message', 'request_id'.",
        "versioning": "Standard: Use Semantic Versioning (v1, v2, v3). Maintain backward compatibility for at least 2 versions.",
        "response_format": "Standard: All responses must be JSON. Use snake_case for field names. Include 'data', 'meta' and 'errors' (if any)."
    },
    "security": {
        "auth": "Standard: Use JWT with RS256 algorithm. Token must be passed in 'Authorization: Bearer <token>' header.",
        "pii": "Standard: No raw PII in logs. Mask emails as [MASKED_EMAIL], phones as [MASKED_PHONE].",
        "encryption": "Standard: Use AES-256 for data at rest, TLS 1.3 for data in transit.",
        "rate_limiting": "Standard: Implement rate limiting using Redis. Default: 100 requests per minute per IP."
    },
    "db": {
        "transactions": "Standard: Always use context managers for DB transactions. Timeout: 5 seconds. Retry: 3 times with exponential backoff.",
        "migrations": "Standard: Use Alembic for migrations. Always create rollback migration before forward.",
        "indexing": "Standard: Create indexes on foreign keys and frequently queried fields. Use BRIN for time-series data."
    },
    "python": {
        "style": "Standard: Follow PEP 8. Use Black formatter. Maximum line length: 100.",
        "types": "Standard: Use Pydantic v2 for data validation. Use type hints everywhere.",
        "async": "Standard: Use async/await for I/O operations. Use asyncio.run() for entry points.",
        "testing": "Standard: Use pytest. Target 80% coverage. Mock external dependencies."
    },
    "deployment": {
        "cicd": "Standard: Use GitHub Actions. Require approval for production. All tests must pass.",
        "containerization": "Standard: Use Docker. Multi-stage builds for production images. Use Alpine Linux base.",
        "monitoring": "Standard: Use Prometheus for metrics, Grafana for dashboards. Log to stdout in JSON format."
    }
}

SEARCH_CACHE = {}


@mcp.tool()
def search_standard(domain: str, topic: str) -> str:
    """
    Search for standards in Context 7 knowledge base.

    Args:
        domain: Knowledge domain (api, security, db, python, deployment)
        topic: Specific topic to search for

    Returns:
        Matching standard or fallback message
    """
    domain_key = domain.lower()
    cache_key = f"{domain_key}:{topic.lower()}"

    if cache_key in SEARCH_CACHE:
        return f"[Context 7 / CACHED]: {SEARCH_CACHE[cache_key]}"

    if domain_key in CONTEXT_7_KNOWLEDGE:
        domain_knowledge = CONTEXT_7_KNOWLEDGE[domain_key]

        for key, value in domain_knowledge.items():
            key_lower = key.lower()
            value_lower = value.lower()
            topic_lower = topic.lower()

            if topic_lower in key_lower or any(word in value_lower for word in topic_lower.split()):
                SEARCH_CACHE[cache_key] = value
                return f"[Context 7 / {domain.upper()}]: {value}"

    return f"[Context 7]: No specific standard found for '{topic}' in '{domain}'. Use general best practices."


@mcp.tool()
def list_domains() -> List[str]:
    """
    List all available knowledge domains in Context 7.

    Returns:
        List of domain names
    """
    return list(CONTEXT_7_KNOWLEDGE.keys())


@mcp.resource("kb://architecture/principles")
def get_arch_principles() -> str:
    """
    Get main architectural principles of the company.

    Returns:
        Architectural principles document
    """
    return """
    Architectural Principles (Context 7):

    1. High Cohesion, Low Coupling
       - Related functionality should be in the same module
       - Modules should communicate through well-defined interfaces

    2. Fail Fast Principles
       - Validate inputs at the boundary
       - Fail early with clear error messages
       - Do not silently swallow exceptions

    3. Eventual Consistency for Microservices
       - Accept that consistency is not immediate
       - Use sagas for distributed transactions
       - Design for conflict resolution

    4. API First Design
       - All services expose REST APIs
       - API contracts are documented in OpenAPI/Swagger
       - API versioning is mandatory

    5. Security by Default
       - Authentication and authorization are mandatory
       - All data in transit is encrypted
       - PII is masked in logs
    """


@mcp.resource("kb://tech_stack")
def get_tech_stack() -> str:
    """
    Get current technology stack information.

    Returns:
        Technology stack in JSON format
    """
    stack = {
        "backend": {
            "language": "Python 3.11+",
            "framework": "FastAPI",
            "async": "asyncio"
        },
        "database": {
            "primary": "PostgreSQL 15",
            "cache": "Redis 7",
            "orm": "SQLAlchemy 2.0"
        },
        "message_queue": {
            "broker": "Redis",
            "worker": "Celery",
            "streams": "Redis Streams"
        },
        "llm": {
            "provider": "OpenAI",
            "model": "GPT-4o",
            "fallback": "GPT-4o-mini"
        },
        "infrastructure": {
            "container": "Docker",
            "orchestration": "Docker Compose",
            "monitoring": "Prometheus + Grafana"
        },
        "development": {
            "testing": "pytest",
            "linting": "Black, Ruff",
            "cicd": "GitHub Actions"
        }
    }
    return json.dumps(stack, indent=2)


@mcp.resource("kb://coding_standards/python")
def get_python_standards() -> str:
    """
    Get Python coding standards.

    Returns:
        Python-specific coding standards
    """
    return """
    Python Coding Standards (Context 7):

    1. Code Style
       - Follow PEP 8
       - Use Black for formatting (line_length=100)
       - Use isort for imports

    2. Type Hints
       - Mandatory for all public functions
       - Use Pydantic models for data validation
       - Use Optional[T] for nullable values

    3. Async Patterns
       - Use async/await for I/O operations
       - Use asyncio.gather() for concurrent operations
       - Use context managers (async with) for resources

    4. Error Handling
       - Create custom exception classes
       - Use logging instead of print()
       - Never catch bare Exception

    5. Structure
       - src/ package for main code
       - tests/ for tests
       - Use __init__.py for package imports
    """


@mcp.resource("kb://security/guidelines")
def get_security_guidelines() -> str:
    """
    Get security guidelines and best practices.

    Returns:
        Security guidelines document
    """
    return """
    Security Guidelines (Context 7):

    1. Authentication
       - Use JWT (RS256) for API authentication
       - Token expiration: 1 hour
       - Refresh token rotation: mandatory

    2. Authorization
       - Role-Based Access Control (RBAC)
       - Principle of Least Privilege
       - Resource-level permissions

    3. PII Handling
       - Never log raw PII
       - Use PII Guard for masking
       - Encrypt sensitive data at rest (AES-256)

    4. API Security
       - Rate limiting: 100 req/min per IP
       - CORS: strict origin check
       - Input validation: mandatory

    5. Secrets Management
       - Use environment variables
       - Never commit secrets to git
       - Rotate secrets regularly
    """


@mcp.tool()
def get_best_practices(domain: str) -> str:
    """
    Get best practices for a specific domain.

    Args:
        domain: Domain name (api, security, db, python, deployment)

    Returns:
        Best practices summary
    """
    domain_key = domain.lower()

    if domain_key == "api":
        return """
        API Best Practices:
        - Use RESTful design principles
        - Implement proper HTTP status codes
        - Use cursor-based pagination
        - Include request_id for tracing
        - Version your APIs (v1, v2, ...)
        """
    elif domain_key == "security":
        return """
        Security Best Practices:
        - Encrypt all data in transit (TLS 1.3)
        - Encrypt sensitive data at rest (AES-256)
        - Use JWT for authentication
        - Implement RBAC for authorization
        - Mask PII in logs
        """
    elif domain_key == "db":
        return """
        Database Best Practices:
        - Use connection pooling
        - Always use transactions for writes
        - Index frequently queried fields
        - Use migrations (Alembic)
        - Set appropriate timeouts
        """
    elif domain_key == "python":
        return """
        Python Best Practices:
        - Use type hints
        - Follow PEP 8
        - Use async/await for I/O
        - Use context managers
        - Write tests (pytest)
        """
    elif domain_key == "deployment":
        return """
        Deployment Best Practices:
        - Use Docker containers
        - Implement CI/CD pipeline
        - Monitor everything (Prometheus)
        - Log in JSON format
        - Use blue-green deployment
        """
    else:
        return f"No best practices found for domain: {domain}"


if __name__ == "__main__":
    mcp.run()
