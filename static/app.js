let currentCase = null;
let busy = false;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : (res.statusText || "请求失败"));
  }
  return data;
}

function setBusy(v) {
  busy = v;
  const ids = [
    "btn_create", "btn_send", "btn_demo_fill", "btn_confirm", "btn_precheck",
    "btn_pipeline", "btn_skip", "btn_wrong", "btn_finish",
  ];
  ids.forEach((id) => {
    const el = $(id);
    if (el) el.disabled = v || (id !== "btn_create" && !currentCase);
  });
  $("chat_input").disabled = v || !currentCase;
}

function renderMessages(caseData) {
  const box = $("chat");
  box.innerHTML = "";
  for (const m of caseData.messages) {
    const div = document.createElement("div");
    div.className = `bubble ${m.role}`;
    let body = `<div class="meta">${m.sender} · ${m.ts}</div><div>${escapeHtml(m.content)}</div>`;
    if (m.kind === "checklist" && m.payload.items) {
      body += `<div class="checklist"><ol>${m.payload.items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ol></div>`;
    }
    if (m.kind === "confirmation" && m.payload.company) {
      const c = m.payload.company;
      const people = m.payload.people || [];
      body += `<div class="confirm">
        <h4>注册香港公司确认单</h4>
        <div class="row">中文名称：${escapeHtml(c.name_cn)}</div>
        <div class="row">英文名称：${escapeHtml(c.name_en)}</div>
        <div class="row">注册资本：${escapeHtml(c.capital)} 港币</div>
        <div class="row">业务性质：${escapeHtml(c.business_nature)}</div>
        <div class="row">注册地址：${escapeHtml(c.registered_address_cn)}</div>
        <hr />
        ${people.map((p, idx) => `<div class="row">${idx + 1}. ${escapeHtml(p.role)} ${escapeHtml(p.name_cn)}（${escapeHtml(p.name_en)}） 持股 ${escapeHtml(p.share_ratio)}<br/>证件 ${escapeHtml(p.id_type)}:${escapeHtml(p.id_number)}</div>`).join("")}
      </div>`;
    }
    if (m.kind === "file" && m.payload.path) {
      body += `<div class="checklist">路径：${escapeHtml(m.payload.path)}</div>`;
    }
    if (m.kind === "validation" && m.payload) {
      body += renderValidationHtml(m.payload, true);
    }
    div.innerHTML = body;
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

function renderValidationHtml(report, compact = false) {
  if (!report) return "";
  const cls = report.passed ? "pass" : "fail";
  const rows = (report.checks || []).slice(0, compact ? 8 : 50);
  const more = (report.checks || []).length - rows.length;
  return `<div class="validation ${cls}" style="margin-top:8px">
    <h3>${escapeHtml(report.title || "校验")} · ${escapeHtml(report.summary || "")}</h3>
    <table>
      <thead><tr><th>结果</th><th>字段</th><th>说明</th></tr></thead>
      <tbody>
        ${rows.map((r) => `<tr>
          <td class="${r.ok ? "ok-tag" : "bad-tag"}">${r.ok ? "通过" : "失败"}</td>
          <td>${escapeHtml(r.name)}</td>
          <td>${escapeHtml(r.detail || "")}</td>
        </tr>`).join("")}
      </tbody>
    </table>
    ${more > 0 ? `<div class="muted">…另有 ${more} 项</div>` : ""}
  </div>`;
}

function renderSide(caseData) {
  $("case_badge").textContent = `案件 ${caseData.id}`;
  $("chat_title").textContent = `企微群 · ${caseData.company.name_cn}-注册+开户`;
  $("status_label").textContent = caseData.status_label;
  $("action_bar").hidden = false;

  const pipe = $("pipeline");
  pipe.innerHTML = "";
  for (const step of caseData.pipeline) {
    const li = document.createElement("li");
    li.className = step.current ? "current" : step.done ? "done" : "";
    li.innerHTML = `<span class="dot"></span><span>${step.label}</span>`;
    pipe.appendChild(li);
  }

  const acc = caseData.account;
  $("info").innerHTML = `
    <dl>
      <dt>公司</dt><dd>${escapeHtml(caseData.company.name_cn)}</dd>
      <dt>英文名</dt><dd>${escapeHtml(caseData.company.name_en)}</dd>
      <dt>业务性质</dt><dd>${escapeHtml(caseData.company.business_nature || "—")}</dd>
      <dt>归档路径</dt><dd>${escapeHtml(caseData.archive_path || "—")}</dd>
      <dt>系统账号</dt><dd>${escapeHtml(acc ? acc.username : "—")}</dd>
      <dt>临时密码</dt><dd>${escapeHtml(acc ? acc.password : "—")}</dd>
      <dt>最近RPA</dt><dd>${escapeHtml(caseData.last_rpa_mode || "normal")}</dd>
    </dl>`;

  const vbox = $("validation_box");
  const latest = caseData.latest_validation;
  vbox.innerHTML = latest
    ? renderValidationHtml(latest, false)
    : `<div class="fieldmap">暂无校验报告。可先点「填前校验」，或跑自动流程后查看回读结果。</div>`;

  const maps = caseData.field_maps || {};
  const accFields = (maps.account || []).map((f) => `${f.label} → <code>${f.selector}</code>${f.required ? "*" : ""}`).join("<br/>");
  const filFields = (maps.filing || []).slice(0, 6).map((f) => `${f.label} → <code>${f.selector}</code>${f.required ? "*" : ""}`).join("<br/>");
  $("fieldmap").innerHTML = `<strong>字段映射（不靠页面坐标）</strong><br/>账号申请：<br/>${accFields || "—"}<br/><br/>正式填报（部分）：<br/>${filFields || "—"}`;

  const shots = $("shots");
  shots.innerHTML = "";
  for (const url of caseData.rpa_screenshots || []) {
    const img = document.createElement("img");
    img.src = url + "?t=" + Date.now();
    img.alt = "RPA screenshot";
    shots.appendChild(img);
  }

  $("logs").textContent = (caseData.logs || []).join("\n");
}

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function applyCase(caseData) {
  currentCase = caseData;
  renderMessages(caseData);
  renderSide(caseData);
  setBusy(false);
}

async function createCase() {
  setBusy(true);
  try {
    const caseData = await api("/api/cases", {
      method: "POST",
      body: JSON.stringify({
        company_name_cn: $("company_cn").value.trim(),
        company_name_en: "Xingte Group Lesilong (Hong Kong) International Trading Limited",
      }),
    });
    applyCase(caseData);
  } catch (e) {
    alert(e.message);
    setBusy(false);
  }
}

async function sendChat(text) {
  if (!currentCase || !text.trim()) return;
  setBusy(true);
  try {
    const caseData = await api(`/api/cases/${currentCase.id}/chat`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    applyCase(caseData);
    $("chat_input").value = "";
  } catch (e) {
    alert(e.message);
    setBusy(false);
  }
}

async function demoFill() {
  setBusy(true);
  try {
    applyCase(await api(`/api/cases/${currentCase.id}/demo-fill`, { method: "POST", body: "{}" }));
  } catch (e) {
    alert(e.message);
    setBusy(false);
  }
}

async function runPipeline(mode = "normal") {
  setBusy(true);
  try {
    applyCase(await api(`/api/cases/${currentCase.id}/run-pipeline`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }));
  } catch (e) {
    alert(e.message);
    setBusy(false);
  }
}

async function precheck() {
  setBusy(true);
  try {
    applyCase(await api(`/api/cases/${currentCase.id}/precheck`, { method: "POST", body: "{}" }));
  } catch (e) {
    alert(e.message);
    setBusy(false);
  }
}

async function finishCase() {
  setBusy(true);
  try {
    applyCase(await api(`/api/cases/${currentCase.id}/finish`, { method: "POST", body: "{}" }));
  } catch (e) {
    alert(e.message);
    setBusy(false);
  }
}

$("btn_create").addEventListener("click", createCase);
$("btn_send").addEventListener("click", () => sendChat($("chat_input").value));
$("chat_input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat($("chat_input").value);
});
$("btn_demo_fill").addEventListener("click", demoFill);
$("btn_confirm").addEventListener("click", async () => {
  if (!currentCase) return;
  setBusy(true);
  try {
    applyCase(await api(`/api/cases/${currentCase.id}/confirm`, { method: "POST", body: "{}" }));
  } catch (e) {
    alert(e.message);
    setBusy(false);
  }
});
$("btn_precheck").addEventListener("click", precheck);
$("btn_pipeline").addEventListener("click", () => runPipeline("normal"));
$("btn_skip").addEventListener("click", () => runPipeline("skip"));
$("btn_wrong").addEventListener("click", () => runPipeline("wrong"));
$("btn_finish").addEventListener("click", finishCase);
