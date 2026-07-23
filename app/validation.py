from __future__ import annotations

import re
from typing import Any

from app.models import Case


def _parse_share(text: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else 0.0


def validate_case_before_rpa(case: Case) -> dict[str, Any]:
    """填前业务校验：缺字段、经营范围长度、持股合计等。"""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    c = case.company
    add("公司中文名", bool(c.name_cn.strip()), c.name_cn or "缺失")
    add("公司英文名", bool(c.name_en.strip()), c.name_en or "缺失")
    add("注册资本", bool(c.capital.strip()), c.capital or "缺失")
    add(
        "业务性质",
        bool(c.business_nature.strip()) and len(c.business_nature.strip()) <= 30,
        f"「{c.business_nature}」长度={len(c.business_nature.strip())}（限30字）",
    )
    add("注册地址(EN)", bool(c.registered_address_en.strip()), c.registered_address_en or "缺失")
    add("至少一名董事/股东", len(case.people) >= 1, f"人数={len(case.people)}")

    total = 0.0
    for i, p in enumerate(case.people, 1):
        prefix = f"成员{i} {p.name_cn or '(未命名)'}"
        add(f"{prefix}-中文名", bool(p.name_cn.strip()), p.name_cn or "缺失")
        add(f"{prefix}-英文名", bool(p.name_en.strip()), p.name_en or "缺失")
        add(f"{prefix}-证件号", bool(p.id_number.strip()), p.id_number or "缺失")
        add(f"{prefix}-持股", bool(p.share_ratio.strip()), p.share_ratio or "缺失")
        add(f"{prefix}-电话", bool(p.phone.strip()), p.phone or "缺失")
        add(f"{prefix}-英文地址", bool(p.address_en.strip()), p.address_en or "缺失")
        total += _parse_share(p.share_ratio)

    add("持股合计=100%", abs(total - 100.0) < 0.01, f"当前合计={total}%")

    failed = [x for x in checks if not x["ok"]]
    return {
        "stage": "precheck",
        "title": "填前业务校验",
        "passed": len(failed) == 0,
        "summary": "通过" if not failed else f"未通过 {len(failed)} 项",
        "checks": checks,
        "failed": failed,
    }


def compare_readback(expected: str, actual: str) -> bool:
    return (expected or "").strip() == (actual or "").strip()


def build_readback_report(
    stage: str,
    title: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    failed = [r for r in rows if not r.get("ok")]
    return {
        "stage": stage,
        "title": title,
        "passed": len(failed) == 0,
        "summary": "回读一致" if not failed else f"回读不一致/漏填 {len(failed)} 项",
        "checks": rows,
        "failed": failed,
    }
