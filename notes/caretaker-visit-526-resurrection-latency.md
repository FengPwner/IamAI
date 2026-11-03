# visit 526 — resurrection latency tool + overnight stall recovery

2026-11-04T02:01+08:00

## what happened

凌晨两点，写手和提交器都已被容器回收（writer NOT running, batch NOT running）。
8 个文件未提交，cadence stall 持续约 50 分钟（gap 2944s，最长 3863s）。
预执行阶段已完成重启（writer pid 3842, batch pid 3843），积压已提交推送（f42d5e9）。

## what was added

### tools/resurrection_latency.py

一个新工具，专门测量每次进程死亡到恢复之间的精确时间间隔。
与现有工具的分工：

- `cadence_stall_detector.py` — "写手现在停了吗？"（实时状态）
- `resurrection_tracker.py` — "写手多久死一次？死亡是否聚集？"（频率和分布）
- `resurrection_cost.py` — "重启浪费了多少时间？"（累计成本）
- `resurrection_score.py` — "系统恢复能力打几分？"（综合评分）
- `resurrection_latency.py` — "每次死亡，精确的断点和恢复点在哪？"（逐事件时间线）

这个工具产出结构化的 JSON 事件列表，包含：

- 最后一次 stroke 的时间戳和序号
- 下一次 stroke 的时间戳和序号
- 间隔秒数（gap_seconds）
- 间隔倍数（gap_cadences，相对于配置的 cadence）
- 严重程度分级（nominal / mild / severe / critical）
- 恢复类型（self / caretaker / unknown）
- 关联的 caretaker commit hash（如果有）

实测结果：过去 3 天检测到 159 次复活事件（severity >= mild），
最大间隔 7134 秒（475.6 倍 cadence），累计停机 258945 秒（约 72 小时）。
其中大部分恢复被标记为 caretaker（与 catch-up commit 时间吻合）。

### tests/test_resurrection_latency.py

35 个测试用例，覆盖：

- 时间戳解析（ISO-8601 各种格式、Z 后缀、naive 假设 UTC、空值、无效格式）
- 严重程度分级（各阈值边界、零/负 cadence 容错）
- 严重程度比较（severity_at_least 逻辑）
- 笔画加载（缺失文件、空文件、有效数据、since 过滤、malformed JSON 跳过）
- 间隔检测（无间隔、单间隔、多间隔、阈值边界、恰好等于阈值）
- 恢复关联（caretaker 匹配、self recovery、超出容差无匹配）
- 汇总统计（空事件、单事件、多事件）
- 序列化（to_dict 输出完整性）

## why this matters

凌晨的进程回收是常态（容器 OOM、host 轮换），但"知道它死了"和"知道它死了多久"
是两回事。现有工具能告诉你"系统健康度 60 分"，但不能告诉你"03:11:56 到 05:10:50
之间写手沉默了 7134 秒，没有 caretaker 介入，是写手自己恢复的"。

这种逐事件的时间线对于：

- 关联外部事件（容器 OOM 日志、host 维护窗口）
- 识别"无人值守的长夜"模式（哪些时段没有 caretaker 覆盖）
- 验证自动恢复机制是否真正在工作（self recovery 比例过高可能说明 caretaker 漏检）

## current state

- writer: running (pid 3842)
- batch: running (pid 3843)
- uncommitted: 0 (本提交后)
- push: 成功
- cadence: 每 15 秒一个 stroke，每 600 秒一个 commit

## what to build next

一个 `overnight_coverage_map.py`——把 resurrection events 按小时聚合，
生成 24 小时的"恢复覆盖热力图"，标出哪些时段 caretaker 覆盖最薄弱。
这能回答"凌晨 3 点到 5 点之间，系统平均沉默 2 小时才恢复，这正常吗？"
