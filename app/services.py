from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.models import (
    STATUS_LABELS,
    AccountCreds,
    Case,
    CaseStatus,
    ChatMessage,
    CompanyInfo,
    PersonInfo,
)

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "cases"
ARCHIVE_DIR = ROOT / "archives"
SCREENSHOT_DIR = ROOT / "screenshots"
MOCK_EMAIL_DIR = ROOT / "mock_mailbox"

for d in (CASES_DIR, ARCHIVE_DIR, SCREENSHOT_DIR, MOCK_EMAIL_DIR):
    d.mkdir(parents=True, exist_ok=True)

MATERIAL_CHECKLIST = [
    "董事/股东身份证或护照扫描件（四角完整、清晰、无水印）",
    "住址证明（近3个月水电煤/银行账单/驾照等；提供身份证可免）",
    "手持证件自拍（证件信息清晰可见）",
    "经营范围/业务性质（30字以内）",
    "各股东持股比例",
    "注册资本（默认 10,000 港币）",
    "董事及股东手机号码（大陆号码可用）",
    "白纸手写签名",
]

FAQ = {
    "地址证明": "如已提供身份证，一般无需再单独提供住址证明。",
    "手机": "可以使用大陆手机号码，不强制要求香港号码。",
    "资本": "注册资本默认按 10,000 港币、每股 1 港币处理，如需调整请说明。",
    "签名": "请在白纸上手写签名后拍照上传，字迹清晰即可。",
    "确认": "请核对确认单后回复「确认提交」。",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def short_id() -> str:
    return uuid4().hex[:8]


class CaseStore:
    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}

    def get(self, case_id: str) -> Optional[Case]:
        return self._cases.get(case_id)

    def save(self, case: Case) -> Case:
        case.updated_at = now_str()
        self._cases[case.id] = case
        path = CASES_DIR / f"{case.id}.json"
        path.write_text(case.model_dump_json(indent=2), encoding="utf-8")
        return case

    def list_cases(self) -> list[Case]:
        return sorted(self._cases.values(), key=lambda c: c.created_at, reverse=True)


store = CaseStore()


def add_log(case: Case, text: str) -> None:
    case.logs.append(f"[{now_str()}] {text}")


def add_message(
    case: Case,
    role: str,
    sender: str,
    content: str,
    kind: str = "text",
    payload: Optional[dict] = None,
) -> ChatMessage:
    msg = ChatMessage(
        id=short_id(),
        role=role,
        sender=sender,
        content=content,
        kind=kind,
        payload=payload or {},
        ts=now_str(),
    )
    case.messages.append(msg)
    return msg


def create_case(company_name_cn: str, company_name_en: str) -> Case:
    case = Case(
        id=short_id(),
        status=CaseStatus.CREATED,
        company=CompanyInfo(name_cn=company_name_cn, name_en=company_name_en),
        created_at=now_str(),
        updated_at=now_str(),
    )
    add_log(case, f"创建案件：{company_name_cn}")
    add_message(
        case,
        "system",
        "系统",
        f"已创建企微群：{company_name_cn}-注册+开户",
        kind="status",
    )
    add_message(
        case,
        "bot",
        "赢态工商·AI助手",
        "您好，我是工商注册助手。已为您准备香港公司注册材料清单，请按清单准备并发送材料。",
    )
    add_message(
        case,
        "bot",
        "赢态工商·AI助手",
        "材料清单如下：",
        kind="checklist",
        payload={"items": MATERIAL_CHECKLIST},
    )
    case.status = CaseStatus.COLLECTING
    add_log(case, "状态 → 材料收集中；已发送材料清单")
    return store.save(case)


def answer_faq(text: str) -> Optional[str]:
    for key, value in FAQ.items():
        if key in text:
            return value
    if any(k in text for k in ("清单", "材料", "要什么")):
        return "材料清单已发送。核心包括证件扫描件、手持证件照、业务性质、持股比例、手机号和签名。"
    return None


def load_demo_data(case: Case) -> Case:
    """一键填充演示数据，模拟客户已交齐材料。"""
    case.company.business_nature = "国际贸易及供应链管理"
    case.company.capital = "10000"
    case.people = [
        PersonInfo(
            role="董事兼股东",
            name_cn="黄泽军",
            name_en="HUANG ZEJUN",
            nationality="中国",
            id_type="身份证",
            id_number="440301199001011234",
            share_ratio="80%",
            address_cn="广东省深圳市南山区科技园南路88号",
            address_en="No.88 South Science Park Rd, Nanshan, Shenzhen, Guangdong",
            phone="13800138000",
            materials=["身份证", "手持证件照", "签名", "手机号"],
        ),
        PersonInfo(
            role="股东",
            name_cn="黄泽春",
            name_en="HUANG ZECHUN",
            nationality="中国香港",
            id_type="护照",
            id_number="K12345678",
            share_ratio="20%",
            address_cn="香港九龙旺角弥敦道500号",
            address_en="500 Nathan Road, Mong Kok, Kowloon, Hong Kong",
            phone="13900139000",
            materials=["护照", "住址证明", "手持证件照", "签名", "手机号"],
        ),
    ]
    case.missing_materials = []
    add_message(case, "client", "客户·好久不见", "材料已按清单发齐，请核对。")
    add_message(
        case,
        "bot",
        "赢态工商·AI助手",
        "已识别并结构化材料，正在生成《注册香港公司确认单》，请核对。",
    )
    add_message(
        case,
        "bot",
        "赢态工商·AI助手",
        "请核对以下确认单，如无误请回复「确认提交」。董事住址证明与签名模板可后补。",
        kind="confirmation",
        payload=build_confirmation_payload(case),
    )
    case.status = CaseStatus.AWAITING_CONFIRM
    add_log(case, "演示数据已填充；状态 → 待客户确认")
    return store.save(case)


def build_confirmation_payload(case: Case) -> dict:
    return {
        "company": case.company.model_dump(),
        "people": [p.model_dump() for p in case.people],
    }


def is_confirm_text(text: str) -> bool:
    normalized = text.strip().replace(" ", "").lower()
    return normalized in {"确认提交", "确认", "confirm", "confirmsubmit"} or "确认提交" in text


def confirm_case(case: Case) -> Case:
    case.status = CaseStatus.CONFIRMED
    add_message(
        case,
        "bot",
        "赢态工商·AI助手",
        "已收到确认。开始整理资料建档，并进入账号申请流程。",
    )
    add_log(case, "客户确认提交；状态 → 已确认提交")
    return store.save(case)


def handle_client_message(case: Case, text: str) -> Case:
    text = text.strip()
    add_message(case, "client", "客户·好久不见", text)

    if case.status == CaseStatus.AWAITING_CONFIRM and is_confirm_text(text):
        return confirm_case(case)

    faq = answer_faq(text)
    if faq:
        add_message(case, "bot", "赢态工商·AI助手", faq)
        add_log(case, f"FAQ 答疑：{text}")
        return store.save(case)

    if case.status == CaseStatus.COLLECTING:
        add_message(
            case,
            "bot",
            "赢态工商·AI助手",
            "已收到。可继续发送其他材料，或点击「一键填充演示数据」快速进入确认环节。",
        )
    else:
        add_message(
            case,
            "bot",
            "赢态工商·AI助手",
            f"当前状态：{STATUS_LABELS.get(case.status, case.status)}。如需确认请回复「确认提交」。",
        )
    return store.save(case)


def archive_case(case: Case) -> Case:
    date_prefix = datetime.now().strftime("%y.%m.%d")
    safe_name = case.company.name_cn.replace("/", "_").replace("\\", "_")
    folder = ARCHIVE_DIR / f"{date_prefix}_{safe_name}" / "收集资料"
    folder.mkdir(parents=True, exist_ok=True)

    for person in case.people:
        person_dir = folder / person.name_cn
        person_dir.mkdir(parents=True, exist_ok=True)
        note = person_dir / "材料说明.txt"
        note.write_text(
            "\n".join(
                [
                    f"姓名：{person.name_cn} / {person.name_en}",
                    f"角色：{person.role}",
                    f"证件：{person.id_type} {person.id_number}",
                    f"持股：{person.share_ratio}",
                    f"电话：{person.phone}",
                    f"已收材料：{', '.join(person.materials)}",
                ]
            ),
            encoding="utf-8",
        )

    confirm_path = folder.parent / "确认单.txt"
    lines = [
        "注册香港公司确认单",
        "=" * 32,
        f"中文名称：{case.company.name_cn}",
        f"英文名称：{case.company.name_en}",
        f"注册资本：{case.company.capital} 港币",
        f"业务性质：{case.company.business_nature}",
        f"注册地址：{case.company.registered_address_cn}",
        "",
        "董事、股东成员：",
    ]
    for i, p in enumerate(case.people, 1):
        lines.extend(
            [
                f"  {i}. {p.role} {p.name_cn}（{p.name_en}）",
                f"     持股 {p.share_ratio} | {p.id_type}:{p.id_number}",
                f"     地址：{p.address_cn}",
            ]
        )
    confirm_path.write_text("\n".join(lines), encoding="utf-8")

    meta = folder.parent / "case.json"
    meta.write_text(case.model_dump_json(indent=2), encoding="utf-8")

    case.archive_path = str(folder.parent)
    case.status = CaseStatus.ARCHIVED
    add_message(
        case,
        "bot",
        "赢态工商·AI助手",
        f"资料已归档：{case.archive_path}",
        kind="file",
        payload={"path": case.archive_path},
    )
    add_log(case, f"归档完成：{case.archive_path}")
    return store.save(case)


def write_mock_email(case: Case) -> AccountCreds:
    username = f"cr{case.id}"
    password = f"Hk@{case.id[:4]}2026"
    subject = f"[CR e-Services] Account Created - {case.company.name_en}"
    body = (
        f"Dear Applicant,\n\n"
        f"Your CR e-Services account has been created.\n"
        f"Company: {case.company.name_cn}\n"
        f"Username: {username}\n"
        f"Temporary Password: {password}\n\n"
        f"Please login to ICRIS3EP to complete company registration.\n"
    )
    mail_path = MOCK_EMAIL_DIR / f"{case.id}.eml.txt"
    mail_path.write_text(f"Subject: {subject}\n\n{body}", encoding="utf-8")
    creds = AccountCreds(username=username, password=password, email_subject=subject)
    case.account = creds
    add_log(case, f"模拟邮件已写入：{mail_path.name}")
    return creds


def parse_mailbox(case: Case) -> Optional[AccountCreds]:
    mail_path = MOCK_EMAIL_DIR / f"{case.id}.eml.txt"
    if not mail_path.exists():
        return None
    text = mail_path.read_text(encoding="utf-8")
    username = ""
    password = ""
    subject = ""
    for line in text.splitlines():
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
        if line.strip().startswith("Username:"):
            username = line.split(":", 1)[1].strip()
        if "Temporary Password:" in line or line.strip().startswith("Temporary Password"):
            password = line.split(":", 1)[1].strip()
    if username and password:
        creds = AccountCreds(username=username, password=password, email_subject=subject)
        case.account = creds
        add_log(case, f"邮箱解析成功：账号 {username}")
        return creds
    return None
