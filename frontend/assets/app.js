const $ = (selector) => document.querySelector(selector);
let conversationId = localStorage.getItem("planner-session") || crypto.randomUUID();
localStorage.setItem("planner-session", conversationId);

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `요청 실패 (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function switchView(name) {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  if (name === "plans") loadPlans();
  if (name === "logs") loadLogs();
  location.hash = name;
}

document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => switchView(item.dataset.view)));

function addMessage(role, text, isError = false) {
  const box = document.createElement("div");
  box.className = `message ${role}${isError ? " error" : ""}`;
  box.innerHTML = `<span class="message-label">${role === "user" ? "OPERATOR" : "PLANNER"}</span><p>${escapeHtml(text)}</p>`;
  $("#messages").append(box);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

function renderEvents(events, target = "#trace") {
  const list = $(target);
  const visible = events.filter((event) => ["stage.started", "tool.completed", "agent.replanned"].includes(event.event_type));
  list.innerHTML = visible.map((event, index) => {
    const failure = event.event_type === "tool.completed" && event.payload?.ok === false;
    const label = event.event_type === "stage.started" ? `${event.stage} 단계` : event.event_type === "agent.replanned" ? "재계획" : `${event.tool_name} Tool`;
    const detail = event.event_type === "tool.completed" ? (failure ? event.payload.error_code : `${event.duration_ms ?? 0} ms`) : event.event_type === "agent.replanned" ? `횟수 ${event.payload.replan_count} · 기존 결과 재사용` : event.created_at;
    return `<li data-seq="${index + 1}" class="${failure ? "failure" : event.event_type === "agent.replanned" ? "replan" : ""}"><strong>${escapeHtml(label)}</strong><span class="trace-meta">${escapeHtml(detail)}</span></li>`;
  }).join("") || '<li class="empty">표시할 이벤트가 없습니다.</li>';
  if (target === "#trace") $("#trace-count").textContent = `${visible.length} steps`;
}

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  addMessage("user", message);
  input.value = "";
  $("#send-button").disabled = true;
  $("#chat-state").textContent = "조건 분석 · Tool 실행 중";
  try {
    const result = await api("/api/v1/chat", { method: "POST", body: JSON.stringify({ message, session_id: conversationId }) });
    addMessage("assistant", result.text || "응답 내용이 없습니다.", ["failed", "partial"].includes(result.status));
    $("#chat-state").textContent = `완료 · 재계획 ${result.replan_count}회`;
    const detail = await api(`/api/v1/logs/${result.session_id}`);
    renderEvents(detail.events);
  } catch (error) {
    addMessage("assistant", error.message, true);
    $("#chat-state").textContent = "실패 · 입력과 서버 설정을 확인하세요";
  } finally {
    $("#send-button").disabled = false;
    input.focus();
  }
});

$("#plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.session_id = conversationId;
  try {
    const result = await api("/api/v1/plans", { method: "POST", body: JSON.stringify(payload) });
    const count = result.overlaps.length;
    $("#plan-notice").className = `notice ${count ? "warning" : ""}`;
    $("#plan-notice").textContent = count ? `계획은 저장됐지만 겹치는 계획이 ${count}건 있습니다.` : "계획을 저장했습니다.";
    event.target.reset();
    loadPlans();
  } catch (error) {
    $("#plan-notice").className = "notice error";
    $("#plan-notice").textContent = error.message;
  }
});

async function loadPlans() {
  try {
    const { plans } = await api("/api/v1/plans");
    $("#plan-count").textContent = `${plans.length} plans`;
    $("#plan-list").innerHTML = plans.map((plan) => `<tr data-plan="${plan.id}">
      <td><input data-field="title" value="${escapeHtml(plan.title)}"><small>${escapeHtml(plan.alarm_code || "-")}</small></td>
      <td><input data-field="plan_date" type="date" value="${plan.plan_date}"></td>
      <td><input data-field="start_time" type="time" value="${plan.start_time}"> <input data-field="end_time" type="time" value="${plan.end_time}"></td>
      <td><input data-field="location" value="${escapeHtml(plan.location || "")}"></td>
      <td><div class="row-actions"><button data-action="save">수정</button><button data-action="delete" class="danger">삭제</button></div></td>
    </tr>`).join("") || '<tr><td colspan="5" class="muted">저장된 계획이 없습니다.</td></tr>';
  } catch (error) { $("#plan-notice").textContent = error.message; }
}

$("#plan-list").addEventListener("click", async (event) => {
  const action = event.target.dataset.action;
  if (!action) return;
  const row = event.target.closest("tr");
  const id = row.dataset.plan;
  try {
    if (action === "delete") await api(`/api/v1/plans/${id}`, { method: "DELETE" });
    else {
      const payload = {};
      row.querySelectorAll("[data-field]").forEach((input) => { payload[input.dataset.field] = input.value; });
      const result = await api(`/api/v1/plans/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
      $("#plan-notice").className = `notice ${result.overlaps.length ? "warning" : ""}`;
      $("#plan-notice").textContent = result.overlaps.length ? `수정됐지만 겹치는 계획이 ${result.overlaps.length}건 있습니다.` : "계획을 수정했습니다.";
    }
    loadPlans();
  } catch (error) { $("#plan-notice").className = "notice error"; $("#plan-notice").textContent = error.message; }
});

async function loadLogs() {
  const { logs } = await api("/api/v1/logs");
  $("#log-count").textContent = `${logs.length} sessions`;
  $("#log-list").innerHTML = logs.map((log) => `<div class="log-row" data-log="${log.session_id}"><div><strong>${escapeHtml(log.user_request)}</strong><small>${escapeHtml(log.status)} · ${log.event_count} events · ${escapeHtml(log.created_at)}</small></div><div class="log-actions"><button data-action="view">보기</button><button data-action="delete" class="danger">삭제</button></div></div>`).join("") || '<p class="muted">실행 로그가 없습니다.</p>';
}

$("#log-list").addEventListener("click", async (event) => {
  const action = event.target.dataset.action;
  if (!action) return;
  const row = event.target.closest("[data-log]");
  const id = row.dataset.log;
  if (action === "delete") { await api(`/api/v1/logs/${id}`, { method: "DELETE" }); loadLogs(); $("#log-detail").innerHTML = '<li class="empty">실행을 선택하세요.</li>'; return; }
  const detail = await api(`/api/v1/logs/${id}`);
  $("#log-detail-title").textContent = `${detail.events.length} events`;
  renderEvents(detail.events, "#log-detail");
});

api("/api/v1/health").then((health) => {
  $(".health").classList.add("ready");
  $("#health-text").textContent = health.manual_index_ready ? "매뉴얼 인덱스 준비됨" : "일정 기능 준비됨 · 매뉴얼 인덱스 없음";
}).catch(() => { $("#health-text").textContent = "서버 연결 실패"; });

switchView((location.hash || "#chat").slice(1));
