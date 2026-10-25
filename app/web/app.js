const $ = (selector) => document.querySelector(selector);
const examples = {
  reforming: "使用 Peng-Robinson 物性方法和 HYSYS 可用的热力学平衡数据，在 Equilibrium Reactor 中模拟甲烷蒸汽重整。进料物流 Feed 的总流量 3700 kmol/h，摩尔组成 Methane=0.27027027、Water=0.72972973，温度 520 degC，绝对压力 1350 kPa。反应包括 CH4 + H2O ⇌ CO + 3H2 和 CO + H2O ⇌ CO2 + H2，组分集合为 Methane、Water、Carbon Monoxide、Carbon Dioxide 和 Hydrogen。比较出口温度 600 degC 与 710 degC 两个工况；两个工况出口绝对压力均为 1350 kPa，压降均为 0 kPa。",
  toluene: "使用 Peng-Robinson 物性方法模拟甲苯歧化。纯甲苯进料 10000 kg/h，380℃、2500 kPa，使用 Conversion Reactor，总转化率 50%。产物为苯以及邻、间、对二甲苯；若没有选择性数据，请要求我确认等比例假设。"
};

let pollTimer = null;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function request(url, options = {}) {
  const response = await fetch(url, {headers: {"Content-Type": "application/json"}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `请求失败：${response.status}`);
  return body;
}

async function loadHealth() {
  try {
    const health = await request("/api/health");
    const ai = health.ai.status === "configured" ? "AI 已配置" : "AI 未配置";
    $("#connection-status").textContent = `${ai} · HYSYS ${health.hysys.status}`;
  } catch { $("#connection-status").textContent = "服务连接失败"; }
}

function showReview(data) {
  const spec = data.spec || data.draft;
  $("#spec-json").value = spec ? JSON.stringify(spec, null, 2) : "";
  const issues = data.issues || [];
  const explanation = data.decision?.explanation;
  const messages = issues.map((issue) => `${issue.field}：${issue.message}`);
  if (explanation) messages.unshift(explanation);
  $("#issues").textContent = messages.length ? messages.join("；") : "规格完整，任务已自动提交到 HYSYS 队列。";
  $("#issues").classList.toggle("blocking", issues.length > 0);
  $("#decision-badge").textContent = data.executable ? "可执行" : "需要补充";
  $("#confirm-button").disabled = !spec || !(spec.assumptions || []).length;
  $("#run-button").disabled = !spec;
}

function showResult(run) {
  const body = $("#result-body");
  body.replaceChildren();
  $("#result-downloads").replaceChildren();
  if (run.result) {
    const result = run.result;
    const real = result.source === "hysys";
    body.className = "result-summary";
    body.append(node("p", real ? "来源：真实 HYSYS 计算" : "测试 / 降级数据，不能用于考核结果", real ? "notice" : "notice blocking"));
    body.append(node("p", `求解状态：${result.converged ? "已取得稳定求解数据" : "未收敛"} · HYSYS ${result.hysys_version || "版本未提供"}`));
    for (const [name, stream] of Object.entries(result.streams || {})) {
      body.append(node("h3", name));
      body.append(node("p", `${stream.temperature_k?.toFixed(2)} K · ${stream.pressure_kpa?.toFixed(2)} kPa（绝压） · ${stream.phase}`));
      const table = node("table");
      const head = node("tr");
      ["组分", "摩尔分数", "kmol/h", "kg/h"].forEach(label => head.append(node("th", label)));
      const thead = node("thead"); thead.append(head); table.append(thead);
      const rows = node("tbody");
      for (const [component, flow] of Object.entries(stream.molar_flows_kmol_h || {})) {
        const row = node("tr");
        [component, stream.mole_fractions?.[component], flow, stream.mass_flows_kg_h?.[component]]
          .forEach(value => row.append(node("td", typeof value === "number" ? value.toPrecision(6) : value ?? "—")));
        rows.append(row);
      }
      table.append(rows); body.append(table);
    }
    body.append(node("p", `热负荷：${result.reactor_duty_kw ?? "未提供"} kW`));
    body.append(node("h3", "独立物料 / 元素衡算"));
    body.append(node("pre", Object.keys(result.validation || {}).length ? JSON.stringify(result.validation, null, 2) : "未提供衡算证据", "code-view"));
    const assumptions = (run.spec.assumptions || []).map(item => item.text);
    if (assumptions.length) body.append(node("p", `本次假设：${assumptions.join("；")}`));
    (result.warnings || []).forEach(warning => body.append(node("p", warning, "notice blocking")));
    const files = ["result.json", "streams.csv", ...(result.case_paths || []).map(path => path.split(/[\\/]/).pop())];
    files.forEach(filename => {
      const link = node("a", `下载 ${filename}`, "chip");
      link.href = `/api/runs/${encodeURIComponent(run.id)}/artifacts/${encodeURIComponent(filename)}`;
      link.download = filename;
      $("#result-downloads").append(link);
    });
  } else if (run.state === "failed") {
    body.textContent = `运行失败：${run.error || "请查看事件记录"}`;
    body.className = "notice blocking";
  }
}

async function refreshRun(runId) {
  const run = await request(`/api/runs/${runId}`);
  $("#run-state").textContent = run.state;
  $("#run-progress").textContent = `运行 ${run.id}：${run.state}${run.error ? ` · ${run.error}` : ""}`;
  const terminal = ["succeeded", "failed", "cancelled"].includes(run.state);
  if (terminal) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    showResult(run);
    await loadHistory();
  }
}

function trackRun(run) {
  if (!run) return;
  if (pollTimer) clearInterval(pollTimer);
  $("#result-body").textContent = "等待本次 HYSYS 求解结果…";
  $("#result-downloads").replaceChildren();
  $("#run-state").textContent = run.state;
  $("#run-progress").textContent = `运行 ${run.id} 已进入后台串行队列。`;
  $("#progress").scrollIntoView({behavior: "smooth"});
  refreshRun(run.id).catch((error) => { $("#run-progress").textContent = error.message; });
  pollTimer = setInterval(() => {
    refreshRun(run.id).catch((error) => {
      clearInterval(pollTimer);
      pollTimer = null;
      $("#run-progress").textContent = error.message;
    });
  }, 1000);
}

async function parseSpec() {
  const text = $("#modeling-request").value.trim();
  if (!text) { $("#parse-message").textContent = "请先输入建模需求"; return; }
  $("#parse-button").disabled = true;
  $("#parse-message").textContent = "正在解析并校验…";
  try {
    const workflow = await request("/api/workflows/submit", {
      method: "POST",
      body: JSON.stringify({text})
    });
    showReview(workflow);
    $("#parse-message").textContent = workflow.run ? "已自动提交" : "解析完成，请补充阻断项";
    $("#spec-review").scrollIntoView({behavior: "smooth"});
    trackRun(workflow.run);
  } catch (error) { $("#parse-message").textContent = error.message; }
  finally { $("#parse-button").disabled = false; }
}

function readEditedSpec() {
  try { return JSON.parse($("#spec-json").value); }
  catch { throw new Error("规格 JSON 格式不正确，请检查逗号和引号"); }
}

async function validateAndRun() {
  $("#run-button").disabled = true;
  try {
    const draft = readEditedSpec();
    const prepared = await request("/api/specs/prepare", {
      method: "POST",
      body: JSON.stringify(draft)
    });
    showReview(prepared);
    if (!prepared.executable) return;
    const run = await request("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        spec: prepared.spec,
        original_text: $("#modeling-request").value,
        auto_start: true
      })
    });
    trackRun(run);
  } catch (error) {
    $("#issues").textContent = error.message;
    $("#issues").classList.add("blocking");
  } finally {
    $("#run-button").disabled = false;
  }
}

async function confirmAssumptions() {
  try {
    const spec = readEditedSpec();
    (spec.assumptions || []).forEach((assumption) => { assumption.confirmed = true; });
    $("#spec-json").value = JSON.stringify(spec, null, 2);
    await validateAndRun();
  } catch (error) {
    $("#issues").textContent = error.message;
    $("#issues").classList.add("blocking");
  }
}

async function loadHistory() {
  try {
    const runs = await request("/api/runs");
    const list = $("#history-list");
    list.replaceChildren();
    if (!runs.length) list.append(node("p", "暂无运行记录", "empty-state"));
    runs.slice().reverse().forEach(run => {
      const item = node("article", undefined, "history-item");
      const info = node("div");
      const button = node("button", run.spec.title, "text-button");
      button.type = "button";
      button.addEventListener("click", () => {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
        showResult(run);
        $("#result").scrollIntoView({behavior: "smooth"});
      });
      info.append(button, node("span", run.id));
      const status = node("div");
      status.append(node("strong", run.state), node("span", new Date(run.updated_at).toLocaleString()));
      item.append(info, status); list.append(item);
    });
  } catch { $("#history-list").innerHTML = '<p class="empty-state">运行历史加载失败</p>'; }
}

document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => { $("#modeling-request").value = examples[button.dataset.example]; }));
$("#parse-button").addEventListener("click", parseSpec);
$("#confirm-button").addEventListener("click", confirmAssumptions);
$("#run-button").addEventListener("click", validateAndRun);
$("#refresh-history").addEventListener("click", loadHistory);
loadHealth();
loadHistory();
