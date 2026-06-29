#!/usr/bin/env python3
"""MCP server: ci_templates — CI/CD pipeline template generation."""

import asyncio
import json
import sys
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

TEMPLATES = {
    "python": {
        "language": "python",
        "description": "Python CI/CD pipeline (lint, test, build, deploy)",
        "default_stages": ["lint", "test", "build", "deploy"],
        "base_image": "python:3.12-slim",
        "package_manager": "pip",
        "test_frameworks": ["pytest", "unittest"],
        "linters": ["flake8", "pylint", "mypy", "ruff"],
        "yaml": (
            "stages:\n"
            "  - lint\n"
            "  - test\n"
            "  - build\n"
            "  - deploy\n"
            "\n"
            "variables:\n"
            "  PYTHON_VERSION: \"3.12\"\n"
            "  PIP_CACHE_DIR: \"$CI_PROJECT_DIR/.cache/pip\"\n"
            "\n"
            "cache:\n"
            "  paths:\n"
            "    - .cache/pip\n"
            "    - venv/\n"
            "\n"
            ".python-base:\n"
            "  image: python:${PYTHON_VERSION}-slim\n"
            "  before_script:\n"
            "    - pip install -r requirements.txt\n"
            "\n"
            "lint:flake8:\n"
            "  stage: lint\n"
            "  extends: .python-base\n"
            "  script:\n"
            "    - pip install flake8\n"
            "    - flake8 src/ --max-line-length=120\n"
            "\n"
            "lint:mypy:\n"
            "  stage: lint\n"
            "  extends: .python-base\n"
            "  script:\n"
            "    - pip install mypy\n"
            "    - mypy src/ --ignore-missing-imports\n"
            "\n"
            "test:unit:\n"
            "  stage: test\n"
            "  extends: .python-base\n"
            "  script:\n"
            "    - pip install pytest pytest-cov\n"
            "    - pytest tests/ --cov=src --cov-report=xml\n"
            "  coverage: '/(?i)total.*? (\\d+%)$/'\n"
            "  artifacts:\n"
            "    reports:\n"
            "      coverage_report:\n"
            "        coverage_format: cobertura\n"
            "        path: coverage.xml\n"
            "\n"
            "build:\n"
            "  stage: build\n"
            "  extends: .python-base\n"
            "  script:\n"
            "    - python -m build\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - dist/\n"
            "\n"
            "deploy:\n"
            "  stage: deploy\n"
            "  image: alpine:latest\n"
            "  script:\n"
            "    - echo \"Deploying ${DEPLOY_TARGET}...\"\n"
            "  environment:\n"
            "    name: ${DEPLOY_TARGET}\n"
            "  when: manual\n"
        ),
    },
    "node": {
        "language": "node",
        "description": "Node.js CI/CD pipeline (lint, test, build, deploy)",
        "default_stages": ["lint", "test", "build", "deploy"],
        "base_image": "node:20-alpine",
        "package_manager": "npm",
        "test_frameworks": ["jest", "mocha", "vitest"],
        "linters": ["eslint", "prettier"],
        "yaml": (
            "stages:\n"
            "  - lint\n"
            "  - test\n"
            "  - build\n"
            "  - deploy\n"
            "\n"
            "variables:\n"
            "  NODE_VERSION: \"20\"\n"
            "  npm_config_cache: \"$CI_PROJECT_DIR/.npm\"\n"
            "\n"
            "cache:\n"
            "  paths:\n"
            "    - .npm\n"
            "    - node_modules/\n"
            "\n"
            ".node-base:\n"
            "  image: node:${NODE_VERSION}-alpine\n"
            "  before_script:\n"
            "    - npm ci\n"
            "\n"
            "lint:eslint:\n"
            "  stage: lint\n"
            "  extends: .node-base\n"
            "  script:\n"
            "    - npx eslint . --format json --output-file eslint-report.json\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - eslint-report.json\n"
            "    when: always\n"
            "\n"
            "test:unit:\n"
            "  stage: test\n"
            "  extends: .node-base\n"
            "  script:\n"
            "    - npm test -- --coverage --coverageReporters=cobertura\n"
            "  coverage: '/All files[^|]*\\|[^|]*\\s+(\\d+\\.?\\d*)/'\n"
            "  artifacts:\n"
            "    reports:\n"
            "      coverage_report:\n"
            "        coverage_format: cobertura\n"
            "        path: coverage/cobertura-coverage.xml\n"
            "\n"
            "build:\n"
            "  stage: build\n"
            "  extends: .node-base\n"
            "  script:\n"
            "    - npm run build\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - dist/\n"
            "\n"
            "deploy:\n"
            "  stage: deploy\n"
            "  image: alpine:latest\n"
            "  script:\n"
            "    - echo \"Deploying ${DEPLOY_TARGET}...\"\n"
            "  environment:\n"
            "    name: ${DEPLOY_TARGET}\n"
            "  when: manual\n"
        ),
    },
    "docker": {
        "language": "docker",
        "description": "Docker build+push pipeline",
        "default_stages": ["build", "test", "deploy"],
        "base_image": "docker:24",
        "package_manager": None,
        "test_frameworks": [],
        "linters": ["hadolint"],
        "yaml": (
            "stages:\n"
            "  - lint\n"
            "  - build\n"
            "  - test\n"
            "  - deploy\n"
            "\n"
            "variables:\n"
            "  DOCKER_TLS_CERTDIR: \"/certs\"\n"
            "  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA\n"
            "\n"
            "lint:dockerfile:\n"
            "  stage: lint\n"
            "  image: hadolint/hadolint:latest-debian\n"
            "  script:\n"
            "    - hadolint Dockerfile\n"
            "\n"
            "build:\n"
            "  stage: build\n"
            "  image: docker:24\n"
            "  services:\n"
            "    - docker:24-dind\n"
            "  script:\n"
            "    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY\n"
            "    - docker build -t $IMAGE_TAG .\n"
            "    - docker push $IMAGE_TAG\n"
            "\n"
            "test:image:\n"
            "  stage: test\n"
            "  image: docker:24\n"
            "  services:\n"
            "    - docker:24-dind\n"
            "  script:\n"
            "    - docker pull $IMAGE_TAG\n"
            "    - docker run --rm $IMAGE_TAG --version\n"
            "  needs: [\"build\"]\n"
            "\n"
            "deploy:\n"
            "  stage: deploy\n"
            "  image: alpine:latest\n"
            "  script:\n"
            "    - echo \"Deploying image $IMAGE_TAG to ${DEPLOY_TARGET}...\"\n"
            "  environment:\n"
            "    name: ${DEPLOY_TARGET}\n"
            "  when: manual\n"
        ),
    },
    "k8s": {
        "language": "kubernetes",
        "description": "Kubernetes deployment pipeline",
        "default_stages": ["build", "deploy"],
        "base_image": "bitnami/kubectl",
        "package_manager": None,
        "test_frameworks": [],
        "linters": ["kubeval"],
        "yaml": (
            "stages:\n"
            "  - validate\n"
            "  - deploy\n"
            "\n"
            "variables:\n"
            "  KUBE_NAMESPACE: \"default\"\n"
            "  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA\n"
            "\n"
            "validate:manifests:\n"
            "  stage: validate\n"
            "  image: ghcr.io/yannh/kubeconform:latest\n"
            "  script:\n"
            "    - kubeconform -summary k8s/\n"
            "\n"
            "deploy:staging:\n"
            "  stage: deploy\n"
            "  image: bitnami/kubectl:latest\n"
            "  script:\n"
            "    - kubectl config use-context ${KUBE_CONTEXT}\n"
            "    - kubectl set image deployment/${APP_NAME} ${APP_NAME}=${IMAGE_TAG} -n ${KUBE_NAMESPACE}\n"
            "    - kubectl rollout status deployment/${APP_NAME} -n ${KUBE_NAMESPACE}\n"
            "  environment:\n"
            "    name: staging\n"
            "  only:\n"
            "    - develop\n"
            "\n"
            "deploy:production:\n"
            "  stage: deploy\n"
            "  image: bitnami/kubectl:latest\n"
            "  script:\n"
            "    - kubectl config use-context ${KUBE_CONTEXT}\n"
            "    - kubectl set image deployment/${APP_NAME} ${APP_NAME}=${IMAGE_TAG} -n ${KUBE_NAMESPACE}\n"
            "    - kubectl rollout status deployment/${APP_NAME} -n ${KUBE_NAMESPACE}\n"
            "  environment:\n"
            "    name: production\n"
            "  when: manual\n"
            "  only:\n"
            "    - main\n"
        ),
    },
    "ml-training": {
        "language": "python",
        "description": "ML model training pipeline (data validation, train, evaluate, register)",
        "default_stages": ["validate", "train", "evaluate", "register"],
        "base_image": "python:3.12-slim",
        "package_manager": "pip",
        "test_frameworks": ["pytest"],
        "linters": ["flake8", "ruff"],
        "yaml": (
            "stages:\n"
            "  - validate\n"
            "  - train\n"
            "  - evaluate\n"
            "  - register\n"
            "\n"
            "variables:\n"
            "  PYTHON_VERSION: \"3.12\"\n"
            "  MODEL_NAME: $CI_PROJECT_NAME\n"
            "  EXPERIMENT_NAME: \"default\"\n"
            "\n"
            "validate:data:\n"
            "  stage: validate\n"
            "  image: python:${PYTHON_VERSION}-slim\n"
            "  script:\n"
            "    - pip install pandas great-expectations\n"
            "    - python scripts/validate_data.py\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - data/validated/\n"
            "\n"
            "train:model:\n"
            "  stage: train\n"
            "  image: python:${PYTHON_VERSION}-slim\n"
            "  script:\n"
            "    - pip install -r requirements.txt\n"
            "    - python scripts/train.py --experiment ${EXPERIMENT_NAME}\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - models/\n"
            "      - metrics/\n"
            "\n"
            "evaluate:model:\n"
            "  stage: evaluate\n"
            "  image: python:${PYTHON_VERSION}-slim\n"
            "  script:\n"
            "    - pip install -r requirements.txt\n"
            "    - python scripts/evaluate.py --threshold ${METRIC_THRESHOLD:-0.8}\n"
            "  needs: [\"train:model\"]\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - reports/\n"
            "\n"
            "register:model:\n"
            "  stage: register\n"
            "  image: python:${PYTHON_VERSION}-slim\n"
            "  script:\n"
            "    - pip install mlflow\n"
            "    - python scripts/register_model.py --model ${MODEL_NAME}\n"
            "  when: manual\n"
            "  only:\n"
            "    - main\n"
        ),
    },
    "go": {
        "language": "go",
        "description": "Go CI/CD pipeline (vet, test, build, deploy)",
        "default_stages": ["vet", "test", "build", "deploy"],
        "base_image": "golang:1.22-alpine",
        "package_manager": "go modules",
        "test_frameworks": ["go test"],
        "linters": ["golangci-lint", "gofmt"],
        "yaml": (
            "stages:\n"
            "  - vet\n"
            "  - test\n"
            "  - build\n"
            "  - deploy\n"
            "\n"
            "variables:\n"
            "  GO_VERSION: \"1.22\"\n"
            "\n"
            ".go-base:\n"
            "  image: golang:${GO_VERSION}-alpine\n"
            "  before_script:\n"
            "    - go mod download\n"
            "\n"
            "vet:\n"
            "  stage: vet\n"
            "  extends: .go-base\n"
            "  script:\n"
            "    - go vet ./...\n"
            "    - test -z \"$(gofmt -l .)\"\n"
            "\n"
            "lint:golangci:\n"
            "  stage: vet\n"
            "  extends: .go-base\n"
            "  script:\n"
            "    - go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest\n"
            "    - golangci-lint run ./...\n"
            "\n"
            "test:\n"
            "  stage: test\n"
            "  extends: .go-base\n"
            "  script:\n"
            "    - go test -race -coverprofile=coverage.out ./...\n"
            "    - go tool cover -func=coverage.out\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - coverage.out\n"
            "\n"
            "build:\n"
            "  stage: build\n"
            "  extends: .go-base\n"
            "  script:\n"
            "    - go build -o bin/app ./cmd/app\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - bin/\n"
            "\n"
            "deploy:\n"
            "  stage: deploy\n"
            "  image: alpine:latest\n"
            "  script:\n"
            "    - echo \"Deploying to ${DEPLOY_TARGET}...\"\n"
            "  when: manual\n"
        ),
    },
    "rust": {
        "language": "rust",
        "description": "Rust CI/CD pipeline (check, test, build, deploy)",
        "default_stages": ["check", "test", "build", "deploy"],
        "base_image": "rust:1.77-slim",
        "package_manager": "cargo",
        "test_frameworks": ["cargo test"],
        "linters": ["clippy", "rustfmt"],
        "yaml": (
            "stages:\n"
            "  - check\n"
            "  - test\n"
            "  - build\n"
            "  - deploy\n"
            "\n"
            "variables:\n"
            "  CARGO_HOME: $CI_PROJECT_DIR/.cargo\n"
            "\n"
            "cache:\n"
            "  paths:\n"
            "    - .cargo/\n"
            "    - target/\n"
            "\n"
            "check:fmt:\n"
            "  stage: check\n"
            "  image: rust:1.77-slim\n"
            "  script:\n"
            "    - rustup component add rustfmt\n"
            "    - cargo fmt -- --check\n"
            "\n"
            "check:clippy:\n"
            "  stage: check\n"
            "  image: rust:1.77-slim\n"
            "  script:\n"
            "    - rustup component add clippy\n"
            "    - cargo clippy -- -D warnings\n"
            "\n"
            "test:\n"
            "  stage: test\n"
            "  image: rust:1.77-slim\n"
            "  script:\n"
            "    - cargo test --verbose\n"
            "\n"
            "build:release:\n"
            "  stage: build\n"
            "  image: rust:1.77-slim\n"
            "  script:\n"
            "    - cargo build --release\n"
            "  artifacts:\n"
            "    paths:\n"
            "      - target/release/\n"
            "\n"
            "deploy:\n"
            "  stage: deploy\n"
            "  image: alpine:latest\n"
            "  script:\n"
            "    - echo \"Deploying to ${DEPLOY_TARGET}...\"\n"
            "  when: manual\n"
        ),
    },
}

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFS = [
    {
        "name": "list_templates",
        "description": "List available CI/CD pipeline templates.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_template",
        "description": "Get full template YAML for a specific pipeline type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_name": {
                    "type": "string",
                    "description": "Template name (e.g. python, node, docker, k8s, ml-training, go, rust)",
                },
            },
            "required": ["template_name"],
        },
    },
    {
        "name": "generate_pipeline",
        "description": "Generate a complete CI/CD pipeline configuration from parameters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Programming language (python, node, go, rust, docker)",
                },
                "stages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Pipeline stages (e.g. [\"lint\", \"test\", \"build\", \"deploy\"])",
                },
                "deploy_target": {
                    "type": "string",
                    "description": "Deployment target (k8s, docker, bare-metal, aws, gcp)",
                },
            },
            "required": ["language"],
        },
    },
    {
        "name": "generate_docker_stage",
        "description": "Generate a Docker build+push stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "registry": {
                    "type": "string",
                    "description": "Docker registry URL (default: $CI_REGISTRY)",
                },
                "image_name": {
                    "type": "string",
                    "description": "Docker image name",
                },
                "dockerfile": {
                    "type": "string",
                    "description": "Path to Dockerfile (default: Dockerfile)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional image tags",
                },
            },
            "required": ["image_name"],
        },
    },
    {
        "name": "generate_test_stage",
        "description": "Generate a test stage (unit, integration, lint).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Programming language",
                },
                "test_type": {
                    "type": "string",
                    "enum": ["unit", "integration", "lint"],
                    "description": "Type of test stage",
                },
                "framework": {
                    "type": "string",
                    "description": "Test framework override (e.g. pytest, jest, go test)",
                },
                "coverage": {
                    "type": "boolean",
                    "description": "Enable coverage reporting (default: true)",
                },
            },
            "required": ["language", "test_type"],
        },
    },
    {
        "name": "generate_deploy_stage",
        "description": "Generate a deploy stage for a target environment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["k8s", "docker", "bare-metal", "aws", "gcp"],
                    "description": "Deployment target platform",
                },
                "environment": {
                    "type": "string",
                    "description": "Environment name (staging, production)",
                },
                "app_name": {
                    "type": "string",
                    "description": "Application name",
                },
                "manual": {
                    "type": "boolean",
                    "description": "Require manual trigger (default: true for production)",
                },
            },
            "required": ["target", "environment"],
        },
    },
    {
        "name": "validate_pipeline",
        "description": "Validate a pipeline YAML configuration and check for common mistakes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "yaml_content": {
                    "type": "string",
                    "description": "Pipeline YAML content to validate",
                },
            },
            "required": ["yaml_content"],
        },
    },
    {
        "name": "check_health",
        "description": "Health check: available templates count, server version.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_response(request_id, result):
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n"


def make_error(request_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "error": err}) + "\n"


# ---------------------------------------------------------------------------
# Stage generators
# ---------------------------------------------------------------------------

def _docker_stage(registry, image_name, dockerfile="Dockerfile", tags=None):
    tags = tags or []
    lines = [
        "docker_build_push:",
        "  stage: build",
        "  image: docker:24",
        "  services:",
        "    - docker:24-dind",
        "  variables:",
        f"    IMAGE_NAME: {image_name}",
        "    IMAGE_TAG: $CI_COMMIT_SHORT_SHA",
        "  script:",
        f"    - docker build -f {dockerfile} -t $CI_REGISTRY_IMAGE:$IMAGE_TAG .",
        "    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY",
        "    - docker push $CI_REGISTRY_IMAGE:$IMAGE_TAG",
    ]
    for t in tags:
        lines.append(f"    - docker tag $CI_REGISTRY_IMAGE:$IMAGE_TAG $CI_REGISTRY_IMAGE:{t}")
        lines.append(f"    - docker push $CI_REGISTRY_IMAGE:{t}")
    return "\n".join(lines)


def _test_stage(language, test_type, framework=None, coverage=True):
    lang = language.lower()
    stage_map = {"unit": "test", "integration": "test", "lint": "lint"}
    stage = stage_map.get(test_type, "test")

    if test_type == "lint":
        return _lint_stage(lang, framework)

    if lang == "python":
        fw = framework or "pytest"
        lines = [
            f"test_{test_type}:",
            f"  stage: {stage}",
            "  image: python:3.12-slim",
            "  before_script:",
            "    - pip install -r requirements.txt",
            "  script:",
        ]
        if fw == "pytest":
            opts = "--cov=src" if coverage else ""
            lines.append(f"    - pip install pytest pytest-cov")
            lines.append(f"    - pytest tests/{test_type}/ {opts}")
            if coverage:
                lines.append("  coverage: '/(?i)total.*? (\\d+%)$/'")
        else:
            lines.append(f"    - python -m unittest discover -s tests/{test_type}")
        return "\n".join(lines)

    if lang == "node":
        fw = framework or "jest"
        lines = [
            f"test_{test_type}:",
            f"  stage: {stage}",
            "  image: node:20-alpine",
            "  before_script:",
            "    - npm ci",
            "  script:",
        ]
        if fw == "jest":
            cov_flag = " --coverage" if coverage else ""
            lines.append(f"    - npx jest --testPathPattern=tests/{test_type}{cov_flag}")
        elif fw == "vitest":
            lines.append(f"    - npx vitest run --dir tests/{test_type}")
        else:
            lines.append(f"    - npm test")
        return "\n".join(lines)

    if lang == "go":
        lines = [
            f"test_{test_type}:",
            f"  stage: {stage}",
            "  image: golang:1.22-alpine",
            "  before_script:",
            "    - go mod download",
            "  script:",
            "    - go test -race -coverprofile=coverage.out ./...",
            "    - go tool cover -func=coverage.out",
        ]
        return "\n".join(lines)

    if lang == "rust":
        lines = [
            f"test_{test_type}:",
            f"  stage: {stage}",
            "  image: rust:1.77-slim",
            "  script:",
            "    - cargo test --verbose",
        ]
        return "\n".join(lines)

    return f"# test stage for {language}/{test_type}: not yet implemented"


def _lint_stage(language, framework=None):
    if language == "python":
        linter = framework or "flake8"
        return (
            "lint:\n"
            "  stage: lint\n"
            "  image: python:3.12-slim\n"
            "  before_script:\n"
            "    - pip install -r requirements.txt\n"
            f"  script:\n"
            f"    - pip install {linter}\n"
            f"    - {linter} src/ --max-line-length=120\n"
        )
    if language == "node":
        linter = framework or "eslint"
        return (
            "lint:\n"
            "  stage: lint\n"
            "  image: node:20-alpine\n"
            "  before_script:\n"
            "    - npm ci\n"
            f"  script:\n"
            f"    - npx {linter} .\n"
        )
    if language == "go":
        return (
            "lint:\n"
            "  stage: lint\n"
            "  image: golang:1.22-alpine\n"
            "  before_script:\n"
            "    - go mod download\n"
            "  script:\n"
            "    - go vet ./...\n"
            "    - test -z \"$(gofmt -l .)\"\n"
        )
    if language == "rust":
        return (
            "lint:\n"
            "  stage: lint\n"
            "  image: rust:1.77-slim\n"
            "  script:\n"
            "    - rustup component add clippy rustfmt\n"
            "    - cargo fmt -- --check\n"
            "    - cargo clippy -- -D warnings\n"
        )
    return f"# lint stage for {language}: not yet implemented"


def _deploy_stage(target, environment, app_name=None, manual=None):
    if manual is None:
        manual = environment.lower() in ("production", "prod")

    manual_line = "  when: manual\n" if manual else ""

    if target == "k8s":
        app = app_name or "${APP_NAME}"
        ns = "${KUBE_NAMESPACE}"
        return (
            f"deploy:{environment}:\n"
            f"  stage: deploy\n"
            f"  image: bitnami/kubectl:latest\n"
            f"  script:\n"
            f"    - kubectl config use-context ${{KUBE_CONTEXT}}\n"
            f"    - kubectl apply -f k8s/ -n {ns}\n"
            f"    - kubectl rollout status deployment/{app} -n {ns}\n"
            f"  environment:\n"
            f"    name: {environment}\n"
            f"{manual_line}"
        )

    if target == "docker":
        return (
            f"deploy:{environment}:\n"
            f"  stage: deploy\n"
            f"  image: docker:24\n"
            f"  services:\n"
            f"    - docker:24-dind\n"
            f"  script:\n"
            f"    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY\n"
            f"    - docker pull $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA\n"
            f"    - docker run -d --name {app_name or 'app'} $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA\n"
            f"  environment:\n"
            f"    name: {environment}\n"
            f"{manual_line}"
        )

    if target == "bare-metal":
        return (
            f"deploy:{environment}:\n"
            f"  stage: deploy\n"
            f"  image: alpine:latest\n"
            f"  before_script:\n"
            f"    - apk add --no-cache openssh-client\n"
            f"    - eval $(ssh-agent -s)\n"
            f"    - echo \"$SSH_PRIVATE_KEY\" | tr -d '\\r' | ssh-add -\n"
            f"  script:\n"
            f"    - ssh ${{DEPLOY_USER}}@${{DEPLOY_HOST}} \"cd /opt/{app_name or 'app'} && ./deploy.sh\"\n"
            f"  environment:\n"
            f"    name: {environment}\n"
            f"{manual_line}"
        )

    if target == "aws":
        return (
            f"deploy:{environment}:\n"
            f"  stage: deploy\n"
            f"  image:\n"
            f"    name: amazon/aws-cli:latest\n"
            f"    entrypoint: [\"\"]\n"
            f"  script:\n"
            f"    - aws ecs update-service --cluster {app_name or 'app'}-cluster --service {app_name or 'app'}-service --force-new-deployment\n"
            f"  environment:\n"
            f"    name: {environment}\n"
            f"{manual_line}"
        )

    if target == "gcp":
        return (
            f"deploy:{environment}:\n"
            f"  stage: deploy\n"
            f"  image: google/cloud-sdk:slim\n"
            f"  script:\n"
            f"    - gcloud auth activate-service-account --key-file $GCP_SERVICE_KEY\n"
            f"    - gcloud run deploy {app_name or 'app'} --image $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA --region ${GCP_REGION} --platform managed\n"
            f"  environment:\n"
            f"    name: {environment}\n"
            f"{manual_line}"
        )

    return f"# deploy stage for {target}: not yet implemented"


# ---------------------------------------------------------------------------
# Pipeline generator
# ---------------------------------------------------------------------------

def _generate_pipeline(language, stages=None, deploy_target=None):
    lang = language.lower()
    tpl = TEMPLATES.get(lang)

    if tpl:
        result = tpl["yaml"]
        if deploy_target:
            result += "\n\n" + _deploy_stage(deploy_target, "production")
        return result

    # Fallback: generic pipeline
    stages = stages or ["lint", "test", "build", "deploy"]
    lines = ["stages:"]
    for s in stages:
        lines.append(f"  - {s}")
    lines.append("")
    lines.append(f"# Generic pipeline for {language}")
    lines.append("# Customize stages as needed")
    lines.append("")

    for s in stages:
        if s == "lint":
            lines.append(_lint_stage(lang))
        elif s == "test":
            lines.append(_test_stage(lang, "unit", coverage=True))
        elif s == "build":
            lines.append(f"build:\n  stage: build\n  script:\n    - echo \"Building {language} project...\"\n")
        elif s == "deploy" and deploy_target:
            lines.append(_deploy_stage(deploy_target, "staging"))
        elif s == "deploy":
            lines.append("deploy:\n  stage: deploy\n  script:\n    - echo \"Deploying...\"\n  when: manual\n")
        else:
            lines.append(f"{s}:\n  stage: {s}\n  script:\n    - echo \"Running {s}...\"\n")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def _validate_pipeline(yaml_content):
    errors = []
    warnings = []

    lines = yaml_content.split("\n")

    # Basic structural checks
    has_stages = any(line.strip().startswith("stages:") or line.strip().startswith("stages :") for line in lines)
    if not has_stages:
        errors.append("Missing 'stages:' definition")

    # Check for tabs (YAML prohibits tabs)
    for i, line in enumerate(lines, 1):
        if "\t" in line:
            errors.append(f"Line {i}: contains tab character (YAML uses spaces)")

    # Check stage references exist
    stage_names = set()
    job_stages = []
    in_stages = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("stages:"):
            in_stages = True
            continue
        if in_stages:
            if stripped.startswith("- "):
                stage_names.add(stripped[2:].strip().strip('"').strip("'"))
            elif not stripped.startswith("#") and stripped:
                in_stages = False

    # Extract job definitions (lines with exactly 2-space indent, no leading dash, ending with colon)
    job_pattern = re.compile(r"^  [a-zA-Z0-9_-]+:")
    job_names = set()
    for line in lines:
        m = job_pattern.match(line)
        if m:
            name = line.strip().rstrip(":")
            # Skip known non-job keywords
            if name not in ("variables", "cache", "before_script", "after_script", "script",
                            "image", "services", "artifacts", "only", "except", "rules",
                            "when", "environment", "needs", "extends", "coverage",
                            "paths", "reports", "coverage_report", "coverage_format",
                            "name", "entrypoint"):
                job_names.add(name)

    # Check stage: references in jobs
    stage_ref_pattern = re.compile(r"^\s+stage:\s*(.+)$")
    referenced_stages = set()
    for line in lines:
        m = stage_ref_pattern.match(line)
        if m:
            referenced_stages.add(m.group(1).strip().strip('"').strip("'"))

    unreferenced = referenced_stages - stage_names
    if unreferenced and stage_names:
        warnings.append(f"Jobs reference stages not in 'stages:' list: {', '.join(sorted(unreferenced))}")

    # Check for common mistakes
    if "latest" in yaml_content and "image:" in yaml_content:
        count = yaml_content.count(":latest")
        if count > 0:
            warnings.append(f"Uses ':latest' image tag ({count} occurrence(s)) — pin versions for reproducibility")

    if "$CI_COMMIT_SHORT_SHA" not in yaml_content and "docker push" in yaml_content:
        warnings.append("Docker push without explicit image tag — consider using $CI_COMMIT_SHORT_SHA")

    # Check script: has content
    in_script = False
    script_line_count = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("script:"):
            in_script = True
            script_line_count = 0
            continue
        if in_script:
            if stripped.startswith("- "):
                script_line_count += 1
            elif stripped and not stripped.startswith("#"):
                in_script = False
                if script_line_count == 0:
                    errors.append(f"Line {i}: 'script:' section is empty")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "total_lines": len(lines),
            "stages_defined": len(stage_names),
            "jobs_detected": len(job_names),
        },
    }


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------

def handle_request(method, params, request_id):
    # --- protocol methods ---
    if method == "initialize":
        return make_response(request_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "ci_templates", "version": "1.0.0"},
        })

    if method == "notifications/initialized":
        return None  # notification, no response

    if method == "tools/list":
        return make_response(request_id, {"tools": TOOL_DEFS})

    if method == "resources/list":
        return make_response(request_id, {"resources": []})

    if method == "prompts/list":
        return make_response(request_id, {"prompts": []})

    # --- tool calls ---
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "list_templates":
            items = []
            for key, tpl in TEMPLATES.items():
                items.append({
                    "name": key,
                    "language": tpl["language"],
                    "description": tpl["description"],
                    "default_stages": tpl["default_stages"],
                    "test_frameworks": tpl["test_frameworks"],
                    "linters": tpl["linters"],
                })
            return make_response(request_id, {
                "content": [{"type": "text", "text": json.dumps(items, indent=2, ensure_ascii=False)}],
            })

        if tool_name == "get_template":
            name = arguments.get("template_name", "").lower()
            tpl = TEMPLATES.get(name)
            if not tpl:
                return make_error(request_id, -32602, f"Unknown template: {name}")
            return make_response(request_id, {
                "content": [{"type": "text", "text": tpl["yaml"]}],
            })

        if tool_name == "generate_pipeline":
            language = arguments.get("language", "")
            stages = arguments.get("stages")
            deploy_target = arguments.get("deploy_target")
            if not language:
                return make_error(request_id, -32602, "Missing required parameter: language")
            result = _generate_pipeline(language, stages, deploy_target)
            return make_response(request_id, {
                "content": [{"type": "text", "text": result}],
            })

        if tool_name == "generate_docker_stage":
            image_name = arguments.get("image_name", "")
            if not image_name:
                return make_error(request_id, -32602, "Missing required parameter: image_name")
            registry = arguments.get("registry", "$CI_REGISTRY")
            dockerfile = arguments.get("dockerfile", "Dockerfile")
            tags = arguments.get("tags", [])
            result = _docker_stage(registry, image_name, dockerfile, tags)
            return make_response(request_id, {
                "content": [{"type": "text", "text": result}],
            })

        if tool_name == "generate_test_stage":
            language = arguments.get("language", "")
            test_type = arguments.get("test_type", "")
            if not language or not test_type:
                return make_error(request_id, -32602, "Missing required parameters: language, test_type")
            framework = arguments.get("framework")
            coverage = arguments.get("coverage", True)
            result = _test_stage(language, test_type, framework, coverage)
            return make_response(request_id, {
                "content": [{"type": "text", "text": result}],
            })

        if tool_name == "generate_deploy_stage":
            target = arguments.get("target", "")
            environment = arguments.get("environment", "")
            if not target or not environment:
                return make_error(request_id, -32602, "Missing required parameters: target, environment")
            app_name = arguments.get("app_name")
            manual = arguments.get("manual")
            result = _deploy_stage(target, environment, app_name, manual)
            return make_response(request_id, {
                "content": [{"type": "text", "text": result}],
            })

        if tool_name == "validate_pipeline":
            yaml_content = arguments.get("yaml_content", "")
            if not yaml_content:
                return make_error(request_id, -32602, "Missing required parameter: yaml_content")
            result = _validate_pipeline(yaml_content)
            return make_response(request_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
            })

        if tool_name == "check_health":
            return make_response(request_id, {
                "content": [{"type": "text", "text": json.dumps({
                    "status": "ok",
                    "templates_count": len(TEMPLATES),
                    "template_names": list(TEMPLATES.keys()),
                    "version": "1.0.0",
                    "protocol": "MCP/2024-11-05",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })}],
            })

        return make_error(request_id, -32601, f"Unknown tool: {tool_name}")

    return make_error(request_id, -32601, f"Unknown method: {method}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def main():
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            writer.write(make_error(None, -32700, f"Parse error: {exc}").encode("utf-8"))
            await writer.drain()
            continue

        request_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        response = handle_request(method, params, request_id)
        if response is not None:
            writer.write(response.encode("utf-8"))
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
