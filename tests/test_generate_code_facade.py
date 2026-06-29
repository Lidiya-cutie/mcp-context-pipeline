import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from host_orchestrator import ContextOrchestrator


def test_generate_code_passes_unified_code_task_to_external_search(monkeypatch):
    orchestrator = ContextOrchestrator(enable_external_knowledge=False)

    captured = {}

    async def fake_external_search(**kwargs):
        captured.update(kwargs)
        return {"status": "ok", "intent": "code"}

    monkeypatch.setattr(orchestrator, "external_search", fake_external_search)

    async def run_case():
        return await orchestrator.generate_code(
            prompt="Build FastAPI endpoint for JWT auth",
            description="Need refresh token flow",
            requirements=["use pydantic models", "handle token expiration"],
            language="python",
            framework="fastapi",
            doc_urls=["https://fastapi.tiangolo.com/tutorial/security/"],
            repo="owner/repo",
            constraints=["no global state"],
            tests_required=True,
            limit=3,
        )

    result = asyncio.run(run_case())

    assert result["status"] == "ok"
    assert captured["intent"] == "code"
    assert captured["domain"] == "python"
    assert captured["library"] == "fastapi"
    assert captured["repo"] == "owner/repo"
    assert captured["limit"] == 3
    assert "code_task" in captured
    assert captured["code_task"]["prompt"] == "Build FastAPI endpoint for JWT auth"
    assert captured["code_task"]["framework"] == "fastapi"
    assert captured["code_task"]["doc_urls"] == ["https://fastapi.tiangolo.com/tutorial/security/"]
    assert captured["code_task"]["tests_required"] is True


def test_normalize_code_task_fields():
    task = ContextOrchestrator._normalize_code_task(
        prompt="Generate code",
        requirements=["a", "b"],
        language="Python",
        framework="FastAPI",
        doc_urls=["https://example.com/doc"],
        repo="owner/repo",
        constraints=["c1"],
        tests_required=False,
        description="desc",
        document="doc body",
    )

    assert task["prompt"] == "Generate code"
    assert task["language"] == "python"
    assert task["framework"] == "FastAPI"
    assert task["requirements"] == ["a", "b"]
    assert task["doc_urls"] == ["https://example.com/doc"]
    assert task["constraints"] == ["c1"]
    assert task["tests_required"] is False
    assert task["description"] == "desc"
    assert task["document"] == "doc body"
