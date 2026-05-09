#!/usr/bin/env node
/*
 * bin/keepa-cli.js
 * 文件说明：npm bin wrapper，用于把 keepa-cli/kc 转发到 Python 模块。
 * 主要职责：定位可用 Python 解释器，设置 PYTHONPATH，并执行 python -m keepa_cli。
 * 依赖边界：不实现业务逻辑，不读取 Keepa API key，不访问网络。
 */

const { spawnSync } = require("node:child_process");
const path = require("node:path");

const packageRoot = path.resolve(__dirname, "..");
const candidates = process.env.KEEPA_CLI_PYTHON
  ? [process.env.KEEPA_CLI_PYTHON]
  : process.platform === "win32"
    ? ["python", "py", "python3"]
    : ["python3", "python"];

function runPython(candidate) {
  const env = {
    ...process.env,
    PYTHONPATH: process.env.PYTHONPATH ? `${packageRoot}${path.delimiter}${process.env.PYTHONPATH}` : packageRoot,
  };
  const args = candidate === "py" ? ["-3", "-m", "keepa_cli", ...process.argv.slice(2)] : ["-m", "keepa_cli", ...process.argv.slice(2)];
  return spawnSync(candidate, args, { stdio: "inherit", env });
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
console.error(`keepa-cli requires Python 3.11+ on PATH${reason}`);
process.exit(127);
