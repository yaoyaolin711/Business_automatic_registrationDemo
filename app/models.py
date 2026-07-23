from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CaseStatus(str, Enum):
    CREATED = "created"
    COLLECTING = "collecting"
    AWAITING_CONFIRM = "awaiting_confirm"
    CONFIRMED = "confirmed"
    ARCHIVED = "archived"
    ACCOUNT_APPLYING = "account_applying"
    WAITING_EMAIL = "waiting_email"
    FILLING = "filling"
    PENDING_HUMAN = "pending_human"
    DONE = "done"


STATUS_LABELS = {
    CaseStatus.CREATED: "新建案件",
    CaseStatus.COLLECTING: "材料收集中",
    CaseStatus.AWAITING_CONFIRM: "待客户确认",
    CaseStatus.CONFIRMED: "已确认提交",
    CaseStatus.ARCHIVED: "已建档归档",
    CaseStatus.ACCOUNT_APPLYING: "申请系统账号",
    CaseStatus.WAITING_EMAIL: "等待邮箱账号",
    CaseStatus.FILLING: "登录填报中",
    CaseStatus.PENDING_HUMAN: "待人工核对",
    CaseStatus.DONE: "流程结束",
}


class PersonInfo(BaseModel):
    role: str = "董事兼股东"
    name_cn: str = ""
    name_en: str = ""
    nationality: str = "中国"
    id_type: str = "身份证"
    id_number: str = ""
    share_ratio: str = ""
    address_cn: str = ""
    address_en: str = ""
    phone: str = ""
    materials: list[str] = Field(default_factory=list)


class CompanyInfo(BaseModel):
    name_cn: str = ""
    name_en: str = ""
    capital: str = "10000"
    business_nature: str = ""
    registered_address_cn: str = "香港九龙观塘成业街7号旺角商业大厦"
    registered_address_en: str = "Mong Kok Commercial Building, 7 Shing Yip Street, Kwun Tong, Kowloon, Hong Kong"


class AccountCreds(BaseModel):
    username: str = ""
    password: str = ""
    email_subject: str = ""


class ChatMessage(BaseModel):
    id: str
    role: str  # bot | client | system | staff
    sender: str
    content: str
    kind: str = "text"  # text | checklist | confirmation | file | status
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: str = ""


class Case(BaseModel):
    id: str
    status: CaseStatus = CaseStatus.CREATED
    company: CompanyInfo = Field(default_factory=CompanyInfo)
    people: list[PersonInfo] = Field(default_factory=list)
    archive_path: str = ""
    account: Optional[AccountCreds] = None
    messages: list[ChatMessage] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    rpa_screenshots: list[str] = Field(default_factory=list)
    validation_reports: list[dict[str, Any]] = Field(default_factory=list)
    last_rpa_mode: str = "normal"
    missing_materials: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class CreateCaseRequest(BaseModel):
    company_name_cn: str = "享特集团乐思龙(香港)国际贸易有限公司"
    company_name_en: str = "Xingte Group Lesilong (Hong Kong) International Trading Limited"


class ChatRequest(BaseModel):
    text: str


class PipelineRequest(BaseModel):
    mode: str = "normal"  # normal | skip | wrong


class UploadMeta(BaseModel):
    person_name: str = "黄泽军"
    material_type: str = "身份证"
