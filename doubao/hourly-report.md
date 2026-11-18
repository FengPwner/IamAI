# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-18 08:21（Asia/Shanghai），UTC 2026-11-18 00:21
- 同步前本地 HEAD：cb51572d（Doubao，07:21 一笔）
- 同步后本地 HEAD：417575c6（Qwen），与 origin/main 一致
- 新进入的提交：2 笔，均 Qwen（`bfa5b4d8` 08:01 catch-up、`417575c6` 08:12 visit 694 推送守卫 + 42 测试）
- 仓库跟踪行数：603554
- 豆包写手：拉起后 2 秒退出（`doubao tree exceeded the line budget`）

## 发现一本账长期没记：我的提交记账停在 10 月 30 日

体检三个状态文件时，发现它们各说各话：

| 文件 | 内容 | 归谁写 |
|---|---|---|
| `data/doubao_state.json` | `seq: 1394` | 我自己的笔画序号（`iamai/doubao.py`） |
| `data/writer_state.doubao.json` | `seq: 1684`，history 停在 10-14 | 通用 `Writer` 类（我没走这条路径） |
| `data/commit_state.doubao.json` | `commit_seq: 40`，`last_commit: 2026-10-30` | 提交记账 |

前两个数字不一致是历史原因：doubao_loop 用的是 `DoubaoWriter` 自己的计数（1394），通用 Writer 那份停在旧路径上。
**但第三个是真问题**——它停在 10 月 30 日，而 git 里我自那以后有 **37 笔提交**。

原因也清楚：兜底走的是"直接 `git commit` + `push_with_rebase`"（任务允的那个备选路径），
压根不经过 `commit_batch`，而提交记账是 `commit_batch` 才写的。所以这 18 天里账本一页没翻。
换句话说，任何照这个文件判断"豆包最近有没有提交"的看板，都会看到一个 18 天没动静的写手——那是假的。

这轮按 git 事实对账：`commit_seq: 40 + 37 = 77`，`last_commit` 改成这次提交的真实时间。
数字不是拍的，是用 `git log --since=<旧值> --author=doubao@iamai.local` 数出来的。

套件复跑：**13/13 全绿，12.4 秒**。

## 待决

1. 豆包 40 万行阈值是否对齐 70 万——恢复写作的唯一开关，仍等这一句。
2. Qwen 侧三处慢点（177s / ≈60s / 30s，合计 267s of 354s）。
