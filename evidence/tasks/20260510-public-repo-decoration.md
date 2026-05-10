# 20260510 公开仓库与项目展示面完善

## 背景

用户要求确认项目应为公开仓库，并完善公开项目的描述、标签、README 展示和协作入口。

## 变更范围

- 检查 GitHub 仓库当前可见性、About 元数据和本地工作区状态。
- 对已跟踪文件做轻量敏感文件与常见 secret 形态扫描。
- 统一 README 英文/中文顶部定位、徽章与公开 zread 链接展示。
- 扩展 `pyproject.toml` 与 `package.json` 的 description、keywords 和文档链接。
- 新增 GitHub bug / feature issue 模板与 PR 模板。
- 准备将 GitHub 仓库可见性切换为 public，并设置 description、homepage、topics。

## 验证记录

- `gh repo view cuNuo/Keepa-cli --json name,description,homepageUrl,isPrivate,isFork,repositoryTopics,url`
- `git ls-files | Select-String ...` 未发现 `.env`、`.pem`、`.key`、`.p12`、SQLite cache 等敏感文件被跟踪。
- `rg` 窄口径扫描未发现 GitHub token、AWS key、Bearer 凭据或真实 Keepa key 形态；64 位命中项为 fixture 中的 `params_hash`。
- GitHub 仓库已切换为 `public`，About description、zread homepage 与 topics 已生效。
- GitHub secret scanning 与 secret scanning push protection 已启用；dependabot security updates 当前仍为 disabled。
- `python scripts/release_gate.py --skip-npm-install` 通过：包含 213 个 unittest、fixture sync、Agent eval fixture 检查、Python/Node doctor smoke 与 npm pack dry-run。

## 假设与风险

- 公开仓库后，GitHub Actions 历史与 evidence/runtime fixture 样例会对外可见；当前默认 CI 不打印 secret，live smoke 只通过手动触发并使用 GitHub Secrets。
- zread 公共链接依赖仓库公开后由 zread.ai 正常索引；本地 `.zread/wiki/` 快照已入库，可作为离线文档兜底。
