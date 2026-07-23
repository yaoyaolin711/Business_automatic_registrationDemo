from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.fieldmap import ACCOUNT_FIELDS, FILING_FIELDS, FillMode, PlannedFill, build_fill_plan
from app.models import Case
from app.services import SCREENSHOT_DIR, add_log, now_str
from app.validation import build_readback_report, compare_readback, validate_case_before_rpa

ROOT = Path(__file__).resolve().parent.parent


class RpaValidationError(RuntimeError):
    """填前/回读校验失败，阻断提交。"""

    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


async def _input_value(page, selector: str) -> str:
    return (await page.input_value(selector)).strip()


async def _apply_plan(page, plan: PlannedFill) -> None:
    if plan.action == "skip":
        # 故意漏填：清空
        if plan.control == "select":
            # select 无法真正空时保持默认，演示用填一个空 option 不适用，改为不操作
            return
        await page.fill(plan.selector, "")
        return
    if plan.control == "select":
        await page.select_option(plan.selector, value=plan.actual_to_write)
    else:
        await page.fill(plan.selector, plan.actual_to_write)


async def _readback_rows(page, plans: list[PlannedFill]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for plan in plans:
        actual = await _input_value(page, plan.selector)
        # skip 场景：期望有值但页面为空 → 失败
        # wrong 场景：页面值与 expected 不一致 → 失败
        # fill 场景：应完全一致
        ok = compare_readback(plan.expected, actual)
        issue = ""
        if not ok:
            if not actual and plan.required:
                issue = "漏填"
            elif actual != plan.expected:
                issue = "错填/不一致"
            else:
                issue = "不匹配"
        rows.append(
            {
                "name": plan.label,
                "key": plan.key,
                "selector": plan.selector,
                "expected": plan.expected,
                "actual": actual,
                "required": plan.required,
                "action": plan.action,
                "ok": ok if plan.required or plan.expected else True,
                "detail": f"期望「{plan.expected}」实际「{actual}」" + (f"（{issue}）" if issue else ""),
            }
        )
    return rows


def _save_report(case: Case, report: dict[str, Any]) -> Path:
    out_dir = SCREENSHOT_DIR / case.id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"validation_{report['stage']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if case.archive_path:
        archive = Path(case.archive_path)
        if archive.exists():
            (archive / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _attach_report(case: Case, report: dict[str, Any]) -> None:
    case.validation_reports.append(report)
    path = _save_report(case, report)
    add_log(case, f"校验报告已保存：{path.name} | {report['summary']}")


async def run_account_application(
    case: Case,
    base_url: str,
    mode: FillMode = "normal",
) -> tuple[list[str], dict[str, Any]]:
    """申请账号：填前校验 → 按字段映射填写 → 回读 → 通过才提交。"""
    from playwright.async_api import async_playwright

    pre = validate_case_before_rpa(case)
    _attach_report(case, pre)
    if not pre["passed"]:
        raise RpaValidationError(f"填前校验未通过：{pre['summary']}", pre)

    plans = build_fill_plan(case, ACCOUNT_FIELDS, mode=mode)
    shots: list[str] = []
    out_dir = SCREENSHOT_DIR / case.id
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(f"{base_url}/mock/cr-register", wait_until="networkidle")

        # 页面断言：关键表单存在
        await page.wait_for_selector("#reg_form")
        await page.wait_for_selector("#btn_submit")

        for plan in plans:
            await _apply_plan(page, plan)

        rows = await _readback_rows(page, plans)
        report = build_readback_report("account_readback", "账号申请页回读校验", rows)
        report["mode"] = mode
        _attach_report(case, report)

        shot1 = out_dir / "01_account_form.png"
        await page.screenshot(path=str(shot1), full_page=True)
        shots.append(str(shot1))

        if not report["passed"]:
            fail_shot = out_dir / "01b_account_blocked.png"
            await page.screenshot(path=str(fail_shot), full_page=True)
            shots.append(str(fail_shot))
            await browser.close()
            raise RpaValidationError(
                "账号申请回读校验失败，已阻断提交（防漏填/错填）",
                report,
            )

        await page.click("#btn_submit")
        await page.wait_for_selector("#result_ok")

        shot2 = out_dir / "02_account_submitted.png"
        await page.screenshot(path=str(shot2), full_page=True)
        shots.append(str(shot2))
        await browser.close()

    add_log(case, f"RPA：账号申请已提交（mode={mode}）")
    return shots, report


async def run_company_filing(
    case: Case,
    base_url: str,
    mode: FillMode = "normal",
) -> tuple[list[str], dict[str, Any]]:
    """正式填报：登录 → 字段映射填写 → 回读 → 通过才提交。"""
    from playwright.async_api import async_playwright

    if not case.account:
        raise RuntimeError("缺少账号信息，无法填报")

    pre = validate_case_before_rpa(case)
    # 正式填报阶段再记一份摘要（若已有同 stage 不重复轰炸，仍追加便于演示）
    filing_pre = {**pre, "stage": "filing_precheck", "title": "正式填报前业务校验"}
    _attach_report(case, filing_pre)
    if not filing_pre["passed"]:
        raise RpaValidationError(f"正式填报前校验未通过：{filing_pre['summary']}", filing_pre)

    plans = build_fill_plan(case, FILING_FIELDS, mode=mode)
    shots: list[str] = []
    out_dir = SCREENSHOT_DIR / case.id
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(f"{base_url}/mock/cr-filing", wait_until="networkidle")

        await page.fill("#username", case.account.username)
        await page.fill("#password", case.account.password)
        await page.click("#btn_login")
        await page.wait_for_selector("#filing_form")

        for plan in plans:
            await _apply_plan(page, plan)

        rows = await _readback_rows(page, plans)
        report = build_readback_report("filing_readback", "正式填报页回读校验", rows)
        report["mode"] = mode
        _attach_report(case, report)

        shot1 = out_dir / "03_filing_form.png"
        await page.screenshot(path=str(shot1), full_page=True)
        shots.append(str(shot1))

        if not report["passed"]:
            fail_shot = out_dir / "03b_filing_blocked.png"
            await page.screenshot(path=str(fail_shot), full_page=True)
            shots.append(str(fail_shot))
            await browser.close()
            raise RpaValidationError(
                "正式填报回读校验失败，已阻断提交（防漏填/错填）",
                report,
            )

        await page.click("#btn_submit_filing")
        await page.wait_for_selector("#filing_ok")

        shot2 = out_dir / "04_filing_done.png"
        await page.screenshot(path=str(shot2), full_page=True)
        shots.append(str(shot2))
        await browser.close()

    add_log(case, f"RPA：正式填报完成（{now_str()}，mode={mode}）")
    return shots, report
