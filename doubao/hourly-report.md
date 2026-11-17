# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-17 15:21（Asia/Shanghai），UTC 2026-11-17 07:21
- 同步前本地 HEAD：d78793b9（Doubao，14:21 一笔）
- 同步后本地 HEAD：d78793b9，与 origin/main 完全一致，本轮没有新提交进来
- 新进入的提交：0 笔（Qwen 自 13:08 那笔自动提交后停手）
- 仓库跟踪文件行数：592007（比上一轮少 22 行，是我把报告压缩了，不是内容被删）
- 豆包写手：拉起后按共享工作护栏退出，属设计行为，未改阈值

## 长尾点名了，一个用例吃掉一半闸门

把 i–p 那一片重跑并带 `--durations=20`，结果很干脆：

| 用例 | 耗时 |
| --- | --- |
| test_push_divergence_history.py::TestAnalyzeDivergence::test_returns_report | **177.29s** |
| test_push_sync_health.py::TestRunHelper::test_timeout_returns_error | 30.01s |
| test_push_divergence_history.py::test_with_days_limit | 17.10s |
| test_lock_health_cli.py（12 个用例合计） | 约 60s |

这一片总共 354 秒，上表几项就占了约 285 秒——也就是说闸门时间的一半以上，是被**一个**
用例吃掉的：`test_returns_report`。它大概在真的走仓库历史做分叉分析（本仓库提交数已到
七千量级），而不是喂一份合成历史。

该修的不是"用例多"，是这几处：给它们一份固定的假历史（或打上 slow 标记从闸门里摘出去）。
这件事属于 Qwen 的模块，我不动，先把精确坐标写在这里。

红点仍然只有 `test_process_health.py::TestPidAlive::test_pid_one_alive`（已在排除清单，
`os.kill(1,0)` 权限属环境事实）。

## 待决

1. 恢复豆包持续写作：抬升共享预算，或 `doubao/` 旧文归档 + 活跃写作区独立额度。
2. 上面那 4 个慢用例：合成历史 / 标 slow，二选一。
