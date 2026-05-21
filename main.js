const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  crashReporter,
  dialog,
  screen,
  shell,
} = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

const APP_TITLE = "设计出图";
const BACKEND_STARTUP_TIMEOUT_MS = 90000;
const HEALTH_CHECK_INTERVAL_MS = 300;
const HEALTH_CHECK_TIMEOUT_MS = 1200;
const BACKEND_PORT_START = 18789;
const BACKEND_PORT_END = 18989;
const DIAG_POLL_INTERVAL_MS = 2000;
const EXTERNAL_BROWSER_FALLBACK_DELAY_MS = 25000;
const WATCHDOG_FALLBACK_DELAY_MS = EXTERNAL_BROWSER_FALLBACK_DELAY_MS + 3000;
const COMPAT_FLAG_FILES = ["compat-mode.flag", "disable-gpu.flag"];
const ENABLE_GPU_FLAG_FILES = ["enable-gpu.flag"];
const DISABLE_EXTERNAL_BROWSER_FALLBACK_FLAG_FILES = [
  "disable-external-browser-fallback.flag",
  "no-browser-fallback.flag",
];

let mainWindow = null;
let backendProcess = null;
let backendPort = null;
let tray = null;
let keepAliveTimer = null;
let externalFallbackTimer = null;
let externalFallbackArmed = false;
let externalFallbackOpened = false;
let isQuitting = false;
let isStarting = false;
let diagPollTimer = null;
let watchdogStatePath = null;
let watchdogLogPath = null;
let watchdogHeartbeatTimer = null;
let watchdogState = {};
let embeddedReady = false;

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  appendEarlyShellLog("second instance rejected before ready");
  app.quit();
}

function hasCliFlag(flag) {
  return process.argv.some((arg) => arg === flag || arg.startsWith(`${flag}=`));
}

function existsQuietly(targetPath) {
  try {
    return fs.existsSync(targetPath);
  } catch (_error) {
    return false;
  }
}

function appendEarlyShellLog(message) {
  try {
    for (const root of resolveEarlyInstallRoots()) {
      const logDir = path.join(root, "logs");
      fs.mkdirSync(logDir, { recursive: true });
      fs.appendFileSync(
        path.join(logDir, "electron-early.log"),
        `[${new Date().toISOString()}] ${message}\n`,
        "utf8"
      );
    }
  } catch (_error) {
    // Logging must never block startup.
  }
}

function resolveEarlyInstallRoot() {
  return app.isPackaged ? path.dirname(process.execPath) : path.resolve(__dirname, "..");
}

function resolveEarlyInstallRoots() {
  const roots = [resolveEarlyInstallRoot()];
  if (process.env.PORTABLE_EXECUTABLE_DIR) {
    roots.unshift(process.env.PORTABLE_EXECUTABLE_DIR);
  }
  if (app.isPackaged && process.resourcesPath) {
    roots.push(process.resourcesPath);
  }
  return Array.from(new Set(roots.filter(Boolean)));
}

function isCompatibilityModeRequested() {
  const installRoots = resolveEarlyInstallRoots();
  return (
    process.env.IMAG_REPLICATE2_COMPAT_MODE === "1" ||
    process.env.IMAG_REPLICATE2_DISABLE_GPU === "1" ||
    hasCliFlag("--compat") ||
    hasCliFlag("--disable-gpu") ||
    installRoots.some((installRoot) =>
      COMPAT_FLAG_FILES.some((fileName) => existsQuietly(path.join(installRoot, fileName)))
    )
  );
}

function isGpuExplicitlyEnabled() {
  const installRoots = resolveEarlyInstallRoots();
  return (
    process.env.IMAG_REPLICATE2_ENABLE_GPU === "1" ||
    hasCliFlag("--enable-gpu") ||
    installRoots.some((installRoot) =>
      ENABLE_GPU_FLAG_FILES.some((fileName) => existsQuietly(path.join(installRoot, fileName)))
    )
  );
}

function isExternalBrowserFallbackDisabled() {
  const installRoots = resolveEarlyInstallRoots();
  return (
    process.env.IMAG_REPLICATE2_DISABLE_EXTERNAL_BROWSER === "1" ||
    process.env.IMAG_REPLICATE2_EXTERNAL_BROWSER === "0" ||
    hasCliFlag("--disable-external-browser-fallback") ||
    installRoots.some((installRoot) =>
      DISABLE_EXTERNAL_BROWSER_FALLBACK_FLAG_FILES.some((fileName) =>
        existsQuietly(path.join(installRoot, fileName))
      )
    )
  );
}

const useCompatibilityMode = !isGpuExplicitlyEnabled() && isCompatibilityModeRequested();
const allowExternalBrowserFallback = !isExternalBrowserFallbackDisabled();

app.commandLine.appendSwitch("force-color-profile", "srgb");
try {
  const chromiumLogPath = path.join(resolveEarlyInstallRoot(), "logs", "electron-chromium.log");
  fs.mkdirSync(path.dirname(chromiumLogPath), { recursive: true });
  app.commandLine.appendSwitch("enable-logging");
  app.commandLine.appendSwitch("log-file", chromiumLogPath);
  app.commandLine.appendSwitch("v", "1");
} catch (error) {
  appendEarlyShellLog(`chromium logging setup failed: ${error.message}`);
}
app.commandLine.appendSwitch(
  "disable-features",
  [
    "CalculateNativeWinOcclusion",
    "HardwareMediaKeyHandling",
    "MediaFoundationVideoCapture",
    "UseEcoQoSForBackgroundProcess",
    "UseSkiaRenderer",
    "CanvasOopRasterization",
    "DCompPresenter",
    "DirectCompositionVideoOverlays",
  ].join(",")
);
app.commandLine.appendSwitch("disable-renderer-backgrounding");
app.commandLine.appendSwitch("disable-background-timer-throttling");
app.commandLine.appendSwitch("disable-backgrounding-occluded-windows");
if (process.platform === "win32") {
  app.commandLine.appendSwitch("disable-direct-composition");
  app.commandLine.appendSwitch("disable-gpu-sandbox");
  app.commandLine.appendSwitch("disable-native-gpu-memory-buffers");
  app.commandLine.appendSwitch("disable-zero-copy");
}
if (useCompatibilityMode) {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("disable-gpu-compositing");
  app.commandLine.appendSwitch("disable-accelerated-2d-canvas");
  app.commandLine.appendSwitch("disable-accelerated-video-decode");
}
try {
  const crashDumpsPath = path.join(resolveEarlyInstallRoot(), "crash-dumps");
  fs.mkdirSync(crashDumpsPath, { recursive: true });
  app.setPath("crashDumps", crashDumpsPath);
  crashReporter.start({
    uploadToServer: false,
    compress: false,
    ignoreSystemCrashHandler: false,
  });
  appendEarlyShellLog(`crash reporter started path=${crashDumpsPath}`);
} catch (error) {
  appendEarlyShellLog(`crash reporter setup failed: ${error.message}`);
}
appendEarlyShellLog(
  `process starting compatMode=${useCompatibilityMode} externalBrowserFallback=${allowExternalBrowserFallback}`
);

function resolveAssetRoot() {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
}

function resolveProjectRoot() {
  return app.isPackaged ? app.getPath("userData") : path.resolve(__dirname, "..");
}

function resolveInstallRoot() {
  if (app.isPackaged && process.env.PORTABLE_EXECUTABLE_DIR) {
    return process.env.PORTABLE_EXECUTABLE_DIR;
  }
  return app.isPackaged ? path.dirname(app.getPath("exe")) : path.resolve(__dirname, "..");
}

function resolveShellLogPath() {
  return path.join(resolveProjectRoot(), "logs", "electron-shell.log");
}

function appendShellLog(message) {
  const logPath = resolveShellLogPath();
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const line = `[${new Date().toISOString()}] ${message}\n`;
  fs.appendFileSync(logPath, line, "utf8");
}

function appendShellLogQuietly(message) {
  try {
    appendShellLog(message);
  } catch (_error) {
    appendEarlyShellLog(message);
  }
}

function resolveWatchdogLogPath() {
  if (watchdogLogPath) {
    return watchdogLogPath;
  }
  return path.join(resolveProjectRoot(), "logs", "electron-watchdog.log");
}

function appendWatchdogLog(message) {
  try {
    const logPath = resolveWatchdogLogPath();
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${message}\n`, "utf8");
  } catch (error) {
    appendEarlyShellLog(`watchdog log failed: ${error.message}`);
  }
}

function writeWatchdogState(patch = {}) {
  if (!watchdogStatePath) {
    return;
  }
  watchdogState = {
    ...watchdogState,
    ...patch,
    updatedAt: new Date().toISOString(),
  };
  try {
    fs.mkdirSync(path.dirname(watchdogStatePath), { recursive: true });
    fs.writeFileSync(watchdogStatePath, JSON.stringify(watchdogState, null, 2), "utf8");
  } catch (error) {
    appendShellLogQuietly(`watchdog state write failed: ${formatError(error)}`);
  }
}

function markEmbeddedReady(stage) {
  if (embeddedReady) {
    return;
  }
  embeddedReady = true;
  writeWatchdogState({
    embeddedReady: true,
    embeddedReadyAt: new Date().toISOString(),
    embeddedReadyStage: stage,
    fallbackStatus: "cancelled",
    fallbackReason: "",
  });
  appendShellLogQuietly(`embedded renderer ready stage=${stage}`);
  disarmExternalBrowserFallback();
}

process.on("uncaughtException", (error) => {
  writeWatchdogState({
    uncaughtException: error.stack || error.message || String(error),
  });
  appendShellLogQuietly(`uncaught exception: ${error.stack || error.message || error}`);
});

process.on("unhandledRejection", (reason) => {
  const message = reason && reason.stack ? reason.stack : String(reason);
  writeWatchdogState({
    unhandledRejection: message,
  });
  appendShellLogQuietly(`unhandled rejection: ${message}`);
});

process.on("beforeExit", (code) => {
  writeWatchdogState({
    processBeforeExitCode: code,
  });
  appendShellLogQuietly(`process beforeExit code=${code}`);
});

process.on("exit", (code) => {
  writeWatchdogState({
    processExitCode: code,
    processExitAt: new Date().toISOString(),
  });
  appendShellLogQuietly(`process exit code=${code}`);
});

function formatError(error) {
  if (!error) {
    return "";
  }
  return error.stack || error.message || String(error);
}

function safeStat(targetPath) {
  try {
    const stat = fs.statSync(targetPath);
    return {
      exists: true,
      isDirectory: stat.isDirectory(),
      size: stat.size,
      modified: stat.mtime.toISOString(),
    };
  } catch (error) {
    return {
      exists: false,
      error: error.message,
    };
  }
}

function logDiagnosticSnapshot(stage) {
  const installRoot = resolveInstallRoot();
  const assetRoot = resolveAssetRoot();
  const projectRoot = resolveProjectRoot();
  const snapshot = {
    stage,
    pid: process.pid,
    execPath: process.execPath,
    cwd: process.cwd(),
    argv: process.argv,
    platform: process.platform,
    arch: process.arch,
    versions: process.versions,
    appIsPackaged: app.isPackaged,
    compatMode: useCompatibilityMode,
    externalBrowserFallback: allowExternalBrowserFallback,
    externalBrowserOpened: externalFallbackOpened,
    embeddedReady,
    portableExecutableDir: process.env.PORTABLE_EXECUTABLE_DIR || "",
    installRoot,
    assetRoot,
    projectRoot,
    appPath: app.getAppPath(),
    exePath: app.getPath("exe"),
    logsPath: path.dirname(resolveShellLogPath()),
    resourcesPath: process.resourcesPath || "",
    paths: {
      backendExe: safeStat(path.join(assetRoot, "backend-exe", "design_output_backend.exe")),
      backendExeInternal: safeStat(path.join(assetRoot, "backend-exe", "_internal")),
      web: safeStat(path.join(assetRoot, "web")),
      appAsar: safeStat(path.join(assetRoot, "app.asar")),
      seedConfig: safeStat(path.join(assetRoot, "seed-config.json")),
      configExample: safeStat(path.join(assetRoot, "config.example.json")),
      compatFlag: safeStat(path.join(assetRoot, "compat-mode.flag")),
      installCompatFlag: safeStat(path.join(installRoot, "compat-mode.flag")),
      disableExternalBrowserFallbackFlag: safeStat(
        path.join(assetRoot, "disable-external-browser-fallback.flag")
      ),
      installDisableExternalBrowserFallbackFlag: safeStat(
        path.join(installRoot, "disable-external-browser-fallback.flag")
      ),
    },
    env: {
      TEMP: process.env.TEMP || "",
      TMP: process.env.TMP || "",
      USERPROFILE: process.env.USERPROFILE || "",
      APPDATA: process.env.APPDATA || "",
      LOCALAPPDATA: process.env.LOCALAPPDATA || "",
      PROCESSOR_ARCHITECTURE: process.env.PROCESSOR_ARCHITECTURE || "",
      IMAG_REPLICATE2_COMPAT_MODE: process.env.IMAG_REPLICATE2_COMPAT_MODE || "",
      IMAG_REPLICATE2_DISABLE_GPU: process.env.IMAG_REPLICATE2_DISABLE_GPU || "",
      IMAG_REPLICATE2_ENABLE_GPU: process.env.IMAG_REPLICATE2_ENABLE_GPU || "",
      IMAG_REPLICATE2_EXTERNAL_BROWSER: process.env.IMAG_REPLICATE2_EXTERNAL_BROWSER || "",
      IMAG_REPLICATE2_DISABLE_EXTERNAL_BROWSER:
        process.env.IMAG_REPLICATE2_DISABLE_EXTERNAL_BROWSER || "",
    },
    memoryUsage: process.memoryUsage(),
  };
  appendShellLog(`diagnostic snapshot ${JSON.stringify(snapshot)}`);
}

function startDiagnosticPoll() {
  if (diagPollTimer) {
    clearInterval(diagPollTimer);
  }
  diagPollTimer = setInterval(() => {
    try {
      const backendState = backendProcess
        ? {
            pid: backendProcess.pid,
            killed: backendProcess.killed,
            exitCode: backendProcess.exitCode,
            signalCode: backendProcess.signalCode,
          }
        : null;
      const windowState = mainWindow
        ? {
            destroyed: mainWindow.isDestroyed(),
            visible: !mainWindow.isDestroyed() && mainWindow.isVisible(),
            focused: !mainWindow.isDestroyed() && mainWindow.isFocused(),
            minimized: !mainWindow.isDestroyed() && mainWindow.isMinimized(),
            url: !mainWindow.isDestroyed() ? mainWindow.webContents.getURL() : "",
            rendererPid:
              !mainWindow.isDestroyed() && mainWindow.webContents.getOSProcessId
                ? mainWindow.webContents.getOSProcessId()
                : "",
          }
        : null;
      appendShellLog(
        `diagnostic poll isStarting=${isStarting} isQuitting=${isQuitting} backend=${JSON.stringify(
          backendState
        )} window=${JSON.stringify(windowState)}`
      );
    } catch (error) {
      appendShellLogQuietly(`diagnostic poll failed: ${formatError(error)}`);
    }
  }, DIAG_POLL_INTERVAL_MS);
  diagPollTimer.unref?.();
}

function stopDiagnosticPoll() {
  if (!diagPollTimer) {
    return;
  }
  clearInterval(diagPollTimer);
  diagPollTimer = null;
}

function startWatchdog(baseUrl) {
  if (!allowExternalBrowserFallback) {
    appendShellLog("watchdog disabled because external browser fallback is disabled");
    return;
  }
  const logDir = path.dirname(resolveShellLogPath());
  watchdogStatePath = path.join(logDir, "electron-watchdog-state.json");
  watchdogLogPath = path.join(logDir, "electron-watchdog.log");
  watchdogState = {
    appTitle: APP_TITLE,
    startedAt: new Date().toISOString(),
    electronPid: process.pid,
    exePath: app.getPath("exe"),
    execPath: process.execPath,
    cwd: process.cwd(),
    argv: process.argv,
    baseUrl,
    rendererUrl: buildRendererUrl(baseUrl),
    backendHealthUrl: `${baseUrl}/api/health`,
    allowExternalBrowserFallback,
    compatMode: useCompatibilityMode,
    embeddedReady: false,
    fallbackStatus: "watching",
    watchdogFallbackDelayMs: WATCHDOG_FALLBACK_DELAY_MS,
    watchdogLogPath,
    shellLogPath: resolveShellLogPath(),
  };
  writeWatchdogState(watchdogState);

  const watchdogScript = app.isPackaged
    ? path.join(process.resourcesPath, "watchdog.js")
    : path.join(__dirname, "watchdog.js");
  appendShellLog(`starting watchdog script=${watchdogScript} state=${watchdogStatePath}`);
  try {
    const child = spawn(process.execPath, [watchdogScript, watchdogStatePath], {
      cwd: resolveInstallRoot(),
      env: {
        ...process.env,
        ELECTRON_RUN_AS_NODE: "1",
      },
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    });
    child.unref();
    writeWatchdogState({
      watchdogSpawned: true,
      watchdogSpawnedAt: new Date().toISOString(),
      watchdogChildPid: child.pid || "",
    });
    watchdogHeartbeatTimer = setInterval(() => {
      writeWatchdogState({
        heartbeatAt: new Date().toISOString(),
        electronPid: process.pid,
        embeddedReady,
        isQuitting,
      });
    }, 1000);
    watchdogHeartbeatTimer.unref?.();
  } catch (error) {
    appendShellLog(`watchdog spawn failed: ${formatError(error)}`);
    writeWatchdogState({
      watchdogSpawned: false,
      watchdogSpawnError: formatError(error),
    });
  }
}

function stopWatchdog(reason) {
  if (watchdogHeartbeatTimer) {
    clearInterval(watchdogHeartbeatTimer);
    watchdogHeartbeatTimer = null;
  }
  writeWatchdogState({
    shutdownRequested: true,
    shutdownReason: reason,
    shutdownAt: new Date().toISOString(),
  });
}

function findFreePort() {
  return new Promise((resolve) => {
    let candidatePort = BACKEND_PORT_START;
    const tryListen = () => {
      if (candidatePort > BACKEND_PORT_END) {
        findEphemeralPort().then(resolve);
        return;
      }
      const server = net.createServer();
      server.once("error", (error) => {
        if (candidatePort === BACKEND_PORT_START || candidatePort % 20 === 0) {
          appendShellLogQuietly(`port probe busy port=${candidatePort} error=${error.message}`);
        }
        candidatePort += 1;
        tryListen();
      });
      server.listen(candidatePort, "127.0.0.1", () => {
        const selectedPort = candidatePort;
        appendShellLogQuietly(`port probe selected fixed port=${selectedPort}`);
        server.close(() => resolve(selectedPort));
      });
    };
    tryListen();
  });
}

function findEphemeralPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === "string") {
          reject(new Error("无法获取空闲端口。"));
          return;
        }
        appendShellLogQuietly(`port probe selected ephemeral port=${address.port}`);
        resolve(address.port);
      });
    });
    server.on("error", reject);
  });
}

function startBackend(port) {
  const projectRoot = resolveProjectRoot();
  const assetRoot = resolveAssetRoot();
  const env = {
    ...process.env,
    IMAG_REPLICATE2_PORT: String(port),
    IMAG_REPLICATE2_PROJECT_ROOT: projectRoot,
    IMAG_REPLICATE2_ASSET_ROOT: assetRoot,
  };

  if (app.isPackaged) {
    const backendExePath = path.join(
      process.resourcesPath,
      "backend-exe",
      "design_output_backend.exe"
    );
    const webDirPath = path.join(process.resourcesPath, "web");
    appendShellLog(`install root: ${resolveInstallRoot()}`);
    appendShellLog(`resources root: ${process.resourcesPath}`);
    appendShellLog(`user data root: ${projectRoot}`);
    appendShellLog(
      `backend env port=${env.IMAG_REPLICATE2_PORT} projectRoot=${projectRoot} assetRoot=${assetRoot}`
    );

    if (fs.existsSync(backendExePath)) {
      appendShellLog(`starting packaged backend exe: ${backendExePath}`);
      for (const requiredPath of [backendExePath, webDirPath]) {
        if (!fs.existsSync(requiredPath)) {
          throw new Error(`???????${requiredPath}`);
        }
      }
      backendProcess = spawn(backendExePath, [], {
        cwd: projectRoot,
        env,
        windowsHide: true,
      });
    } else {
      const pythonHome = path.join(process.resourcesPath, "python-runtime");
      const pythonExecutable = path.join(pythonHome, "python.exe");
      const scriptPath = path.join(process.resourcesPath, "backend", "backend_main.py");
      appendShellLog(`backend exe not found, falling back to bundled Python runtime`);
      appendShellLog(`starting packaged backend: ${pythonExecutable} ${scriptPath}`);
      for (const requiredPath of [pythonExecutable, scriptPath, webDirPath]) {
        if (!fs.existsSync(requiredPath)) {
          throw new Error(`???????${requiredPath}`);
        }
      }
      backendProcess = spawn(pythonExecutable, [scriptPath], {
        cwd: projectRoot,
        env: {
          ...env,
          PYTHONHOME: pythonHome,
          PYTHONPATH: path.join(pythonHome, "Lib", "site-packages"),
        },
        windowsHide: true,
      });
    }
  } else {
    const pythonCommand = process.env.PYTHON_PATH || "python";
    const scriptPath = path.join(projectRoot, "backend_main.py");
    appendShellLog(`starting dev backend: ${pythonCommand} ${scriptPath}`);
    backendProcess = spawn(pythonCommand, [scriptPath], {
      cwd: projectRoot,
      env,
      windowsHide: true,
    });
  }

  appendShellLog(`backend spawned pid=${backendProcess.pid || ""}`);
  backendProcess.on("error", (error) => {
    appendShellLog(`backend spawn error: ${formatError(error)}`);
  });
  backendProcess.stdout?.on("data", (chunk) => {
    appendShellLog(`backend stdout: ${chunk.toString().trimEnd()}`);
  });
  backendProcess.stderr?.on("data", (chunk) => {
    appendShellLog(`backend stderr: ${chunk.toString().trimEnd()}`);
  });
  backendProcess.on("exit", (code, signal) => {
    appendShellLog(`backend exit code=${code} signal=${signal || ""}`);
    backendProcess = null;
    if (!isQuitting) {
      dialog.showErrorBox(APP_TITLE, "本地后端已退出，请重新启动应用。");
      app.quit();
    }
  });
  backendProcess.on("close", (code, signal) => {
    appendShellLog(`backend close code=${code} signal=${signal || ""}`);
  });
  backendProcess.on("disconnect", () => {
    appendShellLog("backend disconnect");
  });
}

function checkBackendHealth(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: HEALTH_CHECK_TIMEOUT_MS }, (response) => {
      response.on("aborted", () => {
        appendShellLog(`backend health response aborted status=${response.statusCode || ""}`);
      });
      response.resume();
      resolve({
        ok: response.statusCode >= 200 && response.statusCode < 300,
        statusCode: response.statusCode,
      });
    });

    request.on("timeout", () => {
      request.destroy(new Error("health check timeout"));
    });
    request.on("error", reject);
  });
}

async function waitForBackend(url, timeoutMs = BACKEND_STARTUP_TIMEOUT_MS) {
  const startedAt = Date.now();
  let attempts = 0;
  while (Date.now() - startedAt < timeoutMs) {
    attempts += 1;
    try {
      const response = await checkBackendHealth(url);
      if (response.ok) {
        appendShellLog(`backend health ok after ${attempts} checks elapsedMs=${Date.now() - startedAt}`);
        return;
      }
      appendShellLog(`backend health HTTP ${response.statusCode} attempt=${attempts}`);
    } catch (error) {
      // Wait and retry.
      if (attempts <= 5 || attempts % 20 === 0) {
        appendShellLog(
          `backend health pending attempt=${attempts} elapsedMs=${Date.now() - startedAt}: ${error.message}`
        );
      }
    }
    await new Promise((resolve) => setTimeout(resolve, HEALTH_CHECK_INTERVAL_MS));
  }
  throw new Error("本地后端启动超时。");
}

function calculateWindowBounds() {
  const workArea = screen.getPrimaryDisplay().workAreaSize;
  const width = Math.max(1040, Math.min(1540, workArea.width - 40));
  const height = Math.max(720, Math.min(980, workArea.height - 40));
  return {
    width,
    height,
    minWidth: Math.min(1040, width),
    minHeight: Math.min(720, height),
  };
}

function createMainWindow(initialUrl = "") {
  const iconPath = path.join(resolveAssetRoot(), "icon.ico");
  const bounds = calculateWindowBounds();
  appendShellLog(`creating main window ${bounds.width}x${bounds.height} initialUrl=${initialUrl || ""}`);
  mainWindow = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    minWidth: bounds.minWidth,
    minHeight: bounds.minHeight,
    title: APP_TITLE,
    icon: iconPath,
    autoHideMenuBar: true,
    backgroundColor: "#d6c8b2",
    show: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      backgroundThrottling: false,
    },
  });

  mainWindow.once("ready-to-show", () => {
    appendShellLog("main window ready-to-show");
    if (!mainWindow.isVisible()) {
      mainWindow.show();
    }
  });

  mainWindow.on("show", () => {
    appendShellLog("main window show");
  });

  mainWindow.on("hide", () => {
    appendShellLog("main window hide");
  });

  mainWindow.on("close", () => {
    appendShellLog(`main window close isStarting=${isStarting} isQuitting=${isQuitting}`);
  });

  mainWindow.on("closed", () => {
    appendShellLog(`main window closed isStarting=${isStarting} isQuitting=${isQuitting}`);
    mainWindow = null;
  });

  mainWindow.on("focus", () => {
    appendShellLog("main window focus");
  });

  mainWindow.on("blur", () => {
    appendShellLog("main window blur");
  });

  mainWindow.on("minimize", () => {
    appendShellLog("main window minimize");
  });

  mainWindow.on("restore", () => {
    appendShellLog("main window restore");
  });

  mainWindow.on("unresponsive", () => {
    appendShellLog("main window unresponsive");
  });

  mainWindow.on("responsive", () => {
    appendShellLog("main window responsive");
  });

  mainWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    appendShellLog(`renderer console level=${level} source=${sourceId}:${line} message=${message}`);
    if (message.includes("startup step: render-all-complete")) {
      markEmbeddedReady("client-render-all-complete");
    }
  });

  mainWindow.webContents.on("dom-ready", () => {
    const rendererUrl = mainWindow?.webContents.getURL() || "";
    appendShellLog(`renderer dom-ready url=${rendererUrl}`);
    writeWatchdogState({
      rendererDomReadyAt: new Date().toISOString(),
      rendererDomReadyUrl: rendererUrl,
    });
  });

  mainWindow.webContents.on("did-finish-load", () => {
    const rendererUrl = mainWindow?.webContents.getURL() || "";
    appendShellLog(`renderer did-finish-load url=${rendererUrl}`);
    writeWatchdogState({
      rendererDidFinishLoadAt: new Date().toISOString(),
      rendererDidFinishLoadUrl: rendererUrl,
    });
    if (isAppRendererUrl(rendererUrl)) {
      markEmbeddedReady("did-finish-load");
    }
  });

  mainWindow.webContents.on("did-start-loading", () => {
    appendShellLog(`renderer did-start-loading url=${mainWindow?.webContents.getURL() || ""}`);
  });

  mainWindow.webContents.on("did-stop-loading", () => {
    appendShellLog(`renderer did-stop-loading url=${mainWindow?.webContents.getURL() || ""}`);
  });

  mainWindow.webContents.on("did-start-navigation", (_event, url, isInPlace, isMainFrame) => {
    appendShellLog(
      `renderer did-start-navigation mainFrame=${isMainFrame} inPlace=${isInPlace} url=${url}`
    );
  });

  mainWindow.webContents.on(
    "did-navigate",
    (_event, url, httpResponseCode, httpStatusText) => {
      appendShellLog(
        `renderer did-navigate status=${httpResponseCode} text=${httpStatusText} url=${url}`
      );
    }
  );

  mainWindow.webContents.on(
    "did-navigate-in-page",
    (_event, url, isMainFrame, _frameProcessId, _frameRoutingId) => {
      appendShellLog(`renderer did-navigate-in-page mainFrame=${isMainFrame} url=${url}`);
    }
  );

  mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
    appendShellLog(
      `renderer did-fail-load code=${errorCode} description=${errorDescription} url=${validatedURL}`
    );
    if (allowExternalBrowserFallback && !externalFallbackOpened && !isQuitting) {
      stopExternalBrowserFallback();
      armExternalBrowserFallback(
        validatedURL || resolveCurrentRendererUrl(),
        `did-fail-load code=${errorCode} ${errorDescription}`
      );
    }
  });

  mainWindow.webContents.on(
    "did-fail-provisional-load",
    (_event, errorCode, errorDescription, validatedURL) => {
      appendShellLog(
        `renderer did-fail-provisional-load code=${errorCode} description=${errorDescription} url=${validatedURL}`
      );
      if (allowExternalBrowserFallback && !externalFallbackOpened && !isQuitting) {
        stopExternalBrowserFallback();
        armExternalBrowserFallback(
          validatedURL || resolveCurrentRendererUrl(),
          `did-fail-provisional-load code=${errorCode} ${errorDescription}`
        );
      }
    }
  );

  mainWindow.webContents.on("page-title-updated", (_event, title) => {
    appendShellLog(`renderer page-title-updated title=${title}`);
  });

  mainWindow.webContents.on("certificate-error", (_event, url, error) => {
    appendShellLog(`renderer certificate-error url=${url} error=${error}`);
  });

  mainWindow.webContents.on("plugin-crashed", (_event, name, version) => {
    appendShellLog(`renderer plugin-crashed name=${name} version=${version}`);
  });

  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    appendShellLog(`renderer gone reason=${details.reason} exitCode=${details.exitCode}`);
    writeWatchdogState({
      rendererGone: true,
      rendererGoneAt: new Date().toISOString(),
      rendererGoneReason: details.reason,
      rendererGoneExitCode: details.exitCode,
    });
    if (allowExternalBrowserFallback && !externalFallbackOpened && !isQuitting) {
      stopExternalBrowserFallback();
      armExternalBrowserFallback(
        resolveCurrentRendererUrl(),
        `render-process-gone reason=${details.reason} exitCode=${details.exitCode}`
      );
    }
  });

  if (initialUrl) {
    mainWindow.loadURL(initialUrl);
    return;
  }

  const loadingHtml = `
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8" />
        <style>
          body {
            margin: 0;
            display: grid;
            place-items: center;
            height: 100vh;
            color: #2b2119;
            background: #e8dcc6;
            font: 14px/1.5 "Microsoft YaHei UI", "Segoe UI", sans-serif;
          }
          main { text-align: center; }
          h1 { margin: 0 0 8px; font-size: 22px; }
          p { margin: 0; color: rgba(43, 33, 25, 0.72); }
        </style>
      </head>
      <body>
        <main>
          <h1>${APP_TITLE}</h1>
          <p>正在启动本地服务...</p>
        </main>
      </body>
    </html>
  `;
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(loadingHtml)}`);
}

function loadRenderer(url) {
  const rendererUrl = buildRendererUrl(url);
  writeWatchdogState({
    rendererUrl,
    rendererLoadStartedAt: new Date().toISOString(),
    fallbackStatus: allowExternalBrowserFallback ? "armed" : "disabled",
  });
  if (!mainWindow || mainWindow.isDestroyed()) {
    appendShellLog("main window missing before renderer load; creating with renderer url");
    createMainWindow(rendererUrl);
    return;
  }
  appendShellLog(`loading renderer url: ${rendererUrl}`);
  mainWindow.loadURL(rendererUrl);
}

function buildRendererUrl(baseUrl) {
  try {
    const rendererUrl = new URL(baseUrl);
    if (useCompatibilityMode) {
      rendererUrl.searchParams.set("compat", "1");
    }
    return rendererUrl.toString();
  } catch (_error) {
    if (!useCompatibilityMode || baseUrl.includes("compat=1")) {
      return baseUrl;
    }
    return `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}compat=1`;
  }
}

function resolveCurrentRendererUrl() {
  return backendPort ? buildRendererUrl(`http://127.0.0.1:${backendPort}`) : "";
}

function isAppRendererUrl(url) {
  try {
    const parsedUrl = new URL(url);
    return (
      ["127.0.0.1", "localhost"].includes(parsedUrl.hostname) &&
      (!backendPort || parsedUrl.port === String(backendPort))
    );
  } catch (_error) {
    return false;
  }
}

function startKeepAlive() {
  if (keepAliveTimer) {
    return;
  }
  keepAliveTimer = setInterval(() => {
    // Holding a referenced timer keeps the Electron helper alive while the browser UI is open.
  }, 60 * 60 * 1000);
}

function stopKeepAlive() {
  if (!keepAliveTimer) {
    return;
  }
  clearInterval(keepAliveTimer);
  keepAliveTimer = null;
}

function stopExternalBrowserFallback() {
  if (!externalFallbackTimer) {
    externalFallbackArmed = false;
    return;
  }
  clearTimeout(externalFallbackTimer);
  externalFallbackTimer = null;
  externalFallbackArmed = false;
}

function clearExternalBrowserFallback() {
  stopExternalBrowserFallback();
  externalFallbackOpened = false;
  stopKeepAlive();
}

function reopenEmbeddedWindow() {
  const rendererUrl = resolveCurrentRendererUrl();
  if (!rendererUrl) {
    appendShellLog("reopen embedded requested but renderer url is unavailable");
    return;
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    appendShellLog(`reopen embedded creating window url=${rendererUrl}`);
    createMainWindow(rendererUrl);
    return;
  }
  appendShellLog(`reopen embedded focusing window url=${rendererUrl}`);
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
}

function createTray(rendererUrl) {
  if (tray || process.platform !== "win32") {
    return;
  }
  const iconPath = path.join(resolveAssetRoot(), "icon.ico");
  tray = new Tray(iconPath);
  tray.setToolTip(`${APP_TITLE} - 本地服务运行中`);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: "打开界面",
        click: () => {
          appendShellLog(`tray open embedded renderer url=${rendererUrl}`);
          reopenEmbeddedWindow();
        },
      },
      {
        label: "打开日志目录",
        click: () => {
          shell.openPath(path.dirname(resolveShellLogPath()));
        },
      },
      { type: "separator" },
      {
        label: "退出",
        click: () => {
          appendShellLog("tray quit requested");
          app.quit();
        },
      },
    ])
  );
}

async function openExternalBrowserFallback(rawUrl, reason) {
  if (!allowExternalBrowserFallback || externalFallbackOpened || isQuitting) {
    return;
  }
  const rendererUrl = buildRendererUrl(rawUrl);
  appendShellLog(`external fallback activating reason=${reason} url=${rendererUrl}`);
  writeWatchdogState({
    fallbackStatus: "opening",
    fallbackReason: reason,
    fallbackUrl: rendererUrl,
    fallbackRequestedAt: new Date().toISOString(),
  });
  createTray(rendererUrl);
  startKeepAlive();
  try {
    externalFallbackOpened = true;
    await shell.openExternal(rendererUrl);
    writeWatchdogState({
      fallbackStatus: "opened",
      fallbackOpenedAt: new Date().toISOString(),
    });
  } catch (error) {
    externalFallbackOpened = false;
    appendShellLog(`external fallback open failed: ${formatError(error)}`);
    writeWatchdogState({
      fallbackStatus: "failed",
      fallbackError: formatError(error),
    });
  }
}

function armExternalBrowserFallback(baseUrl, reason = "embedded renderer did not become ready") {
  if (!allowExternalBrowserFallback || externalFallbackArmed || isQuitting) {
    return;
  }
  externalFallbackArmed = true;
  writeWatchdogState({
    fallbackStatus: "armed",
    fallbackReason: reason,
    fallbackUrl: buildRendererUrl(baseUrl),
    fallbackDelayMs: EXTERNAL_BROWSER_FALLBACK_DELAY_MS,
  });
  externalFallbackTimer = setTimeout(async () => {
    if (isQuitting) {
      return;
    }
    await openExternalBrowserFallback(baseUrl, reason);
  }, EXTERNAL_BROWSER_FALLBACK_DELAY_MS);
}

function disarmExternalBrowserFallback() {
  clearExternalBrowserFallback();
  writeWatchdogState({
    fallbackStatus: "cancelled",
    fallbackReason: "",
  });
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) {
    return;
  }
  appendShellLog(`stopping backend pid=${backendProcess.pid}`);
  try {
    backendProcess.kill();
  } catch (error) {
    appendShellLog(`backend kill failed: ${error.message}`);
  }
}

app.on("window-all-closed", () => {
  appendShellLogQuietly(`window-all-closed isStarting=${isStarting} isQuitting=${isQuitting}`);
  if (isStarting && !isQuitting) {
    return;
  }
  if (externalFallbackOpened && !isQuitting) {
    appendShellLogQuietly("window-all-closed ignored because external fallback is active");
    return;
  }
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  appendShellLogQuietly(`app before-quit isStarting=${isStarting}`);
  isQuitting = true;
  stopDiagnosticPoll();
  stopWatchdog("electron before-quit");
  stopExternalBrowserFallback();
  stopKeepAlive();
  tray?.destroy();
  tray = null;
  stopBackend();
});

app.on("will-quit", () => {
  appendShellLogQuietly("app will-quit");
});

app.on("quit", (_event, exitCode) => {
  appendShellLogQuietly(`app quit exitCode=${exitCode}`);
});

app.on("activate", () => {
  appendShellLogQuietly(`app activate externalFallback=${allowExternalBrowserFallback}`);
  const rendererUrl = resolveCurrentRendererUrl();
  if (!mainWindow && rendererUrl) {
    createMainWindow(rendererUrl);
  }
});

app.on("second-instance", () => {
  appendShellLogQuietly(`second instance received externalFallback=${allowExternalBrowserFallback}`);
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
    return;
  }
  reopenEmbeddedWindow();
});

app.whenReady().then(async () => {
  try {
    isStarting = true;
    app.setName(APP_TITLE);
    appendShellLog(`electron shell starting compatMode=${useCompatibilityMode}`);
    logDiagnosticSnapshot("startup");
    startDiagnosticPoll();
    backendPort = await findFreePort();
    appendShellLog(`selected backend port=${backendPort}`);
    startBackend(backendPort);
    const baseUrl = `http://127.0.0.1:${backendPort}`;
    await waitForBackend(`${baseUrl}/api/health`);
    startWatchdog(baseUrl);
    createMainWindow();
    loadRenderer(baseUrl);
    armExternalBrowserFallback(baseUrl, "embedded renderer did not report ready");
    isStarting = false;
    logDiagnosticSnapshot("renderer-load-requested");
  } catch (error) {
    isStarting = false;
    appendShellLog(`startup failed: ${formatError(error)}`);
    writeWatchdogState({
      startupFailed: true,
      startupFailedAt: new Date().toISOString(),
      startupError: formatError(error),
    });
    dialog.showErrorBox(APP_TITLE, String(error.message || error));
    app.quit();
  }
});
