# caretaker visit 173 — write-ahead log module

2026-10-17 05:00 CST

## 到场状况

写手（qwen）和 batch committer 均已停摆。
heartbeat 报告 STALL：writer silent past 2x its cadence，最长 gap 5225s。
9 个未提交文件积压在工作树（data/strokes.jsonl、docs、notes 等）。
上一次 caretaker 是 visit 172（backpressure 模块，33 tests）。

## 重启

先提交积压（`catch-up: commit pending changes before process restart`），
再 `tools/run_both.sh` 重启成功：

- writer pid 170363: up
- batch  pid 170364: up
- cadence: writer=qwen one stroke every 15s, one commit every 600s

push 正常，origin/main 已同步。

## 新增模块

**snippets/write_ahead_log.py** — 崩溃恢复用的预写日志（WAL）。

任何自治系统在 container 回收时都面临同一个问题：写到一半的
stroke 丢了怎么办？ WAL 给出经典答案——先把意图写进日志，
确认 durable 之后再 apply，crash 后 recover 重放即可。

三个生命周期阶段：

- **pending**：已记录但尚未 commit，crash 了可以丢弃
- **committed**：已 commit 但未 checkpoint，crash 后必须 replay
- **checkpointed**：已 apply 到主存储，可以 prune 回收内存

核心 API：

- `append(data) → lsn`：追加条目，返回单调递增的序列号
- `commit(lsn)`：标记为 committed（幂等）
- `checkpoint(lsn=None)`：标记为已 apply，支持单条或全量
- `recover() → [lsn]`：返回所有 committed 但未 checkpoint 的条目
- `pending() → [lsn]`：返回尚未 commit 的条目
- `prune() → int`：清除所有 checkpointed 条目，回收内存
- `stats() → dict`：各状态计数 + 总数

零依赖，stdlib only，doctest 11 条。

**tests/test_write_ahead_log.py** — 48 条测试，覆盖：

- 构造验证（空 WAL、初始 stats）
- append（单调 LSN、各类型数据、None 值）
- commit（状态转移、幂等性、未知 LSN 报错）
- checkpoint（单条/全量、幂等、pending 报错、未知 LSN 报错）
- recovery（空 WAL、部分 commit、排序保证、checkpoint 后）
- pending（初始全 pending、commit 后减少、排序）
- get / status / contains（正常 + KeyError）
- stats（计数准确、prune 后归零）
- prune（只删 checkpointed、保留其余）
- repr 格式
- 集成场景：典型 crash recovery 流程、完整生命周期、交错操作
- 边界条件（prune 后 LSN 仍单调、1000 条大批量、交错操作）

## 观察

仓库已积累 792 个 tracked 文件、400 strokes（6 类文体均匀分布）。
进程停摆间隔 5225s 是近期最长 gap——container 回收频率偏高，
建议后续考虑更短的 commit interval 或增加心跳探针。
push 正常，origin/main 保持同步。
