const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const rcedit = path.join(root, "node_modules", "electron-winstaller", "vendor", "rcedit.exe");
const icon = path.join(root, "electron", "icon.ico");
const unpackedExe = path.join(root, "dist-electron", "win-unpacked", "设计出图.exe");
const tempExe = path.join(root, "dist-electron", "win-unpacked", "design-output-icon-temp.exe");

for (const filePath of [rcedit, icon, unpackedExe]) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing required file: ${filePath}`);
  }
}

fs.copyFileSync(unpackedExe, tempExe);

try {
  const result = spawnSync(rcedit, [tempExe, "--set-icon", icon], {
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
  fs.copyFileSync(tempExe, unpackedExe);
} finally {
  fs.rmSync(tempExe, { force: true });
}

console.log(`win-unpacked exe icon updated: ${unpackedExe}`);
