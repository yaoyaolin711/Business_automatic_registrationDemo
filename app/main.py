from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.fieldmap import ACCOUNT_FIELDS, FILING_FIELDS
from app.models import (
    STATUS_LABELS,
    CaseStatus,
    ChatRequest,
    CreateCaseRequest,
    PipelineRequest,
)
from app.rpa import RpaValidationError, run_account_application, run_company_filing
from app.services import (
    add_log,
    add_message,
    archive_case,
    confirm_case,
    create_case,
    handle_client_message,
    load_demo_data,
    parse_mailbox,
    store,
    write_mock_email,
)
from app.validation import validate_case_before_rpa

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="工商注册流程 AI 化 Demo", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/screenshots", StaticFiles(directory=str(ROOT / "screenshots")), name="screenshots")


def public_case(case):
    data = case.model_dump()
    data["status_label"] = STATUS_LABELS.get(case.status, case.status.value)
    data["pipeline"] = [
        {
            "key": s.value,
            "label": STATUS_LABELS[s],
            "done": _rank(case.status) >= _rank(s),
            "current": case.status == s,
        }
        for s in CaseStatus
        if s != CaseStatus.CREATED
    ]
    data["rpa_screenshots"] = [
        "/screenshots/" + Path(p).relative_to(ROOT / "screenshots").as_posix()
        for p in case.rpa_screenshots
        if Path(p).exists()
    ]
    data["field_maps"] = {
        "account": [
            {"key": f.key, "label": f.label, "selector": f.selector, "required": f.required}
            for f in ACCOUNT_FIELDS
        ],
        "filing": [
            {"key": f.key, "label": f.label, "selector": f.selector, "required": f.required}
            for f in FILING_FIELDS
        ],
    }
    latest = case.validation_reports[-1] if case.validation_reports else None
    data["latest_validation"] = latest
    return data


def _rank(status: CaseStatus) -> int:
    return list(CaseStatus).index(status)


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/mock/cr-register", response_class=HTMLResponse)
async def mock_cr_register():
    return FileResponse(STATIC / "mock_cr_register.html")


@app.get("/mock/cr-filing", response_class=HTMLResponse)
async def mock_cr_filing():
    return FileResponse(STATIC / "mock_cr_filing.html")


@app.get("/api/cases")
async def list_cases():
    return [public_case(c) for c in store.list_cases()]


@app.post("/api/cases")
async def api_create_case(body: CreateCaseRequest):
    case = create_case(body.company_name_cn, body.company_name_en)
    return public_case(case)


@app.get("/api/cases/{case_id}")
async def get_case(case_id: str):
    case = store.get(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    return public_case(case)


@app.post("/api/cases/{case_id}/chat")
async def chat(case_id: str, body: ChatRequest):
    case = store.get(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    case = handle_client_message(case, body.text)
    return public_case(case)


@app.post("/api/cases/{case_id}/demo-fill")
async def demo_fill(case_id: str):
    case = store.get(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if case.status not in (CaseStatus.COLLECTING, CaseStatus.CREATED, CaseStatus.AWAITING_CONFIRM):
        raise HTTPException(400, f"当前状态不可填充：{case.status}")
    case = load_demo_data(case)
    return public_case(case)


@app.post("/api/cases/{case_id}/confirm")
async def api_confirm(case_id: str):
    case = store.get(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    if case.status != CaseStatus.AWAITING_CONFIRM:
        raise HTTPException(400, f"当前状态不可确认：{case.status}")
    add_message(case, "client", "客户·好久不见", "确认提交")
    case = confirm_case(case)
    return public_case(case)


@app.post("/api/cases/{case_id}/precheck")
async def api_precheck(case_id: str):
    case = store.get(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    report = validate_case_before_rpa(case)
    case.validation_reports.append(report)
    add_log(case, f"手动填前校验：{report['summary']}")
    add_message(
        case,
        "bot",
        "赢态工商·AI助手",
        f"填前校验结果：{report['summary']}"
        + ("" if report["passed"] else "。请先补齐材料后再跑自动流程。"),
        kind="validation",
        payload=report,
    )
    store.save(case)
    return public_case(case)


@app.post("/api/cases/{case_id}/run-pipeline")
async def run_pipeline(case_id: str, request: Request, body: PipelineRequest = PipelineRequest()):
    """确认后跑通：归档 → 申请账号 → 读邮箱 → 填报 → 通知人工。

    mode=normal 正常；skip 故意漏填；wrong 故意错填（用于演示拦截）。
    """
    case = store.get(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")

    mode = body.mode or "normal"
    if mode not in {"normal", "skip", "wrong"}:
        raise HTTPException(400, "mode 仅支持 normal / skip / wrong")

    if case.status not in (
        CaseStatus.CONFIRMED,
        CaseStatus.ARCHIVED,
        CaseStatus.ACCOUNT_APPLYING,
        CaseStatus.WAITING_EMAIL,
        CaseStatus.FILLING,
        CaseStatus.PENDING_HUMAN,
    ):
        raise HTTPException(400, "请先让客户回复「确认提交」")

    base = str(request.base_url).rstrip("/")
    case.last_rpa_mode = mode
    store.save(case)

    # 1) 归档
    if case.status == CaseStatus.CONFIRMED:
        case = archive_case(case)

    # 2) 申请账号（支持失败后重试）
    if case.status in (CaseStatus.ARCHIVED, CaseStatus.ACCOUNT_APPLYING):
        case.status = CaseStatus.ACCOUNT_APPLYING
        tip = {
            "normal": "正在按字段映射填写 CR 账号申请页，并做回读校验…",
            "skip": "演示模式：故意漏填必填项，预期会被回读校验拦截。",
            "wrong": "演示模式：故意填错必填项，预期会被回读校验拦截。",
        }[mode]
        add_message(case, "bot", "赢态工商·AI助手", tip)
        add_log(case, f"状态 → 申请系统账号（mode={mode}）")
        store.save(case)
        try:
            shots, report = await run_account_application(case, base, mode=mode)
            case.rpa_screenshots.extend(shots)
            write_mock_email(case)
            case.status = CaseStatus.WAITING_EMAIL
            add_message(
                case,
                "bot",
                "赢态工商·AI助手",
                f"账号申请回读通过（{report['summary']}），正在监听邮箱…",
                kind="validation",
                payload=report,
            )
            add_log(case, "状态 → 等待邮箱账号")
            store.save(case)
        except RpaValidationError as e:
            add_message(
                case,
                "bot",
                "赢态工商·AI助手",
                f"已拦截提交：{e}。可切换回「正常模式」重试。",
                kind="validation",
                payload=e.report,
            )
            add_log(case, f"账号申请被校验拦截：{e}")
            store.save(case)
            return public_case(case)
        except Exception as e:
            add_log(case, f"账号申请失败：{e}")
            store.save(case)
            raise HTTPException(500, f"账号申请 RPA 失败：{e}") from e

    # 故意破坏模式只演示到账号申请拦截即可
    if mode in {"skip", "wrong"}:
        return public_case(case)

    # 3) 读邮箱
    if case.status == CaseStatus.WAITING_EMAIL:
        creds = parse_mailbox(case)
        if not creds:
            raise HTTPException(500, "邮箱中未解析到账号")
        add_message(
            case,
            "bot",
            "赢态工商·AI助手",
            f"已从邮箱读取账号：{creds.username}（临时密码已保存）",
            kind="status",
        )
        case.status = CaseStatus.FILLING
        add_log(case, "状态 → 登录填报中")
        store.save(case)

    # 4) 正式填报（支持失败后重试）
    if case.status == CaseStatus.FILLING:
        add_message(case, "bot", "赢态工商·AI助手", "正在登录 ICRIS，按字段映射填报并回读校验…")
        store.save(case)
        try:
            shots, report = await run_company_filing(case, base, mode="normal")
            case.rpa_screenshots.extend(shots)
            case.status = CaseStatus.PENDING_HUMAN
            add_message(
                case,
                "bot",
                "赢态工商·AI助手",
                f"正式填报回读通过（{report['summary']}）。",
                kind="validation",
                payload=report,
            )
            add_message(
                case,
                "staff",
                "系统通知",
                f"@贺艳 案件《{case.company.name_cn}》已完成自动填报，请核对后续开户/递交事项。\n归档路径：{case.archive_path}",
                kind="status",
            )
            add_message(
                case,
                "bot",
                "赢态工商·AI助手",
                "自动流程已完成，已提醒对应同事处理后续事项。",
            )
            add_log(case, "状态 → 待人工核对")
            store.save(case)
        except RpaValidationError as e:
            add_message(
                case,
                "bot",
                "赢态工商·AI助手",
                f"正式填报已拦截：{e}",
                kind="validation",
                payload=e.report,
            )
            add_log(case, f"正式填报被校验拦截：{e}")
            store.save(case)
            return public_case(case)
        except Exception as e:
            add_log(case, f"填报失败：{e}")
            store.save(case)
            raise HTTPException(500, f"填报 RPA 失败：{e}") from e

    return public_case(case)


@app.post("/api/cases/{case_id}/finish")
async def finish(case_id: str):
    case = store.get(case_id)
    if not case:
        raise HTTPException(404, "案件不存在")
    case.status = CaseStatus.DONE
    add_message(case, "system", "系统", "人工核对完成，流程结束。", kind="status")
    add_log(case, "状态 → 流程结束")
    store.save(case)
    return public_case(case)
