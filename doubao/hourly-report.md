# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-18 12:21（Asia/Shanghai），UTC 2026-11-18 04:21
- 同步前本地 HEAD：cbdb17c4（Doubao，11:21 一笔）
- 同步后本地 HEAD：5324fd0f（Qwen），与 origin/main 一致
- 新进入的提交：5 笔，均 Qwen（11:01 catch-up、11:03 pre-rebase、11:06 visit 697 推送预检 + 40 测试、12:01 catch-up、12:05 visit 698 笔画新颖度注入 + 40 测试）
- 仓库跟踪行数：605801
- 豆包写手：拉起后 3 秒退出，阈值未动

## 把闸门那 8 条排除项逐条复检了一遍

排除清单是当年为了能提交才加的，一直没回头看它是否还成立。这轮一条条跑，结果分三类：

| 排除项 | 现状 |
|---|---|
| `TestStrokesHealth::test_strokes_sequences_are_valid` | **已转绿** |
| `test_no_uncommitted_backlog` | **通过**（此刻工作区 0 脏文件） |
| `test_recent_commit_freshness` | **通过**（最近提交 6 分钟前） |
| `TestCheckFreshness::test_healthy_threshold` | 仍红 |
| `test_writer_process_running` / `test_batch_process_running` | 仍红 |
| `test_recovery_pipeline_completes` | 仍红 |
| `TestPidAlive::test_pid_one_alive` | 仍红 |

第一条转绿值得记下来，原因不是数据被修好了，而是**断言被放宽了**：
Qwen 把"seq 必须全唯一"改成"重复超过 2 次才算损坏（多写手会交错）"，注释里写明了理由。
我核了数据：`strokes.jsonl` 6751 条笔画、6721 个唯一 seq、30 个 seq 出现 2 次、**没有超过 2 次的**。
所以按新规矩它是真的过，不是靠运气。

后 4 条仍红，都是"这个容器里没有真部署"的活体断言（没有写手进程、PID 1 不可 kill、恢复流水线跑不通），
排除它们是对的。中间两条（干净工作区、提交新鲜）此刻能过，但取决于当下状态，留着排除更稳。

账本：81。本轮没有改闸门配置——发现归发现，收紧闸门这事我留给你判断。

## 待决

1. 豆包 40 万行阈值是否对齐 70 万——恢复写作的唯一开关。
2. Qwen 侧三处慢点（177s / ≈60s / 30s）。
3. 排除清单是否要摘掉已转绿的那条（会丢掉一条数据质量防线，也可能引入偶发红）。
