from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from app.models import Case


FillMode = Literal["normal", "skip", "wrong"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    selector: str
    required: bool = True
    control: str = "input"  # input | select
    # 从 Case 取值；返回 None 表示本页不填该字段
    value_fn: Callable[[Case], str] | None = None


def _applicant_email(case: Case) -> str:
    return f"demo+{case.id}@yingtai.local"


def _applicant_phone(case: Case) -> str:
    return case.people[0].phone if case.people else ""


def _person(case: Case, idx: int):
    return case.people[idx] if len(case.people) > idx else None


def _director_name(case: Case) -> str:
    p = _person(case, 0)
    return f"{p.name_cn} / {p.name_en}" if p else ""


def _director_id(case: Case) -> str:
    p = _person(case, 0)
    return p.id_number if p else ""


def _director_share(case: Case) -> str:
    p = _person(case, 0)
    return p.share_ratio if p else ""


def _director_address(case: Case) -> str:
    p = _person(case, 0)
    return p.address_en if p else ""


def _shareholder2_name(case: Case) -> str:
    p = _person(case, 1)
    return f"{p.name_cn} / {p.name_en}" if p else ""


def _shareholder2_id(case: Case) -> str:
    p = _person(case, 1)
    return p.id_number if p else ""


def _shareholder2_share(case: Case) -> str:
    p = _person(case, 1)
    return p.share_ratio if p else ""


ACCOUNT_FIELDS: list[FieldSpec] = [
    FieldSpec("company_name_en", "Company Name (English)", "#company_name_en", value_fn=lambda c: c.company.name_en),
    FieldSpec("company_name_cn", "Company Name (Chinese)", "#company_name_cn", value_fn=lambda c: c.company.name_cn),
    FieldSpec("applicant_email", "Applicant Email", "#applicant_email", value_fn=_applicant_email),
    FieldSpec("applicant_phone", "Applicant Phone", "#applicant_phone", value_fn=_applicant_phone),
    FieldSpec("business_nature", "Nature of Business", "#business_nature", value_fn=lambda c: c.company.business_nature),
    FieldSpec("capital", "Share Capital (HKD)", "#capital", control="select", value_fn=lambda c: c.company.capital),
]

FILING_FIELDS: list[FieldSpec] = [
    FieldSpec("reg_name_en", "Company Name (EN)", "#reg_name_en", value_fn=lambda c: c.company.name_en),
    FieldSpec("reg_name_cn", "Company Name (CN)", "#reg_name_cn", value_fn=lambda c: c.company.name_cn),
    FieldSpec("reg_address", "Registered Office Address", "#reg_address", value_fn=lambda c: c.company.registered_address_en),
    FieldSpec("reg_nature", "Nature of Business", "#reg_nature", value_fn=lambda c: c.company.business_nature),
    FieldSpec("reg_capital", "Share Capital", "#reg_capital", value_fn=lambda c: c.company.capital),
    FieldSpec("director_name", "Director / Shareholder 1 Name", "#director_name", value_fn=_director_name),
    FieldSpec("director_id", "Director ID / Passport", "#director_id", value_fn=_director_id),
    FieldSpec("director_share", "Director Shareholding", "#director_share", value_fn=_director_share),
    FieldSpec("director_address", "Director Residential Address", "#director_address", value_fn=_director_address),
    FieldSpec(
        "shareholder2_name",
        "Shareholder 2 Name",
        "#shareholder2_name",
        required=False,
        value_fn=_shareholder2_name,
    ),
    FieldSpec(
        "shareholder2_id",
        "Shareholder 2 ID / Passport",
        "#shareholder2_id",
        required=False,
        value_fn=_shareholder2_id,
    ),
    FieldSpec(
        "shareholder2_share",
        "Shareholder 2 Shareholding",
        "#shareholder2_share",
        required=False,
        value_fn=_shareholder2_share,
    ),
]


@dataclass
class PlannedFill:
    key: str
    label: str
    selector: str
    expected: str
    required: bool
    control: str
    action: str = "fill"  # fill | skip | wrong
    actual_to_write: str = ""


def build_fill_plan(case: Case, fields: list[FieldSpec], mode: FillMode = "normal") -> list[PlannedFill]:
    plans: list[PlannedFill] = []
    required_keys = [f.key for f in fields if f.required]
    sabotage_key = required_keys[2] if len(required_keys) > 2 else (required_keys[0] if required_keys else "")

    for spec in fields:
        raw = (spec.value_fn(case) if spec.value_fn else "") or ""
        # 非必填且空值：跳过
        if not raw and not spec.required:
            continue
        plan = PlannedFill(
            key=spec.key,
            label=spec.label,
            selector=spec.selector,
            expected=raw,
            required=spec.required,
            control=spec.control,
            action="fill",
            actual_to_write=raw,
        )
        if mode == "skip" and spec.key == sabotage_key:
            plan.action = "skip"
            plan.actual_to_write = ""
        elif mode == "wrong" and spec.key == sabotage_key:
            plan.action = "wrong"
            plan.actual_to_write = f"WRONG_{raw}" if raw else "WRONG_VALUE"
        plans.append(plan)
    return plans
