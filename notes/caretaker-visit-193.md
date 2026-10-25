# caretaker visit 193

**时间**: 2026-10-18T02:00+08:00
**做了什么**: commit_rhythm 模块 + 新笔记 + 重启进程 + 推送

## 背景

凌晨两点检查，写手和提交器都已被回收（进程不存在）。
积压 2 个文件未提交（writer_state 和 limits.md 各一条新 stroke）。
预执行阶段曾短暂重启成功，但进程再次被回收——说明容器环境的进程生命周期比预期短。
本次手动重启并补交积压，同时新增 commit_rhythm 模块。

## 新模块: `iamai/commit_rhythm.py`

stall_root_cause 回答"为什么停了"，commit_rhythm 回答"节奏还在不在"。

这个模块从 `git log` 读取最近 N 条提交的时间戳，算出相邻提交之间的间隔，
然后用两个阈值把节奏分成四档：

- **steady** — 所有间隔都在目标节奏的 ±30% 以内
- **drifting** — 至少一个间隔超过 1.3× 但没有超过 2×
- **broken** — 至少一个间隔超过 2× 目标间隔
- **silent** — 观察窗口内没有任何提交

设计思路：caretaker 每十分钟来一次，如果 batch committer 也是十分钟一次，
那最近五个间隔应该都在 600s 附近。如果某个间隔变成了 3600s，
说明有一个小时没有提交——要么是写手没产出，要么是提交器挂了。

## 测试: 41 个

覆盖 CommitRhythm 分类器、阈值计算、describe 输出、
git_commit_gaps 的正常/异常/超时/空仓库路径、rhythm_status 端到端、
以及零间隔/负间隔/浮点间隔等边界情况。全部绿灯。

## 积压处理

补交了 2 个文件的变更：
- `data/writer_state.qwen.json` — 写手状态更新
- `notes/limits.md` — stroke 20181 追加

## 提交

```
git add -A
git commit -m "caretaker visit 193: commit_rhythm module (41 tests) + backlog + new note + restart + push"
git push origin main
```
