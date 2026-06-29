---
name: "Container Image Security & SBOM Generation"
role: "DevOps"
trigger: "Сканирование образов, Trivy/Grype, SBOM, base image hardening, CVE triage"
priority: critical
allowed_tools: ["bash", "trivy", "syft", "mcp:registry"]
context_rules:
 include: ["docker/", "config/image_policies.yaml"]
 exclude: ["*.tar", "tmp/"]
memory_integration: true
worktree_isolation: false
---
## Цель
Zero-vulnerability base: сканирование до push, генерация SBOM, авто-patch критических CVE.

## Алгоритм
1. Запустить `trivy image --severity HIGH,CRITICAL`.
2. Сгенерировать SBOM через `syft`.
3. Сравнить с `image_policies.yaml`.
4. Блокировать push при breach, сохранить отчёт.

## Интеграции
- MCP: `registry`, `trivy_api`.
- `.claudeignore`: скрыть `scan_logs/`, оставить `security_report.json`.

## Ограничения
- Fail on critical CVE.
- Only distroless/minimal bases allowed.

## Формат вывода
`{"vuln_count": 0, "sbom_generated": true, "compliance": "PASS", "block_push": false}`

## Фоллбэк
При critical → auto-create PR с updated base, block merge.
