const { app, BrowserWindow, Menu, dialog, screen, shell, crashReporter } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

const APP_TITLE = "设计出图";
const BACKEND_STARTUP_TIMEOUT_MS = 120000;
const HEALTH_CHECK_INTERVAL_MS = 350;
const HEALTH_CHECK_TIMEOUT_MS = 1200;
const BACKEND_PORT_START = 18789;
const BACKEND_PORT_END = 18989;
const COMPAT_FLAG_FILES = ["compat-mode.flag", "disable-gpu.flag"];
const ENABLE_GPU_FLAG_FILES = ["enable-gpu.flag"];

let mainWindow = null;
let backendProcess = null;
let backendPort = null;
let isQuitting = false;

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
}

function existsQuietly(targetPath) {
  try {
    return fs.existsSync(targetPath);
  } catch (_error) {
    return false;
  }
}

function resolveInstallRoot() {
  if (app.isPackaged && process.env.PORTABLE_EXECUTABLE_DIR) {
    return process.env.PORTABLE_EXECUTABLE_DIR;
  }
  return app.isPackaged ? path.dirname(app.getPath("exe")) : path.resolve(__dirname, "..");
}

function resolveAssetRoot() {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
}

function resolveProjectRoot() {
  return app.isPackaged ? app.getPath("userData") : path.resolve(__dirname, "..");
}

function resolveEarlyRoots() {
  const roots = [resolveInstallRoot()];
  if (app.isPackaged && process.resourcesPath) {
    roots.push(process.resourcesPath);
  }
  return Array.from(new Set(roots.filter(Boolean)));
}

function hasCliFlag(flag) {
  return process.argv.some((arg) => arg === flag || arg.startsWith(`${flag}=`));
}

function isGpuExplicitlyEnabled() {
  return (
    process.env.IMAG_REPLICATE2_ENABLE_GPU === "1" ||
    hasCliFlag("--enable-gpu") ||
    resolveEarlyRoots().some((root) =>
      ENABLE_GPU_FLAG_FILES.some((fileName) => existsQuietly(path.join(root, fileName)))
    )
  );
}

function isCompatibilityModeRequested() {
  return (
    process.env.IMAG_REPLICATE2_COMPAT_MODE === "1" ||
    process.env.IMAG_REPLICATE2_DISABLE_GPU === "1" ||
    hasCliFlag("--compat") ||
    hasCliFlag("--disable-gpu") ||
    resolveEarlyRoots().some((root) =>
      COMPAT_FLAG_FILES.some((fileName) => existsQuietly(path.join(root, fileName)))
    )
  );
}

const useCompatibilityMode = !isGpuExplicitlyEnabled() && isCompatibilityModeRequested();

app.commandLine.appendSwitch("force-color-profile", "srgb");
app.commandLine.appendSwitch(
  "disable-features",
  [
    "CalculateNativeWinOcclusion",
    "HardwareMediaKeyHandling",
    "UseEcoQoSForBackgroundProcess",
    "UseSkiaRenderer",
    "CanvasOopRasterization",
    "DCompPresenter",
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
}

function resolveShellLogPath() {
  return path.join(resolveProjectRoot(), "logs", "electron-platform-shell.log");
}

function appendShellLog(message) {
  try {
    const logPath = resolveShellLogPath();
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${message}\n`, "utf8");
  } catch (_error) {
    // Startup logging should never block the shell.
  }
}

function formatError(error) {
  return error?.stack || error?.message || String(error || "");
}

function copySeedConfigIfNeeded(projectRoot, assetRoot) {
  const runtimeDir = path.join(projectRoot, "platform_runtime");
  const configPath = path.join(runtimeDir, "config.json");
  if (existsQuietly(configPath)) {
    return;
  }
  const seedPath = path.join(assetRoot, "platform-seed-config.json");
  const fallbackPath = path.join(assetRoot, "config.example.json");
  const sourcePath = existsQuietly(seedPath) ? seedPath : fallbackPath;
  if (!existsQuietly(sourcePath)) {
    appendShellLog(`seed config missing source=${sourcePath}`);
    return;
  }
  fs.mkdirSync(runtimeDir, { recursive: true });
  fs.copyFileSync(sourcePath, configPath);
  appendShellLog(`seed config copied source=${sourcePath} target=${configPath}`);
}

function copySeedDatabaseIfNeeded(projectRoot, assetRoot) {
  const runtimeDir = path.join(projectRoot, "platform_runtime");
  const databasePath = path.join(runtimeDir, "platform.db");
  if (existsQuietly(databasePath)) {
    return;
  }
  const seedPath = path.join(assetRoot, "platform-seed.db");
  if (!existsQuietly(seedPath)) {
    appendShellLog(`seed database missing source=${seedPath}`);
    return;
  }
  fs.mkdirSync(runtimeDir, { recursive: true });
  for (const suffix of ["", "-wal", "-shm"]) {
    const sourcePath = path.join(assetRoot, `platform-seed.db${suffix}`);
    if (!existsQuietly(sourcePath)) {
      continue;
    }
    const targetPath = path.join(runtimeDir, `platform.db${suffix}`);
    fs.copyFileSync(sourcePath, targetPath);
    appendShellLog(`seed database copied source=${sourcePath} target=${targetPath}`);
  }
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
      server.once("error", () => {
        candidatePort += 1;
        tryListen();
      });
      server.listen(candidatePort, "127.0.0.1", () => {
        const selectedPort = candidatePort;
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
        resolve(address.port);
      });
    });
    server.on("error", reject);
  });
}

function buildBackendEnv(port) {
  const projectRoot = resolveProjectRoot();
  const assetRoot = resolveAssetRoot();
  const runtimeDir = path.join(projectRoot, "platform_runtime");
  copySeedConfigIfNeeded(projectRoot, assetRoot);
  copySeedDatabaseIfNeeded(projectRoot, assetRoot);
  return {
    ...process.env,
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
    PLATFORM_DESKTOP_MODE: "1",
    PLATFORM_DESKTOP_USER_ONLY: "1",
    PLATFORM_DESKTOP_GLOBAL_SECRETS: "1",
    PLATFORM_HOST: "127.0.0.1",
    PLATFORM_PORT: String(port),
    PLATFORM_BASE_DIR: runtimeDir,
    PLATFORM_DATABASE_PATH: path.join(runtimeDir, "platform.db"),
    PLATFORM_STORAGE_DIR: path.join(runtimeDir, "storage"),
    PLATFORM_CONFIG_PATH: path.join(runtimeDir, "config.json"),
    PLATFORM_COOKIE_SECURE: "0",
    PLATFORM_WORKER_CONCURRENCY: process.env.PLATFORM_WORKER_CONCURRENCY || "100",
    PLATFORM_DEFAULT_USER_CONCURRENT_LIMIT:
      process.env.PLATFORM_DEFAULT_USER_CONCURRENT_LIMIT || "30",
    PLATFORM_MAX_USER_CONCURRENT_LIMIT:
      process.env.PLATFORM_MAX_USER_CONCURRENT_LIMIT || "100",
    PLATFORM_ENABLE_PIPELINE: "1",
  };
}

function startBackend(port) {
  const assetRoot = resolveAssetRoot();
  const projectRoot = resolveProjectRoot();
  const env = buildBackendEnv(port);
  appendShellLog(`starting platform backend port=${port} packaged=${app.isPackaged}`);
  appendShellLog(`projectRoot=${projectRoot} assetRoot=${assetRoot}`);

  if (app.isPackaged) {
    const pythonHome = path.join(assetRoot, "python-runtime");
    const pythonExecutable = path.join(pythonHome, "python.exe");
    const backendRoot = path.join(assetRoot, "platform-backend");
    for (const requiredPath of [pythonExecutable, backendRoot]) {
      if (!existsQuietly(requiredPath)) {
        throw new Error(`缺少打包资源：${requiredPath}`);
      }
    }
    backendProcess = spawn(pythonExecutable, ["-m", "platform_backend.app.launcher"], {
      cwd: backendRoot,
      env: {
        ...env,
        PYTHONHOME: pythonHome,
        PYTHONPATH: [
          backendRoot,
          path.join(pythonHome, "Lib", "site-packages"),
          path.join(pythonHome, "Lib"),
        ].join(path.delimiter),
      },
      windowsHide: true,
    });
  } else {
    const pythonCommand = process.env.PYTHON_PATH || "python";
    backendProcess = spawn(pythonCommand, ["-m", "platform_backend.app.launcher"], {
      cwd: assetRoot,
      env,
      windowsHide: true,
    });
  }

  backendProcess.stdout?.on("data", (chunk) => {
    appendShellLog(`backend stdout: ${chunk.toString().trimEnd()}`);
  });
  backendProcess.stderr?.on("data", (chunk) => {
    appendShellLog(`backend stderr: ${chunk.toString().trimEnd()}`);
  });
  backendProcess.on("error", (error) => {
    appendShellLog(`backend spawn error: ${formatError(error)}`);
  });
  backendProcess.on("exit", (code, signal) => {
    appendShellLog(`backend exit code=${code} signal=${signal || ""}`);
    backendProcess = null;
    if (!isQuitting) {
      dialog.showErrorBox(APP_TITLE, "本地平台服务已退出，请重新启动应用。");
      app.quit();
    }
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
    appendShellLog(`backend kill failed: ${formatError(error)}`);
  }
}

function checkBackendHealth(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: HEALTH_CHECK_TIMEOUT_MS }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 300);
    });
    request.on("timeout", () => request.destroy(new Error("health check timeout")));
    request.on("error", reject);
  });
}

async function waitForBackend(url) {
  const startedAt = Date.now();
  let attempts = 0;
  while (Date.now() - startedAt < BACKEND_STARTUP_TIMEOUT_MS) {
    attempts += 1;
    try {
      if (await checkBackendHealth(url)) {
        appendShellLog(`backend health ok attempts=${attempts}`);
        return;
      }
    } catch (error) {
      if (attempts <= 5 || attempts % 20 === 0) {
        appendShellLog(`backend health pending attempt=${attempts}: ${error.message}`);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, HEALTH_CHECK_INTERVAL_MS));
  }
  throw new Error("本地平台服务启动超时。");
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

function createMainWindow(initialUrl) {
  const bounds = calculateWindowBounds();
  const iconPath = path.join(resolveAssetRoot(), "icon.ico");
  mainWindow = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    minWidth: bounds.minWidth,
    minHeight: bounds.minHeight,
    title: APP_TITLE,
    icon: iconPath,
    autoHideMenuBar: true,
    backgroundColor: "#f1eee8",
    show: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      backgroundThrottling: false,
    },
  });

  Menu.setApplicationMenu(null);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://127.0.0.1:") || url.startsWith("http://localhost:")) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    appendShellLog(`renderer console level=${level} source=${sourceId}:${line} message=${message}`);
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    appendShellLog(`renderer gone reason=${details.reason} exitCode=${details.exitCode}`);
  });
  mainWindow.webContents.on("did-fail-load", (_event, code, description, validatedUrl) => {
    appendShellLog(`renderer did-fail-load code=${code} description=${description} url=${validatedUrl}`);
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  mainWindow.loadURL(initialUrl);
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  stopBackend();
});

app.on("second-instance", () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
  }
});

app.whenReady().then(async () => {
  try {
    app.setName(APP_TITLE);
    try {
      const crashDumpsPath = path.join(resolveProjectRoot(), "crash-dumps");
      fs.mkdirSync(crashDumpsPath, { recursive: true });
      app.setPath("crashDumps", crashDumpsPath);
      crashReporter.start({ uploadToServer: false, compress: false });
    } catch (error) {
      appendShellLog(`crash reporter setup failed: ${formatError(error)}`);
    }
    appendShellLog(`platform desktop shell starting compatMode=${useCompatibilityMode}`);
    backendPort = await findFreePort();
    startBackend(backendPort);
    const baseUrl = `http://127.0.0.1:${backendPort}`;
    await waitForBackend(`${baseUrl}/api/v1/health`);
    createMainWindow(`${baseUrl}/user/`);
  } catch (error) {
    appendShellLog(`startup failed: ${formatError(error)}`);
    dialog.showErrorBox(APP_TITLE, String(error.message || error));
    app.quit();
  }
});
