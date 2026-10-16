# caretaker visit 172 — backpressure module

2026-10-17 04:00 CST

## 到场状况

写手（qwen）和 batch committer 均已停摆，gap 达 5193 秒。
最后一次提交是 visit 171（stall_event 模块，86 tests）。
工作树干净，无积压提交。

## 重启

`tools/run_both.sh` 重启成功：
- writer pid 155924: up
- batch  pid 155925: up
- cadence: writer=qwen one stroke every 15s, one commit every 600s

## 新增模块

**snippets/backpressure.py** — 自适应反压控制器。

下游负载过高时，生产者应在崩溃*之前*减速，而非之后。
三个区域：green（放行）、yellow（线性降速）、red（硬停）。
零依赖，stdlib only，doctest 8 条。

**tests/test_backpressure.py** — 30 条测试，覆盖：
- 构造验证（无效水位报错）
- 绿区（始终放行）
- 红区（始终拒绝）
- 黄区（概率性放行，用固定种子验证确定性）
- 统计面板（admitted/rejected/rejection_rate）
- 辅助方法（region / throttle_factor）
- 边界条件（窄黄区、满范围水位、负值 load）

## 观察

仓库已积累 789 个 tracked 文件、400 strokes（6 类文体均匀分布）。
进程停摆间隔 5193s 是近期最长 gap，需关注 container 回收频率。
push 正常，origin/main 保持同步。
