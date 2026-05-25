const queryParams = new URLSearchParams(window.location.search);

function reportStartupStep(step, detail = {}) {
  try {
    console.info(`startup step: ${step}`, detail);
    const body = JSON.stringify({
      step,
      detail,
      href: window.location.href,
      userAgent: navigator.userAgent,
      at: new Date().toISOString(),
    });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/client-log", new Blob([body], { type: "application/json" }));
      return;
    }
    void fetch("/api/client-log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    });
  } catch (_error) {
    // Client diagnostics must never block startup.
  }
}

window.addEventListener("error", (event) => {
  const target = event.target;
  if (target && target !== window) {
    const source =
      target.currentSrc || target.src || target.href || target.tagName || "unknown resource";
    console.error(`resource load error: ${source}`);
    return;
  }
  console.error(
    `window error: ${event.message || "unknown"} at ${event.filename || ""}:${
      event.lineno || ""
    }:${event.colno || ""}`,
    event.error || ""
  );
});

window.addEventListener("unhandledrejection", (event) => {
  console.error("unhandled promise rejection:", event.reason);
});

const state = {
  apiBase: queryParams.get("apiBase") || "",
  settings: null,
  sharedPool: null,
  history: [],
  jobs: [],
  currentRoute: "style-replicate",
  currentJobId: null,
  pollTimer: null,
  autosaveTimer: null,
  isHydratingSettings: false,
  taskDefaultsApplied: false,
  defaultUserPrompt: "",
  defaultStyleReplicate2UserPrompt: "",
  userPromptInitialized: false,
  userPromptPristine: true,
  logEntries: [],
  currentLogKey: "app",
  logScope: "global",
  isLogModalOpen: false,
  isImageModalOpen: false,
  imageModalLastPointerButton: null,
  imageModalContextMenuArmedUntil: 0,
  logTargetJobId: null,
  imageModalRunId: null,
  imageModalJobId: null,
  imageModalItems: [],
  imageModalIndex: 0,
  colorMatchPromptScroll: {},
  lastJobsSignature: "",
  lastHistorySignature: "",
  lastSharedPoolSignature: "",
  knownJobStatuses: {},
  audioContext: null,
  audioUnlocked: false,
  editInputAttachments: [],
  editConversations: [],
  editConversationId: null,
  editGenerationMode: "normal",
  historyVisibleCount: 30,
  editConversationScrollRequest: null,
  editConversationPersistTimer: null,
  editConversationPersistPayload: null,
  deletedEditConversationIds: new Set(),
  replicateReferenceFiles: {
    style: [],
    product: [],
    style2: [],
  },
  previewObjectUrls: {
    style: null,
    product: null,
    style2: null,
    colorTone: null,
    colorScene: null,
  },
  platformCsrfToken: "",
  platformUser: null,
};

const EDIT_STREAM_BOTTOM_THRESHOLD = 40;
const AGENT_CONTEXT_MAX_MESSAGES = 80;
const AGENT_CONTEXT_MAX_RESULT_URLS = 8;
const AGENT_CONTEXT_MAX_ATTACHMENTS = 12;
const AGENT_CONTEXT_MAX_IMAGE_REFS = 48;
const IMAGE_MODEL_GPT_IMAGE_2 = "gpt-image-2";
const GPT_IMAGE_2_1K_MODEL_ID = "gpt-image-2-1k";
const IMAGE_MODEL_NANO_BANANA_2 = "gemini-3.1-flash-image-preview";
const IMAGE_MODEL_NANO_BANANA_PRO = "gemini-3-pro-image-preview";
const API_BASE_SETTING_KEYS = new Set([
  "llm_api_base",
  "color_match_api_base",
  "image_agent_api_base",
  "image_api_base",
  "gpt_image_1k_api_base",
  "gpt_image_api_base",
  "gemini_image_api_base",
]);
const LEGACY_IMAGE_MODEL_ALIASES = {
  "nano-banana-2": IMAGE_MODEL_NANO_BANANA_2,
  "nano-banana-2-1k": IMAGE_MODEL_NANO_BANANA_2,
  "nano-banana-2-2k": IMAGE_MODEL_NANO_BANANA_2,
  "nano-banana-2-4k": IMAGE_MODEL_NANO_BANANA_2,
  "nano-banana-pro": IMAGE_MODEL_NANO_BANANA_PRO,
  "nano-banana-pro-1k": IMAGE_MODEL_NANO_BANANA_PRO,
  "nano-banana-pro-2k": IMAGE_MODEL_NANO_BANANA_PRO,
  "nano-banana-pro-4k": IMAGE_MODEL_NANO_BANANA_PRO,
};
const NANO_BANANA_COMMON_ASPECT_RATIOS = new Set([
  "1:1",
  "2:3",
  "3:2",
  "3:4",
  "4:3",
  "4:5",
  "5:4",
  "9:16",
  "16:9",
  "21:9",
]);
const NANO_BANANA_2_ONLY_ASPECT_RATIOS = new Set(["1:4", "4:1", "1:8", "8:1"]);
const POLL_INTERVAL_MS = 2200;

const refs = {};

function currentUserStorageToken() {
  const user = state.platformUser || {};
  const raw = user.id || user.username || "anonymous";
  return String(raw || "anonymous").replace(/[^a-zA-Z0-9_-]+/g, "_");
}

function editConversationsStorageKey() {
  return `imagReplicate2.user.${currentUserStorageToken()}.imageEditConversations`;
}

function deletedEditConversationsStorageKey() {
  return `imagReplicate2.user.${currentUserStorageToken()}.deletedImageEditConversationIds`;
}

function taskSoundStorageKey() {
  return `imagReplicate2.user.${currentUserStorageToken()}.taskSoundEnabled`;
}

function isTaskSoundEnabled() {
  return window.localStorage.getItem(taskSoundStorageKey()) !== "0";
}

function unlockTaskAudio() {
  if (state.audioUnlocked) {
    return;
  }
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) {
    return;
  }
  try {
    state.audioContext = state.audioContext || new AudioContextCtor();
    if (state.audioContext.state === "suspended") {
      void state.audioContext.resume();
    }
    state.audioUnlocked = true;
  } catch (_error) {
    state.audioUnlocked = false;
  }
}

function playTaskTone(kind) {
  if (!isTaskSoundEnabled()) {
    return;
  }
  unlockTaskAudio();
  const context = state.audioContext;
  if (!context) {
    return;
  }
  const now = context.currentTime;
  const notes = kind === "failed" ? [440, 196] : [523, 880];
  const peakGain = 1;
  const noteGap = kind === "failed" ? 0.12 : 0.11;
  const noteDuration = kind === "failed" ? 0.2 : 0.16;
  notes.forEach((frequency, index) => {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = kind === "failed" ? "triangle" : "sine";
    oscillator.frequency.value = frequency;
    const start = now + index * noteGap;
    const end = start + noteDuration;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(peakGain, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, end);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(end + 0.02);
  });
}

function markJobQueuedForSound(jobId) {
  if (!jobId) {
    return;
  }
  state.knownJobStatuses[jobId] = "queued";
}

function maybeNotifyJobStatusChanges(jobs) {
  const nextStatuses = {};
  jobs.forEach((job) => {
    const jobId = job.job_id || job.id;
    if (!jobId) {
      return;
    }
    const status = job.status || "";
    const previous = state.knownJobStatuses[jobId];
    nextStatuses[jobId] = status;
    if (!previous || previous === status) {
      return;
    }
    if (status === "completed" || status === "partial") {
      playTaskTone("completed");
    } else if (status === "failed") {
      playTaskTone("failed");
    }
  });
  state.knownJobStatuses = nextStatuses;
}

document.addEventListener("DOMContentLoaded", () => {
  void initializePlatformApp();
});

async function initializePlatformApp() {
  reportStartupStep("dom-content-loaded");
  cacheDom();
  reportStartupStep("dom-cached");
  enhancePasswordFields();
  hardenSettingsAutofill();
  reportStartupStep("password-fields-enhanced");
  bindEvents();
  bindPlatformActions();
  reportStartupStep("events-bound");
  await ensurePlatformSession();
  applyPlatformUserChrome();
  await bootstrap();
}

function bindPlatformActions() {
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-platform-action]");
    if (!target) {
      return;
    }
    if (target.dataset.platformAction === "logout") {
      void logoutPlatform();
    }
  });
}

async function ensurePlatformSession() {
  if (await loadPlatformSession()) {
    return;
  }
  document.body.classList.add("platform-auth-required");
  const panel = ensurePlatformLoginPanel();
  const form = panel.querySelector("form");
  const title = panel.querySelector("[data-auth-title]");
  const submitButton = panel.querySelector("[data-auth-submit]");
  const toggleButton = panel.querySelector("[data-platform-auth-toggle]");
  const message = panel.querySelector(".platform-login__message");
  enhancePasswordFields();

  const setMode = (mode) => {
    const isRegistering = mode === "register";
    form.dataset.authMode = isRegistering ? "register" : "login";
    title.textContent = isRegistering ? "注册账号" : "账号密码登录";
    submitButton.textContent = isRegistering ? "注册并进入" : "登录";
    toggleButton.textContent = isRegistering ? "已有账号，返回登录" : "没有账号，立即注册";
    form.elements.namedItem("password").autocomplete = isRegistering
      ? "new-password"
      : "current-password";
    message.textContent = "";
  };

  toggleButton.addEventListener("click", () => {
    setMode(form.dataset.authMode === "register" ? "login" : "register");
  });

  await new Promise((resolve) => {
    form.addEventListener(
      "submit",
      (event) => {
        event.preventDefault();
        void (async () => {
          const data = new FormData(form);
          const isRegistering = form.dataset.authMode === "register";
          const endpoint = isRegistering ? "/api/v1/auth/register" : "/api/v1/auth/login";
          message.textContent = "";
          submitButton.disabled = true;
          submitButton.textContent = isRegistering ? "注册中..." : "登录中...";
          try {
            const payload = await platformFetch(endpoint, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                username: data.get("username"),
                password: data.get("password"),
              }),
            });
            state.platformCsrfToken = payload.csrf_token || "";
            state.platformUser = payload.user || null;
            document.body.classList.remove("platform-auth-required");
            panel.hidden = true;
            resolve();
          } catch (error) {
            message.textContent = error.message || (isRegistering ? "注册失败。" : "登录失败。");
          } finally {
            submitButton.disabled = false;
            submitButton.textContent = isRegistering ? "注册并进入" : "登录";
          }
        })();
      },
      { once: false }
    );
  });
}

async function loadPlatformSession() {
  try {
    const payload = await platformFetch("/api/v1/auth/me");
    state.platformCsrfToken = payload.csrf_token || "";
    state.platformUser = payload.user || null;
    return Boolean(state.platformUser);
  } catch (_error) {
    state.platformCsrfToken = "";
    state.platformUser = null;
    return false;
  }
}

function ensurePlatformLoginPanel() {
  let panel = document.getElementById("platformLoginPanel");
  if (panel) {
    panel.hidden = false;
    return panel;
  }
  panel = document.createElement("section");
  panel.id = "platformLoginPanel";
  panel.className = "platform-login";
  panel.innerHTML = `
    <form class="platform-login__card" data-auth-mode="login">
      <p class="eyebrow">内部 Web 平台</p>
      <h2 data-auth-title>账号密码登录</h2>
      <label class="field">
        <span>账号</span>
        <input name="username" autocomplete="username" required />
      </label>
      <label class="field">
        <span>密码</span>
        <input name="password" type="password" autocomplete="current-password" required />
      </label>
      <button class="primary-action" type="submit" data-auth-submit>登录</button>
      <button class="secondary-action platform-login__switch" type="button" data-platform-auth-toggle>
        没有账号，立即注册
      </button>
      <p class="platform-login__message" role="alert"></p>
    </form>
  `;
  document.body.appendChild(panel);
  return panel;
}

function applyPlatformUserChrome() {
  const eyebrow = document.querySelector(".brand-block .eyebrow");
  if (eyebrow) {
    eyebrow.textContent = "内部 Web 平台";
  }
  const topActions = document.querySelector(".top-actions");
  if (!topActions || document.getElementById("platformUserBadge")) {
    return;
  }
  const user = state.platformUser || {};
  const badge = document.createElement("span");
  badge.id = "platformUserBadge";
  badge.className = "status-pill status-pill--user";
  badge.textContent = `${user.display_name || user.username || "用户"} · ${user.role || "user"}`;
  topActions.prepend(badge);
  if (user.role === "admin") {
    const adminLink = document.createElement("a");
    adminLink.className = "icon-button platform-top-link";
    adminLink.href = "/admin/";
    adminLink.textContent = "管理后台";
    topActions.appendChild(adminLink);
  }
  const logoutButton = document.createElement("button");
  logoutButton.className = "icon-button";
  logoutButton.type = "button";
  logoutButton.dataset.platformAction = "logout";
  logoutButton.textContent = "退出";
  topActions.appendChild(logoutButton);
}

async function logoutPlatform() {
  stopPolling();
  try {
    await platformFetch("/api/v1/auth/logout", {
      method: "POST",
      body: "{}",
    });
  } finally {
    window.location.reload();
  }
}

async function platformFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Platform-Client", "user");
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD"].includes(method) && state.platformCsrfToken) {
    headers.set("X-CSRF-Token", state.platformCsrfToken);
  }
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : await response.text();
  if (!response.ok) {
    throw new Error(formatApiErrorPayload(payload));
  }
  return payload;
}

function cacheDom() {
  refs.navChips = Array.from(document.querySelectorAll(".nav-chip"));
  refs.views = Array.from(document.querySelectorAll(".page-view"));
  refs.sharedPoolBadge = document.getElementById("sharedPoolBadge");

  refs.replicateForm = document.getElementById("replicateForm");
  refs.userPromptInput = refs.replicateForm.elements.namedItem("user_prompt");
  refs.openDataButton = document.getElementById("openDataButton");
  refs.taskSharedPoolValue = document.getElementById("taskSharedPoolValue");
  refs.taskImagesPerPromptValue = document.getElementById("taskImagesPerPromptValue");
  refs.taskJobStatusValue = document.getElementById("taskJobStatusValue");
  refs.taskUpdatedAtValue = document.getElementById("taskUpdatedAtValue");
  refs.taskBoard = document.getElementById("taskBoard");

  refs.replicate2Form = document.getElementById("replicate2Form");
  refs.replicate2UserPromptInput =
    refs.replicate2Form.elements.namedItem("user_prompt");
  refs.replicate2OpenDataButton = document.getElementById("replicate2OpenDataButton");
  refs.replicate2TaskSharedPoolValue = document.getElementById(
    "replicate2TaskSharedPoolValue"
  );
  refs.replicate2TaskImagesPerPromptValue = document.getElementById(
    "replicate2TaskImagesPerPromptValue"
  );
  refs.replicate2TaskJobStatusValue = document.getElementById(
    "replicate2TaskJobStatusValue"
  );
  refs.replicate2TaskUpdatedAtValue = document.getElementById(
    "replicate2TaskUpdatedAtValue"
  );
  refs.replicate2TaskBoard = document.getElementById("replicate2TaskBoard");

  refs.imageEditForm = document.getElementById("imageEditForm");
  refs.editOpenDataButton = document.getElementById("editOpenDataButton");
  refs.editFilesInput = document.getElementById("editFilesInput");
  refs.editFilesName = document.getElementById("editFilesName");
  refs.editPreviewGrid = document.getElementById("editPreviewGrid");
  refs.editDropZone = document.getElementById("editDropZone");
  refs.editPromptInput = document.getElementById("editPromptInput");
  refs.editModeButtons = Array.from(document.querySelectorAll("[data-edit-mode]"));
  refs.editAgentNote = document.getElementById("editAgentNote");
  refs.editPickFilesButton = document.getElementById("editPickFilesButton");
  refs.editNewConversationButton = document.getElementById("editNewConversationButton");
  refs.editConversationList = document.getElementById("editConversationList");
  refs.editHistoryList = document.getElementById("editHistoryList");
  refs.editConversationStream = document.getElementById("editConversationStream");
  refs.editConversationTitle = document.getElementById("editConversationTitle");
  refs.editConversationMeta = document.getElementById("editConversationMeta");
  refs.editTaskSharedPoolValue = document.getElementById("editTaskSharedPoolValue");
  refs.editTaskImagesPerPromptValue = document.getElementById(
    "editTaskImagesPerPromptValue"
  );
  refs.editTaskJobStatusValue = document.getElementById("editTaskJobStatusValue");
  refs.editTaskUpdatedAtValue = document.getElementById("editTaskUpdatedAtValue");
  refs.editTaskBoard = document.getElementById("editTaskBoard");

  refs.colorMatchForm = document.getElementById("colorMatchForm");
  refs.colorOpenDataButton = document.getElementById("colorOpenDataButton");
  refs.colorToneFileInput = document.getElementById("colorToneFileInput");
  refs.colorToneFileName = document.getElementById("colorToneFileName");
  refs.colorTonePreviewImage = document.getElementById("colorTonePreviewImage");
  refs.colorTonePreviewMeta = document.getElementById("colorTonePreviewMeta");
  refs.colorSceneFileInput = document.getElementById("colorSceneFileInput");
  refs.colorSceneFileName = document.getElementById("colorSceneFileName");
  refs.colorScenePreviewImage = document.getElementById("colorScenePreviewImage");
  refs.colorScenePreviewMeta = document.getElementById("colorScenePreviewMeta");
  refs.colorTaskSharedPoolValue = document.getElementById("colorTaskSharedPoolValue");
  refs.colorTaskOutputValue = document.getElementById("colorTaskOutputValue");
  refs.colorTaskJobStatusValue = document.getElementById("colorTaskJobStatusValue");
  refs.colorTaskUpdatedAtValue = document.getElementById("colorTaskUpdatedAtValue");
  refs.colorTaskBoard = document.getElementById("colorTaskBoard");

  refs.historyList = document.getElementById("historyList");
  refs.historyCardTemplate = document.getElementById("historyCardTemplate");

  refs.settingsForm = document.getElementById("settingsForm");
  refs.autosaveBadgeInline = document.getElementById("autosaveBadgeInline");
  refs.saveSettingsButton = document.getElementById("saveSettingsButton");

  refs.styleFileInput = document.getElementById("styleFileInput");
  refs.styleFileName = document.getElementById("styleFileName");
  refs.styleUrlInput = document.getElementById("styleUrlInput");
  refs.styleClearReferenceButton = document.getElementById("styleClearReferenceButton");
  refs.productFileInput = document.getElementById("productFileInput");
  refs.productFileName = document.getElementById("productFileName");
  refs.productUrlInput = document.getElementById("productUrlInput");
  refs.productClearReferenceButton = document.getElementById(
    "productClearReferenceButton"
  );
  refs.stylePreviewImage = document.getElementById("stylePreviewImage");
  refs.stylePreviewMeta = document.getElementById("stylePreviewMeta");
  refs.productPreviewImage = document.getElementById("productPreviewImage");
  refs.productPreviewMeta = document.getElementById("productPreviewMeta");
  refs.style2FileInput = document.getElementById("style2FileInput");
  refs.style2FileName = document.getElementById("style2FileName");
  refs.style2UrlInput = document.getElementById("style2UrlInput");
  refs.style2ClearReferenceButton = document.getElementById(
    "style2ClearReferenceButton"
  );
  refs.style2PreviewImage = document.getElementById("style2PreviewImage");
  refs.style2PreviewMeta = document.getElementById("style2PreviewMeta");

  refs.openLogModalButton = document.getElementById("openLogModalButton");
  refs.logModal = document.getElementById("logModal");
  refs.logEntryTabs = document.getElementById("logEntryTabs");
  refs.logEntryTitle = document.getElementById("logEntryTitle");
  refs.logEntryPath = document.getElementById("logEntryPath");
  refs.logModalContent = document.getElementById("logModalContent");
  refs.openGlobalLogsButton = document.getElementById("openGlobalLogsButton");
  refs.openCurrentJobLogsButton = document.getElementById("openCurrentJobLogsButton");
  refs.refreshLogsButton = document.getElementById("refreshLogsButton");
  refs.openLogsFolderButton = document.getElementById("openLogsFolderButton");
  refs.logModalCloseButtons = Array.from(
    document.querySelectorAll("[data-close-log-modal]")
  );

  refs.imageModal = document.getElementById("imageModal");
  refs.imageModalViewport = refs.imageModal.querySelector(".image-viewer__viewport");
  refs.imageModalContent = document.getElementById("imageModalContent");
  refs.imageModalCaption = document.getElementById("imageModalCaption");
  refs.imageModalCounter = document.getElementById("imageModalCounter");
  refs.imageModalDownloadCurrentButton = document.getElementById(
    "imageModalDownloadCurrentButton"
  );
  refs.imageModalDownloadAllButton = document.getElementById(
    "imageModalDownloadAllButton"
  );
  refs.imageModalSelectDownloadButton = document.getElementById(
    "imageModalSelectDownloadButton"
  );
  refs.imageModalPrevButton = document.getElementById("imageModalPrevButton");
  refs.imageModalNextButton = document.getElementById("imageModalNextButton");
  refs.imageModalContextMenu = document.getElementById("imageModalContextMenu");
  refs.imageModalSaveAsButton = document.getElementById("imageModalSaveAsButton");
  refs.imageModalCopyButton = document.getElementById("imageModalCopyButton");
  refs.imageModalCloseButtons = Array.from(
    document.querySelectorAll("[data-close-image-modal]")
  );
}

function enhancePasswordFields() {
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    if (isSettingsInput(input)) {
      input.autocomplete = "new-password";
      input.setAttribute("data-lpignore", "true");
      input.setAttribute("data-1p-ignore", "true");
    }
    if (input.closest(".password-reveal")) {
      return;
    }
    const wrapper = document.createElement("span");
    wrapper.className = "password-reveal";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "password-reveal__button";
    button.setAttribute("aria-label", "按住显示密钥");
    button.setAttribute("title", "按住显示密钥");
    button.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"></path>
        <circle cx="12" cy="12" r="3"></circle>
      </svg>
    `;
    button.setAttribute("aria-label", "显示或隐藏密钥");
    button.setAttribute("title", "显示或隐藏密钥");
    button.setAttribute("aria-pressed", "false");

    const reveal = () => {
      input.type = "text";
      button.classList.add("is-active");
      button.setAttribute("aria-pressed", "true");
    };
    const conceal = () => {
      input.type = "password";
      button.classList.remove("is-active");
      button.setAttribute("aria-pressed", "false");
    };
    const toggle = () => {
      if (input.type === "password") {
        reveal();
      } else {
        conceal();
      }
    };

    button.addEventListener("click", (event) => {
      event.preventDefault();
      toggle();
    });
    button.addEventListener("contextmenu", (event) => event.preventDefault());
    wrapper.appendChild(button);
  });
}

function isSettingsInput(element) {
  return Boolean(element?.closest?.("#settingsForm"));
}

function hardenSettingsAutofill() {
  if (!refs.settingsForm) {
    return;
  }
  refs.settingsForm.autocomplete = "off";
  Array.from(refs.settingsForm.elements).forEach((element) => {
    if (!element.name) {
      return;
    }
    if (API_BASE_SETTING_KEYS.has(element.name)) {
      element.autocomplete = "off";
      element.inputMode = "url";
      element.spellcheck = false;
    }
    if (isSecretSettingField(element)) {
      element.autocomplete = "new-password";
      element.setAttribute("data-lpignore", "true");
      element.setAttribute("data-1p-ignore", "true");
    }
  });
}

function bindEvents() {
  window.addEventListener(
    "pointerdown",
    () => {
      unlockTaskAudio();
    },
    { once: true }
  );
  refs.navChips.forEach((chip) => {
    chip.addEventListener("click", () => setRoute(chip.dataset.route));
  });

  refs.replicateForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void submitReplicateTask();
  });
  refs.replicate2Form.addEventListener("submit", (event) => {
    event.preventDefault();
    void submitReplicate2Task();
  });
  refs.imageEditForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void submitImageEditTask();
  });
  refs.colorMatchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void submitColorMatchTask();
  });
  refs.userPromptInput.addEventListener("focus", handleUserPromptFocus);
  refs.userPromptInput.addEventListener("input", handleUserPromptInput);

  refs.openDataButton.addEventListener("click", () => {
    void openDataDirectory();
  });
  refs.replicate2OpenDataButton.addEventListener("click", () => {
    void openDataDirectory();
  });
  refs.editOpenDataButton.addEventListener("click", () => {
    void openDataDirectory();
  });
  refs.colorOpenDataButton.addEventListener("click", () => {
    void openDataDirectory();
  });
  refs.editPickFilesButton.addEventListener("click", () => {
    refs.editFilesInput.click();
  });
  refs.editModeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setEditGenerationMode(button.dataset.editMode || "normal");
    });
  });
  refs.editNewConversationButton.addEventListener("click", () => {
    clearEditComposer({ render: false });
    createEditConversation();
  });

  refs.settingsForm.addEventListener("input", onSettingsChanged);
  refs.settingsForm.addEventListener("change", onSettingsChanged);
  refs.saveSettingsButton.addEventListener("click", () => {
    void saveSettings();
  });

  refs.styleFileInput.addEventListener("change", () => {
    addReferenceFiles("style", Array.from(refs.styleFileInput.files || []));
    refs.styleFileInput.value = "";
  });
  refs.styleUrlInput.addEventListener("input", () => renderReferencePreview("style"));
  refs.styleClearReferenceButton.addEventListener("click", () =>
    clearReferenceGroup("style")
  );
  refs.productFileInput.addEventListener("change", () => {
    addReferenceFiles("product", Array.from(refs.productFileInput.files || []));
    refs.productFileInput.value = "";
  });
  refs.productUrlInput.addEventListener("input", () =>
    renderReferencePreview("product")
  );
  refs.productClearReferenceButton.addEventListener("click", () =>
    clearReferenceGroup("product")
  );
  refs.style2FileInput.addEventListener("change", () => {
    addReferenceFiles("style2", Array.from(refs.style2FileInput.files || []));
    refs.style2FileInput.value = "";
  });
  refs.style2UrlInput.addEventListener("input", () => renderReferencePreview("style2"));
  refs.style2ClearReferenceButton.addEventListener("click", () =>
    clearReferenceGroup("style2")
  );
  refs.colorToneFileInput.addEventListener("change", () =>
    renderColorMatchPreview("colorTone")
  );
  refs.colorSceneFileInput.addEventListener("change", () =>
    renderColorMatchPreview("colorScene")
  );
  refs.editFilesInput.addEventListener("change", () => {
    addEditFiles(Array.from(refs.editFilesInput.files || []));
    refs.editFilesInput.value = "";
  });
  refs.editDropZone.addEventListener("paste", (event) => {
    void handleEditPaste(event);
  });
  refs.editDropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    refs.editDropZone.classList.add("is-dragging");
  });
  refs.editDropZone.addEventListener("dragleave", () => {
    refs.editDropZone.classList.remove("is-dragging");
  });
  refs.editDropZone.addEventListener("drop", (event) => {
    void handleEditDrop(event);
  });
  refs.editPromptInput.addEventListener("keydown", (event) => {
    if (event.isComposing) {
      return;
    }
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.altKey &&
      !event.ctrlKey &&
      !event.metaKey
    ) {
      event.preventDefault();
      refs.imageEditForm.requestSubmit();
    }
  });

  refs.openLogModalButton.addEventListener("click", () => {
    void openLogModal();
  });
  refs.openGlobalLogsButton?.addEventListener("click", () => {
    state.logScope = "global";
    state.logTargetJobId = null;
    state.currentLogKey = "total";
    void refreshLogs();
  });
  refs.openCurrentJobLogsButton?.addEventListener("click", () => {
    state.logScope = "job";
    state.logTargetJobId = state.currentJobId || resolveCurrentJobId();
    state.currentLogKey = "run";
    void refreshLogs();
  });
  refs.refreshLogsButton.addEventListener("click", () => {
    void refreshLogs();
  });
  refs.openLogsFolderButton.addEventListener("click", () => {
    void openLogsDirectory();
  });
  refs.logModalCloseButtons.forEach((button) => {
    button.addEventListener("click", closeLogModal);
  });

  refs.imageModalCloseButtons.forEach((button) => {
    button.addEventListener("click", closeImageModal);
  });
  refs.imageModalDownloadCurrentButton.addEventListener("click", () => {
    void downloadActiveModalImage();
  });
  refs.imageModalDownloadAllButton.addEventListener("click", () => {
    if (state.imageModalJobId) {
      void downloadJobImages(state.imageModalJobId);
    }
  });
  refs.imageModalSelectDownloadButton.addEventListener("click", () => {
    if (state.imageModalJobId) {
      void openDownloadSelection(state.imageModalJobId);
    }
  });
  refs.imageModalPrevButton.addEventListener("click", () => {
    stepImageModal(-1);
  });
  refs.imageModalNextButton.addEventListener("click", () => {
    stepImageModal(1);
  });
  refs.imageModalViewport.addEventListener("contextmenu", (event) => {
    if (!state.isImageModalOpen || !getActiveImageModalItem()) {
      return;
    }
    event.preventDefault();
    const isArmedForContextMenu =
      state.imageModalContextMenuArmedUntil > Date.now() &&
      state.imageModalLastPointerButton === 2;
    if (!isArmedForContextMenu) {
      hideImageModalContextMenu();
      return;
    }
    showImageModalContextMenu(event.clientX, event.clientY);
  });
  refs.imageModalViewport.addEventListener("pointerdown", (event) => {
    state.imageModalLastPointerButton =
      typeof event.button === "number" ? event.button : null;
    state.imageModalContextMenuArmedUntil =
      event.button === 2 ? Date.now() + 800 : 0;
    if (
      !refs.imageModalContextMenu.hidden &&
      !refs.imageModalContextMenu.contains(event.target)
    ) {
      hideImageModalContextMenu();
    }
  });
  refs.imageModalViewport.addEventListener("scroll", hideImageModalContextMenu, {
    passive: true,
  });
  refs.imageModal.addEventListener("pointerdown", (event) => {
    if (
      !refs.imageModalContextMenu.hidden &&
      !refs.imageModalContextMenu.contains(event.target)
    ) {
      hideImageModalContextMenu();
    }
  });
  refs.imageModalSaveAsButton.addEventListener("click", () => {
    hideImageModalContextMenu();
    void downloadActiveModalImage();
  });
  refs.imageModalCopyButton.addEventListener("click", () => {
    hideImageModalContextMenu();
    void copyActiveModalImage();
  });
  refs.imageModalContextMenu.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  window.addEventListener("keydown", (event) => {
    if (state.isImageModalOpen) {
      if (event.key === "Escape") {
        closeImageModal();
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        stepImageModal(-1);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        stepImageModal(1);
        return;
      }
    }

    if (event.key !== "Escape") {
      return;
    }
    if (state.isLogModalOpen) {
      closeLogModal();
    }
  });

  window.addEventListener("beforeunload", () => {
    persistEditConversationsImmediately({ keepalive: true });
    revokePreviewUrl("style");
    revokePreviewUrl("product");
    revokePreviewUrl("style2");
    revokePreviewUrl("colorTone");
    revokePreviewUrl("colorScene");
    clearEditAttachments();
  });
}

function setEditGenerationMode(mode) {
  state.editGenerationMode = mode === "agent" ? "agent" : "normal";
  refs.editModeButtons.forEach((button) => {
    const isActive = button.dataset.editMode === state.editGenerationMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
  const countField = refs.imageEditForm.querySelector(".edit-count-field");
  const countInput = refs.imageEditForm.elements.namedItem("images_per_prompt");
  const resolutionInput = refs.imageEditForm.elements.namedItem("output_resolution");
  const aspectInput = refs.imageEditForm.elements.namedItem("output_aspect_ratio");
  const resolutionField = resolutionInput?.closest(".edit-aspect-field");
  const aspectField = aspectInput?.closest(".edit-aspect-field");
  const isAgent = state.editGenerationMode === "agent";
  refs.imageEditForm.classList.toggle("is-agent-mode", isAgent);
  if (countField) {
    countField.hidden = isAgent;
  }
  if (resolutionField) {
    resolutionField.hidden = isAgent;
  }
  if (aspectField) {
    aspectField.hidden = isAgent;
  }
  if (countInput) {
    countInput.disabled = isAgent;
    countInput.required = !isAgent;
  }
  if (resolutionInput) {
    resolutionInput.disabled = isAgent;
    resolutionInput.required = !isAgent;
  }
  if (aspectInput) {
    aspectInput.disabled = isAgent;
    aspectInput.required = !isAgent;
  }
  if (refs.editAgentNote) {
    refs.editAgentNote.hidden = !isAgent;
  }
}

async function bootstrap() {
  try {
    reportStartupStep("bootstrap-start");
    loadDeletedEditConversationIds();
    const payload = await apiFetch("/api/bootstrap");
    reportStartupStep("bootstrap-payload-received", {
      historyCount: Array.isArray(payload.history) ? payload.history.length : 0,
      jobsCount: Array.isArray(payload.jobs) ? payload.jobs.length : 0,
      hasSettings: Boolean(payload.settings),
    });
    state.settings = payload.settings || {};
    state.sharedPool = payload.shared_pool || null;
    state.history = filterDeletedEditConversationHistory(payload.history || []);
    state.jobs = payload.jobs || [];
    state.lastSharedPoolSignature = stableJsonSignature(state.sharedPool);
    state.lastHistorySignature = stableJsonSignature(state.history);
    state.lastJobsSignature = stableJsonSignature(state.jobs);
    state.currentJobId = resolveCurrentJobId();
    loadEditConversations(payload.edit_conversations || []);
    if (hydrateEditMessagesInputImageUrls()) {
      saveEditConversations();
    }
    if (hydrateEditConversationTextRepliesFromHistory(state.history)) {
      saveEditConversations();
    }
    if (!state.editConversations.length) {
      loadEditConversations(reconstructEditConversationsFromHistory(state.history));
      if (state.editConversations.length) {
        saveEditConversations();
      }
    }
    ensureEditConversation();
    setEditGenerationMode(state.editGenerationMode);
    applySettingsToForm();
    applyTaskDefaults(true);
    renderReferencePreview("style");
    renderReferencePreview("product");
    renderReferencePreview("style2");
    renderColorMatchPreview("colorTone");
    renderColorMatchPreview("colorScene");
    renderEditPreview();
    renderAll();
    reportStartupStep("render-all-complete");
    startPolling();
    reportStartupStep("polling-started");
  } catch (error) {
    reportStartupStep("bootstrap-failed", {
      message: error?.message || String(error),
      stack: error?.stack || "",
    });
    refs.taskBoard.innerHTML = `<p class="muted-copy">${escapeHtml(error.message)}</p>`;
  }
}

function renderAll() {
  renderNav();
  renderTopStatus();
  renderTaskMetrics();
  renderTaskBoard();
  renderHistory();
  renderEditWorkspace();
}

function stableJsonSignature(value) {
  try {
    return JSON.stringify(value ?? null);
  } catch (_error) {
    return String(Date.now());
  }
}

function renderNav() {
  refs.navChips.forEach((chip) => {
    chip.classList.toggle("is-active", chip.dataset.route === state.currentRoute);
  });

  refs.views.forEach((view) => {
    view.classList.toggle("is-visible", view.dataset.view === state.currentRoute);
  });
}

function setRoute(route) {
  state.currentRoute = route;
  renderNav();
  if (route === "image-edit") {
    requestEditConversationScrollToBottom();
    renderEditWorkspace();
    setTimeout(() => refs.editPromptInput?.focus(), 0);
  }
}

function getSharedPoolDisplay() {
  const capacity =
    Number(state.sharedPool?.capacity) ||
    Number(state.settings?.default_concurrency) ||
    Number(state.sharedPool?.size) ||
    0;
  const available =
    state.sharedPool && Number.isFinite(Number(state.sharedPool.available))
      ? Number(state.sharedPool.available)
      : capacity;
  if (!capacity) {
    return "-";
  }
  return `${available} / ${capacity}`;
}

function getSharedPoolAvailability() {
  const capacity =
    Number(state.sharedPool?.capacity) ||
    Number(state.sharedPool?.size) ||
    Number(state.settings?.default_concurrency) ||
    0;
  const available =
    state.sharedPool && Number.isFinite(Number(state.sharedPool.available))
      ? Number(state.sharedPool.available)
      : capacity;
  return {
    available: Math.max(0, Math.trunc(available || 0)),
    capacity: Math.max(0, Math.trunc(capacity || 0)),
  };
}

function renderTopStatus() {
  const { available, capacity } = getSharedPoolAvailability();
  refs.sharedPoolBadge.classList.remove(
    "status-pill--quota-ok",
    "status-pill--quota-low",
    "status-pill--quota-danger"
  );
  if (!capacity) {
    refs.sharedPoolBadge.textContent = "任务额度 -";
    refs.sharedPoolBadge.title = "当前任务额度不可用";
    return;
  }
  const stateClass =
    available < 3
      ? "status-pill--quota-danger"
      : available < 10
        ? "status-pill--quota-low"
        : "status-pill--quota-ok";
  refs.sharedPoolBadge.classList.add(stateClass);
  refs.sharedPoolBadge.textContent = `任务额度 ${available}`;
  refs.sharedPoolBadge.title = `当前还可提交 ${available} 个任务，总额度 ${capacity}。`;
}

function renderTaskMetrics() {
  const currentJob = getCurrentJob("style-replicate");
  refs.taskSharedPoolValue.textContent = getSharedPoolDisplay();
  refs.taskImagesPerPromptValue.textContent =
    state.settings?.default_images_per_prompt ?? "-";
  refs.taskJobStatusValue.textContent = formatStatus(currentJob?.status || "idle");
  refs.taskUpdatedAtValue.textContent = formatDateTime(currentJob?.updated_at);

  const replicate2Job = getCurrentJob("style-replicate-v2");
  if (refs.replicate2TaskSharedPoolValue) {
    refs.replicate2TaskSharedPoolValue.textContent = getSharedPoolDisplay();
  }
  if (refs.replicate2TaskImagesPerPromptValue) {
    refs.replicate2TaskImagesPerPromptValue.textContent =
      state.settings?.default_images_per_prompt ?? "-";
  }
  if (refs.replicate2TaskJobStatusValue) {
    refs.replicate2TaskJobStatusValue.textContent = formatStatus(
      replicate2Job?.status || "idle"
    );
  }
  if (refs.replicate2TaskUpdatedAtValue) {
    refs.replicate2TaskUpdatedAtValue.textContent = formatDateTime(
      replicate2Job?.updated_at
    );
  }

  const editJob = getCurrentJob(["image-edit", "image-agent"]);
  if (refs.editTaskSharedPoolValue) {
    refs.editTaskSharedPoolValue.textContent = getSharedPoolDisplay();
  }
  if (refs.editTaskImagesPerPromptValue) {
    refs.editTaskImagesPerPromptValue.textContent =
      editJob?.task_key === "image-agent"
        ? editJob?.summary?.request_count || "Agent"
        : editJob?.metadata?.images_per_prompt ?? state.settings?.default_images_per_prompt ?? "-";
  }
  if (refs.editTaskJobStatusValue) {
    refs.editTaskJobStatusValue.textContent = formatStatus(editJob?.status || "idle");
  }
  if (refs.editTaskUpdatedAtValue) {
    refs.editTaskUpdatedAtValue.textContent = formatDateTime(editJob?.updated_at);
  }

  const colorJob = getCurrentJob("color-match");
  if (refs.colorTaskSharedPoolValue) {
    refs.colorTaskSharedPoolValue.textContent = getSharedPoolDisplay();
  }
  if (refs.colorTaskOutputValue) {
    const outputLabel =
      colorJob?.summary?.output_label ||
      colorJob?.metadata?.output_label ||
      formatOutputSelection({
        outputResolution: state.settings?.default_output_resolution,
        outputAspectRatio: state.settings?.default_output_aspect_ratio,
      });
    refs.colorTaskOutputValue.textContent = outputLabel;
  }
  if (refs.colorTaskJobStatusValue) {
    refs.colorTaskJobStatusValue.textContent = formatStatus(colorJob?.status || "idle");
  }
  if (refs.colorTaskUpdatedAtValue) {
    refs.colorTaskUpdatedAtValue.textContent = formatDateTime(colorJob?.updated_at);
  }
}

function renderTaskBoard() {
  renderTaskBoardFor({
    board: refs.taskBoard,
    taskKey: "style-replicate",
    statuses: ["queued", "running", "completed", "partial", "failed"],
    emptyText: "提交后复刻风格图片任务会出现在这里。",
  });
  renderTaskBoardFor({
    board: refs.replicate2TaskBoard,
    taskKey: "style-replicate-v2",
    statuses: ["queued", "running", "completed", "partial", "failed"],
    emptyText: "提交后复刻风格图片2任务会出现在这里。",
  });
  renderTaskBoardFor({
    board: refs.editTaskBoard,
    taskKey: ["image-edit", "image-agent"],
    statuses: ["queued", "running", "completed", "partial", "failed"],
    emptyText: "当前没有运行中或刚失败的图片生成任务。",
  });
  renderTaskBoardFor({
    board: refs.colorTaskBoard,
    taskKey: "color-match",
    statuses: ["queued", "running", "completed", "partial", "failed"],
    emptyText: "提交后追色任务会出现在这里。",
  });
}

function renderTaskBoardFor({ board, taskKey, statuses = null, emptyText }) {
  if (!board) {
    return;
  }
  board.innerHTML = "";
  const jobs = state.jobs.filter((job) => {
    const matchesTask = Array.isArray(taskKey)
      ? taskKey.includes(job.task_key)
      : job.task_key === taskKey;
    if (!matchesTask) {
      return false;
    }
    return !statuses || statuses.includes(job.status);
  });

  if (!jobs.length) {
    board.innerHTML = `<p class="muted-copy">${escapeHtml(emptyText)}</p>`;
    return;
  }

  jobs.slice(0, 10).forEach((job) => {
    board.appendChild(buildTaskCard(job));
  });
}

function loadDeletedEditConversationIds() {
  try {
    const raw = window.localStorage.getItem(deletedEditConversationsStorageKey());
    const parsed = raw ? JSON.parse(raw) : [];
    state.deletedEditConversationIds = new Set(
      Array.isArray(parsed)
        ? parsed.filter((item) => typeof item === "string" && item)
        : []
    );
  } catch (_error) {
    state.deletedEditConversationIds = new Set();
  }
}

function saveDeletedEditConversationIds() {
  const ids = Array.from(state.deletedEditConversationIds || []);
  if (ids.length) {
    window.localStorage.setItem(
      deletedEditConversationsStorageKey(),
      JSON.stringify(ids.slice(-120))
    );
  } else {
    window.localStorage.removeItem(deletedEditConversationsStorageKey());
  }
}

function isDeletedEditConversationId(conversationId) {
  return Boolean(
    conversationId &&
      state.deletedEditConversationIds instanceof Set &&
      state.deletedEditConversationIds.has(conversationId)
  );
}

function rememberDeletedEditConversationId(conversationId) {
  if (!conversationId) {
    return;
  }
  if (!(state.deletedEditConversationIds instanceof Set)) {
    state.deletedEditConversationIds = new Set();
  }
  state.deletedEditConversationIds.add(conversationId);
  saveDeletedEditConversationIds();
}

function forgetDeletedEditConversationId(conversationId) {
  if (!conversationId || !(state.deletedEditConversationIds instanceof Set)) {
    return;
  }
  if (state.deletedEditConversationIds.delete(conversationId)) {
    saveDeletedEditConversationIds();
  }
}

function conversationIdFromHistoryRecord(record, fallback = "") {
  return typeof record?.conversation_id === "string" && record.conversation_id.trim()
    ? record.conversation_id.trim()
    : fallback;
}

function normalizePersistedEditConversations(source) {
  if (!Array.isArray(source)) {
    return [];
  }

  return source
    .map((conversation) => {
      const messages = Array.isArray(conversation?.messages)
        ? conversation.messages
            .map((message) => ({
              id:
                typeof message?.id === "string" && message.id
                  ? message.id
                  : `msg-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
              prompt: String(message?.prompt || "").trim(),
              mode: message?.mode === "agent" ? "agent" : "normal",
              imageModel:
                normalizeImageModel(message?.imageModel || message?.image_model) ||
                IMAGE_MODEL_GPT_IMAGE_2,
              outputResolution:
                String(message?.outputResolution || "").trim() ||
                String(message?.output_resolution || "").trim() ||
                "auto",
              outputAspectRatio:
                String(message?.outputAspectRatio || "").trim() ||
                String(message?.output_aspect_ratio || "").trim() ||
                String(message?.aspectRatio || "").trim() ||
                "auto",
              resolvedSize:
                String(message?.resolvedSize || "").trim() ||
                String(message?.resolved_size || "").trim() ||
                "",
              imagesPerPrompt: normalizeEditImagesPerPrompt(message?.imagesPerPrompt),
              createdAt:
                typeof message?.createdAt === "string" && message.createdAt
                  ? message.createdAt
                  : new Date().toISOString(),
              jobId:
                typeof message?.jobId === "string" && message.jobId
                  ? message.jobId
                  : null,
              runId:
                typeof message?.runId === "string" && message.runId
                  ? message.runId
                  : null,
              status: typeof message?.status === "string" ? message.status : "queued",
              error: typeof message?.error === "string" ? message.error : "",
              agentResponseText:
                typeof message?.agentResponseText === "string"
                  ? message.agentResponseText
                  : typeof message?.agent_response_text === "string"
                    ? message.agent_response_text
                    : "",
              agentSummary:
                message?.agentSummary && typeof message.agentSummary === "object"
                  ? message.agentSummary
                  : message?.agent_summary && typeof message.agent_summary === "object"
                    ? message.agent_summary
                    : null,
              resultUrls: Array.isArray(message?.resultUrls)
                ? message.resultUrls.filter((item) => typeof item === "string" && item)
                : [],
              resultThumbnailUrls: Array.isArray(message?.resultThumbnailUrls)
                ? message.resultThumbnailUrls.filter(
                    (item) => typeof item === "string" && item
                  )
                : Array.isArray(message?.result_thumbnail_urls)
                  ? message.result_thumbnail_urls.filter(
                      (item) => typeof item === "string" && item
                    )
                  : [],
              inputCount: Number.isFinite(Number(message?.inputCount))
                ? Math.max(0, Number.parseInt(message.inputCount, 10))
                : Array.isArray(message?.attachments)
                  ? message.attachments.length
                  : 0,
              attachments: Array.isArray(message?.attachments)
                ? message.attachments
                    .map((item, index) => normalizeAttachmentItem(item, index))
                    .filter((item) => item.name)
                : [],
            }))
            .filter((message) => message.prompt)
        : [];

      return {
        id:
          typeof conversation?.id === "string" && conversation.id
            ? conversation.id
            : `edit-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
        title:
          typeof conversation?.title === "string" && conversation.title.trim()
            ? conversation.title.trim()
            : "图片生成",
        createdAt:
          typeof conversation?.createdAt === "string" && conversation.createdAt
            ? conversation.createdAt
            : new Date().toISOString(),
        updatedAt:
          typeof conversation?.updatedAt === "string" && conversation.updatedAt
            ? conversation.updatedAt
            : new Date().toISOString(),
        messages,
      };
    })
    .filter((conversation) => !isDeletedEditConversationId(conversation.id))
    .filter((conversation) => conversation.messages.length > 0)
    .slice(0, 30);
}

function syncEditMessagesFromJobs() {
  if (!Array.isArray(state.editConversations) || !Array.isArray(state.jobs)) {
    return false;
  }
  let changed = false;
  state.editConversations.forEach((conversation) => {
    (conversation.messages || []).forEach((message) => {
      if (!message.jobId) {
        return;
      }
      const job = state.jobs.find((item) => item.job_id === message.jobId);
      if (!job) {
        return;
      }
      if (message.status !== job.status) {
        message.status = job.status;
        changed = true;
      }
      if (job.error && message.error !== job.error) {
        message.error = job.error;
        changed = true;
      }
      const previewItems = getJobPreviewItems(job);
      const previewUrls = previewItems.map((item) => item.url);
      if (previewUrls.length && !arraysEqual(message.resultUrls || [], previewUrls)) {
        message.resultUrls = previewUrls;
        changed = true;
      }
      const previewThumbnailUrls = previewItems.map((item) => item.thumbnailUrl);
      if (
        previewThumbnailUrls.length &&
        !arraysEqual(message.resultThumbnailUrls || [], previewThumbnailUrls)
      ) {
        message.resultThumbnailUrls = previewThumbnailUrls;
        changed = true;
      }
    });
  });
  return changed;
}

function serializeEditConversations() {
  return state.editConversations
    .filter((conversation) => Array.isArray(conversation?.messages) && conversation.messages.length)
    .slice(0, 30)
    .map((conversation) => ({
      id: conversation.id,
      title: conversation.title,
      createdAt: conversation.createdAt,
      updatedAt: conversation.updatedAt,
      messages: (conversation.messages || []).slice(-80).map((message) => ({
        id: message.id,
        prompt: message.prompt,
        mode: message.mode || "normal",
        outputResolution: message.outputResolution,
        outputAspectRatio: message.outputAspectRatio,
        resolvedSize: message.resolvedSize || "",
        imagesPerPrompt: message.imagesPerPrompt || 1,
        createdAt: message.createdAt,
        jobId: message.jobId || null,
        runId: message.runId || null,
        status: message.status || "queued",
        error: message.error || "",
        agentResponseText: message.agentResponseText || "",
        agentSummary: message.agentSummary || null,
        resultUrls: Array.isArray(message.resultUrls) ? message.resultUrls : [],
        resultThumbnailUrls: Array.isArray(message.resultThumbnailUrls)
          ? message.resultThumbnailUrls
          : [],
        inputCount: message.inputCount || message.attachments?.length || 0,
        attachments: (message.attachments || []).map((item) => ({
          name: item.name,
          src:
            typeof item?.src === "string" && item.src && !item.src.startsWith("blob:")
              ? item.src
              : "",
          thumbnailSrc:
            typeof item?.thumbnailSrc === "string" &&
            item.thumbnailSrc &&
            !item.thumbnailSrc.startsWith("blob:")
              ? item.thumbnailSrc
              : typeof item?.thumbnailUrl === "string" &&
                  item.thumbnailUrl &&
                  !item.thumbnailUrl.startsWith("blob:")
                ? item.thumbnailUrl
                : typeof item?.thumbnail_src === "string" &&
                    item.thumbnail_src &&
                    !item.thumbnail_src.startsWith("blob:")
                  ? item.thumbnail_src
                  : "",
        })),
      })),
    }));
}

function isPersistableImageSrc(value) {
  return (
    typeof value === "string" &&
    value &&
    !value.startsWith("blob:")
  );
}

function normalizeImageSrcValue(value) {
  return typeof value === "string" ? value.trim() : "";
}

function isKnownThumbnailImageUrl(value) {
  const text = normalizeImageSrcValue(value);
  if (!text) {
    return false;
  }
  return (
    text.includes("/api/v1/pipeline-thumbnails/") ||
    /\/_thumbs\/[^?#]+\.webp(?:[?#].*)?$/i.test(text) ||
    /\.thumb\.webp(?:[?#].*)?$/i.test(text)
  );
}

function isSafeReusableImageUrl(value) {
  const text = normalizeImageSrcValue(value);
  return Boolean(text && !text.startsWith("blob:") && !isKnownThumbnailImageUrl(text));
}

function originalUrlFromKnownThumbnailUrl(value) {
  const text = normalizeImageSrcValue(value);
  if (!text.includes("/api/v1/pipeline-thumbnails/")) {
    return "";
  }
  const original = text.replace("/api/v1/pipeline-thumbnails/", "/api/v1/pipeline-files/");
  if (/\/_thumbs\/[^?#]+\.webp(?:[?#].*)?$/i.test(original)) {
    return "";
  }
  return original;
}

function resolveReusableImageSrc(value, fallbackValue = "") {
  const fallback = normalizeImageSrcValue(fallbackValue);
  const text = normalizeImageSrcValue(value);
  if (!text) {
    return fallback;
  }
  if (text.startsWith("blob:")) {
    return fallback || text;
  }
  if (isKnownThumbnailImageUrl(text)) {
    const originalUrl = originalUrlFromKnownThumbnailUrl(text);
    if (fallback || originalUrl) {
      return fallback || originalUrl;
    }
    return "";
  }
  return text;
}

function normalizeAttachmentItem(item, index = 0, fallbackSrc = "") {
  const rawSrc = normalizeImageSrcValue(item?.src);
  const rawThumbnailSrc =
    normalizeImageSrcValue(item?.thumbnailSrc) ||
    normalizeImageSrcValue(item?.thumbnailUrl) ||
    normalizeImageSrcValue(item?.thumbnail_src);
  const src = resolveReusableImageSrc(rawSrc, fallbackSrc);
  const thumbnailSrc =
    rawThumbnailSrc ||
    (rawSrc.startsWith("blob:") && fallbackSrc ? rawSrc : "") ||
    (rawSrc && isKnownThumbnailImageUrl(rawSrc) ? rawSrc : "");
  return {
    name:
      typeof item?.name === "string" && item.name
        ? item.name
        : `输入图 ${index + 1}`,
    src,
    thumbnailSrc,
  };
}

function attachmentDisplaySrc(attachment) {
  return (
    normalizeImageSrcValue(attachment?.thumbnailSrc) ||
    normalizeImageSrcValue(attachment?.src)
  );
}

function sourceExtensionFromUrl(value) {
  const text = normalizeImageSrcValue(value);
  const match = text.match(/\.([a-zA-Z0-9]{2,5})(?:[?#].*)?$/);
  const rawExtension = match ? match[1].toLowerCase().replace(/[^a-z0-9]+/g, "") : "";
  return rawExtension === "jpeg" ? "jpg" : rawExtension;
}

function getInputImageUrlsFromRecord(record) {
  return Array.isArray(record?.input_image_urls)
    ? record.input_image_urls.filter((item) => typeof item === "string" && item)
    : [];
}

function filterDeletedEditConversationHistory(records = []) {
  if (!Array.isArray(records)) {
    return [];
  }
  return records.filter((record, index) => {
    if (record?.task_key !== "image-edit" && record?.task_key !== "image-agent") {
      return true;
    }
    const fallbackId = `history-${record?.run_id || index}`;
    const conversationId = conversationIdFromHistoryRecord(record, fallbackId);
    return !isDeletedEditConversationId(conversationId);
  });
}

function getMessageInputImageUrls(message) {
  const job = message?.jobId
    ? state.jobs.find((item) => item.job_id === message.jobId)
    : null;
  const jobUrls = getInputImageUrlsFromRecord(job?.record);
  if (jobUrls.length) {
    return jobUrls;
  }
  const historyRecord = state.history.find((record) => {
    if (message?.jobId && record.job_id === message.jobId) {
      return true;
    }
    return Boolean(message?.runId && record.run_id === message.runId);
  });
  return getInputImageUrlsFromRecord(historyRecord);
}

function applyMessageInputImageUrls(message, inputImageUrls) {
  const urls = Array.isArray(inputImageUrls) ? inputImageUrls : [];
  if (!message || !urls.length) {
    return false;
  }
  if (!Array.isArray(message.attachments)) {
    message.attachments = [];
  }
  let changed = false;
  const count = Math.max(
    message.attachments.length,
    urls.length,
    Number.parseInt(String(message.inputCount || 0), 10) || 0
  );
  for (let index = 0; index < count; index += 1) {
    const current = message.attachments[index] || { name: `输入图 ${index + 1}`, src: "" };
    const normalized = normalizeAttachmentItem(current, index, urls[index] || "");
    if (!message.attachments[index]) {
      message.attachments[index] = normalized;
      changed = true;
      continue;
    }
    if (current.src !== normalized.src) {
      current.src = normalized.src;
      changed = true;
    }
    if (!current.thumbnailSrc && normalized.thumbnailSrc) {
      current.thumbnailSrc = normalized.thumbnailSrc;
      changed = true;
    }
    if (!current.name && normalized.name) {
      current.name = normalized.name;
      changed = true;
    }
  }
  return changed;
}

function hydrateEditMessagesInputImageUrls() {
  if (!Array.isArray(state.editConversations) || !state.editConversations.length) {
    return false;
  }
  let changed = false;
  state.editConversations.forEach((conversation) => {
    (conversation.messages || []).forEach((message) => {
      if (applyMessageInputImageUrls(message, getMessageInputImageUrls(message))) {
        changed = true;
      }
    });
  });
  return changed;
}

function normalizeAgentImageRefs(imageRefs) {
  if (!Array.isArray(imageRefs)) {
    return [];
  }
  return imageRefs
    .map((ref) => ({
      id: String(ref?.id || "").trim(),
      type: ref?.type === "input" ? "input" : "result",
      url: isPersistableImageSrc(ref?.url) ? ref.url : "",
      thumbnailUrl: isPersistableImageSrc(ref?.thumbnailUrl) ? ref.thumbnailUrl : "",
      name: String(ref?.name || "").trim(),
      caption: String(ref?.caption || "").trim(),
      messageId: String(ref?.messageId || "").trim(),
      runId: String(ref?.runId || "").trim(),
      createdAt: String(ref?.createdAt || "").trim(),
    }))
    .filter((ref) => ref.id && (ref.url || ref.thumbnailUrl || ref.name || ref.caption));
}

function buildAgentMessageImageRefs(message, messageIndex) {
  const refs = [];
  const prefix = `m${String(messageIndex).padStart(2, "0")}`;
  const messageMeta = {
    messageId: message.id || "",
    runId: message.runId || "",
    createdAt: message.createdAt || "",
  };

  (message.attachments || []).slice(0, AGENT_CONTEXT_MAX_ATTACHMENTS).forEach((attachment, index) => {
    const url = isSafeReusableImageUrl(attachment?.src) ? attachment.src : "";
    const thumbnailUrl = isPersistableImageSrc(attachment?.thumbnailSrc)
      ? attachment.thumbnailSrc
      : url;
    refs.push({
      id: `${prefix}_input_${String(index + 1).padStart(2, "0")}`,
      type: "input",
      url,
      thumbnailUrl,
      name: attachment?.name || `input ${index + 1}`,
      caption: `message ${messageIndex} input image ${index + 1}`,
      ...messageMeta,
    });
  });

  const resultUrls = Array.isArray(message.resultUrls) ? message.resultUrls : [];
  const thumbnailUrls = Array.isArray(message.resultThumbnailUrls)
    ? message.resultThumbnailUrls
    : [];
  resultUrls.slice(0, AGENT_CONTEXT_MAX_RESULT_URLS).forEach((url, index) => {
    if (!isPersistableImageSrc(url)) {
      return;
    }
    refs.push({
      id: `${prefix}_result_${String(index + 1).padStart(2, "0")}`,
      type: "result",
      url,
      thumbnailUrl: isPersistableImageSrc(thumbnailUrls[index]) ? thumbnailUrls[index] : url,
      name: `result ${index + 1}`,
      caption: `message ${messageIndex} generated result ${index + 1}`,
      ...messageMeta,
    });
  });

  return refs;
}

function buildAgentConversationContext(conversation) {
  const messages = Array.isArray(conversation?.messages)
    ? conversation.messages.slice(-AGENT_CONTEXT_MAX_MESSAGES)
    : [];
  const normalizedMessages = messages
    .filter((message) => String(message?.prompt || "").trim())
    .map((message, index) => {
      const messageIndex = index + 1;
      const messageImageRefs = normalizeAgentImageRefs(
        message.imageRefs?.length
          ? message.imageRefs
          : buildAgentMessageImageRefs(message, messageIndex)
      ).slice(0, AGENT_CONTEXT_MAX_IMAGE_REFS);
      return {
        id: message.id || "",
        prompt: String(message.prompt || "").trim(),
        mode: message.mode || "normal",
        imageModel: message.imageModel || IMAGE_MODEL_GPT_IMAGE_2,
        outputResolution: message.outputResolution || "auto",
        outputAspectRatio: message.outputAspectRatio || "auto",
        resolvedSize: message.resolvedSize || "",
        imagesPerPrompt: message.imagesPerPrompt || 1,
        createdAt: message.createdAt || "",
        jobId: message.jobId || null,
        runId: message.runId || null,
        status: message.status || "",
        error: message.error || "",
        agentResponseText: message.agentResponseText || "",
        assistantResponse: message.agentResponseText || "",
        inputCount: message.inputCount || message.attachments?.length || 0,
        resultUrls: Array.isArray(message.resultUrls)
          ? message.resultUrls
              .filter((item) => typeof item === "string" && item)
              .slice(0, AGENT_CONTEXT_MAX_RESULT_URLS)
          : [],
        attachments: Array.isArray(message.attachments)
          ? message.attachments
              .slice(0, AGENT_CONTEXT_MAX_ATTACHMENTS)
              .map((item) => ({
                name: item?.name || "",
                src: isSafeReusableImageUrl(item?.src) ? item.src : "",
                thumbnailSrc: isPersistableImageSrc(item?.thumbnailSrc)
                  ? item.thumbnailSrc
                  : "",
              }))
              .filter((item) => item.name || item.src)
          : [],
        imageRefs: messageImageRefs,
      };
    });
  const imageRefs = normalizeAgentImageRefs(
    normalizedMessages.flatMap((message) => message.imageRefs || [])
  ).slice(-AGENT_CONTEXT_MAX_IMAGE_REFS);
  return {
    id: conversation?.id || "",
    title: conversation?.title || "",
    createdAt: conversation?.createdAt || "",
    updatedAt: conversation?.updatedAt || "",
    imageRefs,
    messages: normalizedMessages,
  };
}

function agentResponseTextFromSummary(summary) {
  const agent = summary?.agent || {};
  const plan = agent.plan || {};
  return String(
    agent.response_text ||
      plan.response_text ||
      (!plan.needs_image ? agent.design_strategy : "") ||
      ""
  ).trim();
}

function reconstructEditConversationsFromHistory(records = []) {
  if (!Array.isArray(records)) {
    return [];
  }

  const groups = new Map();
  const filteredRecords = records
    .filter((record) => record?.task_key === "image-edit" || record?.task_key === "image-agent")
    .slice(0, 120)
    .reverse();

  filteredRecords.forEach((record, index) => {
    const conversationId = conversationIdFromHistoryRecord(
      record,
      `history-${record?.run_id || index}`
    );
    if (isDeletedEditConversationId(conversationId)) {
      return;
    }
    const summary = record?.summary || {};
    const renders = Array.isArray(summary?.renders) ? summary.renders : [];
    const firstPrompt = renders.find(
      (item) => typeof item?.prompt === "string" && item.prompt.trim()
    );
    const prompt = String(record?.prompt || summary?.prompt || firstPrompt?.prompt || "").trim();
    if (!prompt) {
      return;
    }

    const createdAt =
      typeof record?.created_at === "string" && record.created_at
        ? record.created_at
        : new Date().toISOString();
    const inputCount = Number.isFinite(Number(record?.input_image_count))
      ? Math.max(0, Number.parseInt(record.input_image_count, 10))
      : Array.isArray(record?.input_images)
        ? record.input_images.length
        : Array.isArray(summary?.input_images)
          ? summary.input_images.length
          : 0;
    const inputImageUrls = getInputImageUrlsFromRecord(record);
    const conversationTitle =
      typeof record?.conversation_title === "string" && record.conversation_title.trim()
        ? record.conversation_title.trim()
        : compactText(prompt, 18) || "图片生成";
    const resultItems = renders
      .flatMap((item) => imageItemsFromRender(item, conversationTitle))
      .filter(Boolean);
    const latestRecordItems = imageItemsFromRecord(record, conversationTitle);
    const latestResultItems = resultItems.length ? resultItems : latestRecordItems;
    const agentResponseText = agentResponseTextFromSummary(summary);
    const message = {
      id: `history-msg-${record?.run_id || index}`,
      prompt,
      mode: record?.task_key === "image-agent" ? "agent" : "normal",
      imageModel:
        normalizeImageModel(record?.image_model || summary?.image_model) ||
        IMAGE_MODEL_GPT_IMAGE_2,
      outputResolution:
        String(record?.output_resolution || summary?.output_resolution || "auto").trim() ||
        "auto",
      outputAspectRatio:
        String(
          record?.output_aspect_ratio ||
            record?.aspect_ratio ||
            summary?.output_aspect_ratio ||
            summary?.aspect_ratio ||
            "auto"
        ).trim() || "auto",
      resolvedSize: String(record?.resolved_size || summary?.resolved_size || "").trim(),
      imagesPerPrompt: normalizeEditImagesPerPrompt(
        record?.task_key === "image-agent"
          ? summary?.request_count || record?.request_count || 1
          : record?.images_per_prompt || summary?.images_per_prompt || 1
      ),
      createdAt,
      jobId: null,
      runId: typeof record?.run_id === "string" ? record.run_id : null,
      status: typeof record?.status === "string" ? record.status : "completed",
      error:
        typeof record?.error === "string" && record.error
          ? record.error
          : typeof summary?.error === "string"
            ? summary.error
            : "",
      agentResponseText,
      agentSummary: summary?.agent || null,
      resultUrls: latestResultItems.map((item) => item.url),
      resultThumbnailUrls: latestResultItems.map((item) => item.thumbnailUrl),
      inputCount,
      attachments: Array.from({ length: inputCount }, (_item, attachmentIndex) => ({
        name: `输入图 ${attachmentIndex + 1}`,
        src: inputImageUrls[attachmentIndex] || "",
      })),
    };

    const existingConversation = groups.get(conversationId);
    if (existingConversation) {
      existingConversation.messages.push(message);
      existingConversation.updatedAt = createdAt;
      if (!existingConversation.title || existingConversation.title === "图片生成") {
        existingConversation.title = conversationTitle;
      }
      return;
    }

    groups.set(conversationId, {
      id: conversationId,
      title: conversationTitle,
      createdAt,
      updatedAt: createdAt,
      messages: [message],
    });
  });

  return normalizePersistedEditConversations(
    Array.from(groups.values()).sort(
      (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
    )
  );
}

function hydrateEditConversationTextRepliesFromHistory(records = []) {
  if (!Array.isArray(records) || !state.editConversations.length) {
    return false;
  }
  const responseByRunId = new Map();
  const agentSummaryByRunId = new Map();
  records.forEach((record) => {
    const runId = typeof record?.run_id === "string" ? record.run_id : "";
    if (!runId) {
      return;
    }
    const responseText = agentResponseTextFromSummary(record.summary || {});
    if (responseText) {
      responseByRunId.set(runId, responseText);
    }
    if (record?.summary?.agent) {
      agentSummaryByRunId.set(runId, record.summary.agent);
    }
  });
  if (!responseByRunId.size && !agentSummaryByRunId.size) {
    return false;
  }
  let changed = false;
  state.editConversations.forEach((conversation) => {
    (conversation.messages || []).forEach((message) => {
      if (!message.runId) {
        return;
      }
      const responseText = responseByRunId.get(message.runId);
      if (!message.agentResponseText && responseText) {
        message.agentResponseText = responseText;
        changed = true;
      }
      const agentSummary = agentSummaryByRunId.get(message.runId);
      if (!message.agentSummary && agentSummary) {
        message.agentSummary = agentSummary;
        changed = true;
      }
    });
  });
  return changed;
}

function loadEditConversations(seedConversations = null) {
  const hasServerSeed = Array.isArray(seedConversations);
  let candidate = hasServerSeed ? seedConversations : [];
  if (!hasServerSeed) {
    try {
      const raw = window.localStorage.getItem(editConversationsStorageKey());
      candidate = raw ? JSON.parse(raw) : [];
    } catch (_error) {
      candidate = [];
    }
  }

  state.editConversations = normalizePersistedEditConversations(candidate);
  if (state.editConversations.length) {
    window.localStorage.setItem(
      editConversationsStorageKey(),
      JSON.stringify(serializeEditConversations())
    );
  } else {
    window.localStorage.removeItem(editConversationsStorageKey());
  }
}

async function persistEditConversations(payload) {
  try {
    await apiFetch("/api/edit-conversations", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ conversations: payload }),
    });
  } catch (error) {
    console.warn("Failed to persist edit conversations", error);
  }
}

function persistEditConversationsImmediately({ keepalive = false } = {}) {
  const payload = state.editConversationPersistPayload ?? serializeEditConversations();
  if (state.editConversationPersistTimer) {
    window.clearTimeout(state.editConversationPersistTimer);
    state.editConversationPersistTimer = null;
  }
  state.editConversationPersistPayload = payload;

  if (keepalive) {
    const headers = {
      "Content-Type": "application/json",
      "X-Platform-Client": "user",
    };
    if (state.platformCsrfToken) {
      headers["X-CSRF-Token"] = state.platformCsrfToken;
    }
    void fetch(toApiUrl("/api/edit-conversations"), {
      method: "PUT",
      headers,
      credentials: "same-origin",
      body: JSON.stringify({ conversations: payload }),
      keepalive: true,
    });
    return;
  }

  void persistEditConversations(payload);
}

function scheduleEditConversationsPersist(payload) {
  state.editConversationPersistPayload = payload;
  if (state.editConversationPersistTimer) {
    window.clearTimeout(state.editConversationPersistTimer);
  }
  state.editConversationPersistTimer = window.setTimeout(() => {
    state.editConversationPersistTimer = null;
    persistEditConversationsImmediately();
  }, 160);
}

function saveEditConversations() {
  const serializable = serializeEditConversations();
  if (serializable.length) {
    window.localStorage.setItem(
      editConversationsStorageKey(),
      JSON.stringify(serializable)
    );
  } else {
    window.localStorage.removeItem(editConversationsStorageKey());
  }
  state.editConversationPersistPayload = serializable;
  persistEditConversationsImmediately();
}

function ensureEditConversation() {
  if (
    state.editConversationId &&
    state.editConversations.some((item) => item.id === state.editConversationId)
  ) {
    return getActiveEditConversation();
  }
  if (state.editConversations.length) {
    state.editConversationId = state.editConversations[0].id;
    return state.editConversations[0];
  }
  return createEditConversation({ persist: false, render: false });
}

function requestEditConversationScrollToBottom() {
  state.editConversationScrollRequest = "bottom";
}

function isElementAtBottom(element, threshold = 2) {
  if (!element) {
    return true;
  }
  return (
    element.scrollHeight - element.clientHeight - element.scrollTop <= threshold
  );
}

function isElementNearBottom(element, threshold = EDIT_STREAM_BOTTOM_THRESHOLD) {
  if (!element) {
    return true;
  }
  return (
    element.scrollHeight - element.clientHeight - element.scrollTop <= threshold
  );
}

function createEditConversation(options = {}) {
  const now = new Date().toISOString();
  const conversation = {
    id: `edit-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    title: "新图片生成",
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
  forgetDeletedEditConversationId(conversation.id);
  state.editConversations.unshift(conversation);
  state.editConversationId = conversation.id;
  if (options.persist !== false) {
    saveEditConversations();
  }
  if (options.render !== false) {
    requestEditConversationScrollToBottom();
    renderEditWorkspace();
  }
  return conversation;
}

function getActiveEditConversation() {
  return (
    state.editConversations.find((item) => item.id === state.editConversationId) ||
    null
  );
}

function setEditConversation(conversationId) {
  if (!state.editConversations.some((item) => item.id === conversationId)) {
    return;
  }
  state.editConversationId = conversationId;
  requestEditConversationScrollToBottom();
  renderEditWorkspace();
}

async function deleteEditConversation(conversationId) {
  const conversation = state.editConversations.find((item) => item.id === conversationId);
  if (!conversation) {
    return;
  }
  if (!window.confirm(`删除会话“${conversation.title || "图片生成"}”？`)) {
    return;
  }
  const localRunIds = new Set(
    (conversation.messages || [])
      .map((message) => message.runId)
      .filter((runId) => typeof runId === "string" && runId)
  );
  state.history.forEach((record) => {
    if (record?.conversation_id === conversationId && record.run_id) {
      localRunIds.add(record.run_id);
    }
  });
  let payload = null;
  try {
    payload = await apiFetch(`/api/edit-conversations/${encodeURIComponent(conversationId)}`, {
      method: "DELETE",
    });
  } catch (error) {
    if (error.message !== "会话不存在。") {
      window.alert(error.message);
      return;
    }
    await Promise.all(
      Array.from(localRunIds).map(async (runId) => {
        try {
          await apiFetch(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
        } catch (_deleteError) {
          // Missing records are already gone; the local state cleanup below is still correct.
        }
      })
    );
  }
  rememberDeletedEditConversationId(conversationId);
  state.editConversations = state.editConversations.filter(
    (item) => item.id !== conversationId
  );
  const deletedRunIds = new Set(
    (Array.isArray(payload?.deleted_run_ids) ? payload.deleted_run_ids : [])
      .filter((runId) => typeof runId === "string" && runId)
  );
  const deletedJobIds = new Set(
    (Array.isArray(payload?.deleted_job_ids) ? payload.deleted_job_ids : [])
      .filter((jobId) => typeof jobId === "string" && jobId)
  );
  localRunIds.forEach((runId) => deletedRunIds.add(runId));
  if (deletedRunIds.size) {
    state.history = state.history.filter((record) => !deletedRunIds.has(record.run_id));
    state.jobs = state.jobs.filter(
      (job) => !deletedRunIds.has(job.record?.run_id) && !deletedJobIds.has(job.job_id)
    );
    if (state.currentJobId && !state.jobs.some((job) => job.job_id === state.currentJobId)) {
      state.currentJobId = resolveCurrentJobId();
    }
    state.editConversations.forEach((item) => {
      item.messages = (item.messages || []).filter(
        (message) => !deletedRunIds.has(message.runId)
      );
    });
    state.editConversations = state.editConversations.filter(
      (item) => item.messages?.length
    );
  }
  if (state.editConversationId === conversationId) {
    state.editConversationId = state.editConversations[0]?.id || null;
  }
  if (!state.editConversations.length) {
    createEditConversation({ persist: false, render: false });
  }
  saveEditConversations();
  renderHistory();
  renderTaskBoard();
  renderEditWorkspace();
}

function renderEditWorkspace() {
  if (!refs.editConversationList) {
    return;
  }
  ensureEditConversation();
  renderEditConversationList();
  renderEditHistoryList();
  renderEditConversationStream();
  renderEditPreview();
}

function renderEditConversationList() {
  refs.editConversationList.replaceChildren();
  if (!state.editConversations.length) {
    const empty = document.createElement("p");
    empty.className = "muted-copy";
    empty.textContent = "暂无会话。";
    refs.editConversationList.appendChild(empty);
    return;
  }

  state.editConversations.forEach((conversation) => {
    const item = document.createElement("div");
    item.className = "edit-chat-list__item";
    item.classList.toggle("is-active", conversation.id === state.editConversationId);
    item.innerHTML = `
      <button class="edit-chat-list__body" type="button">
        <strong>${escapeHtml(conversation.title || "新图片生成")}</strong>
        <span>${escapeHtml(formatDateTime(conversation.updatedAt))}</span>
      </button>
      <button class="secondary-action secondary-action--small edit-chat-list__delete" type="button" data-delete-conversation title="删除会话">×</button>
    `;
    item.querySelector(".edit-chat-list__body")?.addEventListener("click", () => {
      setEditConversation(conversation.id);
    });
    item.querySelector("[data-delete-conversation]")?.addEventListener("click", () => {
      void deleteEditConversation(conversation.id);
    });
    refs.editConversationList.appendChild(item);
  });
}

function renderEditHistoryList() {
  if (!refs.editHistoryList) {
    return;
  }
  refs.editHistoryList.replaceChildren();
  const records = state.history
    .filter((record) => record.task_key === "image-edit" || record.task_key === "image-agent")
    .slice(0, 10);
  if (!records.length) {
    const empty = document.createElement("p");
    empty.className = "muted-copy";
    empty.textContent = "完成后的图片生成会出现在这里。";
    refs.editHistoryList.appendChild(empty);
    return;
  }

  records.forEach((record) => {
    const item = document.createElement("div");
    item.className = "edit-history-item";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "edit-history-item__body";
    const firstImage = imageItemsFromRecord(record, "历史结果")[0] || null;
    button.innerHTML = `
      <span class="edit-history-item__thumb"></span>
      <span>${escapeHtml(formatDateTime(record.created_at))}</span>
      <strong>出图 ${escapeHtml(String(record.rendered_image_count || 0))}</strong>
    `;
    if (firstImage) {
      const thumb = button.querySelector(".edit-history-item__thumb");
      const image = document.createElement("img");
      image.src = toApiUrl(firstImage.thumbnailUrl);
      image.alt = "历史结果";
      image.loading = "lazy";
      image.decoding = "async";
      makeImageDraggable(image, firstImage.url);
      thumb.appendChild(image);
    }
    button.addEventListener("click", () => {
      const previewItems = imageItemsFromRecord(record, "历史结果");
      const modalItems = modalItemsFromImageItems(previewItems);
      if (!modalItems.length) {
        return;
      }
      openImageModal(modalItems, {
        index: 0,
        runId: record.run_id || null,
        jobId: record.job_id || null,
      });
    });
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "secondary-action secondary-action--small edit-history-item__delete";
    deleteButton.title = "删除历史";
    deleteButton.setAttribute("aria-label", "删除历史");
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", () => {
      void deleteRunHistory(record);
    });
    item.append(button, deleteButton);
    refs.editHistoryList.appendChild(item);
  });
}

function renderEditConversationStream() {
  const conversation = getActiveEditConversation();
  const previousScrollTop = refs.editConversationStream.scrollTop;
  const shouldStickToBottom =
    state.editConversationScrollRequest === "bottom" ||
    isElementAtBottom(refs.editConversationStream);
  refs.editConversationTitle.textContent = conversation?.title || "图片生成";
  refs.editConversationMeta.textContent =
    "可以连续发送多次；Agent 会按需求直接回复文字或生成图片，生成结果可拖回输入框继续编辑。";
  refs.editConversationStream.replaceChildren();

  if (!conversation || !conversation.messages?.length) {
    const empty = document.createElement("div");
    empty.className = "edit-empty-state";
    empty.innerHTML = `
      <p>把图片粘贴到下方输入框，或者拖进来开始。</p>
      <span>支持多张输入图，支持从生成结果继续拖回编辑。</span>
    `;
    refs.editConversationStream.appendChild(empty);
    return;
  }

  let shouldPersist = false;
  conversation.messages.forEach((message) => {
    const job = message.jobId
      ? state.jobs.find((item) => item.job_id === message.jobId)
      : null;
    if (job) {
      if (message.status !== job.status) {
        message.status = job.status;
        shouldPersist = true;
      }
      if (job.record?.run_id && message.runId !== job.record.run_id) {
        message.runId = job.record.run_id;
        shouldPersist = true;
      } else if (job.summary?.run_id && message.runId !== job.summary.run_id) {
        message.runId = job.summary.run_id;
        shouldPersist = true;
      }
      if (job.error && message.error !== job.error) {
        message.error = job.error;
        shouldPersist = true;
      }
      const agentResponseText =
        job.summary?.agent?.response_text ||
        job.summary?.agent?.design_strategy ||
        job.record?.summary?.agent?.response_text ||
        job.record?.summary?.agent?.design_strategy ||
        "";
      if (agentResponseText && message.agentResponseText !== agentResponseText) {
        message.agentResponseText = agentResponseText;
        shouldPersist = true;
      }
      const agentSummary = job.summary?.agent || job.record?.summary?.agent || null;
      if (agentSummary && !message.agentSummary) {
        message.agentSummary = agentSummary;
        shouldPersist = true;
      }
      const jobInputUrls = getInputImageUrlsFromRecord(job.record);
      if (applyMessageInputImageUrls(message, jobInputUrls)) {
        shouldPersist = true;
      }
      if (job.task_key === "image-agent" && message.mode !== "agent") {
        message.mode = "agent";
        shouldPersist = true;
      }
      const jobImagesPerPrompt =
        job.task_key === "image-agent"
          ? job.summary?.request_count || job.metadata?.request_count
          : job.summary?.request_count || job.metadata?.images_per_prompt;
      if (jobImagesPerPrompt && message.imagesPerPrompt !== jobImagesPerPrompt) {
        message.imagesPerPrompt = jobImagesPerPrompt;
        shouldPersist = true;
      }
      const jobImageModel = job.summary?.image_model || job.metadata?.image_model;
      if (jobImageModel && message.imageModel !== jobImageModel) {
        message.imageModel = jobImageModel;
        shouldPersist = true;
      }
      const jobOutputResolution =
        job.summary?.output_resolution || job.metadata?.output_resolution;
      if (jobOutputResolution && message.outputResolution !== jobOutputResolution) {
        message.outputResolution = jobOutputResolution;
        shouldPersist = true;
      }
      const jobOutputAspectRatio =
        job.summary?.output_aspect_ratio || job.metadata?.output_aspect_ratio;
      if (jobOutputAspectRatio && message.outputAspectRatio !== jobOutputAspectRatio) {
        message.outputAspectRatio = jobOutputAspectRatio;
        shouldPersist = true;
      }
      const jobResolvedSize = job.summary?.resolved_size || job.metadata?.resolved_size;
      if (jobResolvedSize && message.resolvedSize !== jobResolvedSize) {
        message.resolvedSize = jobResolvedSize;
        shouldPersist = true;
      }
      const previewUrls = getJobPreviewUrls(job);
      if (previewUrls.length && !arraysEqual(message.resultUrls || [], previewUrls)) {
        message.resultUrls = previewUrls;
        shouldPersist = true;
      }
      const previewItems = getJobPreviewItems(job);
      const previewThumbnailUrls = previewItems.map((item) => item.thumbnailUrl);
      if (
        previewThumbnailUrls.length &&
        !arraysEqual(message.resultThumbnailUrls || [], previewThumbnailUrls)
      ) {
        message.resultThumbnailUrls = previewThumbnailUrls;
        shouldPersist = true;
      }
    }
    refs.editConversationStream.appendChild(buildEditMessage(message, job));
  });

  if (shouldPersist) {
    saveEditConversations();
  }
  const nextMaxScrollTop = Math.max(
    0,
    refs.editConversationStream.scrollHeight - refs.editConversationStream.clientHeight
  );
  refs.editConversationStream.scrollTop = shouldStickToBottom
    ? nextMaxScrollTop
    : Math.min(previousScrollTop, nextMaxScrollTop);
  state.editConversationScrollRequest = null;
}

function buildEditMessage(message, job) {
  const status = job?.status || message.status || "queued";
  const isAgent = message.mode === "agent" || job?.task_key === "image-agent";
  const summary = job?.summary || job?.record?.summary || null;
  const messageAgentSummary = message.agentSummary
    ? {
        ...(summary || {}),
        agent: message.agentSummary,
        phase: summary?.phase || message.agentSummary.phase || status,
      }
    : null;
  const displaySummary = summary || messageAgentSummary;
  const agentResponseText =
    message.agentResponseText ||
    displaySummary?.agent?.response_text ||
    (!displaySummary?.agent?.plan?.needs_image
      ? displaySummary?.agent?.design_strategy
      : "") ||
    "";
  const previewItems = job
    ? getJobPreviewItems(job)
    : (message.resultUrls || [])
        .map((url, index) =>
          normalizeImageItem(
            {
              url,
              thumbnail_url: message.resultThumbnailUrls?.[index] || url,
            },
            index,
            `图片生成 · 第 ${index + 1} 张`
          )
        )
        .filter(Boolean);
  const summaryErrors = Array.isArray(displaySummary?.errors)
    ? displaySummary.errors.filter(Boolean)
    : [];
  const partialErrorText =
    displaySummary?.status === "partial"
      ? [displaySummary.error, ...summaryErrors].filter(Boolean).join("\n\n")
      : "";
  const wrapper = document.createElement("article");
  wrapper.className = `edit-message edit-message--${status}${isAgent ? " edit-message--agent" : ""}`;

  const inputCount = message.inputCount || message.attachments?.length || 0;
  const requestCount = isAgent
    ? summary?.request_count ?? message.imagesPerPrompt ?? 0
    : message.imagesPerPrompt || 1;
  wrapper.innerHTML = `
    <div class="edit-message__request">
      <div class="edit-message__request-head">
        <p class="eyebrow">${isAgent ? "Agent 请求" : "请求"}</p>
        <div class="edit-message__meta">
          <span>${escapeHtml(
            formatOutputSelection({
              outputResolution: message.outputResolution,
              outputAspectRatio: message.outputAspectRatio,
              resolvedSize: message.resolvedSize,
            })
          )}</span>
          <span>模型 ${escapeHtml(message.imageModel || IMAGE_MODEL_GPT_IMAGE_2)}</span>
          <span>输入图 ${escapeHtml(String(inputCount))}</span>
          <span>${isAgent ? "Agent规划" : "生成次数"} ${escapeHtml(String(requestCount))}</span>
          ${
            message.jobId
              ? `<span>任务 ${escapeHtml(message.jobId)}</span>`
              : ""
          }
          <span>${escapeHtml(formatStatus(status))}</span>
          <button class="secondary-action secondary-action--small" type="button" data-rerun-message>
            重新生成
          </button>
          <button class="secondary-action secondary-action--small" type="button" data-edit-message>
            重新编辑
          </button>
          <button class="secondary-action secondary-action--small" type="button" data-copy-prompt>
            复制提示词
          </button>
        </div>
      </div>
      <div class="edit-message__prompt" title="${escapeHtml(message.prompt)}">${escapeHtml(
        message.prompt
      )}</div>
    </div>
    <div class="edit-message__attachments"></div>
    <div class="edit-message__result"></div>
  `;

  const attachmentsNode = wrapper.querySelector(".edit-message__attachments");
  (message.attachments || []).forEach((attachment, index) => {
    const displaySrc = attachmentDisplaySrc(attachment);
    if (displaySrc) {
      const image = document.createElement("img");
      image.src = toApiUrl(displaySrc);
      image.alt = attachment.name || `输入图 ${index + 1}`;
      makeImageDraggable(image, attachment.src);
      attachmentsNode.appendChild(image);
    } else {
      const chip = document.createElement("span");
      chip.textContent = attachment.name || `输入图 ${index + 1}`;
      attachmentsNode.appendChild(chip);
    }
  });

  const resultNode = wrapper.querySelector(".edit-message__result");
  if (isAgent) {
    appendImageAgentDetails(resultNode, displaySummary);
  }

  const appendGeneratingState = (compact = false) => {
    const totalCount = Math.max(
      Number.parseInt(String(message.imagesPerPrompt || 1), 10) || 1,
      previewItems.length || 1
    );
    const progressText =
      previewItems.length >= totalCount
        ? "图片已全部返回，正在整理任务结果。"
        : `已返回 ${previewItems.length} / ${totalCount}，剩余请求会继续返回到这里。`;
    const generating = document.createElement("div");
    generating.className = compact
      ? "edit-generating edit-generating--compact"
      : "edit-generating";
    generating.innerHTML = `
      <span class="task-box__spinner" aria-hidden="true"></span>
      <div>
        <strong>正在生成</strong>
        <p>${escapeHtml(progressText)}</p>
      </div>
    `;
    resultNode.appendChild(generating);
  };

  if (agentResponseText && !previewItems.length && status !== "queued" && status !== "running") {
    const answer = document.createElement("p");
    answer.className = "edit-agent-answer";
    answer.textContent = agentResponseText;
    resultNode.appendChild(answer);
  } else if (previewItems.length) {
    const grid = document.createElement("div");
    grid.className = "edit-result-grid";
    previewItems.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "edit-result-thumb";
      button.setAttribute("aria-label", `查看生成图片 ${index + 1}`);
      const image = document.createElement("img");
      image.src = toApiUrl(item.thumbnailUrl);
      image.alt = `生成图片 ${index + 1}`;
      image.loading = "lazy";
      image.decoding = "async";
      makeImageDraggable(image, item.url);
      button.addEventListener("click", () => {
      openImageModal(modalItemsFromImageItems(previewItems), {
          index,
          runId: job?.record?.run_id || job?.summary?.run_id || message.runId || null,
          jobId: job?.job_id || job?.record?.job_id || null,
        });
      });
      button.appendChild(image);
      grid.appendChild(button);
    });
    resultNode.appendChild(grid);
    if (status === "queued" || status === "running") {
      appendGeneratingState(true);
    } else if (partialErrorText || status === "failed" || status === "partial") {
      appendSelectableError(
        resultNode,
        partialErrorText ||
          job?.error ||
          message.error ||
          (status === "partial" ? "部分生成失败" : "生成失败")
      );
    }
  } else if (status === "queued" || status === "running") {
    resultNode.innerHTML = `
      <div class="edit-generating">
        <span class="task-box__spinner" aria-hidden="true"></span>
        <div>
          <strong>正在生成</strong>
          <p>请求已进入任务队列；Worker 有空位会立即执行，可以继续发送下一条。</p>
        </div>
      </div>
    `;
  } else if (status === "failed" || status === "partial") {
    appendSelectableError(resultNode, job?.error || message.error || "生成失败");
  } else if (agentResponseText) {
    const answer = document.createElement("p");
    answer.className = "edit-agent-answer";
    answer.textContent = agentResponseText;
    resultNode.appendChild(answer);
  } else {
    resultNode.innerHTML = '<p class="muted-copy">任务已完成，但没有解析到图片。</p>';
  }

  const rerunButton = wrapper.querySelector("[data-rerun-message]");
  rerunButton?.addEventListener("click", () => {
    void rerunEditMessage(message.id);
  });
  const editButton = wrapper.querySelector("[data-edit-message]");
  editButton?.addEventListener("click", () => {
    void editEditMessage(message.id);
  });
  const copyPromptButton = wrapper.querySelector("[data-copy-prompt]");
  copyPromptButton?.addEventListener("click", () => {
    void copyTextToClipboard(message.prompt, copyPromptButton);
  });

  return wrapper;
}

function appendSelectableError(container, message) {
  const errorNode = document.createElement("textarea");
  errorNode.className = "edit-error";
  errorNode.readOnly = true;
  errorNode.spellcheck = false;
  errorNode.rows = 2;
  errorNode.value = String(message || "生成失败");
  ["pointerdown", "mousedown", "click", "dblclick", "selectstart"].forEach((eventName) => {
    errorNode.addEventListener(eventName, (event) => {
      event.stopPropagation();
    });
  });
  container.appendChild(errorNode);
  requestAnimationFrame(() => {
    errorNode.style.height = "auto";
    errorNode.style.height = `${Math.min(errorNode.scrollHeight + 2, 220)}px`;
  });
}

function appendImageAgentDetails(container, summary) {
  const agent = summary?.agent || {};
  const plan = agent.plan || {};
  const prompts = Array.isArray(agent.prompts) ? agent.prompts : [];
  const needsImage = plan.needs_image !== false;
  if (!needsImage) {
    return;
  }
  if (!summary && !prompts.length && !plan.summary) {
    return;
  }

  const panel = document.createElement("section");
  panel.className = "edit-agent-panel";
  const steps = Array.isArray(plan.steps) ? plan.steps.slice(0, 4) : [];
  const promptRows = prompts.slice(0, 20);
  panel.innerHTML = `
    <div class="edit-agent-panel__head">
      <div>
        <p class="eyebrow">Agent 过程</p>
        <h4>${escapeHtml(plan.summary || (needsImage ? "正在规划图片生成任务" : "Agent 回复"))}</h4>
      </div>
      <span>${escapeHtml(summary?.phase || agent.phase || "queued")}</span>
    </div>
    ${
      plan.reference_usage
        ? `<p class="edit-agent-panel__copy">${escapeHtml(plan.reference_usage)}</p>`
        : ""
    }
    ${
      needsImage && agent.design_strategy
        ? `<p class="edit-agent-panel__copy">${escapeHtml(agent.design_strategy)}</p>`
        : ""
    }
    ${
      steps.length
        ? `<ol class="edit-agent-steps">${steps
            .map(
              (step) =>
                `<li><strong>${escapeHtml(step.title || "步骤")}</strong><span>${escapeHtml(
                  step.description || ""
                )}</span></li>`
            )
            .join("")}</ol>`
        : ""
    }
    ${
      promptRows.length
        ? `<div class="edit-agent-prompts">${promptRows
            .map(
              (item, index) => `
                <div class="edit-agent-prompt">
                  <div class="edit-agent-prompt__head">
                    <div>
                      <strong>${escapeHtml(item.title || `提示词 ${index + 1}`)}</strong>
                      ${
                        item.output_label || item.effective_image_model
                          ? `<span>${escapeHtml(
                              [item.output_label, item.effective_image_model]
                                .filter(Boolean)
                                .join(" / ")
                            )}</span>`
                          : ""
                      }
                    </div>
                    <button class="secondary-action secondary-action--small" type="button" data-copy-agent-prompt="${index}">
                      复制
                    </button>
                  </div>
                  <p>${escapeHtml(item.prompt || "")}</p>
                </div>
              `
            )
            .join("")}</div>`
        : ""
    }
  `;
  panel.querySelectorAll("[data-copy-agent-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number.parseInt(button.dataset.copyAgentPrompt || "0", 10);
      const promptText = promptRows[index]?.prompt || "";
      void copyTextToClipboard(promptText, button);
    });
  });
  container.appendChild(panel);
}

function buildTaskCard(job) {
  const record = job.record || null;
  const summary = job.summary || record?.summary || null;
  const metadata = job.metadata || {};
  const promptCount = record?.prompt_count ?? metadata.prompt_count ?? "-";
  const outputLabel =
    summary?.output_label ||
    metadata.output_label ||
    record?.output_label ||
    formatOutputSelection({
      outputResolution:
        summary?.output_resolution ||
        metadata.output_resolution ||
        record?.output_resolution,
      outputAspectRatio:
        summary?.output_aspect_ratio ||
        metadata.output_aspect_ratio ||
        record?.output_aspect_ratio ||
        summary?.aspect_ratio ||
        metadata.aspect_ratio ||
        record?.aspect_ratio,
      resolvedSize:
        summary?.resolved_size ||
        metadata.resolved_size ||
        record?.resolved_size,
    });
  const renderedCount = summary?.rendered_image_count ?? record?.rendered_image_count ?? 0;
  const inputImageCount =
    record?.input_image_count ??
    summary?.input_images?.length ??
    metadata.input_image_count ??
    null;
  const primaryMeta =
    (job.task_key === "image-edit" ||
      job.task_key === "image-agent" ||
      job.task_key === "color-match") &&
    inputImageCount !== null
      ? `输入图 ${inputImageCount}`
      : `提示词 ${promptCount}`;
  const jobId = job.job_id || record?.job_id || null;
  const previewItems = getJobPreviewItems(job);
  const modalItems = modalItemsFromImageItems(previewItems);
  const card = document.createElement("article");
  card.className = `task-box task-box--${job.status || "idle"}`;
  card.innerHTML = `
    <div class="task-box__head">
      <div class="task-box__title-wrap">
        <h4 class="task-box__title">${escapeHtml(getJobTitle(job))}</h4>
        <p class="task-box__time">${escapeHtml(formatDateTime(job.created_at))}</p>
      </div>
      <span class="task-box__badge task-box__badge--${escapeHtml(job.status || "idle")}">
        ${
          job.status === "running" || job.status === "queued"
            ? '<span class="task-box__spinner" aria-hidden="true"></span>'
            : ""
        }
        ${escapeHtml(formatStatus(job.status || "idle"))}
      </span>
    </div>
    <div class="task-box__meta">
      <span>${escapeHtml(primaryMeta)}</span>
      <span>出图 ${escapeHtml(String(renderedCount))}</span>
      <span>尺寸 ${escapeHtml(outputLabel)}</span>
    </div>
    <div class="task-box__thumbs"></div>
    <div class="task-box__actions">
      ${
        jobId
          ? '<button class="secondary-action secondary-action--small" type="button" data-download-images>下载全部图片</button>'
          : ""
      }
      ${
        jobId
          ? '<button class="secondary-action secondary-action--small" type="button" data-select-download>选择下载</button>'
          : ""
      }
      ${
        jobId || record?.download_url
          ? '<button class="secondary-action secondary-action--small" type="button" data-download-package>下载任务包</button>'
          : ""
      }
    </div>
  `;

  const thumbs = card.querySelector(".task-box__thumbs");
  const renderedColorMatchResults =
    job.task_key === "color-match" &&
    summary &&
    appendColorMatchResults(thumbs, {
      summary,
      runId: record?.run_id || null,
      jobId,
      promptScrollKey: `task:${job.job_id || record?.run_id || ""}`,
    });
  if (!renderedColorMatchResults) {
    if (!previewItems.length) {
      const placeholder = document.createElement("div");
      placeholder.className = "task-box__placeholder";
      placeholder.textContent =
        job.status === "failed" || job.status === "partial"
          ? job.error || "任务失败"
          : "结果会在生成完成后显示在这里";
      thumbs.appendChild(placeholder);
    } else {
      previewItems.slice(0, 6).forEach((item, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "task-thumb";
        button.setAttribute("aria-label", `查看任务图片 ${index + 1}`);
        button.addEventListener("click", () => {
          openImageModal(modalItems, {
            index,
            runId: record?.run_id || null,
            jobId,
          });
        });

        const image = document.createElement("img");
        image.src = toApiUrl(item.thumbnailUrl);
        image.alt = `${getJobTitle(job)} 预览`;
        image.loading = "lazy";
        image.decoding = "async";
        makeImageDraggable(image, item.url);
        button.appendChild(image);
        thumbs.appendChild(button);
      });
    }
  }

  const downloadImagesButton = card.querySelector("[data-download-images]");
  if (downloadImagesButton && jobId) {
    downloadImagesButton.addEventListener("click", () => {
      void downloadJobImages(jobId);
    });
  }

  const selectDownloadButton = card.querySelector("[data-select-download]");
  if (selectDownloadButton && jobId) {
    selectDownloadButton.addEventListener("click", () => {
      void openDownloadSelection(jobId);
    });
  }

  const downloadPackageButton = card.querySelector("[data-download-package]");
  if (downloadPackageButton) {
    downloadPackageButton.addEventListener("click", () => {
      if (jobId) {
        void downloadJobPackage(jobId);
      } else if (record?.download_url) {
        void downloadRun(record.run_id, record.download_url, "任务包");
      }
    });
  }

  return card;
}

function getJobTitle(job) {
  return (
    job.record?.task_name ||
    job.record?.project_name ||
    job.metadata?.project_name ||
    job.title ||
    "设计出图"
  );
}

function normalizeImageItem(item, index = 0, caption = "") {
  if (typeof item === "string") {
    return {
      url: item,
      thumbnailUrl: item,
      caption,
    };
  }
  if (!item || typeof item !== "object") {
    return null;
  }
  const url = String(item.url || item.src || "").trim();
  if (!url) {
    return null;
  }
  return {
    url,
    thumbnailUrl: String(item.thumbnail_url || item.thumbnailUrl || url).trim() || url,
    caption: item.caption || caption,
    index,
  };
}

function imageItemsFromUrls(urls, captionPrefix = "") {
  return Array.isArray(urls)
    ? urls
        .map((url, index) =>
          normalizeImageItem(
            url,
            index,
            captionPrefix ? `${captionPrefix} · 第 ${index + 1} 张` : ""
          )
        )
        .filter(Boolean)
    : [];
}

function imageItemsFromRender(render, captionPrefix = "") {
  if (Array.isArray(render?.image_items) && render.image_items.length) {
    return render.image_items
      .map((item, index) =>
        normalizeImageItem(
          item,
          index,
          captionPrefix ? `${captionPrefix} · 第 ${index + 1} 张` : ""
        )
      )
      .filter(Boolean);
  }
  const imageUrls = Array.isArray(render?.image_urls) ? render.image_urls : [];
  const thumbnailUrls = Array.isArray(render?.thumbnail_urls)
    ? render.thumbnail_urls
    : [];
  return imageUrls
    .map((url, index) =>
      normalizeImageItem(
        {
          url,
          thumbnail_url: thumbnailUrls[index] || url,
        },
        index,
        captionPrefix ? `${captionPrefix} · 第 ${index + 1} 张` : ""
      )
    )
    .filter(Boolean);
}

function imageItemsFromRecord(record, captionPrefix = "") {
  if (Array.isArray(record?.latest_image_items) && record.latest_image_items.length) {
    return record.latest_image_items
      .map((item, index) =>
        normalizeImageItem(
          item,
          index,
          captionPrefix ? `${captionPrefix} · 第 ${index + 1} 张` : ""
        )
      )
      .filter(Boolean);
  }
  const imageUrls = Array.isArray(record?.latest_image_urls)
    ? record.latest_image_urls
    : [];
  const thumbnailUrls = Array.isArray(record?.latest_thumbnail_urls)
    ? record.latest_thumbnail_urls
    : [];
  return imageUrls
    .map((url, index) =>
      normalizeImageItem(
        {
          url,
          thumbnail_url: thumbnailUrls[index] || url,
        },
        index,
        captionPrefix ? `${captionPrefix} · 第 ${index + 1} 张` : ""
      )
    )
    .filter(Boolean);
}

function modalItemsFromImageItems(items) {
  return items.map((item) => ({
    src: toApiUrl(item.url),
    originalSrc: toApiUrl(item.url),
    thumbnailSrc: toApiUrl(item.thumbnailUrl),
    caption: item.caption || "",
  }));
}

function getJobPreviewUrls(job) {
  const summary = job.summary || job.record?.summary;
  if (summary?.renders?.length) {
    return summary.renders
      .flatMap((item) => (Array.isArray(item.image_urls) ? item.image_urls : []))
      .filter(Boolean);
  }
  if (Array.isArray(job.record?.latest_image_urls)) {
    return job.record.latest_image_urls.filter(Boolean);
  }
  return [];
}

function getJobPreviewItems(job) {
  const title = getJobTitle(job);
  const summary = job.summary || job.record?.summary;
  if (summary?.renders?.length) {
    return summary.renders
      .flatMap((render) => imageItemsFromRender(render, title))
      .filter(Boolean);
  }
  return imageItemsFromRecord(job.record, title);
}

function getColorMatchPresentation(summary) {
  const outputs = summary?.color_match_outputs || {};
  const renders = Array.isArray(summary?.renders) ? summary.renders : [];
  const firstImageItem = (item, label = "") =>
    imageItemsFromRender(item, label).find(Boolean) || null;
  const textRoute = outputs.text_route || {};
  const imageRoute = outputs.image_route || {};
  const analysisImage = outputs.analysis_image || {};
  const desaturatedScene = outputs.desaturated_scene || {};
  const outputItem = (value, label) => {
    if (!value || typeof value !== "object") {
      return null;
    }
    if (Array.isArray(value.image_items) && value.image_items.length) {
      return normalizeImageItem(value.image_items[0], 0, label);
    }
    const url = Array.isArray(value.image_urls) ? value.image_urls.find(Boolean) : "";
    const thumbnailUrl = Array.isArray(value.thumbnail_urls)
      ? value.thumbnail_urls.find(Boolean)
      : "";
    return url
      ? normalizeImageItem({ url, thumbnail_url: thumbnailUrl || url }, 0, label)
      : null;
  };
  const desaturatedSceneItem =
    outputItem(desaturatedScene, "去色输入图") ||
    (summary?.desaturated_scene_url
      ? normalizeImageItem(
          {
            url: summary.desaturated_scene_url,
            thumbnail_url:
              summary.desaturated_scene_thumbnail_url ||
              summary.desaturated_scene_url,
          },
          0,
          "去色输入图"
        )
      : null);
  return {
    textRouteImageItem:
      outputItem(textRoute, "大模型路线结果") ||
      firstImageItem(renders[0], "大模型路线结果"),
    textRoutePrompt:
      outputs.text_route_prompt ||
      textRoute.prompt ||
      renders[0]?.prompt ||
      summary?.color_analysis_text ||
      "",
    imageRouteImageItem:
      outputItem(imageRoute, "第二路线生成结果") ||
      firstImageItem(renders[1], "第二路线生成结果"),
    analysisImageItem:
      outputItem(analysisImage, "第二路线参考色板图") ||
      firstImageItem(renders[2], "第二路线参考色板图"),
    desaturatedSceneItem,
  };
}

function preserveColorMatchPromptScroll(prompt, scrollKey) {
  if (!scrollKey) {
    return;
  }
  const savedScrollTop = state.colorMatchPromptScroll[scrollKey];
  if (Number.isFinite(savedScrollTop)) {
    window.requestAnimationFrame(() => {
      const maxScrollTop = Math.max(0, prompt.scrollHeight - prompt.clientHeight);
      prompt.scrollTop = Math.min(savedScrollTop, maxScrollTop);
    });
  }
  prompt.addEventListener(
    "scroll",
    () => {
      state.colorMatchPromptScroll[scrollKey] = prompt.scrollTop;
    },
    { passive: true }
  );
}

function appendColorMatchResults(
  container,
  { summary, runId = null, jobId = null, promptScrollKey = "" }
) {
  const presentation = getColorMatchPresentation(summary);
  const imageItems = [
    {
      key: "text-route",
      label: "大模型路线结果",
      item: presentation.textRouteImageItem,
    },
    {
      key: "image-route",
      label: "第二路线生成结果",
      item: presentation.imageRouteImageItem,
    },
    {
      key: "analysis-image",
      label: "第二路线参考色板图",
      item: presentation.analysisImageItem,
    },
    {
      key: "desaturated-scene",
      label: "去色输入图",
      item: presentation.desaturatedSceneItem,
    },
  ]
    .map((entry) => ({
      ...entry,
      item: normalizeImageItem(entry.item, 0, entry.label),
    }))
    .filter((entry) => entry.item);
  const hasPrompt = Boolean(String(presentation.textRoutePrompt || "").trim());
  if (!imageItems.length && !hasPrompt) {
    return false;
  }

  const grid = document.createElement("div");
  grid.className = "color-match-result-grid";

  const modalItems = imageItems.map((entry) => ({
    src: toApiUrl(entry.item.url),
    caption: entry.label,
  }));
  const imageIndexByKey = new Map(imageItems.map((entry, index) => [entry.key, index]));

  const appendImageTile = (entry, extraClass = "") => {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = `color-match-result-tile ${extraClass}`.trim();
    tile.setAttribute("aria-label", `查看${entry.label}`);
    tile.addEventListener("click", () => {
      openImageModal(modalItems, {
        index: imageIndexByKey.get(entry.key) || 0,
        runId,
        jobId,
      });
    });

    const label = document.createElement("span");
    label.className = "color-match-result-tile__label";
    label.textContent = entry.label;
    tile.appendChild(label);

    const image = document.createElement("img");
    image.src = toApiUrl(entry.item.thumbnailUrl);
    image.alt = entry.label;
    image.loading = "lazy";
    image.decoding = "async";
    makeImageDraggable(image, entry.item.url);
    tile.appendChild(image);
    grid.appendChild(tile);
  };

  const appendPromptTile = () => {
    const tile = document.createElement("div");
    tile.className = "color-match-prompt-tile";

    const label = document.createElement("span");
    label.className = "color-match-result-tile__label";
    label.textContent = "大模型路线提示词";
    tile.appendChild(label);

    const prompt = document.createElement("pre");
    prompt.textContent = presentation.textRoutePrompt;
    preserveColorMatchPromptScroll(prompt, promptScrollKey);
    tile.appendChild(prompt);
    grid.appendChild(tile);
  };

  const textRouteItem = imageItems.find((item) => item.key === "text-route");
  const imageRouteItem = imageItems.find((item) => item.key === "image-route");
  const analysisItem = imageItems.find((item) => item.key === "analysis-image");
  const desaturatedItem = imageItems.find((item) => item.key === "desaturated-scene");

  if (textRouteItem) {
    appendImageTile(textRouteItem);
  }
  if (hasPrompt) {
    appendPromptTile();
  }
  if (imageRouteItem) {
    appendImageTile(imageRouteItem);
  }
  if (analysisItem) {
    appendImageTile(analysisItem);
  }
  if (desaturatedItem) {
    appendImageTile(desaturatedItem, "color-match-result-tile--support");
  }

  container.appendChild(grid);
  return true;
}

function renderHistory() {
  refs.historyList.innerHTML = "";

  if (!state.history.length) {
    refs.historyList.innerHTML = `
      <p class="muted-copy">
        暂无历史任务。后续生成完成后，预览图会直接出现在这里，支持点开看大图。
      </p>
    `;
    return;
  }

  const visibleRecords = state.history.slice(0, state.historyVisibleCount);
  visibleRecords.forEach((record) => {
    const fragment = refs.historyCardTemplate.content.cloneNode(true);
    const root = fragment.querySelector(".history-card");
    const timeNode = root.querySelector(".history-card__time");
    const statusNode = root.querySelector(".history-card__status");
    const titleNode = root.querySelector(".history-card__title");
    const detailNode = root.querySelector(".history-card__detail");
    const downloadImagesButton = root.querySelector(".history-download-images");
    const selectDownloadButton = root.querySelector(".history-select-download");
    const downloadPackageButton = root.querySelector(".history-download-package");
    const deleteButton = root.querySelector(".history-delete");
    const thumbs = root.querySelector(".history-card__thumbs");
    const recordJobId = record.job_id || null;

    timeNode.textContent = formatDateTime(record.created_at);
    statusNode.textContent = formatStatus(record.status);
    titleNode.textContent = record.task_name || record.project_name || "image";
    const leadingDetail =
      record.task_key === "image-edit" ||
      record.task_key === "image-agent" ||
      record.task_key === "color-match"
        ? `输入图 ${record.input_image_count || record.input_images?.length || 0}`
        : `提示词 ${record.prompt_count || 0}`;
    const outputLabel =
      record.output_label ||
      formatOutputSelection({
        outputResolution: record.output_resolution,
        outputAspectRatio: record.output_aspect_ratio || record.aspect_ratio,
        resolvedSize: record.resolved_size,
      });
    detailNode.textContent = `${leadingDetail} / 出图 ${
      record.rendered_image_count || 0
    } / 尺寸 ${outputLabel}`;

    downloadImagesButton.hidden = !recordJobId;
    selectDownloadButton.hidden = !recordJobId;
    downloadPackageButton.hidden = !recordJobId && !record.download_url;
    downloadImagesButton.addEventListener("click", () => {
      if (recordJobId) {
        void downloadJobImages(recordJobId);
      }
    });
    selectDownloadButton.addEventListener("click", () => {
      if (recordJobId) {
        void openDownloadSelection(recordJobId);
      }
    });
    downloadPackageButton.addEventListener("click", () => {
      if (recordJobId) {
        void downloadJobPackage(recordJobId);
      } else if (record.download_url) {
        void downloadRun(record.run_id, record.download_url);
      }
    });
    deleteButton.addEventListener("click", () => {
      void deleteRunHistory(record);
    });

    if (
      record.task_key === "color-match" &&
      record.summary &&
      appendColorMatchResults(thumbs, {
        summary: record.summary,
        runId: record.run_id || null,
        jobId: recordJobId,
        promptScrollKey: `history:${record.run_id || ""}`,
      })
    ) {
      refs.historyList.appendChild(fragment);
      return;
    }

    const previewItems = imageItemsFromRecord(
      record,
      record.project_name || "image"
    );
    const modalItems = modalItemsFromImageItems(previewItems);
    const visibleItems = previewItems.slice(0, 8);
    if (!visibleItems.length) {
      const empty = document.createElement("p");
      empty.className = "muted-copy";
      empty.textContent = "该任务暂无可预览图片。";
      thumbs.appendChild(empty);
    } else {
      visibleItems.forEach((item, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "history-thumb";
        button.setAttribute("aria-label", `查看历史图片 ${index + 1}`);
        button.addEventListener("click", () => {
          openImageModal(modalItems, {
            index,
            runId: record.run_id || null,
            jobId: recordJobId,
          });
        });

        const image = document.createElement("img");
        image.src = toApiUrl(item.thumbnailUrl);
        image.alt = `${record.project_name || "image"} 预览`;
        image.loading = "lazy";
        image.decoding = "async";
        makeImageDraggable(image, item.url);
        button.appendChild(image);
        thumbs.appendChild(button);
      });
    }

    refs.historyList.appendChild(fragment);
  });

  if (state.history.length > visibleRecords.length) {
    const moreButton = document.createElement("button");
    moreButton.type = "button";
    moreButton.className = "secondary-action history-load-more";
    moreButton.textContent = `显示更多历史（${state.history.length - visibleRecords.length}）`;
    moreButton.addEventListener("click", () => {
      state.historyVisibleCount += 30;
      renderHistory();
    });
    refs.historyList.appendChild(moreButton);
  }
}

function applySettingsToForm() {
  if (!state.settings) {
    return;
  }

  state.isHydratingSettings = true;
  try {
    const outputResolutions = state.settings.available_output_resolutions || [];
    const outputAspectRatios = state.settings.available_output_aspect_ratios || [];
    const imageModels = state.settings.available_image_models || [];
    const llmEndpointTypes = state.settings.available_llm_endpoint_types || [];
    const maxSharedConcurrency = Number(state.settings.max_shared_concurrency || 0) || 1;
    const imageModelSelect = refs.settingsForm.elements.namedItem("image_model");
    const imageAgentEndpointSelect =
      refs.settingsForm.elements.namedItem("image_agent_endpoint_type");
    const settingsResolutionSelect =
      refs.settingsForm.elements.namedItem("default_output_resolution");
    const settingsAspectSelect =
      refs.settingsForm.elements.namedItem("default_output_aspect_ratio");
    const taskResolutionSelect =
      refs.replicateForm.elements.namedItem("output_resolution");
    const taskAspectSelect =
      refs.replicateForm.elements.namedItem("output_aspect_ratio");
    const replicate2ResolutionSelect =
      refs.replicate2Form.elements.namedItem("output_resolution");
    const replicate2AspectSelect =
      refs.replicate2Form.elements.namedItem("output_aspect_ratio");
    const editImageModelSelect =
      refs.imageEditForm.elements.namedItem("image_model");
    const editResolutionSelect =
      refs.imageEditForm.elements.namedItem("output_resolution");
    const editAspectSelect =
      refs.imageEditForm.elements.namedItem("output_aspect_ratio");
    const colorResolutionSelect =
      refs.colorMatchForm.elements.namedItem("output_resolution");
    const colorAspectSelect =
      refs.colorMatchForm.elements.namedItem("output_aspect_ratio");
    const concurrencyInput =
      refs.settingsForm.elements.namedItem("default_concurrency");

    if (imageModelSelect?.tagName === "SELECT") {
      imageModelSelect.innerHTML = buildOptions(
        imageModels,
        state.settings.image_model
      );
    }
    if (imageAgentEndpointSelect?.tagName === "SELECT") {
      imageAgentEndpointSelect.innerHTML = buildOptions(
        llmEndpointTypes,
        state.settings.image_agent_endpoint_type
      );
    }
    settingsResolutionSelect.innerHTML = buildOptions(
      outputResolutions,
      state.settings.default_output_resolution
    );
    settingsAspectSelect.innerHTML = buildOptions(
      outputAspectRatios,
      state.settings.default_output_aspect_ratio
    );
    taskResolutionSelect.innerHTML = buildOptions(
      outputResolutions,
      state.settings.default_output_resolution
    );
    taskAspectSelect.innerHTML = buildOptions(
      outputAspectRatios,
      state.settings.default_output_aspect_ratio
    );
    replicate2ResolutionSelect.innerHTML = buildOptions(
      outputResolutions,
      state.settings.default_output_resolution
    );
    replicate2AspectSelect.innerHTML = buildOptions(
      outputAspectRatios,
      state.settings.default_output_aspect_ratio
    );
    editImageModelSelect.innerHTML = buildOptions(
      imageModels,
      state.settings.image_model
    );
    editResolutionSelect.innerHTML = buildOptions(
      outputResolutions,
      state.settings.default_output_resolution
    );
    editAspectSelect.innerHTML = buildOptions(
      outputAspectRatios,
      state.settings.default_output_aspect_ratio
    );
    colorResolutionSelect.innerHTML = buildOptions(
      outputResolutions,
      state.settings.default_output_resolution
    );
    colorAspectSelect.innerHTML = buildOptions(
      outputAspectRatios,
      state.settings.default_output_aspect_ratio
    );
    concurrencyInput.min = "1";
    concurrencyInput.max = String(maxSharedConcurrency);

    Array.from(refs.settingsForm.elements).forEach((element) => {
      if (!element.name || !(element.name in state.settings)) {
        return;
      }
      if (element.type === "checkbox") {
        element.checked = Boolean(state.settings[element.name]);
        return;
      }
      element.value = state.settings[element.name];
      if (isSecretSettingField(element)) {
        element.dataset.originalSecretValue = String(element.value || "");
      }
    });
    renderSecretFieldStatuses();
  } finally {
    state.isHydratingSettings = false;
  }
}

function getSecretSettingKeys() {
  return Array.isArray(state.settings?._secret_keys) ? state.settings._secret_keys : [];
}

function isSecretSettingField(element) {
  return Boolean(element?.name && getSecretSettingKeys().includes(element.name));
}

function renderSecretFieldStatuses() {
  if (!refs.settingsForm) {
    return;
  }
  getSecretSettingKeys().forEach((key) => {
    const input = refs.settingsForm.elements.namedItem(key);
    if (input) {
      updateSecretFieldStatus(input);
    }
  });
}

function updateSecretFieldStatus(input) {
  const field = input.closest(".field");
  if (!field) {
    return;
  }
  let statusNode = field.querySelector(".secret-save-state");
  if (!statusNode) {
    statusNode = document.createElement("p");
    statusNode.className = "secret-save-state";
    statusNode.dataset.secretStatusFor = input.name;
    field.appendChild(statusNode);
  }

  const status = state.settings?._secret_status?.[input.name] || {};
  const currentValue = String(input.value || "").trim();
  const originalValue = String(input.dataset.originalSecretValue || "").trim();
  const hasDraftValue = Boolean(currentValue);
  statusNode.classList.remove(
    "secret-save-state--saved",
    "secret-save-state--pending",
    "secret-save-state--empty"
  );
  if (status.saved && currentValue && currentValue === originalValue) {
    statusNode.textContent = "已保存，可点击小眼睛查看";
    statusNode.classList.add("secret-save-state--saved");
    input.placeholder = "已保存";
    return;
  }
  if (hasDraftValue) {
    statusNode.textContent = status.saved ? "待保存：会覆盖已保存密钥" : "待保存：将保存为你的密钥";
    statusNode.classList.add("secret-save-state--pending");
    return;
  }
  if (status.saved) {
    statusNode.textContent = "已保存，重新输入会覆盖";
    statusNode.classList.add("secret-save-state--saved");
    input.placeholder = "已保存，重新输入会覆盖";
    return;
  }
  statusNode.textContent = "未保存，请填写后自动保存";
  statusNode.classList.add("secret-save-state--empty");
  input.placeholder = "请输入你的 API Key";
}

function applyTaskDefaults(force = false) {
  if (!state.settings || (!force && state.taskDefaultsApplied)) {
    return;
  }

  const promptInput = refs.replicateForm.elements.namedItem("prompt_count");
  const resolutionSelect = refs.replicateForm.elements.namedItem("output_resolution");
  const aspectSelect = refs.replicateForm.elements.namedItem("output_aspect_ratio");
  const replicate2PromptInput =
    refs.replicate2Form.elements.namedItem("prompt_count");
  const replicate2ResolutionSelect =
    refs.replicate2Form.elements.namedItem("output_resolution");
  const replicate2AspectSelect =
    refs.replicate2Form.elements.namedItem("output_aspect_ratio");
  const editImageModelSelect =
    refs.imageEditForm.elements.namedItem("image_model");
  const editResolutionSelect =
    refs.imageEditForm.elements.namedItem("output_resolution");
  const editAspectSelect =
    refs.imageEditForm.elements.namedItem("output_aspect_ratio");
  const editImagesPerPromptInput =
    refs.imageEditForm.elements.namedItem("images_per_prompt");
  const colorResolutionSelect =
    refs.colorMatchForm.elements.namedItem("output_resolution");
  const colorAspectSelect =
    refs.colorMatchForm.elements.namedItem("output_aspect_ratio");
  state.defaultUserPrompt = String(state.settings.default_user_prompt || "").trim();
  state.defaultStyleReplicate2UserPrompt = String(
    state.settings.style_replicate2_user_prompt || ""
  ).trim();
  if (force || !promptInput.value) {
    promptInput.value = state.settings.default_prompt_count ?? 4;
  }
  if (force || !replicate2PromptInput.value) {
    replicate2PromptInput.value = state.settings.default_prompt_count ?? 4;
  }
  if (force || !resolutionSelect.value) {
    resolutionSelect.value = state.settings.default_output_resolution ?? "auto";
  }
  if (force || !aspectSelect.value) {
    aspectSelect.value = state.settings.default_output_aspect_ratio ?? "auto";
  }
  if (force || !replicate2ResolutionSelect.value) {
    replicate2ResolutionSelect.value = state.settings.default_output_resolution ?? "auto";
  }
  if (force || !replicate2AspectSelect.value) {
    replicate2AspectSelect.value = state.settings.default_output_aspect_ratio ?? "auto";
  }
  if (force || !editImageModelSelect.value) {
    editImageModelSelect.value = state.settings.image_model || IMAGE_MODEL_GPT_IMAGE_2;
  }
  if (force || !editResolutionSelect.value) {
    editResolutionSelect.value = state.settings.default_output_resolution ?? "auto";
  }
  if (force || !editAspectSelect.value) {
    editAspectSelect.value = state.settings.default_output_aspect_ratio ?? "auto";
  }
  if (force || !editImagesPerPromptInput.value) {
    editImagesPerPromptInput.value = state.settings.default_images_per_prompt ?? 1;
  }
  if (force || !colorResolutionSelect.value) {
    colorResolutionSelect.value = state.settings.default_output_resolution ?? "auto";
  }
  if (force || !colorAspectSelect.value) {
    colorAspectSelect.value = state.settings.default_output_aspect_ratio ?? "auto";
  }
  if (
    refs.userPromptInput &&
    state.defaultUserPrompt &&
    (!state.userPromptInitialized ||
      refs.userPromptInput.classList.contains("is-default-prompt"))
  ) {
    refs.userPromptInput.value = state.defaultUserPrompt;
    refs.userPromptInput.classList.add("is-default-prompt");
    state.userPromptPristine = true;
  }
  if (
    refs.replicate2UserPromptInput &&
    state.defaultStyleReplicate2UserPrompt &&
    (force || !refs.replicate2UserPromptInput.value)
  ) {
    refs.replicate2UserPromptInput.value = state.defaultStyleReplicate2UserPrompt;
  }
  state.userPromptInitialized = true;
  state.taskDefaultsApplied = true;
}

function handleUserPromptFocus() {
  if (!state.userPromptPristine) {
    return;
  }
  if (refs.userPromptInput.value !== state.defaultUserPrompt) {
    return;
  }
  refs.userPromptInput.value = "";
  refs.userPromptInput.classList.remove("is-default-prompt");
  state.userPromptPristine = false;
}

function handleUserPromptInput() {
  refs.userPromptInput.classList.remove("is-default-prompt");
  state.userPromptPristine = false;
}

function resolveUserPromptValue(formData) {
  const rawValue = String(formData.get("user_prompt") || "").trim();
  return rawValue || state.defaultUserPrompt || "";
}

function resolveStyleReplicate2UserPromptValue(formData) {
  const rawValue = String(formData.get("user_prompt") || "").trim();
  return rawValue || state.defaultStyleReplicate2UserPrompt || "";
}

function onSettingsChanged(event) {
  if (state.isHydratingSettings) {
    return;
  }

  if (isSecretSettingField(event?.target)) {
    updateSecretFieldStatus(event.target);
  }

  refs.autosaveBadgeInline.textContent = "自动保存中...";
  window.clearTimeout(state.autosaveTimer);
  state.autosaveTimer = window.setTimeout(() => {
    void saveSettings();
  }, 320);
}

async function saveSettings() {
  if (refs.saveSettingsButton) {
    refs.saveSettingsButton.disabled = true;
    refs.saveSettingsButton.textContent = "保存中...";
  }
  try {
    const payload = collectSettingsPayload();
    state.settings = await apiFetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    applySettingsToForm();
    applyTaskDefaults(true);
    await refreshSharedPool();
    renderTopStatus();
    renderTaskMetrics();
    refs.autosaveBadgeInline.textContent = "已同步";
    if (refs.saveSettingsButton) {
      refs.saveSettingsButton.textContent = "已保存";
      window.setTimeout(() => {
        if (refs.saveSettingsButton) {
          refs.saveSettingsButton.textContent = "立即保存";
        }
      }, 1200);
    }
  } catch (error) {
    refs.autosaveBadgeInline.textContent = `保存失败: ${error.message}`;
    if (refs.saveSettingsButton) {
      refs.saveSettingsButton.textContent = "保存失败";
    }
  } finally {
    if (refs.saveSettingsButton) {
      refs.saveSettingsButton.disabled = false;
    }
  }
}

function collectSettingsPayload() {
  const payload = {};
  Array.from(refs.settingsForm.elements).forEach((element) => {
    if (!element.name) {
      return;
    }
    if (API_BASE_SETTING_KEYS.has(element.name) && !isValidApiBaseValue(element.value)) {
      element.value = state.settings?.[element.name] || "";
      return;
    }
    if (
      element.name === "image_model_gpt_image_2_1k" ||
      element.name === "image_model_gpt_image_2"
    ) {
      element.value = normalizeConfiguredImageModelId(element.value);
    }
    payload[element.name] =
      element.type === "checkbox" ? element.checked : element.value;
  });
  return payload;
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

function normalizeConfiguredImageModelId(value) {
  const text = String(value || "").trim();
  return text === "gpt-image-2-1K" ? GPT_IMAGE_2_1K_MODEL_ID : text;
}

function getLimit(key, fallback) {
  const value = Number(state.settings?.limits?.[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

async function submitReplicateTask() {
  const submitButton = refs.replicateForm.querySelector('[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = "提交中...";

  try {
    const formData = new FormData(refs.replicateForm);
    formData.set("user_prompt", resolveUserPromptValue(formData));
    appendReferenceFilesToFormData(formData);
    validateReplicateForm(formData);
    const payload = await apiFetch("/api/tasks/style-replicate", {
      method: "POST",
      body: formData,
    });
    state.currentJobId = payload.job_id;
    markJobQueuedForSound(payload.job_id);
    await refreshSharedPool();
    if (state.isLogModalOpen) {
      state.logTargetJobId = payload.job_id;
    }
    refs.taskJobStatusValue.textContent = "排队中";
    await refreshCurrentJob();
    await refreshHistory();
    await refreshLogs();
  } catch (error) {
    window.alert(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "开始生成";
  }
}

async function submitReplicate2Task() {
  const submitButton = refs.replicate2Form.querySelector('[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = "提交中...";

  try {
    const formData = new FormData(refs.replicate2Form);
    formData.set("user_prompt", resolveStyleReplicate2UserPromptValue(formData));
    appendStyleReplicate2ReferenceFilesToFormData(formData);
    validateStyleReplicate2Form(formData);
    const payload = await apiFetch("/api/tasks/style-replicate-v2", {
      method: "POST",
      body: formData,
    });
    state.currentJobId = payload.job_id;
    markJobQueuedForSound(payload.job_id);
    await refreshSharedPool();
    if (state.isLogModalOpen) {
      state.logTargetJobId = payload.job_id;
    }
    if (refs.replicate2TaskJobStatusValue) {
      refs.replicate2TaskJobStatusValue.textContent = "排队中";
    }
    await refreshCurrentJob();
    await refreshHistory();
    await refreshLogs();
  } catch (error) {
    window.alert(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "开始生成";
  }
}

async function submitColorMatchTask() {
  const submitButton = refs.colorMatchForm.querySelector('[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = "提交中...";

  try {
    const formData = new FormData(refs.colorMatchForm);
    validateColorMatchForm(formData);
    const payload = await apiFetch("/api/tasks/color-match", {
      method: "POST",
      body: formData,
    });
    state.currentJobId = payload.job_id;
    markJobQueuedForSound(payload.job_id);
    await refreshSharedPool();
    if (state.isLogModalOpen) {
      state.logTargetJobId = payload.job_id;
    }
    if (refs.colorTaskJobStatusValue) {
      refs.colorTaskJobStatusValue.textContent = "排队中";
    }
    await refreshCurrentJob();
    await refreshHistory();
    await refreshLogs();
  } catch (error) {
    window.alert(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "开始追色";
  }
}

async function submitImageEditTask() {
  const submitButton = refs.imageEditForm.querySelector('[type="submit"]');
  const conversation = ensureEditConversation();
  const prompt = refs.editPromptInput.value.trim();
  const imageModel =
    refs.imageEditForm.elements.namedItem("image_model").value ||
    state.settings?.image_model ||
    IMAGE_MODEL_GPT_IMAGE_2;
  const outputResolution =
    refs.imageEditForm.elements.namedItem("output_resolution").value;
  const outputAspectRatio =
    refs.imageEditForm.elements.namedItem("output_aspect_ratio").value;
  const mode = state.editGenerationMode === "agent" ? "agent" : "normal";
  const isAgent = mode === "agent";
  const imagesPerPrompt = normalizeEditImagesPerPrompt(
    refs.imageEditForm.elements.namedItem("images_per_prompt").value
  );
  const attachments = state.editInputAttachments.map((attachment) => ({
    file: attachment.file,
    name: attachment.name,
  }));

  await submitImageEditRequest({
    conversation,
    prompt,
    imageModel,
    outputResolution: isAgent ? "agent" : outputResolution,
    outputAspectRatio: isAgent ? "agent" : outputAspectRatio,
    imagesPerPrompt: isAgent ? 1 : imagesPerPrompt,
    attachments,
    mode,
    submitButton,
    clearComposerOnSuccess: true,
  });
}

async function submitImageEditRequest({
  conversation,
  prompt,
  imageModel,
  outputResolution,
  outputAspectRatio,
  imagesPerPrompt,
  attachments,
  mode = "normal",
  submitButton = null,
  clearComposerOnSuccess = false,
  sourceMessageId = "",
}) {
  let message = null;
  let didClearComposer = false;
  const isAgent = mode === "agent";
  const messageOutputResolution = isAgent ? "agent" : outputResolution;
  const messageOutputAspectRatio = isAgent ? "agent" : outputAspectRatio;
  const messageImagesPerPrompt = isAgent ? 1 : imagesPerPrompt;

  try {
    validateImageEditRequest(
      prompt,
      attachments,
      messageImagesPerPrompt,
      imageModel,
      messageOutputResolution,
      messageOutputAspectRatio,
      { isAgent }
    );
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "提交中...";
    }
    const agentConversationContext = isAgent
      ? buildAgentConversationContext(conversation)
      : null;

    message = {
      id: `msg-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      prompt,
      mode: isAgent ? "agent" : "normal",
      imageModel,
      outputResolution: messageOutputResolution,
      outputAspectRatio: messageOutputAspectRatio,
      imagesPerPrompt: messageImagesPerPrompt,
      createdAt: new Date().toISOString(),
      status: "queued",
      sourceMessageId,
      inputCount: attachments.length,
      attachments: attachments.map((attachment) => ({
        name: attachment.name,
        src: URL.createObjectURL(attachment.file),
        thumbnailSrc: "",
      })),
    };
    conversation.messages.push(message);
    requestEditConversationScrollToBottom();
    conversation.updatedAt = message.createdAt;
    if (!conversation.title || conversation.title === "新图片生成") {
      conversation.title = compactText(prompt, 18) || "图片生成";
    }
    renderEditWorkspace();
    saveEditConversations();

    const conversationTitle = conversation.title || "图片生成";
    if (clearComposerOnSuccess) {
      clearEditComposer({ render: false });
      didClearComposer = true;
      renderEditPreview();
    }

    const formData = new FormData();
    formData.set("prompt", prompt);
    formData.set("image_model", imageModel);
    if (!isAgent) {
      formData.set("output_resolution", messageOutputResolution);
      formData.set("output_aspect_ratio", messageOutputAspectRatio);
      formData.set("images_per_prompt", String(messageImagesPerPrompt));
    }
    formData.set("conversation_id", conversation.id);
    formData.set("conversation_title", conversationTitle);
    if (isAgent && agentConversationContext) {
      formData.set("conversation_context", JSON.stringify(agentConversationContext));
    }
    attachments.forEach((attachment) => {
      formData.append("input_files", attachment.file, attachment.name);
    });
    const payload = await apiFetch(isAgent ? "/api/tasks/image-agent" : "/api/tasks/image-edit", {
      method: "POST",
      body: formData,
    });
    state.currentJobId = payload.job_id;
    markJobQueuedForSound(payload.job_id);
    await refreshSharedPool();
    message.jobId = payload.job_id;
    message.status = payload.status || "queued";
    if (payload.summary?.agent?.response_text) {
      message.agentResponseText = payload.summary.agent.response_text;
    }
    if (payload.summary?.agent) {
      message.agentSummary = payload.summary.agent;
    }
    saveEditConversations();
    if (clearComposerOnSuccess && !didClearComposer) {
      clearEditComposer({ render: false });
    }
    renderEditWorkspace();
    if (state.isLogModalOpen) {
      state.logTargetJobId = payload.job_id;
    }
    if (refs.editTaskJobStatusValue) {
      refs.editTaskJobStatusValue.textContent = "排队中";
    }
    await refreshCurrentJob();
    await refreshHistory();
    await refreshLogs();
  } catch (error) {
    if (message) {
      message.status = "failed";
      message.error = error.message;
      saveEditConversations();
      renderEditWorkspace();
    }
    window.alert(error.message);
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = "发送";
    }
  }
}

function parseReferenceUrls(value) {
  return String(value || "")
    .split(/[\s,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function getReferenceConfig(kind) {
  const isStyle = kind === "style";
  if (kind === "style2") {
    const maxCount = getLimit("style_replicate2_reference_max", 10);
    return {
      fileInput: refs.style2FileInput,
      urlInput: refs.style2UrlInput,
      previewSurface: refs.style2PreviewImage,
      previewMeta: refs.style2PreviewMeta,
      fileNameNode: refs.style2FileName,
      clearButton: refs.style2ClearReferenceButton,
      label: "参考图",
      emptyTitle: "未选择参考图",
      emptyDetail: `可上传本地图片，或填写图片链接，合计 1~${maxCount} 张。`,
      previewTitle: "参考图预览",
      maxCount,
    };
  }
  const maxCount = isStyle
    ? getLimit("style_reference_max", 5)
    : getLimit("product_reference_max", 5);
  return {
    fileInput: isStyle ? refs.styleFileInput : refs.productFileInput,
    urlInput: isStyle ? refs.styleUrlInput : refs.productUrlInput,
    previewSurface: isStyle ? refs.stylePreviewImage : refs.productPreviewImage,
    previewMeta: isStyle ? refs.stylePreviewMeta : refs.productPreviewMeta,
    fileNameNode: isStyle ? refs.styleFileName : refs.productFileName,
    clearButton: isStyle
      ? refs.styleClearReferenceButton
      : refs.productClearReferenceButton,
    label: isStyle ? "风格图" : "产品图",
    emptyTitle: isStyle ? "未选择风格图" : "未选择产品图",
    emptyDetail: isStyle
      ? `可上传本地图片，或填写图片链接，合计 1~${maxCount} 张。`
      : `生图请求实际会使用这里的产品图，合计 1~${maxCount} 张。`,
    previewTitle: isStyle ? "风格图预览" : "产品图预览",
    maxCount,
  };
}

function referenceFileKey(file) {
  return [file.name, file.size, file.lastModified, file.type].join("|");
}

function addReferenceFiles(kind, files) {
  const config = getReferenceConfig(kind);
  const currentFiles = state.replicateReferenceFiles[kind];
  const existingKeys = new Set(currentFiles.map(referenceFileKey));
  const urlCount = parseReferenceUrls(config.urlInput.value).length;
  const maxCount = config.maxCount || 5;
  let skippedByLimit = 0;

  files
    .filter((file) => file instanceof File && file.name)
    .forEach((file) => {
      const key = referenceFileKey(file);
      if (existingKeys.has(key)) {
        return;
      }
      if (currentFiles.length + urlCount >= maxCount) {
        skippedByLimit += 1;
        return;
      }
      currentFiles.push(file);
      existingKeys.add(key);
    });

  renderReferencePreview(kind);
  if (skippedByLimit) {
    window.alert(`${config.label}最多支持 ${maxCount} 张。`);
  }
}

function removeReferenceFile(kind, index) {
  state.replicateReferenceFiles[kind].splice(index, 1);
  renderReferencePreview(kind);
}

function removeReferenceUrl(kind, index) {
  const config = getReferenceConfig(kind);
  const urls = parseReferenceUrls(config.urlInput.value);
  urls.splice(index, 1);
  config.urlInput.value = urls.join("\n");
  renderReferencePreview(kind);
}

function clearReferenceGroup(kind) {
  const config = getReferenceConfig(kind);
  state.replicateReferenceFiles[kind] = [];
  config.fileInput.value = "";
  config.urlInput.value = "";
  renderReferencePreview(kind);
}

function appendReferenceFilesToFormData(formData) {
  formData.delete("style_file");
  formData.delete("product_file");
  state.replicateReferenceFiles.style.forEach((file) => {
    formData.append("style_file", file, file.name);
  });
  state.replicateReferenceFiles.product.forEach((file) => {
    formData.append("product_file", file, file.name);
  });
}

function appendStyleReplicate2ReferenceFilesToFormData(formData) {
  formData.delete("reference_file");
  state.replicateReferenceFiles.style2.forEach((file) => {
    formData.append("reference_file", file, file.name);
  });
}

function getReferenceFiles(formData, fieldName) {
  return formData
    .getAll(fieldName)
    .filter((item) => item instanceof File && item.name);
}

function validateReferenceGroup({ label, files, urls, maxCount = 5 }) {
  const total = files.length + urls.length;
  if (total <= 0) {
    throw new Error(`请上传或填写 1 至 ${maxCount} 张${label}。`);
  }
  if (total > maxCount) {
    throw new Error(`${label}最多支持 ${maxCount} 张。`);
  }
}

function validateReplicateForm(formData) {
  validateReferenceGroup({
    label: "风格图",
    files: getReferenceFiles(formData, "style_file"),
    urls: parseReferenceUrls(formData.get("style_url")),
  });
  validateReferenceGroup({
    label: "产品图",
    files: getReferenceFiles(formData, "product_file"),
    urls: parseReferenceUrls(formData.get("product_url")),
  });
}

function validateStyleReplicate2Form(formData) {
  validateReferenceGroup({
    label: "参考图",
    files: getReferenceFiles(formData, "reference_file"),
    urls: parseReferenceUrls(formData.get("reference_url")),
    maxCount: getLimit("style_replicate2_reference_max", 10),
  });
}

function validateColorMatchForm(formData) {
  const toneFile = formData.get("tone_file");
  const sceneFile = formData.get("scene_file");
  if (!(toneFile instanceof File && toneFile.name)) {
    throw new Error("请上传色调参考图。");
  }
  if (!(sceneFile instanceof File && sceneFile.name)) {
    throw new Error("请上传静物场景图。");
  }
}

function normalizeImageModel(value) {
  let normalized = String(value || "").trim().toLowerCase();
  normalized = LEGACY_IMAGE_MODEL_ALIASES[normalized] || normalized;
  if (
    normalized === IMAGE_MODEL_GPT_IMAGE_2 ||
    normalized === IMAGE_MODEL_NANO_BANANA_2 ||
    normalized === IMAGE_MODEL_NANO_BANANA_PRO
  ) {
    return normalized;
  }
  return "";
}

function isNanoBananaModel(value) {
  const model = normalizeImageModel(value);
  return model === IMAGE_MODEL_NANO_BANANA_2 || model === IMAGE_MODEL_NANO_BANANA_PRO;
}

function supportsNanoBananaAspectRatio(model, aspectRatio) {
  if (NANO_BANANA_COMMON_ASPECT_RATIOS.has(aspectRatio)) {
    return true;
  }
  return (
    normalizeImageModel(model) === IMAGE_MODEL_NANO_BANANA_2 &&
    NANO_BANANA_2_ONLY_ASPECT_RATIOS.has(aspectRatio)
  );
}

function validateImageEditRequest(
  prompt,
  attachments,
  imagesPerPrompt,
  imageModel,
  outputResolution,
  outputAspectRatio,
  { isAgent = false } = {}
) {
  if (!prompt) {
    throw new Error("请填写图片生成提示词。");
  }
  const maxInputImages = getLimit("image_edit_input_max", 16);
  if (attachments.length > maxInputImages) {
    throw new Error(`图片生成最多支持 ${maxInputImages} 张输入图。`);
  }
  if (!isAgent && (!Number.isInteger(imagesPerPrompt) || imagesPerPrompt <= 0)) {
    throw new Error("生成次数必须大于 0。");
  }
  const normalizedModel = normalizeImageModel(imageModel);
  if (!normalizedModel) {
    throw new Error("请选择生图模型。");
  }
  if (!isAgent && isNanoBananaModel(normalizedModel)) {
    if (!outputResolution || outputResolution === "auto") {
      throw new Error(`${normalizedModel} 不支持 auto 分辨率，请选择 1K、2K 或 4K。`);
    }
    if (!outputAspectRatio || outputAspectRatio === "auto") {
      throw new Error(`${normalizedModel} 不支持 auto 比例，请选择具体比例。`);
    }
    if (!supportsNanoBananaAspectRatio(normalizedModel, outputAspectRatio)) {
      throw new Error(`${normalizedModel} 不支持比例 ${outputAspectRatio}，请按比例下拉框标注选择。`);
    }
  }
}

function normalizeEditImagesPerPrompt(value) {
  const parsed = Number.parseInt(String(value || "").trim(), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

function renderReferencePreview(kind) {
  const config = getReferenceConfig(kind);
  const selectedFiles = state.replicateReferenceFiles[kind];
  const inputUrls = parseReferenceUrls(config.urlInput.value);
  const totalCount = selectedFiles.length + inputUrls.length;
  const maxCount = config.maxCount || 5;

  revokePreviewUrl(kind);
  config.previewSurface.replaceChildren();
  config.previewSurface.onclick = null;
  config.previewSurface.classList.remove("is-clickable", "has-items", "has-multiple");
  config.clearButton.disabled = totalCount === 0;
  config.fileNameNode.textContent = selectedFiles.length
    ? `${selectedFiles.length} 个文件：${selectedFiles
        .map((file) => file.name)
        .join("、")}`
    : "未选择任何文件";

  if (totalCount) {
    const objectUrls = selectedFiles.map((file) => URL.createObjectURL(file));
    state.previewObjectUrls[kind] = objectUrls;
    const modalItems = [
      ...selectedFiles.map((file, index) => ({
        src: objectUrls[index],
        caption: `${config.label} ${index + 1} · ${file.name}`,
      })),
      ...inputUrls.map((url, index) => ({
        src: url,
        caption: `${config.label}链接 ${index + 1}`,
      })),
    ];
    const previewItems = [
      ...selectedFiles.map((file, index) => ({
        src: objectUrls[index],
        title: file.name,
        remove: () => removeReferenceFile(kind, index),
      })),
      ...inputUrls.map((url, index) => ({
        src: url,
        title: `${config.label}链接 ${index + 1}`,
        remove: () => removeReferenceUrl(kind, index),
      })),
    ];

    config.previewSurface.classList.add("has-items");
    config.previewSurface.classList.toggle("has-multiple", totalCount > 1);
    previewItems.forEach((item, index) => {
      const tile = document.createElement("div");
      tile.className = "reference-preview-tile";
      const imageButton = document.createElement("button");
      imageButton.type = "button";
      imageButton.className = "reference-preview-tile__image";
      imageButton.setAttribute("aria-label", `查看${config.label} ${index + 1}`);
      imageButton.addEventListener("click", () =>
        openImageModal(modalItems, { index })
      );
      const image = document.createElement("img");
      image.src = item.src;
      image.alt = `${config.previewTitle} ${index + 1}`;
      image.addEventListener("error", () => {
        config.previewMeta.textContent = "部分链接预览失败，但提交时仍会按链接请求。";
      });
      imageButton.appendChild(image);

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "reference-preview-tile__remove";
      removeButton.textContent = "×";
      removeButton.setAttribute("aria-label", `删除${config.label} ${index + 1}`);
      removeButton.addEventListener("click", (event) => {
        event.stopPropagation();
        item.remove();
      });

      tile.appendChild(imageButton);
      tile.appendChild(removeButton);
      config.previewSurface.appendChild(tile);
    });
    const overLimitText =
      totalCount > maxCount ? `，已超过上限 ${maxCount} 张` : "";
    config.previewMeta.textContent = `已选择 ${totalCount} 张${config.label}（本地 ${selectedFiles.length} / 链接 ${inputUrls.length}）${overLimitText}。`;
    return;
  }

  const empty = document.createElement("span");
  empty.textContent = config.emptyTitle;
  config.previewSurface.appendChild(empty);
  config.previewMeta.textContent = config.emptyDetail;
}

function renderColorMatchPreview(kind) {
  const config =
    kind === "colorTone"
      ? {
          fileInput: refs.colorToneFileInput,
          fileNameNode: refs.colorToneFileName,
          previewSurface: refs.colorTonePreviewImage,
          previewMeta: refs.colorTonePreviewMeta,
          emptyTitle: "未选择色调参考图",
          emptyDetail: "用于大模型色彩分析和 1K / 4:3 色板信息图生成。",
          previewTitle: "色调参考图预览",
        }
      : {
          fileInput: refs.colorSceneFileInput,
          fileNameNode: refs.colorSceneFileName,
          previewSurface: refs.colorScenePreviewImage,
          previewMeta: refs.colorScenePreviewMeta,
          emptyTitle: "未选择静物场景图",
          emptyDetail: "后端会先生成灰度图，再用色彩分析结果并发上色。",
          previewTitle: "静物场景图预览",
        };
  const selectedFile = config.fileInput.files?.[0] || null;

  revokePreviewUrl(kind);
  config.previewSurface.replaceChildren();
  config.previewSurface.onclick = null;
  config.previewSurface.classList.remove("is-clickable");
  config.fileNameNode.textContent = selectedFile ? selectedFile.name : "未选择任何文件";

  if (selectedFile) {
    const objectUrl = URL.createObjectURL(selectedFile);
    state.previewObjectUrls[kind] = objectUrl;
    const image = document.createElement("img");
    image.src = objectUrl;
    image.alt = config.previewTitle;
    config.previewSurface.appendChild(image);
    config.previewSurface.classList.add("is-clickable");
    config.previewSurface.onclick = () =>
      openImageModal(objectUrl, { caption: selectedFile.name });
    config.previewMeta.textContent = `本地文件：${selectedFile.name}`;
    return;
  }

  const empty = document.createElement("span");
  empty.textContent = config.emptyTitle;
  config.previewSurface.appendChild(empty);
  config.previewMeta.textContent = config.emptyDetail;
}

function revokePreviewUrl(kind) {
  const currentValue = state.previewObjectUrls[kind];
  const urls = Array.isArray(currentValue) ? currentValue : currentValue ? [currentValue] : [];
  urls.forEach((url) => URL.revokeObjectURL(url));
  if (urls.length) {
    state.previewObjectUrls[kind] = null;
  }
}

function renderEditPreview() {
  refs.editPreviewGrid.replaceChildren();

  if (!state.editInputAttachments.length) {
    refs.editFilesName.textContent = "未选择图片";
    const empty = document.createElement("p");
    empty.className = "muted-copy";
    empty.textContent = "粘贴图片、拖拽图片，或点击“加图片”。";
    refs.editPreviewGrid.appendChild(empty);
    return;
  }

  refs.editFilesName.textContent =
    state.editInputAttachments.length === 1
      ? state.editInputAttachments[0].name
      : `已加入 ${state.editInputAttachments.length} 张图片`;
  state.editInputAttachments.forEach((attachment, index) => {
    const tile = document.createElement("div");
    tile.className = "edit-preview-thumb";
    const imageButton = document.createElement("button");
    imageButton.type = "button";
    imageButton.setAttribute("aria-label", `查看输入图片 ${index + 1}`);
    imageButton.addEventListener("click", () => {
      openImageModal(
        state.editInputAttachments.map((item, itemIndex) => ({
          src: item.url,
          originalSrc: item.url,
          thumbnailSrc: item.thumbnailUrl || item.url,
          caption: item.name || `输入图片 ${itemIndex + 1}`,
        })),
        {
          index,
        }
      );
    });

    const image = document.createElement("img");
    image.src = attachment.thumbnailUrl || attachment.url;
    image.alt = `${attachment.name} 预览`;
    imageButton.appendChild(image);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "edit-preview-remove";
    removeButton.textContent = "×";
    removeButton.setAttribute("aria-label", `移除 ${attachment.name}`);
    removeButton.addEventListener("click", () => removeEditAttachment(index));

    tile.appendChild(imageButton);
    tile.appendChild(removeButton);
    refs.editPreviewGrid.appendChild(tile);
  });
}

function addEditFiles(files) {
  const imageFiles = files.filter((file) => file && file.type?.startsWith("image/"));
  imageFiles.forEach((file) => {
    if (state.editInputAttachments.length >= 16) {
      return;
    }
    const previewUrl = URL.createObjectURL(file);
    state.editInputAttachments.push({
      file,
      name: file.name || `image-${state.editInputAttachments.length + 1}.png`,
      url: previewUrl,
      thumbnailUrl: previewUrl,
    });
  });
  renderEditPreview();
}

function removeEditAttachment(index) {
  const [removed] = state.editInputAttachments.splice(index, 1);
  if (removed?.url) {
    URL.revokeObjectURL(removed.url);
  }
  renderEditPreview();
}

function clearEditAttachments() {
  state.editInputAttachments.forEach((attachment) => {
    URL.revokeObjectURL(attachment.url);
  });
  state.editInputAttachments = [];
  renderEditPreview();
}

function clearEditComposer(options = {}) {
  refs.editPromptInput.value = "";
  state.editInputAttachments.forEach((attachment) => {
    URL.revokeObjectURL(attachment.url);
  });
  state.editInputAttachments = [];
  if (options.render !== false) {
    renderEditPreview();
  }
}

async function rerunEditMessage(messageId) {
  const conversation = getActiveEditConversation();
  const sourceMessage = conversation?.messages?.find((message) => message.id === messageId);
  if (!conversation || !sourceMessage) {
    return;
  }

  const attachments = await filesFromEditMessage(sourceMessage);
  const inputCount = Number.isFinite(Number(sourceMessage.inputCount))
    ? Math.max(0, Number.parseInt(sourceMessage.inputCount, 10))
    : Array.isArray(sourceMessage.attachments)
      ? sourceMessage.attachments.length
      : 0;
  if (inputCount > 0 && !attachments.length) {
    window.alert("这条记录没有可复用的输入图。请把结果图拖回输入框，或重新上传图片后再发送。");
    return;
  }

  await submitImageEditRequest({
    conversation,
    prompt: sourceMessage.prompt,
    imageModel:
      sourceMessage.imageModel ||
      state.settings?.image_model ||
      IMAGE_MODEL_GPT_IMAGE_2,
    outputResolution:
      sourceMessage.outputResolution ||
      state.settings?.default_output_resolution ||
      "auto",
    outputAspectRatio:
      sourceMessage.outputAspectRatio ||
      state.settings?.default_output_aspect_ratio ||
      "auto",
    imagesPerPrompt: normalizeEditImagesPerPrompt(
      sourceMessage.imagesPerPrompt || state.settings?.default_images_per_prompt || 1
    ),
    attachments,
    mode: sourceMessage.mode === "agent" ? "agent" : "normal",
    sourceMessageId: sourceMessage.id,
  });
}

function setSelectValue(select, value, fallback = "") {
  if (!select) {
    return;
  }
  const desired = String(value || "").trim();
  const fallbackValue = String(fallback || "").trim();
  const values = Array.from(select.options || []).map((option) => option.value);
  if (desired && values.includes(desired)) {
    select.value = desired;
  } else if (fallbackValue && values.includes(fallbackValue)) {
    select.value = fallbackValue;
  }
}

async function editEditMessage(messageId) {
  const conversation = getActiveEditConversation();
  const sourceMessage = conversation?.messages?.find((message) => message.id === messageId);
  if (!conversation || !sourceMessage) {
    return;
  }

  const attachments = await filesFromEditMessage(sourceMessage);
  const inputCount = Number.isFinite(Number(sourceMessage.inputCount))
    ? Math.max(0, Number.parseInt(sourceMessage.inputCount, 10))
    : Array.isArray(sourceMessage.attachments)
      ? sourceMessage.attachments.length
      : 0;
  if (inputCount > 0 && !attachments.length) {
    window.alert("这条记录没有可复用的输入图。请把结果图拖回输入框，或重新上传图片后再编辑。");
  }

  refs.editPromptInput.value = sourceMessage.prompt || "";
  setEditGenerationMode(sourceMessage.mode === "agent" ? "agent" : "normal");
  setSelectValue(
    refs.imageEditForm.elements.namedItem("image_model"),
    sourceMessage.imageModel,
    state.settings?.image_model || IMAGE_MODEL_GPT_IMAGE_2
  );
  setSelectValue(
    refs.imageEditForm.elements.namedItem("output_resolution"),
    sourceMessage.outputResolution,
    state.settings?.default_output_resolution || "auto"
  );
  setSelectValue(
    refs.imageEditForm.elements.namedItem("output_aspect_ratio"),
    sourceMessage.outputAspectRatio,
    state.settings?.default_output_aspect_ratio || "auto"
  );
  const countInput = refs.imageEditForm.elements.namedItem("images_per_prompt");
  if (countInput) {
    countInput.value = String(
      normalizeEditImagesPerPrompt(
        sourceMessage.imagesPerPrompt || state.settings?.default_images_per_prompt || 1
      )
    );
  }

  state.editInputAttachments.forEach((attachment) => {
    URL.revokeObjectURL(attachment.url);
  });
  state.editInputAttachments = attachments.map((attachment) => ({
    file: attachment.file,
    name: attachment.name,
    url: URL.createObjectURL(attachment.file),
  }));
  state.editInputAttachments.forEach((attachment) => {
    attachment.thumbnailUrl = attachment.url;
  });
  renderEditPreview();
  setRoute("image-edit");
  refs.editPromptInput.focus();
  refs.editPromptInput.setSelectionRange(
    refs.editPromptInput.value.length,
    refs.editPromptInput.value.length
  );
}

async function filesFromEditMessage(message) {
  const files = [];
  const inputImageUrls = getMessageInputImageUrls(message);
  if (applyMessageInputImageUrls(message, inputImageUrls)) {
    saveEditConversations();
  }
  for (const [index, attachment] of (message.attachments || []).entries()) {
    const sourceUrl = resolveReusableImageSrc(attachment.src, inputImageUrls[index] || "");
    if (!sourceUrl || isKnownThumbnailImageUrl(sourceUrl)) {
      continue;
    }
    try {
      const response = await fetch(toApiUrl(sourceUrl));
      if (!response.ok) {
        continue;
      }
      const blob = await response.blob();
      if (!blob.type.startsWith("image/")) {
        continue;
      }
      const extension =
        blob.type.split("/")[1] ||
        sourceExtensionFromUrl(sourceUrl) ||
        "png";
      const name = attachment.name || `rerun-${index + 1}.${extension}`;
      files.push({
        file: new File([blob], name, { type: blob.type }),
        name,
      });
    } catch (_error) {
      // A persisted conversation may only keep image names, not the original blob.
    }
  }
  return files;
}

async function handleEditPaste(event) {
  const items = Array.from(event.clipboardData?.items || []);
  const files = items
    .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter(Boolean);
  const text = event.clipboardData?.getData("text/plain") || "";

  event.preventDefault();

  if (files.length) {
    addEditFiles(files);
    return;
  }

  const addedFromClipboard = await addImagesFromClipboard();
  if (addedFromClipboard) {
    return;
  }

  const trimmedText = text.trim();
  if (trimmedText && /^https?:\/\//i.test(trimmedText)) {
    await addEditImageUrl(trimmedText);
    return;
  }

  if (text) {
    insertEditPromptText(text);
  }
}

async function handleEditDrop(event) {
  event.preventDefault();
  refs.editDropZone.classList.remove("is-dragging");

  const internalImageUrl = event.dataTransfer?.getData("application/x-imag-replicate-image");
  if (internalImageUrl) {
    await addEditImageUrl(internalImageUrl.trim());
    return;
  }

  const droppedFiles = Array.from(event.dataTransfer?.files || []).filter((file) =>
    file.type?.startsWith("image/")
  );
  if (droppedFiles.length) {
    addEditFiles(droppedFiles);
    return;
  }

  const uri =
    event.dataTransfer?.getData("text/uri-list") ||
    event.dataTransfer?.getData("text/plain");
  if (uri) {
    await addEditImageUrl(uri.trim());
  }
}

async function addEditImageUrl(url) {
  try {
    const response = await fetch(toApiUrl(url));
    if (!response.ok) {
      throw new Error("图片读取失败。");
    }
    const blob = await response.blob();
    if (!blob.type.startsWith("image/")) {
      throw new Error("拖入的链接不是图片。");
    }
    const extension =
      blob.type.split("/")[1] ||
      sourceExtensionFromUrl(url) ||
      "png";
    const file = new File([blob], `dragged-${Date.now()}.${extension}`, {
      type: blob.type,
    });
    addEditFiles([file]);
  } catch (error) {
    window.alert(error.message);
  }
}

async function addImagesFromClipboard(options = {}) {
  const browserFiles = await readBrowserClipboardImageFiles();
  if (browserFiles.length) {
    addEditFiles(browserFiles);
    return true;
  }

  const backendFiles = await readBackendClipboardImageFiles();
  if (backendFiles.length) {
    addEditFiles(backendFiles);
    return true;
  }

  if (options.alertIfEmpty) {
    window.alert("剪贴板里没有读到图片。可以复制网页图片、聊天图片，或在文件夹里复制图片文件后再点粘贴。");
  }
  return false;
}

async function readBrowserClipboardImageFiles() {
  if (!navigator.clipboard?.read) {
    return [];
  }
  try {
    const clipboardItems = await navigator.clipboard.read();
    const files = [];
    for (const item of clipboardItems) {
      const imageType = item.types.find((type) => type.startsWith("image/"));
      if (!imageType) {
        continue;
      }
      const blob = await item.getType(imageType);
      const extension = imageType.split("/")[1] || "png";
      files.push(
        new File([blob], `clipboard-${Date.now()}-${files.length + 1}.${extension}`, {
          type: imageType,
        })
      );
    }
    return files;
  } catch (_error) {
    return [];
  }
}

async function readBackendClipboardImageFiles() {
  try {
    const payload = await apiFetch(`/api/clipboard/images?t=${Date.now()}`);
    const items = Array.isArray(payload.items) ? payload.items : [];
    const files = [];
    for (const item of items) {
      if (!item.data_url || !item.mime_type?.startsWith("image/")) {
        continue;
      }
      const response = await fetch(item.data_url);
      const blob = await response.blob();
      files.push(
        new File([blob], item.name || `clipboard-${Date.now()}-${files.length + 1}.png`, {
          type: item.mime_type,
        })
      );
    }
    return files;
  } catch (_error) {
    return [];
  }
}

function insertEditPromptText(text) {
  const input = refs.editPromptInput;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  input.value = `${input.value.slice(0, start)}${text}${input.value.slice(end)}`;
  const nextCursor = start + text.length;
  input.setSelectionRange(nextCursor, nextCursor);
}

function makeImageDraggable(image, sourceUrl) {
  image.draggable = true;
  image.dataset.dragSourceUrl = sourceUrl || "";
  if (image.dataset.dragBound === "true") {
    return;
  }
  image.dataset.dragBound = "true";
  image.addEventListener("dragstart", (event) => {
    const resolvedUrl = toApiUrl(image.dataset.dragSourceUrl || sourceUrl);
    event.dataTransfer?.setData("text/uri-list", resolvedUrl);
    event.dataTransfer?.setData("text/plain", resolvedUrl);
    event.dataTransfer?.setData("application/x-imag-replicate-image", resolvedUrl);
  });
}

function normalizeImageModalItems(itemsOrSrc, caption = "") {
  if (Array.isArray(itemsOrSrc)) {
    return itemsOrSrc
      .map((item) => {
        if (typeof item === "string") {
          return {
            src: item,
            originalSrc: item,
            thumbnailSrc: "",
            caption,
          };
        }
        if (!item?.src) {
          return null;
        }
        return {
          src: item.src,
          originalSrc: item.originalSrc || item.src,
          thumbnailSrc: item.thumbnailSrc || "",
          caption: item.caption || caption,
        };
      })
      .filter(Boolean);
  }

  if (!itemsOrSrc) {
    return [];
  }

  return [
    {
      src: itemsOrSrc,
      originalSrc: itemsOrSrc,
      thumbnailSrc: "",
      caption,
    },
  ];
}

function getActiveImageModalItem() {
  return state.imageModalItems[state.imageModalIndex] || null;
}

function hideImageModalContextMenu() {
  if (!refs.imageModalContextMenu) {
    return;
  }
  state.imageModalLastPointerButton = null;
  state.imageModalContextMenuArmedUntil = 0;
  refs.imageModalContextMenu.hidden = true;
  refs.imageModalContextMenu.style.left = "";
  refs.imageModalContextMenu.style.top = "";
}

function showImageModalContextMenu(clientX, clientY) {
  const activeItem = getActiveImageModalItem();
  if (!activeItem || !refs.imageModalContextMenu) {
    return;
  }

  refs.imageModalContextMenu.hidden = false;
  refs.imageModalContextMenu.style.left = "0px";
  refs.imageModalContextMenu.style.top = "0px";

  const menuRect = refs.imageModalContextMenu.getBoundingClientRect();
  const edgePadding = 12;
  const left = Math.max(
    edgePadding,
    Math.min(clientX, window.innerWidth - menuRect.width - edgePadding)
  );
  const top = Math.max(
    edgePadding,
    Math.min(clientY, window.innerHeight - menuRect.height - edgePadding)
  );
  refs.imageModalContextMenu.style.left = `${left}px`;
  refs.imageModalContextMenu.style.top = `${top}px`;
}

function sanitizeFilenameSegment(value) {
  return String(value || "")
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, " ")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .slice(0, 64);
}

function buildImageModalFilename(item) {
  const preferredName = sanitizeFilenameSegment(item?.caption || "design-output");
  const source = String(item?.originalSrc || item?.src || "");
  const extensionMatch = source.match(/\.([a-zA-Z0-9]{2,5})(?:[?#].*)?$/);
  const dataMatch = source.match(/^data:image\/([a-zA-Z0-9.+-]+)[;,]/i);
  const rawExtension = extensionMatch?.[1] || dataMatch?.[1] || "png";
  const extension = (
    rawExtension.toLowerCase() === "jpeg" ? "jpg" : rawExtension.toLowerCase()
  ).replace(/[^a-z0-9]+/g, "");
  return `${preferredName || "design-output"}.${extension}`;
}

async function fetchImageModalBlob(item) {
  const source = item?.originalSrc || item?.src;
  if (!source) {
    throw new Error("当前图片不可用。");
  }
  const response = await fetch(toApiUrl(source));
  if (!response.ok) {
    throw new Error("读取图片失败。");
  }
  return response.blob();
}

async function downloadActiveModalImage() {
  try {
    const activeItem = getActiveImageModalItem();
    if (!activeItem) {
      return;
    }
    const blob = await fetchImageModalBlob(activeItem);
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = buildImageModalFilename(activeItem);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  } catch (error) {
    window.alert(error.message || "图片保存失败。");
  }
}

async function copyActiveModalImage() {
  if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    window.alert(
      "当前浏览器环境不支持直接复制图片。Chrome 只在 HTTPS 或 localhost 等安全上下文开放图片剪贴板；当前可先用“另存为”。"
    );
    return;
  }

  try {
    const activeItem = getActiveImageModalItem();
    if (!activeItem) {
      return;
    }
    const blob = await fetchImageModalBlob(activeItem);
    const clipboardBlob =
      blob.type && blob.type.startsWith("image/")
        ? blob
        : new Blob([await blob.arrayBuffer()], { type: "image/png" });
    await navigator.clipboard.write([
      new ClipboardItem({
        [clipboardBlob.type]: clipboardBlob,
      }),
    ]);
  } catch (error) {
    if (!window.isSecureContext || error?.name === "NotAllowedError") {
      window.alert(
        "当前浏览器限制了图片复制。请用 HTTPS 或 localhost 打开页面后再试；当前可先用“另存为”。"
      );
      return;
    }
    window.alert(error.message || "复制图片失败。");
  }
}

async function copyTextToClipboard(text, button = null) {
  const value = String(text || "").trim();
  if (!value) {
    window.alert("没有可复制的提示词。");
    return;
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      const input = document.createElement("textarea");
      input.value = value;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.left = "-9999px";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    if (button) {
      const originalText = button.textContent;
      button.textContent = "已复制";
      window.setTimeout(() => {
        if (button.isConnected) {
          button.textContent = originalText;
        }
      }, 1200);
    }
  } catch (error) {
    window.alert(error.message || "复制提示词失败。");
  }
}

function renderImageModal() {
  hideImageModalContextMenu();
  const activeItem = getActiveImageModalItem();
  if (!activeItem) {
    refs.imageModalContent.removeAttribute("src");
    refs.imageModalContent.alt = "";
    refs.imageModalCaption.textContent = "";
    refs.imageModalCounter.textContent = "";
    refs.imageModalPrevButton.hidden = true;
    refs.imageModalNextButton.hidden = true;
    refs.imageModalPrevButton.disabled = true;
    refs.imageModalNextButton.disabled = true;
    return;
  }

  refs.imageModalContent.src = activeItem.src;
  refs.imageModalContent.alt = activeItem.caption || "图片预览";
  refs.imageModalCaption.textContent = activeItem.caption || "";
  makeImageDraggable(refs.imageModalContent, activeItem.originalSrc || activeItem.src);

  const total = state.imageModalItems.length;
  refs.imageModalCounter.textContent = total > 1 ? `${state.imageModalIndex + 1} / ${total}` : "";
  const hasMultiple = total > 1;
  refs.imageModalPrevButton.hidden = !hasMultiple;
  refs.imageModalNextButton.hidden = !hasMultiple;
  refs.imageModalPrevButton.disabled = !hasMultiple || state.imageModalIndex <= 0;
  refs.imageModalNextButton.disabled =
    !hasMultiple || state.imageModalIndex >= total - 1;
}

function openImageModal(itemsOrSrc, options = {}) {
  const caption =
    typeof options === "string"
      ? options
      : options?.caption || "";
  const normalizedItems = normalizeImageModalItems(itemsOrSrc, caption);
  if (!normalizedItems.length) {
    return;
  }

  refs.imageModal.hidden = false;
  state.imageModalLastPointerButton = null;
  state.imageModalContextMenuArmedUntil = 0;
  state.imageModalItems = normalizedItems;
  state.imageModalIndex = Math.min(
    Math.max(Number(options?.index) || 0, 0),
    normalizedItems.length - 1
  );
  state.imageModalRunId = options?.runId || null;
  state.imageModalJobId = options?.jobId || null;
  refs.imageModalDownloadAllButton.hidden = !state.imageModalJobId;
  refs.imageModalSelectDownloadButton.hidden = !state.imageModalJobId;
  state.isImageModalOpen = true;
  renderImageModal();
}

function stepImageModal(offset) {
  if (!state.isImageModalOpen || state.imageModalItems.length <= 1) {
    return;
  }

  const nextIndex = state.imageModalIndex + offset;
  if (nextIndex < 0 || nextIndex >= state.imageModalItems.length) {
    return;
  }

  state.imageModalIndex = nextIndex;
  renderImageModal();
}

function closeImageModal() {
  hideImageModalContextMenu();
  refs.imageModal.hidden = true;
  refs.imageModalContent.removeAttribute("src");
  refs.imageModalContent.alt = "";
  refs.imageModalCaption.textContent = "";
  refs.imageModalCounter.textContent = "";
  refs.imageModalPrevButton.hidden = true;
  refs.imageModalNextButton.hidden = true;
  refs.imageModalPrevButton.disabled = true;
  refs.imageModalNextButton.disabled = true;
  refs.imageModalDownloadAllButton.hidden = true;
  refs.imageModalSelectDownloadButton.hidden = true;
  state.imageModalLastPointerButton = null;
  state.imageModalContextMenuArmedUntil = 0;
  state.imageModalRunId = null;
  state.imageModalJobId = null;
  state.imageModalItems = [];
  state.imageModalIndex = 0;
  state.isImageModalOpen = false;
}

async function openDataDirectory() {
  try {
    await apiFetch("/api/data/open", { method: "POST" });
  } catch (error) {
    window.alert(error.message);
  }
}

async function openRunDirectory(runId) {
  try {
    await apiFetch(`/api/runs/${runId}/open`, { method: "POST" });
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteRunHistory(target) {
  const runId =
    typeof target === "string"
      ? target
      : String(target?.run_id || target?.runId || "");
  const jobId =
    typeof target === "object" && target
      ? String(target.job_id || target.jobId || "")
      : "";
  if (!runId && !jobId) {
    return;
  }
  if (!window.confirm("删除这条历史任务？对应输出目录也会删除。")) {
    return;
  }
  try {
    await deleteHistoryOnServer({ jobId, runId });
  } catch (error) {
    window.alert(error.message);
    return;
  }
  removeDeletedHistory({ jobId, runId });
}

async function deleteHistoryOnServer({ jobId, runId }) {
  let firstError = null;
  if (jobId) {
    try {
      return await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    } catch (error) {
      firstError = error;
      if (!runId || error.message === "task_still_running") {
        throw error;
      }
    }
  }
  if (runId) {
    try {
      return await apiFetch(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    } catch (error) {
      throw firstError || error;
    }
  }
  throw firstError || new Error("missing_delete_target");
}

function removeDeletedHistory({ jobId, runId }) {
  state.history = state.history.filter((record) => {
    const recordJobId = String(record.job_id || "");
    const recordRunId = String(record.run_id || "");
    return !((jobId && recordJobId === jobId) || (runId && recordRunId === runId));
  });
  if (jobId) {
    state.jobs = state.jobs.filter((job) => job.job_id !== jobId);
    if (state.currentJobId === jobId) {
      state.currentJobId = resolveCurrentJobId();
    }
  }
  state.editConversations.forEach((conversation) => {
    conversation.messages = (conversation.messages || []).filter((message) => {
      return !(
        (runId && message.runId === runId) ||
        (jobId && message.jobId === jobId)
      );
    });
  });
  state.editConversations = state.editConversations.filter(
    (conversation) => conversation.messages?.length
  );
  if (
    state.editConversationId &&
    !state.editConversations.some((conversation) => conversation.id === state.editConversationId)
  ) {
    state.editConversationId = state.editConversations[0]?.id || null;
  }
  if (!state.editConversations.length) {
    createEditConversation({ persist: false, render: false });
  }
  saveEditConversations();
  renderHistory();
  renderTaskBoard();
  renderEditWorkspace();
}

function filenameFromContentDisposition(value) {
  const header = String(value || "");
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim().replace(/^"|"$/g, ""));
    } catch (_error) {
      return utf8Match[1].trim().replace(/^"|"$/g, "");
    }
  }
  const asciiMatch = header.match(/filename="?([^";]+)"?/i);
  return asciiMatch?.[1]?.trim() || "";
}

function triggerBlobDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename || "download.zip";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function downloadBlobFromApi(url, fallbackFilename, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Platform-Client", "user");
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD"].includes(method) && state.platformCsrfToken) {
    headers.set("X-CSRF-Token", state.platformCsrfToken);
  }
  const response = await fetch(toApiUrl(url), {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    throw new Error(formatApiErrorPayload(payload));
  }
  const blob = await response.blob();
  const filename =
    filenameFromContentDisposition(response.headers.get("content-disposition")) ||
    fallbackFilename;
  triggerBlobDownload(blob, filename);
}

async function downloadRun(runId, relativeUrl) {
  try {
    const url = relativeUrl || `/api/runs/${encodeURIComponent(runId)}/download?scope=images`;
    await downloadBlobFromApi(url, `设计出图-${runId}.zip`);
  } catch (error) {
    window.alert(error.message || "下载失败。");
  }
}

async function downloadJobImages(jobId) {
  if (!jobId) {
    return;
  }
  try {
    await downloadBlobFromApi(
      `/api/jobs/${encodeURIComponent(jobId)}/download?scope=images`,
      `设计出图-${jobId}-图片.zip`
    );
  } catch (error) {
    window.alert(error.message || "图片下载失败。");
  }
}

async function downloadJobPackage(jobId) {
  if (!jobId) {
    return;
  }
  try {
    await downloadBlobFromApi(
      `/api/jobs/${encodeURIComponent(jobId)}/download?scope=task`,
      `设计出图-${jobId}-任务包.zip`
    );
  } catch (error) {
    window.alert(error.message || "任务包下载失败。");
  }
}

async function downloadSelectedJobFiles(jobId, fileIds) {
  if (!jobId || !fileIds.length) {
    window.alert("请选择要下载的图片。");
    return;
  }
  await downloadBlobFromApi(
    `/api/jobs/${encodeURIComponent(jobId)}/download-selected`,
    `设计出图-${jobId}-选中图片.zip`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        file_ids: fileIds,
        scope: "images",
      }),
    }
  );
}

function formatBytes(size) {
  const value = Number(size || 0);
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let amount = value;
  let unitIndex = 0;
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024;
    unitIndex += 1;
  }
  return `${amount.toFixed(amount >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

async function openDownloadSelection(jobId) {
  if (!jobId) {
    return;
  }

  let payload;
  try {
    payload = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/files`);
  } catch (error) {
    window.alert(error.message || "读取任务文件失败。");
    return;
  }

  const images = Array.isArray(payload.images) ? payload.images : [];
  if (!images.length) {
    window.alert("该任务没有可下载图片。");
    return;
  }

  const shell = document.createElement("div");
  shell.className = "modal-shell download-selection-modal";
  shell.innerHTML = `
    <div class="modal-backdrop" data-close-download-selection></div>
    <section class="modal-panel download-selection-panel" role="dialog" aria-modal="true" aria-labelledby="downloadSelectionTitle">
      <header class="modal-header">
        <div>
          <p class="eyebrow">选择下载</p>
          <h2 id="downloadSelectionTitle">任务图片</h2>
          <p class="download-selection-summary"></p>
        </div>
        <div class="modal-actions">
          <button class="secondary-action" type="button" data-download-select-all>全选</button>
          <button class="secondary-action" type="button" data-download-invert>反选</button>
          <button class="primary-action" type="button" data-download-selected>下载选中</button>
          <button class="icon-button icon-button--quiet" type="button" data-close-download-selection>关闭</button>
        </div>
      </header>
      <div class="download-selection-grid"></div>
    </section>
  `;

  const summary = shell.querySelector(".download-selection-summary");
  const grid = shell.querySelector(".download-selection-grid");
  const close = () => shell.remove();
  shell.querySelectorAll("[data-close-download-selection]").forEach((button) => {
    button.addEventListener("click", close);
  });

  summary.textContent = `${images.length} 张图片，可一次性打包下载，也可以勾选部分图片。`;
  images.forEach((file, index) => {
    const id = String(file.id || "");
    const item = document.createElement("label");
    item.className = "download-selection-item";
    item.innerHTML = `
      <input type="checkbox" value="${escapeHtml(id)}" checked />
      <span class="download-selection-item__thumb"></span>
      <span class="download-selection-item__meta">
        <strong>${escapeHtml(file.name || `图片 ${index + 1}`)}</strong>
        <span>${escapeHtml(formatBytes(file.size_bytes))}</span>
      </span>
    `;
    const thumb = item.querySelector(".download-selection-item__thumb");
    const imageUrl = file.thumbnail_url || file.url;
    if (imageUrl) {
      const image = document.createElement("img");
      image.src = toApiUrl(imageUrl);
      image.alt = file.name || `图片 ${index + 1}`;
      image.loading = "lazy";
      image.decoding = "async";
      thumb.appendChild(image);
    } else {
      thumb.textContent = String(index + 1);
    }
    grid.appendChild(item);
  });

  const selectedIds = () =>
    Array.from(shell.querySelectorAll(".download-selection-item input:checked"))
      .map((input) => input.value)
      .filter(Boolean);

  shell.querySelector("[data-download-select-all]")?.addEventListener("click", () => {
    shell.querySelectorAll(".download-selection-item input").forEach((input) => {
      input.checked = true;
    });
  });
  shell.querySelector("[data-download-invert]")?.addEventListener("click", () => {
    shell.querySelectorAll(".download-selection-item input").forEach((input) => {
      input.checked = !input.checked;
    });
  });
  shell.querySelector("[data-download-selected]")?.addEventListener("click", async () => {
    try {
      await downloadSelectedJobFiles(jobId, selectedIds());
      close();
    } catch (error) {
      window.alert(error.message || "下载选中图片失败。");
    }
  });

  document.body.appendChild(shell);
}

async function openLogModal(jobId = null) {
  refs.logModal.hidden = false;
  state.isLogModalOpen = true;
  state.logScope = jobId ? "job" : "global";
  state.logTargetJobId = jobId || null;
  state.currentLogKey = state.logScope === "global" ? "total" : "run";
  await refreshLogs();
}

function closeLogModal() {
  refs.logModal.hidden = true;
  state.isLogModalOpen = false;
  state.logTargetJobId = null;
  state.logScope = "global";
}

async function refreshLogs() {
  try {
    const query = new URLSearchParams();
    query.set("scope", state.logScope || "global");
    if (state.logScope === "job") {
      const effectiveJobId = state.logTargetJobId || state.currentJobId;
      if (effectiveJobId) {
        query.set("job_id", effectiveJobId);
      }
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const payload = await apiFetch(`/api/logs${suffix}`);
    state.logEntries = payload.entries || [];
    state.currentLogKey =
      state.logEntries.find((entry) => entry.key === state.currentLogKey)?.key ||
      payload.selected_key ||
      state.logEntries[0]?.key ||
      "app";
    renderLogModal();
  } catch (error) {
    refs.logModalContent.textContent = error.message;
  }
}

function renderLogModal() {
  refs.logEntryTabs.innerHTML = "";

  if (!state.logEntries.length) {
    refs.logEntryTitle.textContent = "日志详情";
    refs.logEntryPath.textContent = "";
    refs.logModalContent.textContent = "暂无日志。";
    return;
  }

  state.logEntries.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "log-tab";
    button.textContent = entry.label;
    button.classList.toggle("is-active", entry.key === state.currentLogKey);
    button.addEventListener("click", () => {
      state.currentLogKey = entry.key;
      renderLogModal();
    });
    refs.logEntryTabs.appendChild(button);
  });

  const activeEntry =
    state.logEntries.find((entry) => entry.key === state.currentLogKey) ||
    state.logEntries[0];
  refs.logEntryTitle.textContent = activeEntry.label;
  refs.logEntryPath.textContent = activeEntry.path;
  refs.logModalContent.textContent = activeEntry.content || "日志文件为空。";
}

async function openLogsDirectory() {
  try {
    await apiFetch("/api/logs/open", { method: "POST" });
  } catch (error) {
    window.alert(error.message);
  }
}

function startPolling() {
  stopPolling();
  const tick = async () => {
    try {
      await refreshSharedPool();
      if (state.currentJobId) {
        await refreshCurrentJob();
      }
      if (
        state.currentRoute === "history" ||
        state.currentJobId ||
        state.history.length === 0
      ) {
        await refreshHistory();
      }
      if (state.isLogModalOpen) {
        await refreshLogs();
      }
    } finally {
      state.pollTimer = window.setTimeout(tick, POLL_INTERVAL_MS);
    }
  };
  state.pollTimer = window.setTimeout(tick, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

async function refreshCurrentJob() {
  if (!state.jobs.length && !state.currentJobId) {
    return;
  }
  try {
    const jobs = await apiFetch("/api/jobs");
    const signature = stableJsonSignature(jobs);
    const changed = signature !== state.lastJobsSignature;
    state.lastJobsSignature = signature;
    maybeNotifyJobStatusChanges(jobs);
    state.jobs = jobs;
    if (
      !state.currentJobId ||
      !state.jobs.some((job) => job.job_id === state.currentJobId)
    ) {
      state.currentJobId = resolveCurrentJobId();
    }
    const syncedMessages = syncEditMessagesFromJobs();
    const hydratedInputs = hydrateEditMessagesInputImageUrls();
    const messageChanged = syncedMessages || hydratedInputs;
    if (messageChanged) {
      saveEditConversations();
    }
    if (changed || messageChanged) {
      renderTaskMetrics();
      renderTaskBoard();
      renderEditWorkspace();
    }
  } catch (_error) {
    // Ignore transient polling failures.
  }
}

async function refreshSharedPool() {
  try {
    const sharedPool = await apiFetch("/api/shared-pool");
    const signature = stableJsonSignature(sharedPool);
    if (signature === state.lastSharedPoolSignature) {
      return;
    }
    state.lastSharedPoolSignature = signature;
    state.sharedPool = sharedPool;
    renderTopStatus();
    renderTaskMetrics();
  } catch (_error) {
    // Ignore transient polling failures.
  }
}

async function refreshHistory() {
  try {
    const history = filterDeletedEditConversationHistory(await apiFetch("/api/history"));
    const signature = stableJsonSignature(history);
    if (signature === state.lastHistorySignature) {
      return;
    }
    state.lastHistorySignature = signature;
    state.history = history;
    const syncedMessages = syncEditMessagesFromJobs();
    const hydratedInputs = hydrateEditMessagesInputImageUrls();
    const messageChanged = syncedMessages || hydratedInputs;
    if (messageChanged) {
      saveEditConversations();
    }
    renderHistory();
    renderEditWorkspace();
  } catch (_error) {
    // Ignore transient polling failures.
  }
}

function upsertJob(job) {
  const index = state.jobs.findIndex((item) => item.job_id === job.job_id);
  if (index >= 0) {
    state.jobs[index] = job;
  } else {
    state.jobs.unshift(job);
  }
}

function getCurrentJob(taskKey = null) {
  const candidates = taskKey
    ? state.jobs.filter((job) =>
        Array.isArray(taskKey) ? taskKey.includes(job.task_key) : job.task_key === taskKey
      )
    : state.jobs;
  if (state.currentJobId) {
    return candidates.find((job) => job.job_id === state.currentJobId) || candidates[0] || null;
  }
  return candidates[0] || null;
}

function resolveCurrentJobId(taskKey = null) {
  const candidates = taskKey
    ? state.jobs.filter((job) =>
        Array.isArray(taskKey) ? taskKey.includes(job.task_key) : job.task_key === taskKey
      )
    : state.jobs;
  const runningJob = candidates.find(
    (job) => job.status === "running" || job.status === "queued"
  );
  return runningJob?.job_id || candidates[0]?.job_id || null;
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Platform-Client", "user");
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD"].includes(method) && state.platformCsrfToken) {
    headers.set("X-CSRF-Token", state.platformCsrfToken);
  }
  const response = await fetch(toApiUrl(url), {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const message = formatApiErrorPayload(payload);
    const error = new Error(message);
    if (isJson && payload && typeof payload === "object") {
      error.code = payload.code || "";
      error.category = payload.category || "";
      error.hint = payload.hint || "";
      error.retryable = Boolean(payload.retryable);
    }
    throw error;
  }
  return payload;
}

function formatApiErrorPayload(payload) {
  if (payload && typeof payload === "object") {
    if (payload.error) {
      return formatApiErrorPayload(payload.error);
    }
    if (payload.detail) {
      return formatApiErrorPayload(payload.detail);
    }
    if (Array.isArray(payload)) {
      return payload
        .map((item) => {
          if (item && typeof item === "object") {
            const field = Array.isArray(item.loc)
              ? item.loc.filter((part) => part !== "body").join(".")
              : "";
            return field ? `${field}: ${item.msg || "参数不正确"}` : item.msg;
          }
          return String(item || "");
        })
        .filter(Boolean)
        .join("\n") || "请求失败。";
    }
    return JSON.stringify(payload);
  }
  return String(payload || "请求失败。");
}

function toApiUrl(url) {
  if (!url) {
    return "";
  }
  if (!state.apiBase || /^(https?:|blob:|data:)/i.test(url)) {
    return url;
  }
  if (url.startsWith("/")) {
    return `${state.apiBase}${url}`;
  }
  return `${state.apiBase}/${url}`;
}

function buildOptions(options, selectedValue) {
  return options
    .map(
      (option) =>
        `<option value="${escapeHtml(option.value ?? option)}" ${
          (option.value ?? option) === selectedValue ? "selected" : ""
        }>${escapeHtml(option.label ?? option)}</option>`
    )
    .join("");
}

function formatOutputSelection({
  outputResolution = "",
  outputAspectRatio = "",
  resolvedSize = "",
} = {}) {
  const resolutionOptions = Array.isArray(state.settings?.available_output_resolutions)
    ? state.settings.available_output_resolutions
    : [];
  const aspectRatioOptions = Array.isArray(state.settings?.available_output_aspect_ratios)
    ? state.settings.available_output_aspect_ratios
    : [];
  if (outputResolution === "agent" || outputAspectRatio === "agent") {
    return "Agent 自动";
  }
  const resolutionLabel =
    resolutionOptions.find((item) => item.value === outputResolution)?.label ||
    outputResolution ||
    "";
  const aspectRatioLabel =
    aspectRatioOptions.find((item) => item.value === outputAspectRatio)?.label ||
    formatOutputPreset(outputAspectRatio);

  if (!outputResolution && !outputAspectRatio && !resolvedSize) {
    return "-";
  }
  if (
    outputResolution === "auto" ||
    outputAspectRatio === "auto" ||
    (!outputResolution && outputAspectRatio === "auto")
  ) {
    if (!resolvedSize || resolvedSize === "auto") {
      return "auto";
    }
    const autoPieces = [];
    if (outputResolution && outputResolution !== "auto" && resolutionLabel) {
      autoPieces.push(resolutionLabel);
    }
    autoPieces.push("auto", resolvedSize);
    return autoPieces.join(" / ");
  }

  const pieces = [];
  if (resolutionLabel) {
    pieces.push(resolutionLabel);
  }
  if (aspectRatioLabel && aspectRatioLabel !== "-") {
    pieces.push(aspectRatioLabel);
  }
  if (resolvedSize && resolvedSize !== "auto") {
    pieces.push(resolvedSize);
  }
  return pieces.join(" / ") || "-";
}

function formatOutputPreset(value) {
  const presets = Array.isArray(state.settings?.available_output_presets)
    ? state.settings.available_output_presets
    : [];
  const matched = presets.find((item) => item.value === value);
  if (matched?.label) {
    return matched.label;
  }
  const legacyAliases = {
    "1:1": "1024x1024 · 正方形",
    "3:2": "1536x1024 · 横版",
    "2:3": "1024x1536 · 竖版",
    "7:4": "1792x1024 · 宽横版",
    "4:7": "1024x1792 · 长竖版",
  };
  return legacyAliases[value] || value || "-";
}

function compactText(value, maxLength) {
  const clean = String(value || "").replace(/\s+/g, " ").trim();
  if (clean.length <= maxLength) {
    return clean;
  }
  return `${clean.slice(0, maxLength)}...`;
}

function arraysEqual(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((item, index) => item === right[index]);
}

function formatStatus(status) {
  const labels = {
    idle: "空闲",
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    partial: "部分完成",
    failed: "失败",
  };
  return labels[status] || status;
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
