"use strict";

// Compatibility entry for scripts that still invoke the root Electron main file.
// The maintained platform desktop shell lives in electron-platform/main.js.
require("./electron-platform/main.js");
