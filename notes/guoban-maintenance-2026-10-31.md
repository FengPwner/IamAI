# guoban 仓库维护 · 2026-10-31

应仓库主人要求做一次维护。数字全部实测。

## 测得的当前规模
- 提交：**2349**（GitHub commits API 的 `Link: rel="last"`）
- 追踪文件：**1615**（main 分支 tarball 解包计数）
- 测试函数：**13323** 个 `def test_`，分布在 `tests/` 的 **436** 个文件里
- Python 文件：**1069**
- 总行数：**364517**

## 检查了什么
- **语法/导入冒烟**：`python3 -m compileall -q <repo>` → 退出码 0，全部模块可编译。
- **失效链接**：所有 `.md` 的内联相对链接逐一解析 → **0 处失效**（共 5 条相对链接）。
- **重复文件**：全仓按内容 SHA-256 去重 → **0 组重复**。
- **空文件**：**0 个**。
- 说明：本沙箱没有 `pip` / `pytest`，**无法真正跑测试套件**；CI 在 GitHub Actions 上跑 `pytest -q`。

## 修了什么（信息时效性）
- `README.md`：顶部实测快照 `2026-10-21 · 1774 提交 / 1055 文件 / 7733 测试` → `2026-10-31 · 2349 提交 / 1615 文件 / 13323 测试`；结构表里 `7733 个测试函数` → `13323`。
- `docs/COLLAB.md`：`python3 -m pytest -q  # 7733 个测试` → `13323 个测试`。
- `CHANGELOG.md`：在 `[Unreleased]` 下补一条本次维护。

## 没动什么（以及为什么）
- `docs/DEVLOG.md` / `docs/GARDEN.md` / `docs/METRICS.md` / `notes/*.md` 里的大量旧数字**一律不改**——它们是**带时间戳的历史流水**，改掉等于篡改记录。
- `docs/METRICS.md` 由自动流程再生成，不手改。
- 其它写手目录（`doubao/` `kimi/` `workbuddy/` 等）**一个字没碰**。

## 如何复验
`git ls-files | wc -l`（文件数）、`grep -rc 'def test_' tests | awk -F: '{s+=$2} END{print s}'`（测试数）、`git rev-list --count HEAD`（提交数）。
