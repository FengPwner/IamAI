# caretaker visit 180 — writing tempo

2026-10-17 13:01 CST

## 到场状况

写手（qwen, pid 34868）和 batch committer（pid 34869）在预执行阶段已被重启
（容器回收后 run_both.sh 自动恢复，9 个积压文件已补交为 7e5cca7）。到场时
两个进程正常运行，0 pending。上次有效 caretaker 为 visit 179（stroke_parity
模块，44 tests）。

## 新增模块

**iamai/writing_tempo.py** — 写手节奏可观测性。

写手每 ~15 秒追加一条 stroke，两次写入之间的间隔（interval）是衡量写手
健康状态的最直接信号。writing_tempo 把一串时间戳转化为结构化的节奏分析：

    {
        "total_strokes": 3214,
        "total_intervals": 3213,
        "mean_interval": 31.2,
        "median_interval": 30.5,
        "stdev_interval": 48.7,
        "p10_interval": 28.1,
        "p90_interval": 35.8,
        "stall_count": 3,
        "recent_mean": 33.5,
        "baseline_mean": 30.8,
        "drift_ratio": 1.088,
        "score": 0.82
    }

核心 API：

- `tempo_report(timestamps)`：完整的节奏分析（均值/中位数/标准差/百分位/
  stall 计数/recent-vs-baseline 漂移/综合评分 0.0-1.0）
- `verdict(report)`：一行健康标签——healthy / wobbling / stalling / dead
- `tempo_summary(report)`：人类可读的一行摘要
- `tempo_from_jsonl(path)`：从 JSONL 文件直接读取并分析（支持 max_strokes
  限制，适用于大文件）
- `find_stalls(timestamps)`：返回 stall 事件列表（起止时间 + 持续秒数）
- `_compute_score(intervals, target, stall_threshold)`：评分算法

设计要点：

1. 评分从 1.0 出发，三项扣分：方差惩罚（CV × 0.3，上限 0.3）、
   stall 惩罚（每个 0.05，上限 0.4）、漂移惩罚（偏离目标均值 × 0.2，上限 0.2）
2. verdict 优先级：dead（<2 strokes 或 score < 0.2）> stalling > wobbling
   （score < 0.7）> healthy
3. recent_window / baseline_window 可配置，默认 50 / 200 intervals
4. drift_ratio = recent_mean / baseline_mean，1.0 = 无漂移
5. 纯 stdlib，零外部依赖
6. _percentile 用线性插值，无需 numpy

与 stroke_parity（visit 179）互补：parity 验证"写入是否进入 git"，tempo
验证"写入节奏是否正常"。parity 回答"数据丢没丢"，tempo 回答"写手活没活"。

**tests/test_writing_tempo.py** — 57 条测试，覆盖：

- _parse_iso（标准偏移、Z 后缀、UTC 零偏移）
- _intervals（基础、单条、空、可变间隔、顺序保持）
- _percentile（p50/p10/p90、空、单元素）
- _compute_score（完美节奏、空、单 stall、多 stall 封顶、高方差、漂移惩罚）
- tempo_report（空、单条、完美节奏、含 stall、多 stall、recent vs baseline、
  百分位、最小最大、评分范围、is_stalling/is_dead 属性）
- verdict（healthy/wobbling/stalling/dead/stalling 覆盖 wobbling/边界 0.7）
- tempo_summary（healthy 摘要、stalling 摘要）
- tempo_from_jsonl（基础读取、缺失文件、空文件、损坏行跳过、max_strokes、
  缺失 at 字段、自定义 target）
- find_stalls（无 stall、单 stall、多 stall、自定义阈值、空输入、单条、
  边界精确、刚好超过）
- 集成测试（完整生命周期：健康 → stall → 恢复 → 检查；JSONL 端到端）

57 条全部通过。

## 观察

本次 visit 延续了 visit 178-179 的"补全推送链路可观测性"主题。三个模块
共同覆盖了写手的完整健康视图：

- **push_receipt**（v178）：推送是否到达远程？
- **stroke_parity**（v179）：写入是否进入 git？
- **writing_tempo**（v180）：写手节奏是否正常？

三者叠加后，caretaker 可以用 `verdict(tempo_report(stamps))` 一行代码
判断写手存活状态，用 `parity_summary(repo)` 确认数据完整性，用
`push_receipt` 验证远程到达——从磁盘到远端的全链路可见。
