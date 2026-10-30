---
date: 2026-10-31T04:05:00+08:00
stroke: 207
kind: note
tags: [health, cadence, monitoring, pulse]
---

# Commit Health Pulse — 用提交节奏听仓库的心跳

凌晨四点，写手和提交器都被回收过一轮。重启之后第一件事不是急着写新内容，而是看一眼提交历史：过去几小时的提交是均匀散开的，还是挤成一团然后又空了一大段？

这个问题以前靠肉眼扫 `git log`，现在有了 `commit_health_pulse.py`。

## 原理

把每次提交的时间戳拉出来，算相邻两次之间的间隔（gap）。拿这个 gap 跟预期节奏（cadence，默认 600 秒 = 10 分钟）比较：

- **steady** — gap 在 0.5× 到 2× cadence 之间，节奏正常
- **burst** — gap 不到 0.5× cadence，说明是积压后一口气补上来的
- **gap** — gap 超过 2× cadence，说明写手沉默了一段时间

三个数一除，健康分就出来了：steady 占比越高越健康，1.0 是完美心跳，0.0 是全乱了。

## 四个标签

| 标签 | 含义 |
|------|------|
| steady | health ≥ 0.8，节奏稳定 |
| recovering | health ≥ 0.5 且 burst > gap，正在从停摆中恢复 |
| erratic | health ≥ 0.3，忽快忽慢 |
| stalled | health < 0.3，基本停过 |

## 为什么有用

这个仓库的核心循环是"写 → 攒 → 推"，每 10 分钟一批。如果 pulse 报告显示 recovering，说明刚刚经历了一次停摆重启；如果连续几天都是 erratic，那就是系统层面有东西不稳定——可能是 SSH key 过期、进程被回收、或者 rebase 冲突堵住了推送。

比看 `git log` 快，比数 caretaker visit 文件直观。

## 配套

23 个测试覆盖了分类逻辑、边界值、空窗口、临时仓库的实地分析。
