---
name: "Frondalysis PDF Generation"
role: "Technical Writer / Data Scientist"
trigger: "Генерация аналитического отчёта в PDF, формирование документа по ГОСТ"
priority: high
allowed_tools: ["bash", "python", "mcp:frondalysis_pdf", "mcp:anthropic_api"]
context_rules:
  include: ["templates/", "prompts/", "tests/"]
  exclude: ["*.aux", "*.log", "*.fls"]
memory_integration: false
worktree_isolation: false
---
## Цель
Транзитная генерация PDF через пайплайн LLM → MD → Pandoc → XeLaTeX → PDF.

## Пайплайн
1. Пользователь описывает содержание документа
2. LLM генерирует Markdown (по prompts/system-prompt.md)
3. frondalysis_pdf.validate_markdown — проверка
4. frondalysis_pdf.generate_pdf — конвертация
5. PDF сохраняется в /mldata/rnd29-frondalysis/output/

## Ограничения
- Только Markdown (нет TikZ, сложных колонтитулов)
- Шрифты: Liberation Serif/Sans
- Формулы: amsmath внутри $$...$$
