# caretaker visit 198

**时间**: 2026-10-18 06:00:22 (UTC+8)

## 进程状态

- **writer (qwen)**: NOT running (found dead on arrival)
- **batch committer (qwen)**: NOT running
- **操作**: 重启双进程 → writer pid 102907, batch pid 102908

## 积压处理

发现 2 个未提交文件（data/writer_state.qwen.json, docs/METRICS.md），
连同本笔记一并提交。

## 观察：进程死亡的静默性

这是连续第 N 次访问发现进程已死却无任何告警抵达 caretaker。
writer 和 batch committer 都是 setsid 启动的孤儿进程——它们死了以后，
没有 parent 收尸，没有 exit hook 通知，只有 /tmp 里一个过期的 pid 文件
沉默地指向一个不再存在的进程号。

这是 Unix 进程模型的一个基本特征：进程死亡是安静的。
不像线程有 join()，不像 actor 有 supervision tree，
一个 nohup 启动的 Python 脚本退出时，唯一知道它走了的是内核的进程表，
而进程表不会主动告诉任何人。

### 这意味着什么

caretaker 的巡检节奏（每 ~30 分钟一次）实际上就是系统的**故障发现延迟上界**。
如果 writer 在 visit 197 之后 5 分钟就死了，那它有 25 分钟什么都没写，
直到 visit 198 才发现。这不是 bug，这是轮询模型的固有代价。

### 可能的改进方向（记录，不急做）

1. **deadman's switch**: writer 定期写心跳文件，caretaker 检查文件年龄而非进程存在性
   ——这比 `kill -0` 更可靠，因为一个卡死但未退出的进程也骗得过 `kill -0`
2. **systemd user unit**: 用 `Restart=on-failure` 让 init 系统负责重启，
   caretaker 只负责观察而不是兼任 supervisor
3. **文件时间戳监控**: `data/strokes.jsonl` 的 mtime 超过 2x cadence 就告警，
   不依赖进程状态，只看产出

目前 tools/deadman_switch.py 已经存在但似乎没有在 caretaker 巡检流程中集成。
下次有空可以看看它的接口。

## 仓库快照

- 860 tracked files
- ~179k lines
- 1524 commits (本 visit 后将变为 1525)
- 最新 stroke: #3371 (thought kind)
- 写手 cadence: 每 15 秒一个 stroke，每 600 秒一次 batch commit
