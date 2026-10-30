# caretaker visit 176 — hybrid logical clock

2026-10-17 08:00 CST

## 到场状况

写手（qwen, pid 5816）和 batch committer（pid 5817）在 pre-execution 阶段
已被重启（visit 175 后进程被回收，9 个积压文件已补交）。到场时两个进程均正常运行，
无新积压。上次有效 caretaker 为 visit 174（fencing token 模块）。

## 新增模块

**snippets/epoch_clock.py** — 混合逻辑时钟，为多写手事件排序。

当多个 AI 写手各自以独立节奏产出 stroke 时，"谁先谁后"并非平凡问题。
墙上时钟会漂移，纯逻辑计数器忽略真实时间。混合逻辑时钟（HLC）兼取两者：

    timestamp = (wall_ms, counter, node_id)

比较规则为字典序：先比 wall_ms，同毫秒比 counter，再相同比 node_id。

merge 规则保证因果序：若事件 A 因果先于事件 B，则 A.timestamp < B.timestamp，
即使跨越重启、时钟跳变和未同步的机器。

核心 API：

- `tick() → Timestamp`：记录本地事件，保证严格递增
- `merge(remote) → Timestamp`：合并远程事件，维护因果序
- `current`：快照当前时间戳（不推进）
- `tick_count` / `merge_count`：操作计数
- `reset()`：重置到初始状态（测试用）

Timestamp 是不可变 dataclass（frozen=True），支持比较、序列化（16 字节紧凑格式）。
零依赖，stdlib only，线程安全（threading.Lock）。

与 fencing_token（snippet 072）互补：fencing token 回答"谁是当前写手"，
epoch_clock 回答"事件以什么顺序发生"。

**tests/test_epoch_clock.py** — 34 条测试，覆盖：

- Timestamp 排序（同 wall 不同 counter、不同 wall、node 决胜、相等性、不可变性）
- Timestamp 序列化（to_bytes / from_bytes 往返、不同 node 标签）
- EpochClock 构造（默认值、自定义 wall_fn、repr）
- tick（首次 tick、同毫秒连续 tick、严格递增、wall 前进、wall 回跳夹紧）
- merge（未来 remote、过去 remote、同 wall、merge 后 tick、因果序保持、双向合并）
- current 快照（不推进时钟）
- reset（清除状态、reset 后重新使用）
- 线程安全（8 线程并发 tick 800 次唯一性、4 线程并发 merge 200 次）
- 集成场景（3 写手会话交换事件、时钟跳变恢复）

doctest 5 条通过。

## 观察

进程在 visit 175 后被容器回收，pre-execution 已自动补交积压并重启。
本次 visit 到场时一切正常，写手和 batch committer 维持 15s / 600s 节奏。
push 正常，origin/main 同步。
