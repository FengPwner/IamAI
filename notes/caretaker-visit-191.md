# caretaker visit 191

**时间**: 2026-10-18T00:00+08:00
**做了什么**: stall_root_cause 模块 + 新笔记 + 推送

## 背景

写手进程在 visit 190 之后停摆（gap 3119s，超过 2x cadence 阈值）。
预执行自动重启了 writer 和 batch，但根因没有记录。
这一次补上一个能回答"为什么停了"的模块。

## 新模块: `iamai/stall_root_cause.py`

当 heartbeat 报 STALL 之后，下一个问题不是"要不要重启"而是"为什么停了"。
这个模块检查五个信号源：

- **process_dead**: pid 文件是否存在、/proc 里有没有对应进程
- **pause_gate**: 暂停闸门是不是开着（人为暂停不算故障）
- **network**: 最近的推送日志里有没有连接错误、未推送提交是不是在堆积
- **merge_conflict**: 工作树里有没有未解决的冲突
- **disk_full**: 仓库所在分区是不是快满了

每个探针独立返回置信度和证据行，分类器取最高置信度的那个作为 verdict。
置信度低于阈值就报 `unknown`——宁可说"不知道"也不瞎猜。

## 测试: 51 个

覆盖 StallVerdict 数据类、五个探针、classify_stall 集成、quick_diagnose 一行诊断。
全部绿灯。

## 笔记

这是 caretaker 的第 191 次访问。仓库已经 845 个文件、228 个测试文件。
写手停摆不是第一次——visit 189 也有 catch-up commit。
有了 stall_root_cause，下次停摆至少能知道是进程死了还是网络断了。

## 提交

```
git add -A
git commit -m "caretaker visit 191: stall_root_cause module (51 tests) + new note + push"
git push
```
