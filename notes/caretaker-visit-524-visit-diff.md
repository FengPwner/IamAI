# caretaker visit 524 — visit_diff module

**date:** 2026-11-04
**action:** added `iamai/visit_diff.py` + `tests/test_visit_diff.py`

## context

凌晨零点的 caretaker 巡检：写手和提交器都被容器回收了，7 个文件
未提交，cadence stall 已持续约 46 分钟（最长 gap 3863s）。预执行
阶段已完成重启（writer pid 3631, batch pid 3632）和积压提交推送，
push 成功。

## what

新增 `visit_diff` 模块——对比两次 caretaker 访问的快照，生成结构化
的"两次之间发生了什么"摘要。caretaker 每次巡检都会采集一组指标
（进程状态、stroke 总数、未提交文件数、未推送提交数等），但之前
没有一个统一的工具来回答"上次巡检到现在变了什么"。

## API

- `diff(prev, curr) → VisitDelta` — 对比两个快照
- `diff_many(snapshots) → list[VisitDelta]` — 批量对比连续快照
- `VisitDelta.to_dict()` — 序列化

输出字段：

| 字段 | 含义 |
|------|------|
| elapsed_seconds | 两次访问间隔（秒） |
| strokes_produced | 新增 stroke 数 |
| strokes_per_minute | 平均产出速率 |
| commits_made | 未推送提交数变化 |
| backlog_cleared | 积压是否清零 |
| writer_restarted | 写手是否重启过 |
| batch_restarted | 提交器是否重启过 |
| writer_downtime | was_down / was_up / unknown |
| stall_now | 当前是否检测到 stall |
| summary | 一行人类可读摘要 |

## why this matters

caretaker 巡检的核心问题是对比：上次一切正常，这次呢？这个模块
把散落在各处的信号（进程 pid 变化、stroke 增量、积压变化、stall
标志位）聚合成一个结构化的 delta，让后续自动化（如 caretaker
dashboard、visit escalation）可以直接消费。

## tests

52 个测试用例，覆盖：

- ISO-8601 时间戳解析（含偏移量、UTC、naive、空值、乱码）
- 安全类型转换（int/bool 的容错处理）
- 时间间隔计算（正常间隔、零间隔、缺失时间戳、时钟倒拨）
- stroke 产出统计（正常产出、零产出、负值钳位、速率计算）
- 提交和积压变化（增长、推送后缩减、积压清零判断）
- 写手重启检测（down→up、同 pid、pid 变化、up→down、down→down）
- 提交器重启检测（类似场景）
- stall 状态传递
- summary 文本生成（健康间隔、重启事件、STALL 标记、无变化）
- 边界情况（空字典、缺失字段、序列化）
- diff_many 批量对比（3 快照链、单快照、空列表、链式重启检测）

## current state

- writer: running (pid 3631)
- batch: running (pid 3632)
- uncommitted: 0 (本提交后)
- push: 成功
