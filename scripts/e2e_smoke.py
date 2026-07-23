import json
import urllib.request
from pathlib import Path

base = "http://127.0.0.1:8787"


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def new_case():
    return call(
        "POST",
        "/api/cases",
        {
            "company_name_cn": "享特集团乐思龙(香港)国际贸易有限公司",
            "company_name_en": "Xingte Group Lesilong (Hong Kong) International Trading Limited",
        },
    )


print("=== normal happy path ===")
case = new_case()
case = call("POST", f"/api/cases/{case['id']}/demo-fill", {})
case = call("POST", f"/api/cases/{case['id']}/precheck", {})
assert case["latest_validation"]["passed"], case["latest_validation"]
case = call("POST", f"/api/cases/{case['id']}/confirm", {})
case = call("POST", f"/api/cases/{case['id']}/run-pipeline", {"mode": "normal"})
assert case["status"] == "pending_human", case["status"]
assert any(r["stage"] == "account_readback" and r["passed"] for r in case["validation_reports"])
assert any(r["stage"] == "filing_readback" and r["passed"] for r in case["validation_reports"])
print("OK normal", case["id"], "shots", len(case["rpa_screenshots"]))

print("=== skip should block ===")
case = new_case()
case = call("POST", f"/api/cases/{case['id']}/demo-fill", {})
case = call("POST", f"/api/cases/{case['id']}/confirm", {})
case = call("POST", f"/api/cases/{case['id']}/run-pipeline", {"mode": "skip"})
assert case["status"] == "account_applying", case["status"]
latest = case["latest_validation"]
assert latest and not latest["passed"], latest
print("OK skip blocked:", latest["summary"])

print("=== wrong should block, then retry normal ===")
case = new_case()
case = call("POST", f"/api/cases/{case['id']}/demo-fill", {})
case = call("POST", f"/api/cases/{case['id']}/confirm", {})
case = call("POST", f"/api/cases/{case['id']}/run-pipeline", {"mode": "wrong"})
assert case["status"] == "account_applying"
case = call("POST", f"/api/cases/{case['id']}/run-pipeline", {"mode": "normal"})
assert case["status"] == "pending_human", case["status"]
print("OK wrong->retry", case["id"])

ap = Path(case["archive_path"])
print("ARCHIVE", ap.exists(), list(ap.glob("validation_*.json")))
print("ALL PASSED")
