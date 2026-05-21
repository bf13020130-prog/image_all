const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

const POLL_INTERVAL_MS = 1000;
const HEALTH_TIMEOUT_MS = 900;
const MAX_OBSERVED_LINES = 80;

const statePath = process.argv[2] || "";

function readState() {
  try {
    return JSON.parse(fs.readFileSync(statePath, "utf8"));
  } catch (_error) {
    return {};
  }
}

function writeState(patch) {
  const current = readState();
  const next = {
    ...current,
    ...patch,
    watchdogUpdatedAt: new Date().toISOString(),
  };
  try {
    fs.mkdirSync(path.dirname(statePath), { recursive: true });
    fs.writeFileSync(statePath, JSON.stringify(next, null, 2), "utf8");
  } catch (_error) {
    // Watchdog cannot report anything else if the state path is unavailable.
  }
  return next;
}

function appendLog(state, message) {
  try {
    const logPath =
      state.watchdogLogPath ||
      path.join(path.dirname(statePath || "."), "electron-watchdog.log");
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${message}\n`, "utf8");
  } catch (_error) {
    // Logging must never block the fallback.
  }
}

function isPidRunning(pid) {
  if (!pid) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch (_error) {
    return false;
  }
}

function checkHealth(url) {
  return new Promise((resolve) => {
    const request = http.get(url, { timeout: HEALTH_TIMEOUT_MS }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 300);
    });
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

function openExternal(url) {
  if (process.platform === "win32") {
    spawn("cmd.exe", ["/c", "start", "", url], {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    }).unref();
    return;
  }
  if (process.platform === "darwin") {
    spawn("open", [url], { detached: true, stdio: "ignore" }).unref();
    return;
  }
  spawn("xdg-open", [url], { detached: true, stdio: "ignore" }).unref();
}

function buildWindowsEventCommand(exePath) {
  const escaped = String(exePath || "").replace(/'/g, "''");
  const script = [
    "$ErrorActionPreference = 'Stop'",
    `$target = '${escaped}'`,
    "$targetName = [System.IO.Path]::GetFileName($target)",
    "$since = (Get-Date).AddMinutes(-10)",
    "$events = Get-WinEvent -FilterHashtable @{ LogName = 'Application'; ProviderName = @('Application Error', 'Windows Error Reporting'); StartTime = $since } -MaxEvents 30",
    "$events | Where-Object { (-not $target) -or ($_.Message -like \"*$target*\") -or ($_.Message -like \"*$targetName*\") } | Select-Object -First 6 TimeCreated,Id,ProviderName,Message | ConvertTo-Json -Compress",
  ].join("; ");
  return [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    `try { ${script} } catch { $_.Exception.Message }`,
  ];
}

function captureWindowsEventLog(state) {
  if (process.platform !== "win32" || !state.exePath) {
    return;
  }
  try {
    const child = spawn("powershell.exe", buildWindowsEventCommand(state.exePath), {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    child.stdout.on("data", (chunk) => {
      output += chunk.toString("utf8");
      if (output.length > 20000) {
        output = output.slice(-20000);
      }
    });
    child.stderr.on("data", (chunk) => {
      output += chunk.toString("utf8");
      if (output.length > 20000) {
        output = output.slice(-20000);
      }
    });
    child.on("close", (code) => {
      const normalizedOutput = output.trim();
      appendLog(state, `windows event query exit=${code} output=${normalizedOutput || "<empty>"}`);
      writeState({
        windowsEventQueryExitCode: code,
        windowsEventOutput: normalizedOutput,
      });
    });
  } catch (error) {
    appendLog(state, `windows event query failed: ${error.stack || error.message || error}`);
  }
}

async function main() {
  if (!statePath) {
    return;
  }
  let observed = [];
  let state = writeState({
    watchdogPid: process.pid,
    watchdogStartedAt: new Date().toISOString(),
  });
  appendLog(state, `watchdog started pid=${process.pid} statePath=${statePath}`);

  while (true) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    state = readState();
    const now = Date.now();
    const startedAt = Date.parse(state.startedAt || state.watchdogStartedAt || "") || now;
    const elapsedMs = now - startedAt;
    const electronRunning = isPidRunning(state.electronPid);
    observed.push({
      at: new Date().toISOString(),
      elapsedMs,
      electronRunning,
      embeddedReady: Boolean(state.embeddedReady),
      rendererUrl: state.rendererUrl || "",
      fallbackStatus: state.fallbackStatus || "",
    });
    observed = observed.slice(-MAX_OBSERVED_LINES);

    if (state.embeddedReady || state.shutdownRequested) {
      appendLog(
        state,
        `watchdog exiting embeddedReady=${Boolean(state.embeddedReady)} shutdownRequested=${Boolean(
          state.shutdownRequested
        )}`
      );
      return;
    }

    if (state.fallbackStatus === "opened" || state.fallbackStatus === "failed") {
      appendLog(state, `watchdog exiting fallbackStatus=${state.fallbackStatus}`);
      return;
    }

    const fallbackDelayMs = Number(state.watchdogFallbackDelayMs) || 28000;
    const rendererStartedAt =
      Date.parse(state.rendererLoadStartedAt || state.startedAt || state.watchdogStartedAt || "") ||
      startedAt;
    const rendererElapsedMs = now - rendererStartedAt;
    const shouldFallback =
      state.allowExternalBrowserFallback &&
      state.rendererUrl &&
      ((electronRunning && rendererElapsedMs >= fallbackDelayMs) ||
        (!electronRunning && elapsedMs >= 3000));

    if (!shouldFallback) {
      continue;
    }

    const healthUrl = state.backendHealthUrl || "";
    const backendHealthy = healthUrl ? await checkHealth(healthUrl) : false;
    const reason = electronRunning
      ? `embedded renderer timeout after ${rendererElapsedMs}ms`
      : `electron process disappeared after ${elapsedMs}ms`;
    state = writeState({
      fallbackStatus: "opening",
      fallbackReason: reason,
      backendHealthy,
      observed,
      fallbackRequestedAt: new Date().toISOString(),
    });
    appendLog(
      state,
      `fallback opening reason=${reason} backendHealthy=${backendHealthy} url=${state.rendererUrl}`
    );
    captureWindowsEventLog(state);
    try {
      openExternal(state.rendererUrl);
      writeState({
        fallbackStatus: "opened",
        fallbackOpenedAt: new Date().toISOString(),
      });
      appendLog(state, "fallback opened system default browser");
    } catch (error) {
      writeState({
        fallbackStatus: "failed",
        fallbackError: error.stack || error.message || String(error),
      });
      appendLog(state, `fallback failed: ${error.stack || error.message || error}`);
    }
    return;
  }
}

main().catch((error) => {
  const state = readState();
  appendLog(state, `watchdog fatal: ${error.stack || error.message || error}`);
  writeState({
    watchdogFatal: error.stack || error.message || String(error),
  });
});
