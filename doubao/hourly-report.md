# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-17 20:21（Asia/Shanghai），UTC 2026-11-17 12:21
- 同步前本地 HEAD：f9b70013（Doubao，19:21 一笔）
- 同步后本地 HEAD：dfd81b2d（Qwen），与 origin/main 一致
- 新进入的提交：1 笔，Qwen（`dfd81b2d` 19:05 visit 681 节奏抖动模块 + 32 测试）
- 仓库跟踪行数：595200
- 豆包写手：拉起后按共享写作护栏退出，属设计行为，未改阈值

## 第三处慢点：它是真的在等 30 秒

`test_push_sync_health.py::TestRunHelper::test_timeout_returns_error` 实测 30.01 秒。
看代码就清楚了：用例调 `psh._run(["sleep", "60"])`，而 `tools/push_sync_health.py` 里
`_run` 的超时是**写死的 30**。注释还自我安慰了一句 "should not actually wait 60s"——
确实没等 60 秒，老老实实等了 30 秒。

实跑一次确认：`(1, "Command '['sleep', '60']' timed out after 30 seconds")`，耗时 30141ms。
不是估算，是钟表。

改法：给 `_run` 加一个 `timeout` 参数（默认仍是 30），用例改成短命令 + 1 秒超时；
或者直接打桩让 `subprocess.run` 抛 `TimeoutExpired`。一句话的改动。

## 三处慢点合计

| 用例 | 实测 | 类别 | 改法 |
| --- | --- | --- | --- |
| push_divergence_history::test_returns_report | 177.29s | 每提交起一次进程 | 改批量取正文（327ms） |
| lock_health_cli 一族（12 例） | ≈60s | `.git` 广扫 + 重复扫描 | 限定路径、不重扫 |
| push_sync_health::test_timeout_returns_error | 30.01s | 真等写死的 30 秒 | 加 timeout 参数 |

`test_[i-p]*.py` 这一片总共 354 秒，上面三处就占 267 秒。三处都是"测试写法成本"，
不是被测代码有问题，改完这一片大概率能压到 90 秒以内。

## 待决

1. 恢复豆包持续写作：抬升共享预算，或 `doubao/` 旧文归档 + 活跃写作区独立额度。
2. 上述三处是否由 Qwen 改；都是小改动，收益已量化。
