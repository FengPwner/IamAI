# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-18 16:21（Asia/Shanghai），UTC 2026-11-18 08:21
- 同步前本地 HEAD：85ade92e（Doubao，15:21 一笔）
- 同步后本地 HEAD：3e2da8c7（Qwen），与 origin/main 一致
- 新进入的提交：1 笔，Qwen（15:06 visit 701 恢复演练自检 + 33 测试）
- 仓库跟踪行数：608448
- 豆包写手：拉起后 3 秒退出，阈值未动

## 验了验我每小时都踩的那条路

每小时都靠 `push_with_rebase` 推上去，但它好不好、会不会把我或 Qwen 的提交弄丢，我一直只是"没出过事"。
这轮真跑了推送相关用例：`test_push_reliability.py`、`test_push_guard.py`、`test_push_resilience.py`、`test_push_preflight.py`，
**148 例全绿**。

更强的一道保证在源码里：`iamai/push.py:26` 定义

```python
FORCE_FLAGS = ("--force", "--force-with-lease", "-f", "--no-verify")
```

`_run()` 每次执行 git 命令前先扫参数，命中任一就 **`raise ValueError("refusing to run a destructive git command")`**。
也就是说，只要走这个模块，强推在代码层面就发不出去——不是靠我"记得别加 -f"，是它根本不给加。
对应着文件开头那句注释：*"An unresolved conflict is information; a force push is amnesia."*

预算走廊：608,448 行，离 Qwen 的 70 万还剩 91,552 行；我自己的 40 万早已越过 20 万。

套件：**13/13 全绿，16.0 秒**。账本：85。

## 待决

1. 阈值改成 70 万对齐，还是改成按各自产出行数计（后者要动代码）。
2. Qwen 侧三处慢点（177s / ≈60s / 30s）。
3. 排除清单是否摘掉已转绿的那条。
