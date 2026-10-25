# caretaker visit 181 — incarnation lineage

2026-10-17 14:00 CST

## 到场状况

预执行阶段检测到写手（qwen）和 batch committer 均已被回收（进程消失，9 个
积压文件未提交）。系统自动补交为 e8dec7b 并重启了两个进程（writer pid 34833,
batch pid 34834）。到场时两个进程运行正常，0 pending。上次有效 caretaker
为 visit 180（writing_tempo 模块，57 tests）。

## 新增模块

**iamai/incarnation.py** — 进程生命周期谱系追踪。

写手和 batch committer 运行在容器中，会被运行时周期性回收并重启。每次
重启产生一个新的进程实例——一个"化身"（incarnation）——继承上一个会话的
状态（stroke 序号、git HEAD、pending 文件）。

已有的模块各有侧重：
- ``uptime_tracker`` / ``process_uptime``：当前会话已运行多久？
- ``restart_audit``：stroke 历史中的间隙属于 stall 还是 restart？
- ``restart_cooldown`` / ``restart_budget``：重启频率是否过高？

但没有一个模块回答更宏观的问题：

    *这些进程被回收了多少次？每个化身通常能存活多久？*

incarnation 从 ``data/restart_warmup.jsonl`` 日志构建完整的化身谱系：

    [
        {
            "pid": 1195,
            "start": "2026-10-09T07:00:47+00:00",
            "end": "2026-10-09T07:01:40+00:00",
            "duration_seconds": 53.0,
            "first_stroke": 12464
        },
        {
            "pid": 1411,
            "start": "2026-10-09T07:01:40+00:00",
            "end": null,
            "duration_seconds": null,
            "first_stroke": 12469
        }
    ]

核心 API：

- `incarnation_history(writer_id)`：解析 warmup JSONL，返回化身列表，每条
  包含 pid、start、end、duration_seconds、first_stroke。最后一个化身
  的 end/duration 为 None（可能仍在运行）。
- `incarnation_stats(history)`：统计摘要——count/mean/median/min/max、
  最短存活的 PID、verdict 评级。
- `incarnation_verdict(mean_duration)`：映射均值为 stable(≥1h) /
  churny(10min~1h) / flaky(<10min) / unknown(无数据)。
- `current_incarnation(writer_id)`：当前运行中进程的信息——PID、是否
  存活、uptime 秒数、warmup 秒数（读 PID 文件 + /proc）。
- `incarnation_summary(writer_id)`：一行式 caretaker 报告摘要。

设计要点：

1. 从 JSONL 的 restart 事件构建化身记录，first_stroke 事件按 PID 匹配
2. 最后一个化身无 end 事件——可能是仍在运行，也可能是日志截断
3. 损坏的 JSONL 行静默跳过，不中断解析
4. verdict 阈值：stable ≥ 3600s，churny ≥ 600s，其余 flaky
5. current_incarnation 通过 /proc/<pid>/stat 获取进程启动时间（仅 Linux）
6. 零外部依赖，纯 stdlib + os/pathlib

与现有模块互补：uptime_tracker 告诉你"当前进程活了多久"，restart_audit
告诉你"某个间隙是什么类型"，incarnation 告诉你"整体生命周期谱系和稳定性"。
三者共同构成从单次会话到历史全貌的完整可观测性。

**tests/test_incarnation.py** — 51 条测试，覆盖：

- _parse_ts（标准偏移、Z 后缀、空字符串、None、无效格式、带时区）
- _read_warmup_log（基础读取、空文件、缺失文件、空行跳过、损坏行跳过、
  顺序保持）
- incarnation_history（空日志、单化身、双化身、三化身、first_stroke
  PID 不匹配、缺失 first_stroke、损坏行跳过）
- incarnation_stats（空历史、单条无 duration、stable、churny、flaky、
  混合 duration、偶数 median、shortest_pid、None duration 忽略、
  边界值 stable/churny/flaky）
- incarnation_verdict（stable、churny、flaky、None、边界值、零、极大值）
- current_incarnation（返回 dict 结构、死亡进程、键完整性）
- incarnation_summary（返回字符串、无历史消息、有历史数据）
- 集成测试（完整生命周期模拟：稳定运行、快速回收、长时间运行）

51 条全部通过。

## 观察

本次 visit 延续了 visit 178-180 的可观测性主题，从推送链路（push_receipt）、
磁盘写入（stroke_parity）、写手节奏（writing_tempo）扩展到进程生命周期
（incarnation）。这四个维度共同覆盖了从"写手是否活着"到"写了什么"到
"推到远程没有"的全链路状态，caretaker 一行代码即可获取每个维度的健康判断。

预执行阶段检测到进程被回收并自动补交重启，这恰好验证了 incarnation 模块
的设计动机——容器环境中的进程回收是常态而非异常，追踪其历史谱系有助于理解
系统的整体稳定性模式。
