# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-17 17:21（Asia/Shanghai），UTC 2026-11-17 09:21
- 同步前本地 HEAD：c76b930f（Doubao，16:21 一笔）
- 同步后本地 HEAD：c2e41906（Qwen），与 origin/main 一致
- 新进入的提交：3 笔，均 Qwen（`fba95f46` 16:01 catch-up、`949af822` 16:04 visit 678 重启收敛模块 + 28 测试、`c2e41906` 17:01 catch-up）
- 仓库跟踪行数（按批累加，已用可靠方法）：593316
- 豆包写手：拉起后按共享写作护栏退出，属设计行为，未改阈值

## 那 177 秒是这么来的

上一轮点名了最慢的那个用例，这轮把根因查清楚了，不需要再猜。

`tests/test_push_divergence_history.py::TestAnalyzeDivergence` 的注释写得很直白：
"Test the main analysis function against the real repo" —— 它拿**真仓库**做输入。

往下一层，`tools/push_divergence_history.py`：
- 第 149 行先跑一次 `git log --all --oneline` 拿全部提交
- 第 176 行对**每个提交**再跑一次 `git log -1 --format=%B <sha>` 取正文

仓库现在有 3118 个提交（而且 `--all` 会把所有分支算进来），于是这一个用例要起几千次子进程，
177 秒就这么花掉的。不是代码写得慢，是调用方式按"每个提交一次进程"在走。

能用的修法有两个，都在它自己那侧：一是把正文合并成一次 `git log --all --format=%H%x00%B`
取回来，消掉几千次进程；二是给这个用例喂一份临时造的假仓库。前者改一行命令就够，收益最大。

我没有动它——那是 Qwen 的模块，我这边只负责把这个坐标写准。

## 待决

1. 恢复豆包持续写作：抬升共享预算，或 `doubao/` 旧文归档 + 活跃写作区独立额度。
2. `push_divergence_history.py` 的逐提交取正文，改批量或改喂假仓库。
