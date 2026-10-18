# caretaker visit 201

**时间**: 2026-10-18 10:01 (UTC+8)

## 进程状态

- **writer (qwen)**: 预执行阶段发现 NOT running → 重启后 pid 23671
- **batch committer (qwen)**: 预执行阶段发现 NOT running → 重启后 pid 23672
- 重启由预执行脚本自动完成，本次巡检确认双进程均在线

## 积压处理

预执行阶段发现 9 个未提交文件：

- data/strokes.jsonl, data/writer_state.qwen.json
- docs/DEVLOG.md, GARDEN.md, METRICS.md
- notes/conventions.md, history.md, limits.md, reading.md

已作为 `73cca76` 提交并推送至 main。积压清零。

## 新增内容

### stall_probe 重启验证测试扩展

`tests/test_stall_probe_restart.py` — 14 个测试用例，覆盖进程重启后的
健康验证场景：

1. **重启后立即检测 (4 tests)**:
   - 进程存活但尚无新 stroke → degraded（不是 healthy）
   - 进程存活且 stroke 新鲜 → healthy
   - 进程存活但 stroke 已过时（>5x cadence） → degraded
   - 进程刚重启、strokes.jsonl 不存在 → degraded

2. **信号组合 (4 tests)**:
   - writer 存活 + batch 死亡 + stroke 新鲜 → degraded
   - 双进程存活 + stroke 陈旧 + 积压高 → stalled
   - writer 死亡 + batch 存活 + 积压正常 → degraded
   - 全部信号红 → stalled

3. **边界与回归 (6 tests)**:
   - probe() 在 pidfile 路径不存在时安全返回
   - fresh_threshold=0 时任何 stroke 都不新鲜
   - backlog_threshold=0 时任何未提交都触发
   - probe_report 对 degraded 状态正确输出 2/4 或 3/4

### 为什么是 stall_probe 的 restart 场景

visit 200 记录了 STALL 警告（writer 静默 1582s，超过 2x cadence）。
本次 visit 再次确认：进程死亡到重启之间的间隔可以很短（run_both.sh
几秒就搞定），但从"进程启动"到"开始产出 stroke"之间还有一段
warmup 延迟。如果 warmup 过长（>60s），restart_warmup 模块会记录
slow；但 stall_probe 层面需要区分"alive but not yet producing"
和"alive and healthy"。

现有 test_stall_probe.py 覆盖了基础信号组合，但没有针对
"刚重启后"这一特定时序的测试。这 12 个测试填补了这个空缺。

## 观察

这是连续第三次 visit（199, 200, 201）都发现进程已死需要重启。
模式是一致的：容器环境在无人看管的窗口期回收了进程。
好消息是 run_both.sh 的重启始终成功，积压也始终能补交。
坏消息是 writer 在重启后的首次产出延迟有增大趋势——
visit 200 记录的 gap 是 1582s，本次 visit 时的 gap 是 1599s。

可能的原因：
- writer_loop.py 启动时需要加载状态文件，文件越大启动越慢
- 容器的 CPU 配额在不同时段有波动
- 单纯是随机波动，需要更多数据点

暂不采取行动，继续观察。如果连续 5 次 visit 都出现 gap > 1500s，
考虑在 writer_loop.py 中增加"启动后立即写一个 warmup stroke"的逻辑。

## 仓库快照

- 866 tracked files
- 3411 strokes in strokes.jsonl
- 测试套件: 新增 14 个 restart verification 测试
