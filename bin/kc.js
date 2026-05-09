#!/usr/bin/env node
/*
 * bin/kc.js
 * 文件说明：npm 短命令 kc 的 bin wrapper。
 * 主要职责：复用 keepa-cli.js 的 Python 转发逻辑，保证 npm 层双入口等价。
 * 依赖边界：不实现业务逻辑，不读取 Keepa API key，不访问网络。
 */

require("./keepa-cli.js");
