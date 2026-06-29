"""
Test suite for SkillDispatcher.
Runs against live skills at /mldata/mcp_context_pipeline/Навыки/
"""

import sys
from pathlib import Path

sys.path.insert(0, "/tmp/gradio_hardening")

from skill_dispatcher import SkillDispatcher

SKILLS_DIR = "/mldata/mcp_context_pipeline/Навыки"
MCP_DIR = "/mldata/mcp_context_pipeline/src/mcp_servers"

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = ""):
    global passed, failed
    status = "PASS" if condition else "FAIL"
    if condition:
        passed += 1
    else:
        failed += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")


def main():
    print("=" * 60)
    print("SkillDispatcher Tests")
    print("=" * 60)

    # --- 1. Load all skills ---
    print("\n1. Loading skills...")
    sd = SkillDispatcher(skills_dir=SKILLS_DIR, mcp_servers_dir=MCP_DIR)
    skills = sd.list_skills()
    check("Loaded skills count", len(skills) > 0, f"{len(skills)} skills loaded")
    check("Expected ~60 skills", 55 <= len(skills) <= 65, f"got {len(skills)}")

    # --- 2. Categories / roles ---
    print("\n2. Skill categories (roles)...")
    roles = {}
    for s in skills:
        r = s["role"]
        roles[r] = roles.get(r, 0) + 1
    for role, count in sorted(roles.items(), key=lambda x: -x[1]):
        print(f"    {role}: {count}")
    check("Multiple roles found", len(roles) >= 2, f"{len(roles)} roles")

    # --- 3. Find skill for "PII masking in data" ---
    print('\n3. Find: "PII masking in data"')
    results = sd.find_skill("PII masking in data")
    check("Found results", len(results) > 0)
    if results:
        top = results[0]
        print(f"    Top: {top['stem']} (score={top['score']}) — {top['name']}")
        check(
            "Top result is PII-related",
            "pii" in top["stem"].lower() or "masking" in top["name"].lower(),
            top["stem"],
        )

    # --- 4. Find skill for "CI/CD pipeline setup" ---
    print('\n4. Find: "CI/CD pipeline setup"')
    results = sd.find_skill("CI/CD pipeline setup")
    check("Found results", len(results) > 0)
    if results:
        top = results[0]
        print(f"    Top: {top['stem']} (score={top['score']}) — {top['name']}")
        check(
            "Top result is CI/CD-related",
            "ci" in top["stem"].lower() or "ci" in top["name"].lower() or "deploy" in top["name"].lower(),
            top["stem"],
        )

    # --- 5. Find skill for "GPU monitoring" ---
    print('\n5. Find: "GPU monitoring"')
    results = sd.find_skill("GPU monitoring")
    check("Found results", len(results) > 0)
    if results:
        top = results[0]
        print(f"    Top: {top['stem']} (score={top['score']}) — {top['name']}")
        check(
            "Top result is GPU-related",
            "gpu" in top["stem"].lower(),
            top["stem"],
        )

    # --- 6. Get prompt for a skill ---
    print("\n6. Get skill prompt (pii_context_masking)...")
    prompt = sd.get_skill_prompt("pii_context_masking")
    check("Prompt is non-empty", len(prompt) > 0, f"{len(prompt)} chars")
    check(
        "Prompt contains structured content",
        "Цель" in prompt or "Алгоритм" in prompt or "##" in prompt,
    )
    print(f"    Preview: {prompt[:120]}...")

    # --- 7. Get required tools for pii_context_masking ---
    print("\n7. Required tools for pii_context_masking...")
    tools = sd.get_required_tools("pii_context_masking")
    print(f"    bash_tools:   {tools['bash_tools']}")
    print(f"    mcp_servers:  {tools['mcp_servers']}")
    print(f"    external:     {tools['external']}")
    check("Has bash tools", len(tools["bash_tools"]) > 0, str(tools["bash_tools"]))
    check("Has MCP servers", len(tools["mcp_servers"]) > 0, str(tools["mcp_servers"]))
    check(
        "pii_scanner MCP mapped",
        "pii_scanner" in tools["mcp_servers"],
    )

    # --- 7b. Test MCP alias mapping ---
    print("\n7b. MCP alias mapping (gitlab_ci → ci_platform)...")
    tools_cicd = sd.get_required_tools("automated_ci_cd_models")
    print(f"    tools: {tools_cicd}")
    check(
        "gitlab_ci → ci_platform",
        "ci_platform" in tools_cicd["mcp_servers"],
        str(tools_cicd["mcp_servers"]),
    )

    # --- 8. Activate skill ---
    print("\n8. Activate skill pii_context_masking...")
    plan = sd.activate_skill(
        "pii_context_masking",
        task="Mask all PII in /data/export before upload to cloud",
        llm_provider="anthropic",
    )
    check("Plan has system_prompt", len(plan["system_prompt"]) > 0)
    check("Plan has task", plan["task"] == "Mask all PII in /data/export before upload to cloud")
    check("Plan has mcp_servers", len(plan["mcp_servers"]) > 0)
    check("Plan has provider", plan["provider"] == "anthropic")
    check("Plan has context", len(plan["context"]) > 0)
    print(f"    context: {plan['context']}")
    print(f"    mcp_servers: {plan['mcp_servers']}")

    # --- Summary ---
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
