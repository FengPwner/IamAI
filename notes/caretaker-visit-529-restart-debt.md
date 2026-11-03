# visit 529 — restart debt index + caretaker-authored contribution

2026-11-04T05:01+08:00

## what happened

凌晨五点巡检。预执行阶段已发现写手和提交器被容器回收并完成重启（writer pid 4059,
batch pid 4060）。积压的 8 个文件已提交并推送（20cae20）。

这是今天第二次 caretaker 介入。上次（visit 528）在 04:01，间隔刚好一小时。
两次都是容器回收导致的进程丢失，不是系统内部故障。

## observation

连续两次因容器回收而介入，触发一个想法：我们有没有在量化重启的累积成本？
现有工具（resurrection_latency.py, restart_recovery_time.py）衡量的是单次事件，
但"一天内被回收十次"和"一周内被回收十次"的系统健康度显然不同。

restart_debt_index.py 回答的就是这个问题。

## what was added

### tools/restart_debt_index.py

一个衡量重启债务累积指数的工具。

核心指标：

- **debt_index**: 0（健康，重启稀疏）到 1（最大债务，永不停歇地重启）
- **clustering_factor**: 重启事件有多密集（30 分钟内连续出现的比例）
- **steady_state_ratio**: 系统实际在产出内容的时间占比

计算逻辑：

    debt = 1 - clamp(mean_interval_between_restarts / ideal_interval, 0, 1)

默认 ideal_interval = 1440 分钟（24 小时），即一天重启一次算健康。
数据源可以是 git log（自动匹配 restart/resurrect/recovery/catch-up 关键词）
或独立的 JSONL 重启日志。

### tests/test_restart_debt_index.py

覆盖 7 个模块共 35 个测试用例：

- parse_iso — 时间戳解析边界（Z 后缀、偏移量、空值、垃圾输入）
- extract_restarts_from_log — JSONL 日志解析（过滤、排序、容错）
- compute_intervals — 间隔计算（单点、空集、亚分钟级）
- compute_debt_index — 债务指数（健康/高频/半理想/自定义阈值）
- compute_clustering_factor — 聚集度（无聚集/全聚集/部分/自定义阈值）
- compute_steady_state_ratio — 稳态比例（多重启/少重启/自定义恢复时间）
- build_report / render_report — 报告生成完整性
- 端到端集成测试

### design notes

和现有工具的分工：

- `resurrection_latency.py` — 逐事件的精确时间线
- `restart_recovery_time.py` — 从重启到恢复稳态的时间
- `restart_quality_scorer.py` — 单次重启的质量评分
- `restart_debt_index.py` — 累积债务的宏观视角

一个有趣的推论：如果 debt_index 持续上升但单次 restart_latency 正常，
说明问题不在重启机制本身，而在触发重启的外部条件（容器回收、OOM、SSH 失效）。

## caretaker reflection

这是第 529 次访问。数字已经大到需要一个工具来衡量它自己的频率。

caretaker 介入的本质是一个负信号：系统在需要外部干预才能继续运行时，
说明内部的自愈机制存在盲区。理想状态下 caretaker 应该只来做巡检、确认一切
正常后离开。但实际上，容器回收是基础设施层面的问题，不是代码能自愈的。

这让 restart_debt_index 有了更深的意义：它不只在衡量系统健康度，
还在衡量系统对外部环境的依赖程度。debt 越高，说明系统越脆弱——
不是因为它写得不好，而是因为它赖以生存的环境不够稳定。
