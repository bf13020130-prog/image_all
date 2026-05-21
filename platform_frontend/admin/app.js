let csrfToken = "";
let currentUser = null;

const refs = {};

const SECRET_FIELDS = new Set([
  "llm_api_key",
  "color_match_api_key",
  "image_agent_api_key",
  "image_api_key",
  "image_1k_api_key",
  "gpt_image_api_key",
  "gpt_image_1k_api_key",
  "gemini_image_api_key",
]);

const STATIC_OPTIONS = {
  reasoning_effort: ["none", "low", "medium", "high", "xhigh"],
  reasoning_wire_format: ["reasoning_effort", "reasoning"],
};

const SETTINGS_SECTIONS = [
  {
    title: "提示词/通用大模型",
    fields: [
      { key: "llm_api_base", label: "API Base" },
      { key: "llm_api_key", label: "API Key", type: "password" },
      { key: "chat_model", label: "提示词模型" },
    ],
  },
  {
    title: "追色大模型",
    fields: [
      { key: "color_match_api_base", label: "API Base" },
      { key: "color_match_api_key", label: "API Key", type: "password" },
      { key: "color_match_model", label: "模型 ID" },
    ],
  },
  {
    title: "Agent 大模型",
    fields: [
      { key: "image_agent_api_base", label: "API Base" },
      { key: "image_agent_api_key", label: "API Key", type: "password" },
      { key: "image_agent_model", label: "模型 ID" },
      {
        key: "image_agent_endpoint_type",
        label: "Agent API",
        type: "select",
        optionsKey: "available_llm_endpoint_types",
      },
    ],
  },
  {
    title: "大模型通用请求参数",
    fields: [
      { key: "use_system_proxy", label: "使用系统代理", type: "checkbox", wide: true },
      {
        key: "reasoning_effort",
        label: "Reasoning Effort",
        type: "select",
        options: STATIC_OPTIONS.reasoning_effort,
      },
      {
        key: "reasoning_wire_format",
        label: "Reasoning 格式",
        type: "select",
        options: STATIC_OPTIONS.reasoning_wire_format,
      },
      { key: "llm_connect_timeout_seconds", label: "连接超时 (s)", type: "number", min: 1 },
      { key: "chat_read_timeout_seconds", label: "读取超时 (s)", type: "number", min: 0 },
      { key: "llm_retry_count", label: "重试次数", type: "number", min: 0 },
      { key: "chat_max_tokens", label: "Chat Max Tokens", type: "number", min: 0 },
    ],
  },
  {
    title: "默认生图模型",
    fields: [
      {
        key: "image_model",
        label: "默认生图模型",
        type: "select",
        optionsKey: "available_image_models",
      },
    ],
  },
  {
    title: "旧版兼容生图字段",
    fields: [
      { key: "image_api_base", label: "兼容 API Base" },
      { key: "image_api_key", label: "兼容 API Key", type: "password" },
      { key: "image_1k_api_key", label: "兼容 1K API Key", type: "password" },
      { key: "default_aspect_ratio", label: "旧版默认比例字段" },
    ],
  },
  {
    title: "gpt-image-2 1K",
    fields: [
      { key: "gpt_image_1k_api_base", label: "API Base" },
      { key: "gpt_image_1k_api_key", label: "API Key", type: "password" },
      { key: "image_model_gpt_image_2_1k", label: "模型 ID" },
    ],
  },
  {
    title: "gpt-image-2 2K/4K",
    fields: [
      { key: "gpt_image_api_base", label: "API Base" },
      { key: "gpt_image_api_key", label: "API Key", type: "password" },
      { key: "image_model_gpt_image_2", label: "模型 ID" },
    ],
  },
  {
    title: "Gemini / Nano Banana",
    fields: [
      { key: "gemini_image_api_base", label: "API Base" },
      { key: "gemini_image_api_key", label: "API Key", type: "password" },
    ],
  },
  {
    title: "生图通用请求参数",
    fields: [
      { key: "image_connect_timeout_seconds", label: "连接超时 (s)", type: "number", min: 1 },
      { key: "image_read_timeout_seconds", label: "生图读取超时 (s)", type: "number", min: 0 },
      { key: "download_read_timeout_seconds", label: "下载读取超时 (s)", type: "number", min: 0 },
      { key: "image_retry_count", label: "重试次数", type: "number", min: 0 },
    ],
  },
  {
    title: "默认任务参数",
    fields: [
      { key: "default_prompt_count", label: "默认提示词数", type: "number", min: 1 },
      {
        key: "default_output_resolution",
        label: "默认分辨率",
        type: "select",
        optionsKey: "available_output_resolutions",
      },
      {
        key: "default_output_aspect_ratio",
        label: "默认比例",
        type: "select",
        optionsKey: "available_output_aspect_ratios",
      },
      { key: "default_images_per_prompt", label: "默认生成次数", type: "number", min: 1 },
      { key: "default_concurrency", label: "共享并发池大小", type: "number", min: 1, maxKey: "max_shared_concurrency" },
    ],
  },
  {
    title: "提示词模板",
    fields: [
      { key: "default_user_prompt", label: "默认用户提示词", type: "textarea", rows: 10, wide: true },
      { key: "style_replicate2_user_prompt", label: "复刻风格图片2用户提示词", type: "textarea", rows: 10, wide: true },
      { key: "image_agent_planner_prompt", label: "图片 Agent 规划提示词", type: "textarea", rows: 8, wide: true },
      { key: "image_agent_creator_prompt", label: "图片 Agent 创作提示词", type: "textarea", rows: 10, wide: true },
      { key: "system_prompt", label: "系统提示词内容", type: "textarea", rows: 14, wide: true },
      { key: "style_replicate2_system_prompt", label: "复刻风格图片2系统提示词", type: "textarea", rows: 14, wide: true },
    ],
  },
];

document.addEventListener("DOMContentLoaded", () => {
  refs.loginPanel = document.getElementById("loginPanel");
  refs.adminPanel = document.getElementById("adminPanel");
  refs.loginForm = document.getElementById("loginForm");
  refs.logoutButton = document.getElementById("logoutButton");
  refs.adminBadge = document.getElementById("adminBadge");
  refs.statsGrid = document.getElementById("statsGrid");
  refs.usersList = document.getElementById("usersList");
  refs.jobsList = document.getElementById("jobsList");
  refs.createUserButton = document.getElementById("createUserButton");
  refs.createUserForm = document.getElementById("createUserForm");
  refs.settingsForm = document.getElementById("settingsForm");
  refs.saveGlobalSettingsButton = document.getElementById("saveGlobalSettingsButton");
  refs.refreshButton = document.getElementById("refreshButton");
  refs.logModal = document.getElementById("logModal");
  refs.logModalTitle = document.getElementById("logModalTitle");
  refs.logEntryTabs = document.getElementById("logEntryTabs");
  refs.logEntryPath = document.getElementById("logEntryPath");
  refs.logModalContent = document.getElementById("logModalContent");
  refs.logModalCloseButtons = Array.from(document.querySelectorAll("[data-log-close]"));

  refs.loginForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void runAction(() => login());
  });
  refs.logoutButton.addEventListener("click", () => void runAction(() => logout()));
  refs.createUserButton.addEventListener("click", () => {
    refs.createUserForm.hidden = !refs.createUserForm.hidden;
  });
  refs.createUserForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void runAction(() => createUser());
  });
  refs.saveGlobalSettingsButton.addEventListener("click", () => void runAction(() => saveGlobalSettings()));
  refs.refreshButton.addEventListener("click", () => void runAction(() => loadAll()));
  refs.logModalCloseButtons.forEach((button) => {
    button.addEventListener("click", () => closeLogModal());
  });

  void bootstrap();
});

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Platform-Client", "admin");
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD"].includes((options.method || "GET").toUpperCase()) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(formatApiError(payload.detail || payload.error || "请求失败。"));
  }
  return payload;
}

async function runAction(action) {
  try {
    await action();
  } catch (error) {
    window.alert(error instanceof Error ? error.message : String(error));
  }
}

function formatApiError(detail) {
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .filter(Boolean)
      .join("\n") || "请求参数不正确。";
  }
  if (detail && typeof detail === "object") {
    return JSON.stringify(detail);
  }
  return String(detail || "请求失败。");
}

async function bootstrap() {
  try {
    const payload = await api("/api/v1/auth/me");
    csrfToken = payload.csrf_token;
    currentUser = payload.user;
    if (currentUser.role !== "admin") {
      throw new Error("需要管理员权限。");
    }
    showAdmin();
    await loadAll();
  } catch (_error) {
    showLogin();
  }
}

function showLogin() {
  refs.loginPanel.hidden = false;
  refs.adminPanel.hidden = true;
  refs.logoutButton.hidden = true;
  refs.adminBadge.textContent = "未登录";
}

function showAdmin() {
  refs.loginPanel.hidden = true;
  refs.adminPanel.hidden = false;
  refs.logoutButton.hidden = false;
  refs.adminBadge.textContent = `${currentUser.display_name || currentUser.username} · 管理员`;
}

async function login() {
  const form = new FormData(refs.loginForm);
  const payload = await api("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({
      username: form.get("username"),
      password: form.get("password"),
    }),
  });
  csrfToken = payload.csrf_token;
  currentUser = payload.user;
  if (currentUser.role !== "admin") {
    window.alert("当前账号不是管理员。");
    return;
  }
  showAdmin();
  await loadAll();
}

async function logout() {
  await api("/api/v1/auth/logout", { method: "POST", body: "{}" });
  csrfToken = "";
  currentUser = null;
  showLogin();
}

async function loadAll() {
  await Promise.all([loadSummary(), loadUsers(), loadJobs(), loadSettings()]);
}

async function loadSummary() {
  const data = await api("/api/v1/admin/summary");
  refs.statsGrid.innerHTML = [
    ["用户", data.users],
    ["禁用", data.disabled_users],
    ["任务", data.jobs],
    ["运行中", data.active_jobs],
    ["总存储", `${mb(data.storage_bytes)} MB`],
  ]
    .map(([label, value]) => `<div class="stat"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

async function loadUsers() {
  const payload = await api("/api/v1/admin/users");
  const users = payload.data || [];
  refs.usersList.innerHTML = users.length
    ? users.map(renderUser).join("")
    : '<div class="item"><small>还没有用户。</small></div>';
  refs.usersList.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => void runAction(() => handleUserAction(button)));
  });
}

function renderUser(user) {
  const disabled = user.status === "disabled";
  const quota = user.quota || {};
  return `
    <div class="item">
      <div class="item-row">
        <div>
          <strong>${escapeHtml(user.username)} · ${escapeHtml(user.display_name || "")}</strong>
          <small>${escapeHtml(user.role)} · ${escapeHtml(user.status)} · 存储 ${mb(user.storage_bytes)} MB / ${quota.storage_limit_mb || 0} MB · 并发 ${quota.concurrent_limit || 1}</small>
        </div>
        <div class="item-actions">
          <button class="ghost" data-action="user-logs" data-user-id="${user.id}" data-username="${escapeHtml(user.username)}">任务日志</button>
          <button class="ghost" data-action="reset" data-user-id="${user.id}">重置密码</button>
          <button class="ghost" data-action="${disabled ? "enable" : "disable"}" data-user-id="${user.id}">${disabled ? "启用" : "禁用"}</button>
          <button class="ghost" data-action="quota" data-user-id="${user.id}">调整额度</button>
          <button class="danger" data-action="delete" data-user-id="${user.id}">删除</button>
        </div>
      </div>
    </div>
  `;
}

async function handleUserAction(button) {
  const userId = button.dataset.userId;
  const action = button.dataset.action;
  if (action === "user-logs") {
    await openUserLogs(userId, button.dataset.username || userId);
    return;
  }
  if (action === "reset") {
    const payload = await api(`/api/v1/admin/users/${userId}/password-reset`, {
      method: "POST",
      body: "{}",
    });
    window.alert(`临时密码：${payload.temporary_password}\n请立即发给用户，后台不会保存明文。`);
  }
  if (action === "disable" || action === "enable") {
    await api(`/api/v1/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: action === "enable" ? "active" : "disabled" }),
    });
  }
  if (action === "quota") {
    const concurrentLimit = Number(window.prompt("并发上限", "1") || "1");
    const storageLimitMb = Number(window.prompt("存储上限 MB", "10240") || "10240");
    await api(`/api/v1/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({
        concurrent_limit: concurrentLimit,
        storage_limit_mb: storageLimitMb,
      }),
    });
  }
  if (action === "delete") {
    if (!window.confirm("确定删除这个账号及其关联数据？")) {
      return;
    }
    await api(`/api/v1/admin/users/${userId}`, { method: "DELETE" });
  }
  await loadAll();
}

async function openUserLogs(userId, username = "") {
  const payload = await api("/api/v1/admin/jobs");
  const jobs = (payload.data || []).filter((job) => job.user_id === userId);
  if (!jobs.length) {
    refs.logModal.hidden = false;
    refs.logModalTitle.textContent = `${username || userId} 的任务日志`;
    refs.logEntryPath.textContent = "";
    refs.logEntryTabs.innerHTML = "";
    refs.logModalContent.textContent = "这个用户还没有任务日志。";
    return;
  }
  await openJobLogs(jobs[0].id, `${username || userId} 最近任务日志`);
}

async function createUser() {
  const form = new FormData(refs.createUserForm);
  const password = String(form.get("password") || "").trim();
  if (password && password.length < 8) {
    throw new Error("初始密码至少需要 8 位；也可以留空，由系统自动生成临时密码。");
  }
  const payload = {
    username: form.get("username"),
    display_name: form.get("display_name"),
    password: password || null,
    role: form.get("role"),
    concurrent_limit: Number(form.get("concurrent_limit") || 1),
    storage_limit_mb: Number(form.get("storage_limit_mb") || 10240),
  };
  const result = await api("/api/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  refs.createUserForm.reset();
  refs.createUserForm.hidden = true;
  window.alert(`账号已创建。\n临时密码：${result.temporary_password}`);
  await loadAll();
}

async function loadSettings() {
  const payload = await api("/api/v1/admin/settings");
  renderSettingsForm(payload.settings || {});
}

function renderSettingsForm(settings) {
  refs.settingsForm.innerHTML = "";
  const fragment = document.createDocumentFragment();
  for (const section of SETTINGS_SECTIONS) {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "settings-block";
    const legend = document.createElement("legend");
    legend.textContent = section.title;
    fieldset.appendChild(legend);

    const grid = document.createElement("div");
    grid.className = "settings-grid";
    for (const field of section.fields) {
      grid.appendChild(createSettingField(field, settings));
    }
    fieldset.appendChild(grid);
    fragment.appendChild(fieldset);
  }
  refs.settingsForm.appendChild(fragment);
}

function createSettingField(field, settings) {
  const label = document.createElement("label");
  label.className = `field${field.wide || field.type === "textarea" ? " wide" : ""}`;

  if (field.type === "checkbox") {
    label.classList.add("field--checkbox");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.setting = field.key;
    input.checked = Boolean(settings[field.key]);
    label.append(input, textSpan(field.label));
    return label;
  }

  label.appendChild(textSpan(field.label));
  const control = createControl(field, settings);
  control.dataset.setting = field.key;
  label.appendChild(control);
  return label;
}

function createControl(field, settings) {
  if (field.type === "textarea") {
    const textarea = document.createElement("textarea");
    textarea.rows = field.rows || 8;
    textarea.value = settings[field.key] ?? "";
    return textarea;
  }
  if (field.type === "select") {
    const select = document.createElement("select");
    for (const option of resolveOptions(field, settings)) {
      select.appendChild(createOption(option, settings[field.key]));
    }
    return select;
  }
  const input = document.createElement("input");
  input.type = field.type || (SECRET_FIELDS.has(field.key) ? "password" : "text");
  if (field.min !== undefined) input.min = String(field.min);
  if (field.max !== undefined) input.max = String(field.max);
  if (field.maxKey && settings[field.maxKey] !== undefined) input.max = String(settings[field.maxKey]);
  input.value = settings[field.key] ?? "";
  return input;
}

function resolveOptions(field, settings) {
  const source = field.optionsKey ? settings[field.optionsKey] : field.options;
  if (!Array.isArray(source)) {
    return [];
  }
  return source.map((item) => (
    typeof item === "object" ? item : { value: item, label: item }
  ));
}

function createOption(option, selectedValue) {
  const node = document.createElement("option");
  node.value = option.value;
  node.textContent = option.label || option.value;
  node.selected = String(option.value) === String(selectedValue ?? "");
  return node;
}

function textSpan(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

async function saveGlobalSettings() {
  const settings = collectSettings();
  await api("/api/v1/admin/settings", {
    method: "PUT",
    body: JSON.stringify({ settings }),
  });
  await loadSettings();
  window.alert("默认配置已保存。");
}

function collectSettings() {
  const settings = {};
  refs.settingsForm.querySelectorAll("[data-setting]").forEach((input) => {
    settings[input.dataset.setting] = readControlValue(input);
  });
  return settings;
}

function readControlValue(input) {
  if (input.type === "checkbox") {
    return input.checked;
  }
  if (input.type === "number") {
    return Number(input.value);
  }
  return input.value;
}

async function loadJobs() {
  const payload = await api("/api/v1/admin/jobs");
  const jobs = payload.data || [];
  refs.jobsList.innerHTML = jobs.length
    ? jobs.map(renderJob).join("")
    : '<div class="item"><small>还没有任务。</small></div>';
  refs.jobsList.querySelectorAll("[data-job-action='logs']").forEach((button) => {
    button.addEventListener("click", () => void runAction(() => openJobLogs(button.dataset.jobId)));
  });
}

function renderJob(job) {
  return `
    <div class="item">
      <div class="item-row">
        <div>
          <strong>${escapeHtml(job.title)} · ${escapeHtml(job.status)} · ${job.progress}%</strong>
          <small>${escapeHtml(job.task_type)} · user=${escapeHtml(job.user_id)} · ${escapeHtml(job.created_at || "")} · 存储 ${mb(job.storage_bytes)} MB</small>
        </div>
        <div class="item-actions">
          <button class="ghost" data-job-action="logs" data-job-id="${escapeHtml(job.id)}" type="button">日志</button>
        </div>
      </div>
      ${job.error ? `<small>${escapeHtml(job.error)}</small>` : ""}
    </div>
  `;
}

async function openJobLogs(jobId, loadingTitle = "日志加载中") {
  if (!jobId) {
    return;
  }
  refs.logModal.hidden = false;
  refs.logModalTitle.textContent = loadingTitle;
  refs.logEntryPath.textContent = "";
  refs.logEntryTabs.innerHTML = "";
  refs.logModalContent.textContent = "正在读取日志...";

  const payload = await api(`/api/v1/admin/jobs/${encodeURIComponent(jobId)}/logs`);
  renderLogEntries(payload);
}

function closeLogModal() {
  refs.logModal.hidden = true;
  refs.logEntryTabs.innerHTML = "";
  refs.logEntryPath.textContent = "";
  refs.logModalContent.textContent = "";
}

function renderLogEntries(payload) {
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  refs.logEntryTabs.innerHTML = "";
  if (!entries.length) {
    refs.logModalTitle.textContent = "日志详情";
    refs.logEntryPath.textContent = "";
    refs.logModalContent.textContent = "暂无日志。";
    return;
  }

  let currentKey = payload.selected_key || entries[0].key;
  const renderActive = () => {
    const activeEntry = entries.find((entry) => entry.key === currentKey) || entries[0];
    refs.logModalTitle.textContent = activeEntry.label || "日志详情";
    refs.logEntryPath.textContent = activeEntry.path || "";
    refs.logModalContent.textContent = activeEntry.content || "日志文件为空。";
    refs.logEntryTabs.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.logKey === activeEntry.key);
    });
  };

  entries.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "log-tab";
    button.dataset.logKey = entry.key;
    button.textContent = entry.label || entry.key;
    button.addEventListener("click", () => {
      currentKey = entry.key;
      renderActive();
    });
    refs.logEntryTabs.appendChild(button);
  });
  renderActive();
}

function mb(bytes) {
  return Math.round((Number(bytes || 0) / 1024 / 1024) * 10) / 10;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
