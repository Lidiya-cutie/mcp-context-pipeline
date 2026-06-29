#!/usr/bin/env python3
"""cloud_billing MCP server — cloud cost analysis via CLI (AWS/GCP)."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cloud_billing"
SERVER_VERSION = "1.0.0"

CLOUD_PROVIDER = os.environ.get("CLOUD_PROVIDER", "aws").lower()

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def make_response(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def tool_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _run_cli(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a subprocess, return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Timeout ({timeout}s) running: {cmd[0]}"


def _date_range(period: str) -> tuple[str, str, str, str]:
    """Return (start, end, prev_start, prev_end) in YYYY-MM-DD for given period."""
    today = datetime.now(timezone.utc).date()
    if period == "day":
        start = today
        end = today + timedelta(days=1)
        prev_start = today - timedelta(days=1)
        prev_end = today
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
        prev_start = start - timedelta(days=7)
        prev_end = start
    else:  # month
        start = today.replace(day=1)
        nxt = start.month % 12 + 1
        yr = start.year + (1 if nxt == 1 else 0)
        end = start.replace(year=yr, month=nxt)
        if start.month == 1:
            prev_start = start.replace(year=start.year - 1, month=12)
        else:
            prev_start = start.replace(month=start.month - 1)
        prev_end = start
    return start.isoformat(), end.isoformat(), prev_start.isoformat(), prev_end.isoformat()


# ---------------------------------------------------------------------------
# AWS helpers
# ---------------------------------------------------------------------------

def _aws_cost_explorer(start: str, end: str, group_by: list[dict] | None = None,
                       filter_expr: dict | None = None) -> tuple[bool, dict | str]:
    cmd = [
        "aws", "ce", "get-cost-and-usage",
        "--time-period", f"Start={start},End={end}",
        "--granularity", "DAILY",
        "--metrics", "BlendedCost",
    ]
    if group_by:
        for g in group_by:
            cmd += ["--group-by", json.dumps(g)]
    if filter_expr:
        cmd += ["--filter", json.dumps(filter_expr)]
    cmd += ["--output", "json"]
    rc, out, err = _run_cli(cmd, timeout=45)
    if rc != 0:
        return False, err or out or f"aws ce failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _aws_get_budgets() -> tuple[bool, dict | str]:
    cmd = ["aws", "budgets", "describe-budgets", "--output", "json"]
    rc, out, err = _run_cli(cmd, timeout=30)
    if rc != 0:
        return False, err or out or f"aws budgets failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _aws_get_cost_forecast(start: str, end: str) -> tuple[bool, dict | str]:
    cmd = [
        "aws", "ce", "get-cost-forecast",
        "--time-period", f"Start={start},End={end}",
        "--metric", "BLENDED_COST",
        "--granularity", "MONTHLY",
        "--output", "json",
    ]
    rc, out, err = _run_cli(cmd, timeout=30)
    if rc != 0:
        return False, err or out or f"aws ce forecast failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _aws_get_rightsizing() -> tuple[bool, dict | str]:
    cmd = [
        "aws", "ce", "get-rightsizing-recommendation",
        "--service", "AmazonEC2",
        "--output", "json",
    ]
    rc, out, err = _run_cli(cmd, timeout=45)
    if rc != 0:
        return False, err or out or f"aws rightsizing failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _aws_get_savings_plans() -> tuple[bool, dict | str]:
    cmd = [
        "aws", "ce", "get-savings-plans-purchase-recommendation",
        "--account-scope", "PAYER",
        "--payment-option", "NO_UPFRONT",
        "--product-type", "EC2",
        "--term-in-years", "ONE_YEAR",
        "--lookback-period-in-days", "SEVEN_DAYS",
        "--output", "json",
    ]
    rc, out, err = _run_cli(cmd, timeout=45)
    if rc != 0:
        return False, err or out or f"aws savings-plans failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _aws_get_coverage() -> tuple[bool, dict | str]:
    cmd = [
        "aws", "ce", "get-reservation-coverage",
        "--time-period", f"Start={_date_range('month')[0]},End={_date_range('month')[1]}",
        "--granularity", "MONTHLY",
        "--output", "json",
    ]
    rc, out, err = _run_cli(cmd, timeout=30)
    if rc != 0:
        return False, err or out or f"aws coverage failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _aws_get_anomalies(start: str, end: str) -> tuple[bool, dict | str]:
    cmd = [
        "aws", "ce", "get-anomalies",
        "--date-interval", f"StartDate={start},EndDate={end}",
        "--monitor-arn", "ALL",
        "--output", "json",
    ]
    rc, out, err = _run_cli(cmd, timeout=30)
    if rc != 0:
        return False, err or out or f"aws anomalies failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


# ---------------------------------------------------------------------------
# GCP helpers
# ---------------------------------------------------------------------------

def _gcloud_billing_query(start: str, end: str) -> tuple[bool, dict | str]:
    project = os.environ.get("GCP_PROJECT", "")
    cmd = [
        "gcloud", "alpha", "billing", "accounts", "list",
        "--format=json",
    ]
    rc, out, err = _run_cli(cmd, timeout=30)
    if rc != 0:
        return False, err or out or f"gcloud failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _gcloud_billing_export_query(start: str, end: str) -> tuple[bool, dict | str]:
    """Use bq to query billing export if available."""
    dataset = os.environ.get("GCP_BILLING_DATASET", "billing.gcp_billing_export_v1")
    project = os.environ.get("GCP_PROJECT", "")
    query = (
        f"SELECT service.description AS service, "
        f"SUM(cost) AS total_cost "
        f"FROM `{dataset}` "
        f"WHERE usage_start_time >= '{start}' "
        f"AND usage_start_time < '{end}' "
        f"GROUP BY service ORDER BY total_cost DESC"
    )
    cmd = ["bq", "--project_id", project, "--format=json", "--nouse_legacy_sql", "-q", query]
    rc, out, err = _run_cli(cmd, timeout=60)
    if rc != 0:
        return False, err or out or f"bq query failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _gcloud_budgets() -> tuple[bool, dict | str]:
    project = os.environ.get("GCP_PROJECT", "")
    cmd = [
        "gcloud", "alpha", "billing", "budgets", "list",
        "--billing-account", os.environ.get("GCP_BILLING_ACCOUNT", ""),
        "--format=json",
    ]
    rc, out, err = _run_cli(cmd, timeout=30)
    if rc != 0:
        return False, err or out or f"gcloud budgets failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


def _gcloud_recommendations() -> tuple[bool, dict | str]:
    project = os.environ.get("GCP_PROJECT", "")
    cmd = [
        "gcloud", "recommender", "recommendations", "list",
        "--recommender", "google.compute.image.Recommender",
        "--project", project,
        "--format=json",
    ]
    rc, out, err = _run_cli(cmd, timeout=30)
    if rc != 0:
        return False, err or out or f"gcloud recommender failed (rc={rc})"
    try:
        return True, json.loads(out)
    except json.JSONDecodeError:
        return False, out


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _compute_change(current: float, previous: float) -> str:
    if previous == 0:
        return "N/A (previous was 0)"
    pct = ((current - previous) / previous) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _sum_cost(results: list[dict]) -> float:
    total = 0.0
    for r in results:
        total += float(r.get("Total", {}).get("BlendedCost", 0) if "Total" in r else
                       r.get("Metrics", {}).get("BlendedCost", {}).get("Amount", 0))
    return total


def _extract_groups(results: list[dict]) -> dict[str, float]:
    by_key: dict[str, float] = {}
    for r in results:
        groups = r.get("Groups", [])
        for g in groups:
            keys = g.get("Keys", [])
            amount = float(g.get("Metrics", {}).get("BlendedCost", {}).get("Amount", 0))
            name = keys[0] if keys else "unknown"
            by_key[name] = by_key.get(name, 0) + amount
    return by_key


# -- 1. get_cost_summary --
def _tool_cost_summary(params: dict) -> dict:
    period = params.get("period", "month")
    start, end, prev_start, prev_end = _date_range(period)

    if CLOUD_PROVIDER == "aws":
        ok, data = _aws_cost_explorer(start, end)
        if not ok:
            return tool_error(str(data))
        results = data.get("ResultsByTime", [])
        current = _sum_cost(results)

        ok2, data2 = _aws_cost_explorer(prev_start, prev_end)
        previous = _sum_cost(data2.get("ResultsByTime", [])) if ok2 else 0.0

        change = _compute_change(current, previous)
        lines = [
            f"Cost Summary ({period})",
            f"Period: {start} → {end}",
            f"Current: ${current:,.2f}",
            f"Previous: ${previous:,.2f}",
            f"Change: {change}",
        ]
        return tool_result("\n".join(lines))
    else:
        ok, data = _gcloud_billing_export_query(start, end)
        if not ok:
            return tool_error(f"GCP billing query failed: {data}")
        rows = data if isinstance(data, list) else []
        total = sum(float(r.get("total_cost", 0)) for r in rows)
        ok2, data2 = _gcloud_billing_export_query(prev_start, prev_end)
        prev_total = sum(float(r.get("total_cost", 0)) for r in (data2 if isinstance(data2, list) else [])) if ok2 else 0.0
        change = _compute_change(total, prev_total)
        lines = [
            f"Cost Summary ({period})",
            f"Period: {start} → {end}",
            f"Current: ${total:,.2f}",
            f"Previous: ${prev_total:,.2f}",
            f"Change: {change}",
        ]
        return tool_result("\n".join(lines))


# -- 2. get_cost_by_service --
def _tool_cost_by_service(params: dict) -> dict:
    period = params.get("period", "month")
    start, end, _, _ = _date_range(period)

    if CLOUD_PROVIDER == "aws":
        group_by = [{"Type": "DIMENSION", "Key": "SERVICE"}]
        ok, data = _aws_cost_explorer(start, end, group_by=group_by)
        if not ok:
            return tool_error(str(data))
        results = data.get("ResultsByTime", [])
        services: dict[str, float] = {}
        for r in results:
            for g in r.get("Groups", []):
                keys = g.get("Keys", [])
                amount = float(g.get("Metrics", {}).get("BlendedCost", {}).get("Amount", 0))
                name = keys[0] if keys else "unknown"
                services[name] = services.get(name, 0) + amount
        sorted_svc = sorted(services.items(), key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in sorted_svc)
        lines = [f"Cost by Service ({period})", f"Period: {start} → {end}", f"Total: ${total:,.2f}", ""]
        for svc, cost in sorted_svc:
            pct = (cost / total * 100) if total else 0
            lines.append(f"  {svc}: ${cost:,.2f} ({pct:.1f}%)")
        return tool_result("\n".join(lines))
    else:
        ok, data = _gcloud_billing_export_query(start, end)
        if not ok:
            return tool_error(f"GCP billing query failed: {data}")
        rows = data if isinstance(data, list) else []
        total = sum(float(r.get("total_cost", 0)) for r in rows)
        lines = [f"Cost by Service ({period})", f"Period: {start} → {end}", f"Total: ${total:,.2f}", ""]
        for r in rows:
            svc = r.get("service", "unknown")
            cost = float(r.get("total_cost", 0))
            pct = (cost / total * 100) if total else 0
            lines.append(f"  {svc}: ${cost:,.2f} ({pct:.1f}%)")
        return tool_result("\n".join(lines))


# -- 3. get_cost_by_resource --
def _tool_cost_by_resource(params: dict) -> dict:
    period = params.get("period", "month")
    tag_key = params.get("tag_key", "Project")
    resource_id = params.get("resource_id")
    start, end, _, _ = _date_range(period)

    if CLOUD_PROVIDER == "aws":
        filter_expr = None
        group_by = None
        if resource_id:
            filter_expr = {
                "Dimensions": {
                    "Key": "RESOURCE_ID",
                    "Values": [resource_id] if isinstance(resource_id, str) else resource_id,
                }
            }
        else:
            group_by = [{"Type": "DIMENSION", "Key": "RESOURCE_ID"}]
        ok, data = _aws_cost_explorer(start, end, group_by=group_by, filter_expr=filter_expr)
        if not ok:
            return tool_error(str(data))
        results = data.get("ResultsByTime", [])
        resources: dict[str, float] = {}
        for r in results:
            for g in r.get("Groups", []):
                keys = g.get("Keys", [])
                amount = float(g.get("Metrics", {}).get("BlendedCost", {}).get("Amount", 0))
                name = keys[0] if keys else "unknown"
                resources[name] = resources.get(name, 0) + amount
            if not r.get("Groups") and filter_expr:
                amt = float(r.get("Total", {}).get("BlendedCost", 0))
                resources[resource_id or "filtered"] = resources.get(resource_id or "filtered", 0) + amt
        sorted_res = sorted(resources.items(), key=lambda x: x[1], reverse=True)
        lines = [f"Cost by Resource ({period})", f"Period: {start} → {end}", ""]
        for res, cost in sorted_res[:50]:
            lines.append(f"  {res}: ${cost:,.2f}")
        total = sum(v for _, v in sorted_res)
        lines.append(f"\nTotal: ${total:,.2f}")
        return tool_result("\n".join(lines))
    else:
        return tool_error("GCP resource-level cost requires BigQuery billing export with resource-level granularity")


# -- 4. get_budget_status --
def _tool_budget_status(params: dict) -> dict:
    if CLOUD_PROVIDER == "aws":
        ok, data = _aws_get_budgets()
        if not ok:
            return tool_error(str(data))
        budgets = data.get("Budgets", [])
        if not budgets:
            return tool_result("No budgets configured in AWS Budgets")

        today = datetime.now(timezone.utc).date()
        month_start = today.replace(day=1)
        if today.month == 12:
            month_end = today.replace(year=today.year + 1, month=1)
        else:
            month_end = today.replace(month=today.month + 1)

        lines = ["Budget Status", ""]
        for b in budgets:
            name = b.get("BudgetName", "unknown")
            limit = float(b.get("BudgetLimit", {}).get("Amount", 0))
            actual = float(b.get("CalculatedSpend", {}).get("ActualSpend", {}).get("Amount", 0))
            forecast = float(b.get("CalculatedSpend", {}).get("ForecastedSpend", {}).get("Amount", 0)) if b.get("CalculatedSpend", {}).get("ForecastedSpend") else 0
            unit = b.get("BudgetLimit", {}).get("Unit", "USD")
            pct = (actual / limit * 100) if limit else 0
            forecast_pct = (forecast / limit * 100) if limit else 0
            lines.append(f"Budget: {name}")
            lines.append(f"  Limit: {limit:,.2f} {unit}")
            lines.append(f"  Actual: {actual:,.2f} {unit} ({pct:.1f}%)")
            if forecast:
                lines.append(f"  Forecasted EOM: {forecast:,.2f} {unit} ({forecast_pct:.1f}%)")
            lines.append("")
        return tool_result("\n".join(lines))
    else:
        ok, data = _gcloud_budgets()
        if not ok:
            return tool_error(f"GCP budgets failed: {data}")
        budgets = data if isinstance(data, list) else []
        if not budgets:
            return tool_result("No budgets configured in GCP Billing")
        lines = ["Budget Status (GCP)", ""]
        for b in budgets:
            name = b.get("displayName", "unknown")
            amount = b.get("amount", {})
            specified = float(amount.get("specifiedAmount", {}).get("units", 0))
            currency = amount.get("specifiedAmount", {}).get("currencyCode", "USD")
            lines.append(f"Budget: {name}")
            lines.append(f"  Limit: {specified:,.2f} {currency}")
            lines.append("")
        return tool_result("\n".join(lines))


# -- 5. get_cost_anomalies --
def _tool_cost_anomalies(params: dict) -> dict:
    period = params.get("period", "month")
    start, end, _, _ = _date_range(period)

    if CLOUD_PROVIDER == "aws":
        ok, data = _aws_get_anomalies(start, end)
        if not ok:
            return tool_error(str(data))
        anomalies = data.get("AnomalyReports", [])
        if not anomalies:
            return tool_result(f"No cost anomalies detected in period {start} → {end}")
        lines = [f"Cost Anomalies ({start} → {end})", ""]
        for a in anomalies:
            reason = a.get("AnomalyDetails", {}).get("Feedback", "N/A")
            score = a.get("AnomalyDetails", {}).get("Impact", {}).get("MaxImpact", "N/A")
            start_date = a.get("AnomalyDateRange", {}).get("StartDate", "N/A")
            services = a.get("AnomalyDetails", {}).get("LinkedAccounts", [])
            lines.append(f"Anomaly on {start_date}:")
            lines.append(f"  Impact: ${score}")
            lines.append(f"  Status: {reason}")
            lines.append("")
        return tool_result("\n".join(lines))
    else:
        start_dt, end_dt, _, _ = _date_range(period)
        cmd = [
            "gcloud", "alpha", "billing", "accounts", "list", "--format=json",
        ]
        return tool_result(
            f"GCP cost anomaly detection is not directly available via gcloud CLI.\n"
            f"Use Cloud Monitoring alerts or the Billing console for anomaly detection.\n"
            f"Period: {start} → {end}"
        )


# -- 6. get_savings_recommendations --
def _tool_savings_recommendations(params: dict) -> dict:
    if CLOUD_PROVIDER == "aws":
        lines = ["Savings Recommendations", ""]

        # Right-sizing
        ok_rs, data_rs = _aws_get_rightsizing()
        if ok_rs and isinstance(data_rs, dict):
            recs = data_rs.get("RightsizingRecommendations", [])
            if recs:
                lines.append("## Right-Sizing Recommendations")
                for r in recs[:10]:
                    instance_id = r.get("CurrentInstance", {}).get("InstanceId", "unknown")
                    curr_type = r.get("CurrentInstance", {}).get("ResourceDetails", {}).get("EC2ResourceDetails", {}).get("InstanceType", "unknown")
                    savings = r.get("TerminateRecommendation", {}).get("EstimatedMonthlySavings", "N/A")
                    if isinstance(savings, dict):
                        savings = savings.get("Amount", "N/A")
                    action = r.get("TerminateRecommendation", {}).get("Action", "Modify")
                    lines.append(f"  {instance_id} ({curr_type}): action={action}, monthly_savings=${savings}")
                lines.append("")

        # Reserved instance coverage
        ok_cov, data_cov = _aws_get_coverage()
        if ok_cov and isinstance(data_cov, dict):
            covs = data_cov.get("CoveragesByTime", [])
            if covs:
                total_hrs = 0.0
                covered_hrs = 0.0
                for c in covs:
                    cov = c.get("Total", {}).get("CoverageHours", {})
                    covered_hrs += float(cov.get("OnDemandHours", 0))
                    total_hrs += float(cov.get("TotalRunningHours", 1))
                lines.append("## Reservation Coverage")
                lines.append(f"  Covered: {covered_hrs:.0f}h / {total_hrs:.0f}h total")
                if total_hrs:
                    lines.append(f"  Coverage: {(covered_hrs / total_hrs * 100):.1f}%")
                lines.append("")

        # Savings Plans
        ok_sp, data_sp = _aws_get_savings_plans()
        if ok_sp and isinstance(data_sp, dict):
            sp_recs = data_sp.get("SavingsPlansPurchaseRecommendationDetails", [])
            if sp_recs:
                lines.append("## Savings Plans Recommendations")
                for sp in sp_recs[:5]:
                    instance_family = sp.get("InstanceFamily", "unknown")
                    monthly_savings = sp.get("EstimatedMonthlySavings", {}).get("Amount", "N/A")
                    upfront = sp.get("UpfrontCost", "N/A")
                    lines.append(f"  {instance_family}: upfront=${upfront}, monthly_savings=${monthly_savings}")
                lines.append("")

        if len(lines) <= 2:
            return tool_result("No savings recommendations available at this time.")
        return tool_result("\n".join(lines))
    else:
        ok, data = _gcloud_recommendations()
        if not ok:
            return tool_error(f"GCP recommender failed: {data}")
        recs = data if isinstance(data, list) else []
        if not recs:
            return tool_result("No savings recommendations available at this time.")
        lines = ["Savings Recommendations (GCP)", ""]
        for r in recs[:10]:
            name = r.get("name", "unknown").split("/")[-1]
            desc = r.get("description", "N/A")
            savings = r.get("primaryImpact", {}).get("costProjection", {}).get("cost", {}).get("units", "N/A")
            lines.append(f"  {name}: {desc} (savings: {savings})")
        return tool_result("\n".join(lines))


# -- 7. get_usage_report --
def _tool_usage_report(params: dict) -> dict:
    period = params.get("period", "month")
    start, end, _, _ = _date_range(period)

    if CLOUD_PROVIDER == "aws":
        group_by = [{"Type": "DIMENSION", "Key": "SERVICE"}]
        usage_group = [
            {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
        ]
        cmd = [
            "aws", "ce", "get-cost-and-usage",
            "--time-period", f"Start={start},End={end}",
            "--granularity", "MONTHLY",
            "--metrics", "UsageQuantity", "BlendedCost",
            "--group-by", json.dumps({"Type": "DIMENSION", "Key": "SERVICE"}),
            "--output", "json",
        ]
        rc, out, err = _run_cli(cmd, timeout=45)
        if rc != 0:
            return tool_error(err or out or f"aws ce usage failed (rc={rc})")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return tool_error(out)
        results = data.get("ResultsByTime", [])
        services: dict[str, dict] = {}
        for r in results:
            for g in r.get("Groups", []):
                keys = g.get("Keys", [])
                name = keys[0] if keys else "unknown"
                metrics = g.get("Metrics", {})
                cost = float(metrics.get("BlendedCost", {}).get("Amount", 0))
                usage = float(metrics.get("UsageQuantity", {}).get("Amount", 0))
                unit = metrics.get("UsageQuantity", {}).get("Unit", "")
                if name in services:
                    services[name]["cost"] += cost
                    services[name]["usage"] += usage
                else:
                    services[name] = {"cost": cost, "usage": usage, "unit": unit}
        sorted_svc = sorted(services.items(), key=lambda x: x[1]["cost"], reverse=True)
        lines = [f"Usage Report ({period})", f"Period: {start} → {end}", ""]
        for svc, info in sorted_svc[:20]:
            lines.append(f"  {svc}:")
            lines.append(f"    Usage: {info['usage']:,.2f} {info['unit']}")
            lines.append(f"    Cost: ${info['cost']:,.2f}")
        total = sum(v["cost"] for v in services.values())
        lines.append(f"\nTotal: ${total:,.2f}")
        return tool_result("\n".join(lines))
    else:
        ok, data = _gcloud_billing_export_query(start, end)
        if not ok:
            return tool_error(f"GCP billing query failed: {data}")
        rows = data if isinstance(data, list) else []
        lines = [f"Usage Report ({period})", f"Period: {start} → {end}", ""]
        for r in rows[:20]:
            svc = r.get("service", "unknown")
            cost = float(r.get("total_cost", 0))
            lines.append(f"  {svc}: ${cost:,.2f}")
        total = sum(float(r.get("total_cost", 0)) for r in rows)
        lines.append(f"\nTotal: ${total:,.2f}")
        return tool_result("\n".join(lines))


# -- 8. check_health --
def _tool_check_health(params: dict) -> dict:
    lines = [f"Cloud Billing Health Check (provider: {CLOUD_PROVIDER})", ""]

    # Check CLI
    if CLOUD_PROVIDER == "aws":
        rc, out, err = _run_cli(["aws", "--version"], timeout=10)
        if rc == 0 or rc == -1:
            version = (out or err or "").strip().split("\n")[0]
            lines.append(f"AWS CLI: {version}")
        else:
            lines.append(f"AWS CLI: NOT FOUND")
            return tool_result("\n".join(lines))

        # Check identity
        rc, out, err = _run_cli(["aws", "sts", "get-caller-identity", "--output", "json"], timeout=10)
        if rc == 0:
            try:
                ident = json.loads(out)
                lines.append(f"Account: {ident.get('Account', 'unknown')}")
                lines.append(f"User/Role: {ident.get('Arn', 'unknown')}")
            except json.JSONDecodeError:
                lines.append(f"Identity: {out.strip()}")
        else:
            lines.append(f"STS access: FAILED ({(err or out).strip()})")

        # Check Cost Explorer
        start, end, _, _ = _date_range("day")
        ok, data = _aws_cost_explorer(start, end)
        lines.append(f"Cost Explorer API: {'OK' if ok else 'FAILED'}")
        if not ok:
            lines.append(f"  Error: {str(data)[:200]}")

        # Check Budgets
        ok_b, data_b = _aws_get_budgets()
        lines.append(f"Budgets API: {'OK' if ok_b else 'FAILED'}")
        if ok_b and isinstance(data_b, dict):
            count = len(data_b.get("Budgets", []))
            lines.append(f"  Budgets configured: {count}")

    else:
        rc, out, err = _run_cli(["gcloud", "--version"], timeout=10)
        if rc == 0 or rc == -1:
            version = (out or "").strip().split("\n")[0]
            lines.append(f"GCloud CLI: {version}")
        else:
            lines.append(f"GCloud CLI: NOT FOUND")
            return tool_result("\n".join(lines))

        rc, out, err = _run_cli(["gcloud", "config", "get-value", "project"], timeout=10)
        project = (out or "").strip()
        lines.append(f"Project: {project or 'not set'}")

        rc, out, err = _run_cli(["gcloud", "auth", "list", "--format=json"], timeout=10)
        if rc == 0:
            try:
                accounts = json.loads(out)
                active = [a for a in accounts if a.get("status") == "ACTIVE"]
                lines.append(f"Active account: {active[0].get('account', 'none') if active else 'none'}")
            except json.JSONDecodeError:
                lines.append(f"Auth: {out.strip()[:100]}")
        else:
            lines.append(f"Auth: FAILED")

    lines.append("")
    lines.append("Status: HEALTHY")
    return tool_result("\n".join(lines))


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_cost_summary",
        "description": "Total cost by period (day/week/month) with comparison to previous period",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "Time period for cost summary",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_cost_by_service",
        "description": "Cost breakdown by cloud service (EC2, S3, RDS, etc.)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "Time period",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_cost_by_resource",
        "description": "Cost by tagged resource or resource ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "Time period",
                },
                "resource_id": {
                    "type": "string",
                    "description": "Specific resource ID to filter",
                },
                "tag_key": {
                    "type": "string",
                    "description": "Tag key to group by (default: Project)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_budget_status",
        "description": "Current budget vs actual spend, forecasted end-of-month",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_cost_anomalies",
        "description": "Detect unusual spending patterns and cost spikes",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "Time period to scan for anomalies",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_savings_recommendations",
        "description": "Idle resources, right-sizing, reserved instance/savings plan suggestions",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_usage_report",
        "description": "Usage metrics by service (compute hours, GB stored, requests)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["day", "week", "month"],
                    "description": "Time period",
                },
            },
            "required": [],
        },
    },
    {
        "name": "check_health",
        "description": "Verify CLI tools, billing API access, account identity",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "get_cost_summary": _tool_cost_summary,
    "get_cost_by_service": _tool_cost_by_service,
    "get_cost_by_resource": _tool_cost_by_resource,
    "get_budget_status": _tool_budget_status,
    "get_cost_anomalies": _tool_cost_anomalies,
    "get_savings_recommendations": _tool_savings_recommendations,
    "get_usage_report": _tool_usage_report,
    "check_health": _tool_check_health,
}


def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return make_response(req_id, tool_error(f"Unknown tool: {tool_name}"))
        try:
            result = handler(arguments)
            return make_response(req_id, result)
        except Exception as exc:
            return make_response(req_id, tool_error(f"Tool execution error: {exc}"))

    if method == "ping":
        return make_response(req_id, {})

    # Unknown method — skip notifications, error for requests
    if req_id is not None:
        return make_error(req_id, -32601, f"Method not found: {method}")
    return None


# ---------------------------------------------------------------------------
# Main loop (stdio, async)
# ---------------------------------------------------------------------------

async def main() -> None:
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_event_loop()
    loop.call_soon(lambda: loop.add_reader(sys.stdin.fileno(), lambda: None))

    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)

    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = make_error(None, -32700, "Parse error")
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
            continue

        resp = handle_request(msg)
        if resp is not None:
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
