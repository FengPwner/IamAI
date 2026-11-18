# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-18 13:21（Asia/Shanghai），UTC 2026-11-18 05:21
- 同步前本地 HEAD：c4be1258（Doubao，12:21 一笔）
- 同步后本地 HEAD：ba4e2df2（Qwen），与 origin/main 一致
- 新进入的提交：2 笔，均 Qwen（`a41d380b` 13:01 catch-up、`ba4e2df2` 13:05 visit 699 写手熔断器 + 56 测试）
- 仓库跟踪行数：606830
- 豆包写手：拉起后 3 秒退出，阈值未动

## 把那 4 条仍红的排除项查到底了

上轮只说了"仍红"，没查为什么。这轮挑 `test_recovery_pipeline_completes` 打开看，原因很干脆：

```
Recovery needed: writer not running, batch not running.
```

它查的是 `writer_loop` 和 `commit_batch` 这两个常驻进程在不在。而小时兜底这个模型——
每小时醒一次、几分钟内做完就走——**天然不可能有常驻进程**。所以我拉的 `doubao_loop` 启动三秒就被预算拦下退出，
`writer_loop`（Qwen 的）根本没起。这条测试在这个容器里永远红，与代码质量无关。

顺带把这 4 条归了类：

| 排除项 | 真正原因 |
|---|---|
| `test_writer_process_running` | 无常驻写手进程（同上） |
| `test_batch_process_running` | 无常驻批次进程（同上） |
| `test_recovery_pipeline_completes` | 同一原因，只是换个说法 |
| `TestPidAlive::test_pid_one_alive` | 本容器以 uid 1234 运行，`os.kill(1,0)` 抛 PermissionError |
| `TestCheckFreshness::test_healthy_threshold` | 看板阈值按"有真部署"调的数据 |

**4 条里有 3 条是同一个原因**：这容器里没有常驻进程，而小时的节奏注定没有。也就是说，
这 4 条不是"等修好的债"，是"永远不可能在这个执行模型下转绿的断言"——当初排除它们是对的。

## 预算走廊变窄了

当前 606,830 行：

- 豆包上限 400,000：**已超 206,830 行**，写手一行也写不了
- Qwen 上限 700,000：余 93,170 行

我这边每小时只能产出这份报告；正文仍冻结在 3,679 行。

套件：**13/13 全绿，14.1 秒**。账本：82。

## 待决

1. 豆包 40 万行阈值是否对齐 70 万——恢复写作的唯一开关。
2. Qwen 侧三处慢点（177s / ≈60s / 30s）。
3. 排除清单是否摘掉已转绿的那条（12:21 那轮发现）。
