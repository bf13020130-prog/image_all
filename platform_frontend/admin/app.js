let csrfToken = "";
let currentUser = null;
let revealedGlobalSettings = null;
let currentSettings = {};

const refs = {};

const IMAGE_MODEL_NANO_BANANA_2 = "gemini-3.1-flash-image-preview";
const IMAGE_MODEL_NANO_BANANA_PRO = "gemini-3-pro-image-preview";

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

const KEY_POOL_CONFIGS = {
  llm: {
    poolKey: "llm_key_pool",
    defaultKey: "default_llm_key_id",
    itemLabel: "大模型 Key",
    apiBaseFallbackKey: "llm_api_base",
    modelFallbackKey: "chat_model",
    endpointFallbackKey: "llm_endpoint_type",
    fields: { model: true, endpointType: true },
  },
  gpt1k: {
    poolKey: "gpt_image_1k_key_pool",
    defaultKey: "default_gpt_image_1k_key_id",
    itemLabel: "1K 生图 Key",
    apiBaseFallbackKey: "gpt_image_1k_api_base",
    fields: {},
  },
  gpt2k4k: {
    poolKey: "gpt_image_key_pool",
    defaultKey: "default_gpt_image_key_id",
    itemLabel: "2K/4K 生图 Key",
    apiBaseFallbackKey: "gpt_image_api_base",
    fields: {},
  },
  gemini: {
    poolKey: "gemini_image_key_pool",
    defaultKey: "default_gemini_image_key_id",
    itemLabel: "Banana / Gemini Key",
    apiBaseFallbackKey: "gemini_image_api_base",
    modelFallbackValue: IMAGE_MODEL_NANO_BANANA_2,
    fields: { model: true },
  },
};

function normalizeConfiguredImageModelId(value) {
  const text = String(value || "").trim();
  return text === "gpt-image-2-1K" ? "gpt-image-2-1k" : text;
}

const STATIC_OPTIONS = {
  reasoning_effort: ["none", "low", "medium", "high", "xhigh"],
  reasoning_wire_format: ["reasoning_effort", "reasoning"],
};

const SETTINGS_SECTIONS = [
  {
    title: "大模型 Key 池",
    keyPool: "llm",
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
    title: "gpt-image-2 1K",
    keyPool: "gpt1k",
    fields: [
      { key: "image_model_gpt_image_2_1k", label: "全局模型 ID" },
    ],
  },
  {
    title: "gpt-image-2 2K/4K",
    keyPool: "gpt2k4k",
    fields: [
      { key: "image_model_gpt_image_2", label: "全局模型 ID" },
    ],
  },
  {
    title: "Gemini / Nano Banana",
    keyPool: "gemini",
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
      { key: "default_concurrency", label: "默认单任务并发", type: "number", min: 1, maxKey: "max_shared_concurrency" },
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
  refs.openAdminLogsButton = document.getElementById("openAdminLogsButton");
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
  refs.settingsForm.addEventListener("click", (event) => {
    const addButton = event.target.closest("[data-key-pool-add]");
    if (addButton) {
      addKeyPoolItem(addButton.dataset.keyPoolAdd);
      return;
    }
    const removeButton = event.target.closest("[data-key-pool-remove]");
    if (removeButton) {
      removeKeyPoolItem(removeButton.dataset.keyPoolRemove, removeButton.closest("[data-key-pool-row]"));
    }
  });
  refs.settingsForm.addEventListener("input", (event) => {
    const row = event.target.closest("[data-key-pool-row]");
    if (row) {
      syncKeyPoolDefaultOptions(row.dataset.keyPoolRow);
    }
  });
  refs.settingsForm.addEventListener("change", (event) => {
    const row = event.target.closest("[data-key-pool-row]");
    if (row) {
      syncKeyPoolDefaultOptions(row.dataset.keyPoolRow);
    }
  });
  refs.openAdminLogsButton.addEventListener("click", () => void runAction(() => openAdminLogs()));
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
          <small>${escapeHtml(user.role)} · ${escapeHtml(user.status)} · 存储 ${mb(user.storage_bytes)} MB / ${quota.storage_limit_mb || 0} MB · 并发 ${quota.concurrent_limit || 30}</small>
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
    concurrent_limit: Number(form.get("concurrent_limit") || 30),
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
  revealedGlobalSettings = null;
  currentSettings = payload.settings || {};
  renderSettingsForm(currentSettings);
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

    if (section.keyPool) {
      fieldset.classList.add("key-pool");
      fieldset.dataset.keyPool = section.keyPool;
      fieldset.appendChild(createKeyPoolEditor(section.keyPool, settings));
    }

    if (Array.isArray(section.fields) && section.fields.length) {
      const grid = document.createElement("div");
      grid.className = "settings-grid";
      for (const field of section.fields) {
        grid.appendChild(createSettingField(field, settings));
      }
      fieldset.appendChild(grid);
    }
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
  if (SECRET_FIELDS.has(field.key)) {
    label.appendChild(createSecretControl(field.key, control, settings));
    label.appendChild(createSecretStatus(field.key, settings));
    return label;
  }
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
  if (SECRET_FIELDS.has(field.key)) {
    input.dataset.originalSecretValue = String(input.value || "");
  }
  return input;
}

function createSecretControl(key, input, settings) {
  const wrapper = document.createElement("span");
  wrapper.className = "secret-control";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secret-reveal-button";
  button.dataset.secretKey = key;
  button.setAttribute("aria-label", "查看或隐藏密钥");
  button.setAttribute("title", "查看或隐藏密钥");
  button.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"></path>
      <circle cx="12" cy="12" r="3"></circle>
    </svg>
  `;
  button.addEventListener("click", () => void runAction(() => toggleSecretReveal(input, button)));
  wrapper.append(input, button);
  return wrapper;
}

function createSecretStatus(key, settings) {
  const status = settings?._secret_status?.[key] || {};
  const node = document.createElement("p");
  node.className = `secret-save-state ${
    status.saved ? "secret-save-state--saved" : "secret-save-state--empty"
  }`;
  node.textContent = status.saved
    ? `已设置：${status.masked || "******"}`
    : "未设置默认密钥；管理员账号运行时不会有默认 key";
  return node;
}

async function toggleSecretReveal(input, button) {
  if (input.type === "password") {
    if (shouldFetchSecretValue(input)) {
      const settings = await loadRevealedGlobalSettings();
      const value = settings[input.dataset.setting] ?? "";
      input.value = value;
      input.dataset.originalSecretValue = String(value || "");
      input.dataset.revealedSecret = "1";
    }
    input.type = "text";
    button.classList.add("is-active");
    button.setAttribute("aria-pressed", "true");
    return;
  }
  input.type = "password";
  button.classList.remove("is-active");
  button.setAttribute("aria-pressed", "false");
}

function shouldFetchSecretValue(input) {
  if (input.dataset.revealedSecret === "1") {
    return false;
  }
  const currentValue = String(input.value || "");
  const originalValue = String(input.dataset.originalSecretValue || "");
  if (!currentValue || currentValue === originalValue) {
    return true;
  }
  return currentValue.includes("***") || currentValue.includes("...");
}

async function loadRevealedGlobalSettings() {
  if (revealedGlobalSettings) {
    return revealedGlobalSettings;
  }
  const payload = await api("/api/v1/admin/settings?reveal_secrets=1");
  revealedGlobalSettings = payload.settings || {};
  return revealedGlobalSettings;
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

function createKeyPoolEditor(poolId, settings) {
  const wrapper = document.createElement("div");
  wrapper.className = "key-pool__inner";
  const bar = document.createElement("div");
  bar.className = "key-pool__bar";
  const defaultLabel = document.createElement("label");
  defaultLabel.className = "field";
  defaultLabel.appendChild(textSpan("默认 Key"));
  const defaultSelect = document.createElement("select");
  defaultSelect.dataset.keyPoolDefault = poolId;
  defaultLabel.appendChild(defaultSelect);
  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "ghost key-pool__add";
  addButton.dataset.keyPoolAdd = poolId;
  addButton.textContent = "+ 添加 Key";
  bar.append(defaultLabel, addButton);

  const rowsNode = document.createElement("div");
  rowsNode.className = "key-pool__rows";
  rowsNode.dataset.keyPoolRows = poolId;
  wrapper.append(bar, rowsNode);

  const items = normalizeKeyPoolItems(poolId, settings);
  const displayItems = items.length ? items : [createKeyPoolItem(poolId, settings, 1)];
  displayItems.forEach((item, index) => {
    rowsNode.appendChild(createKeyPoolRow(poolId, item, settings, index + 1));
  });
  window.setTimeout(() => {
    syncKeyPoolDefaultOptions(poolId, settings[KEY_POOL_CONFIGS[poolId].defaultKey] || "");
  }, 0);
  return wrapper;
}

function normalizeKeyPoolItems(poolId, settings = currentSettings) {
  const config = KEY_POOL_CONFIGS[poolId];
  const rawItems = Array.isArray(settings?.[config.poolKey]) ? settings[config.poolKey] : [];
  return rawItems
    .filter((item) => item && typeof item === "object")
    .map((item, index) => ({
      ...createKeyPoolItem(poolId, settings, index + 1),
      ...item,
      id: String(item.id || "").trim() || createKeyPoolItemId(poolId),
      name: String(item.name || "").trim() || `${config.itemLabel} ${index + 1}`,
      api_base:
        String(item.api_base || "").trim() ||
        String(settings?.[config.apiBaseFallbackKey] || "").trim(),
      api_key: String(item.api_key || "").trim(),
      enabled: item.enabled !== false,
    }));
}

function createKeyPoolItem(poolId, settings = currentSettings, index = 1) {
  const config = KEY_POOL_CONFIGS[poolId];
  const fallbackModel =
    config.modelFallbackValue ||
    String(settings?.[config.modelFallbackKey] || "").trim();
  return {
    id: createKeyPoolItemId(poolId),
    name: `${config.itemLabel} ${index}`,
    api_base: String(settings?.[config.apiBaseFallbackKey] || "").trim(),
    api_key: "",
    model: fallbackModel,
    endpoint_type:
      String(settings?.[config.endpointFallbackKey] || "").trim() ||
      "chat_completions",
    enabled: true,
  };
}

function createKeyPoolItemId(poolId) {
  return `${poolId}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function createKeyPoolRow(poolId, item, settings = currentSettings, index = 1) {
  const config = KEY_POOL_CONFIGS[poolId];
  const row = document.createElement("div");
  row.className = "key-pool-row";
  row.dataset.keyPoolRow = poolId;
  row.dataset.keyPoolItemId = item.id;

  const grid = document.createElement("div");
  grid.className = "key-pool-row__grid";
  grid.appendChild(createKeyPoolTextField("名称", "name", item.name || `${config.itemLabel} ${index}`));
  grid.appendChild(createKeyPoolTextField("API Base", "api_base", item.api_base || ""));
  grid.appendChild(createKeyPoolPasswordField(item.api_key || ""));
  if (config.fields.model) {
    grid.appendChild(createKeyPoolModelField(poolId, item.model || "", settings));
  }
  if (config.fields.endpointType) {
    grid.appendChild(createKeyPoolEndpointField(item.endpoint_type || "", settings));
  }
  row.appendChild(grid);

  const actions = document.createElement("div");
  actions.className = "key-pool-row__actions";
  const enabledLabel = document.createElement("label");
  enabledLabel.className = "field--checkbox key-pool-row__enabled";
  const enabledInput = document.createElement("input");
  enabledInput.type = "checkbox";
  enabledInput.checked = item.enabled !== false;
  enabledInput.dataset.keyPoolField = "enabled";
  enabledLabel.append(enabledInput, textSpan("启用"));
  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "ghost key-pool-row__remove";
  removeButton.dataset.keyPoolRemove = poolId;
  removeButton.textContent = "删除";
  actions.append(enabledLabel, removeButton);
  row.appendChild(actions);
  return row;
}

function createKeyPoolTextField(labelText, fieldName, value) {
  const label = document.createElement("label");
  label.appendChild(textSpan(labelText));
  const input = document.createElement("input");
  input.type = "text";
  input.value = value;
  input.dataset.keyPoolField = fieldName;
  if (fieldName === "api_base") {
    input.autocomplete = "off";
    input.inputMode = "url";
    input.spellcheck = false;
  }
  label.appendChild(input);
  return label;
}

function createKeyPoolPasswordField(value) {
  const label = document.createElement("label");
  label.appendChild(textSpan("API Key"));
  const input = document.createElement("input");
  input.type = "password";
  input.value = value;
  input.autocomplete = "new-password";
  input.dataset.keyPoolField = "api_key";
  input.setAttribute("data-lpignore", "true");
  input.setAttribute("data-1p-ignore", "true");
  label.appendChild(input);
  return label;
}

function createKeyPoolModelField(poolId, value, settings) {
  const label = document.createElement("label");
  label.appendChild(textSpan("模型 ID"));
  if (poolId === "gemini") {
    const select = document.createElement("select");
    select.dataset.keyPoolField = "model";
    const options = (settings?.available_image_models || []).filter((option) =>
      isNanoBananaModel(option.value ?? option)
    );
    const selectedValue = value || IMAGE_MODEL_NANO_BANANA_2;
    for (const option of options.length
      ? options
      : [
          { value: IMAGE_MODEL_NANO_BANANA_2, label: IMAGE_MODEL_NANO_BANANA_2 },
          { value: IMAGE_MODEL_NANO_BANANA_PRO, label: IMAGE_MODEL_NANO_BANANA_PRO },
        ]) {
      select.appendChild(createOption(typeof option === "object" ? option : { value: option, label: option }, selectedValue));
    }
    label.appendChild(select);
    return label;
  }
  const input = document.createElement("input");
  input.type = "text";
  input.value = value;
  input.dataset.keyPoolField = "model";
  label.appendChild(input);
  return label;
}

function createKeyPoolEndpointField(value, settings) {
  const label = document.createElement("label");
  label.appendChild(textSpan("API 类型"));
  const select = document.createElement("select");
  select.dataset.keyPoolField = "endpoint_type";
  for (const option of settings?.available_llm_endpoint_types || [
    { value: "chat_completions", label: "/v1/chat/completions" },
    { value: "responses", label: "/v1/responses" },
  ]) {
    select.appendChild(createOption(typeof option === "object" ? option : { value: option, label: option }, value || "chat_completions"));
  }
  label.appendChild(select);
  return label;
}

function isNanoBananaModel(value) {
  const text = String(value || "").trim().toLowerCase();
  return text === IMAGE_MODEL_NANO_BANANA_2 || text === IMAGE_MODEL_NANO_BANANA_PRO;
}

function syncKeyPoolDefaultOptions(poolId, selectedValue = "") {
  const defaultSelect = refs.settingsForm?.querySelector(`[data-key-pool-default="${poolId}"]`);
  if (!defaultSelect || !KEY_POOL_CONFIGS[poolId]) {
    return;
  }
  const wantedValue = selectedValue || defaultSelect.value || "";
  const rows = Array.from(refs.settingsForm.querySelectorAll(`[data-key-pool-row="${poolId}"]`));
  const items = rows.map((row, index) =>
    readKeyPoolRow(poolId, row, index, true, false)
  );
  const selectedId =
    wantedValue && items.some((item) => item.id === wantedValue)
      ? wantedValue
      : items.find((item) => item.enabled && item.api_key)?.id || items[0]?.id || "";
  defaultSelect.innerHTML = "";
  items.forEach((item, index) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name || `${KEY_POOL_CONFIGS[poolId].itemLabel} ${index + 1}`;
    option.selected = item.id === selectedId;
    defaultSelect.appendChild(option);
  });
}

function addKeyPoolItem(poolId) {
  const rowsNode = refs.settingsForm?.querySelector(`[data-key-pool-rows="${poolId}"]`);
  if (!rowsNode || !KEY_POOL_CONFIGS[poolId]) {
    return;
  }
  const nextIndex = rowsNode.querySelectorAll("[data-key-pool-row]").length + 1;
  rowsNode.appendChild(createKeyPoolRow(poolId, createKeyPoolItem(poolId, currentSettings, nextIndex), currentSettings, nextIndex));
  syncKeyPoolDefaultOptions(poolId);
}

function removeKeyPoolItem(poolId, row) {
  if (!row) {
    return;
  }
  row.remove();
  const rowsNode = refs.settingsForm?.querySelector(`[data-key-pool-rows="${poolId}"]`);
  if (rowsNode && !rowsNode.querySelector("[data-key-pool-row]")) {
    rowsNode.appendChild(createKeyPoolRow(poolId, createKeyPoolItem(poolId, currentSettings, 1), currentSettings, 1));
  }
  syncKeyPoolDefaultOptions(poolId);
}

function collectKeyPools() {
  const payload = {};
  Object.entries(KEY_POOL_CONFIGS).forEach(([poolId, config]) => {
    const rows = Array.from(refs.settingsForm.querySelectorAll(`[data-key-pool-row="${poolId}"]`));
    const items = rows
      .map((row, index) => readKeyPoolRow(poolId, row, index, false))
      .filter(Boolean);
    const defaultSelect = refs.settingsForm.querySelector(`[data-key-pool-default="${poolId}"]`);
    const selectedDefault = String(defaultSelect?.value || "").trim();
    payload[config.poolKey] = items;
    payload[config.defaultKey] = items.some((item) => item.id === selectedDefault)
      ? selectedDefault
      : items[0]?.id || "";
  });
  return payload;
}

function readKeyPoolRow(
  poolId,
  row,
  index = 0,
  includeEmpty = false,
  validateApiBase = true
) {
  const config = KEY_POOL_CONFIGS[poolId];
  const readField = (fieldName) => {
    const control = row.querySelector(`[data-key-pool-field="${fieldName}"]`);
    if (!control) {
      return "";
    }
    if (control.type === "checkbox") {
      return control.checked;
    }
    return String(control.value || "").trim();
  };
  let apiBase = readField("api_base");
  if (validateApiBase && !isValidApiBaseValue(apiBase)) {
    apiBase = String(currentSettings?.[config.apiBaseFallbackKey] || "").trim();
    const input = row.querySelector('[data-key-pool-field="api_base"]');
    if (input) {
      input.value = apiBase;
    }
  }
  const apiKey = readField("api_key");
  if (!includeEmpty && !apiKey) {
    return null;
  }
  const item = {
    id: String(row.dataset.keyPoolItemId || "").trim() || createKeyPoolItemId(poolId),
    name: readField("name") || `${config.itemLabel} ${index + 1}`,
    api_base: apiBase,
    api_key: apiKey,
    enabled: Boolean(readField("enabled")),
  };
  if (config.fields.model) {
    item.model = readField("model") || config.modelFallbackValue || "";
  }
  if (config.fields.endpointType) {
    item.endpoint_type = readField("endpoint_type") || "chat_completions";
  }
  return item;
}

function isValidApiBaseValue(value) {
  const text = String(value || "").trim();
  if (!text) {
    return true;
  }
  try {
    const url = new URL(text);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch (_error) {
    return false;
  }
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
    const key = input.dataset.setting;
    const value = readControlValue(input);
    settings[key] =
      key === "image_model_gpt_image_2_1k" || key === "image_model_gpt_image_2"
        ? normalizeConfiguredImageModelId(value)
        : value;
  });
  return {
    ...settings,
    ...collectKeyPools(),
  };
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
  refs.jobsList.querySelectorAll("[data-job-action='delete']").forEach((button) => {
    button.addEventListener("click", () => void runAction(() => deleteAdminJob(button.dataset.jobId)));
  });
}

function renderJob(job) {
  const canDelete = !["queued", "running"].includes(job.status);
  return `
    <div class="item">
      <div class="item-row">
        <div>
          <strong>${escapeHtml(job.title)} · ${escapeHtml(job.status)} · ${job.progress}%</strong>
          <small>${escapeHtml(job.task_type)} · user=${escapeHtml(job.user_id)} · ${escapeHtml(job.created_at || "")} · 存储 ${mb(job.storage_bytes)} MB</small>
        </div>
        <div class="item-actions">
          <button class="ghost" data-job-action="logs" data-job-id="${escapeHtml(job.id)}" type="button">日志</button>
          ${
            canDelete
              ? `<button class="danger" data-job-action="delete" data-job-id="${escapeHtml(job.id)}" type="button">删除</button>`
              : ""
          }
        </div>
      </div>
      ${job.error ? `<small>${escapeHtml(job.error)}</small>` : ""}
    </div>
  `;
}

async function deleteAdminJob(jobId) {
  if (!jobId) {
    return;
  }
  if (!window.confirm("确定删除这个任务？任务记录和对应文件都会删除。")) {
    return;
  }
  await api(`/api/v1/admin/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
  await Promise.all([loadSummary(), loadJobs()]);
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

async function openAdminLogs() {
  refs.logModal.hidden = false;
  refs.logModalTitle.textContent = "总日志";
  refs.logEntryPath.textContent = "";
  refs.logEntryTabs.innerHTML = "";
  refs.logModalContent.textContent = "正在读取日志...";
  const payload = await api("/api/v1/admin/logs");
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
