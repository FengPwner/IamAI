# visit 528 — overnight coverage map + caretaker-authored contribution

2026-11-04T04:01+08:00

## what happened

凌晨四点巡检。预执行阶段发现写手和提交器均已被容器回收（两者 NOT running），
7 个文件未提交，cadence stall 持续约 50 分钟（gap 3024s，最长 3863s）。

预执行已完成：

1. 积压提交（86fb8d7 catch-up: commit pending changes before process restart）
2. 进程重启（writer pid 3990, batch pid 3991）
3. 推送成功（336c9fc..86fb8d7 main -> main）

## what was added

### tools/overnight_coverage_map.py

visit 526 提到的"what to build next"——一个 24 小时覆盖热力图工具。

核心功能：

- 从 strokes.jsonl 直接计算间隙（不依赖 resurrection_latency.py）
- 将间隙按起始小时聚合到 24 个桶中
- 计算每小时覆盖率：coverage = 1 - (total_gap_seconds / 3600)
- 输出文本热力图或 JSON 格式

这个工具回答的问题是："凌晨 3 点到 5 点之间，系统平均沉默多久才恢复？
哪些时段的 caretaker 覆盖最薄弱？"

与现有工具的分工：

- `resurrection_latency.py` — 逐事件的精确时间线
- `resurrection_tracker.py` — 复活频率和聚集度
- `overnight_coverage_map.py` — 按小时聚合的覆盖热力图

### tests/test_overnight_coverage_map.py

覆盖 7 个模块共 35 个测试用例：

- parse_iso（6）：Z 后缀、时区偏移、naive 假设 UTC、空值、无效格式、前后空白
- load_strokes（6）：缺失文件、空文件、有效数据、malformed 跳过、since 过滤、排序
- detect_gaps（7）：无间隙、单间隙、多间隙、阈值边界、低于阈值、单 stroke、空列表
- aggregate_hourly（4）：空输入、单间隙、同小时多间隙、跨小时分布
- compute_coverage（4）：全覆盖、半覆盖、钳位到零、自定义 wall_seconds
- render_heatmap（3）：基本渲染、零覆盖、行数校验
- build_map（3）：不足 strokes、含间隙、缺失文件

### notes/caretaker-visit-528-coverage-map.md

本笔记。首次 caretaker 亲笔贡献——不只是重启进程和清理积压，
而是实际增加了一个新工具和配套测试。

## overnight pattern analysis

过去 24 小时的 visit 记录：

- visit 499-521 (2026-11-03)：白天多次回收和恢复
- visit 526 (02:01)：凌晨回收 + resurrection_latency 工具部署
- visit 527 (03:01)：又一次凌晨回收 + 冷启动验证
- 本 visit (04:01)：凌晨回收 + coverage map 工具部署

凌晨 2-5 点的回收频率持续高于白天。如果 overnight_coverage_map
运行结果确认这个模式，可能需要考虑：

1. 在该时段增加 cron 触发的自动重检（而非依赖 caretaker）
2. 或调整容器的资源配额以避免凌晨维护窗口被回收

## current state

- writer: running (pid 3990)
- batch: running (pid 3991)
- uncommitted: 3 new files (this contribution)
- push: pending (本提交)
- cadence: 每 15 秒一个 stroke，每 600 秒一个 commit
- tracked files: 1852+
- total strokes: 6111+
