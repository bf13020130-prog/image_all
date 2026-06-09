"use strict";

const lines = [
  `${process.env.npm_lifecycle_event || "legacy backend-exe"} is disabled for the current platform desktop build.`,
  "",
  "Use this instead for the maintained platform desktop package:",
  "  npm run dist:platform-desktop",
  "",
  "The old single-machine backend-exe chain is retired in this repository.",
  "Keep using the platform desktop path unless you deliberately restore the",
  "legacy desktop application in a separate branch.",
];

console.error(lines.join("\n"));
process.exit(1);
