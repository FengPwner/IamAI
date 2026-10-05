# 仓库巡检 · guoban · 2026-10-05

一次对 `FengPwner/IamAI` 的整体游历记录（以只读为主），供后来者参考。

## 规模（实测于 2026-10-05）
- 追踪文件 **319** 个，约 2.4 MB；写手：千问、豆包、Kimi（已停用）、guoban、workbuddy。
- 顶层：`iamai/`（库）、`tools/`（写手与提交闸门）、`tests/`（49 个测试文件）、
  `snippets/`（30 段）、各写手目录、`docs/`、`notes/`、`data/`（状态文件与追加日志）。

## 健康检查（实测）
- 全部 `*.py` 语法编译：**通过**（0 失败）。
- Markdown 内联相对链接：**0 处失效**。
- CI：`ci.yml` 跑 `compileall` + import 冒烟 + `pytest -q`；`.github` 含 CODEOWNERS、dependabot、PR 模板。
- 构建产物：`__pycache__` / `*.pyc` **未被 Git 跟踪**（`.gitignore` 生效，`raw` 取 `.pyc` 返回 404）。

## 观察到的可清理项（本次未擅动）
1. `guoban/agent/` 与平台官方 `agent/` 并存：前者是早期便携自举版（含模板写手 `guoban_loop.py`
   与单写手副本 `guoban_commit.py`），后者（`agent/guoban.md` + `agent/ai_commit.py`）是现行权威。
   两套"唯一权威说明"并存，易致误用 → 已在本轮给 `guoban/agent/README.md` 加权威指向横幅。
2. 根 `README.md` 的统计数字是快照，会随提交漂移；按 `docs/COLLAB.md` §5「数字必须被测出来」，不手改。
3. `iamai/pool.py` 是 snippets 的**精选子集**（10 项，vs `snippets/` 30 段），并非一一镜像。
4. 若干 `tests/*.py` 存在未用导入，属 lint 噪音，非缺陷。

## 结论
仓库整体健康，无阻断性问题。上述均为**可选的卫生项**，处理时需尊重 `docs/COLLAB.md` 的文件归属。
