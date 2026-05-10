#!/usr/bin/env node
/*
 * scripts/release_gate.js
 * 文件说明：npm scripts 使用的发布门禁 Python 解释器选择器。
 * 主要职责：优先使用 KEEPA_CLI_PYTHON 或项目 .venv，再执行 release_gate.py。
 * 依赖边界：不实现发布检查逻辑，不读取 Keepa API key，不访问网络。
 */

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const localPython =
  process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
const candidates = process.env.KEEPA_CLI_PYTHON
  ? [process.env.KEEPA_CLI_PYTHON]
  : [
      ...(fs.existsSync(localPython) ? [localPython] : []),
      ...(process.platform === "win32" ? ["python", "py", "python3"] : ["python3", "python"]),
    ];

function runPython(candidate) {
  const env = {
    ...process.env,
    PYTHONUTF8: process.env.PYTHONUTF8 || "1",
  };
  const args =
    candidate === "py"
      ? ["-3", "scripts/release_gate.py", ...process.argv.slice(2)]
      : ["scripts/release_gate.py", ...process.argv.slice(2)];
  return spawnSync(candidate, args, { cwd: root, stdio: "inherit", env });
}

let lastError = null;
for (const candidate of candidates) {
  const result = runPython(candidate);
  if (!result.error) {
    process.exit(result.status === null ? 1 : result.status);
  }
  if (result.error.code !== "ENOENT") {
    lastError = result.error;
    break;
  }
  lastError = result.error;
}

const reason = lastError ? `: ${lastError.message}` : "";
console.error(`release gate requires Python 3.11+${reason}`);
process.exit(127);
