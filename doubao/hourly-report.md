# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-18 06:21（Asia/Shanghai），UTC 2026-11-17 22:21
- 同步前本地 HEAD：85cb0757（Doubao，05:21 一笔），与 origin/main 一致
- 新进入的提交：0 笔（这一小时远端没有动静，Qwen 也停了）
- 仓库跟踪行数：602091
- 豆包写手：拉起后 2 秒退出（`doubao tree exceeded the line budget`）

## 只改了一句注释，没碰阈值

上一轮发现 `tools/doubao_loop.py` 第 31 行那句 `# same budget as the qwen writer` 已经不成立了。
这轮把它改成事实：

```python
MAX_TRACKED_LINES = 400_000  # doubao's own cap; qwen's lives in tools/writer_loop.py
                             # and was raised to 700_000, so the two are no longer the same budget
```

只动注释，不动数值——阈值是护栏，不归我自己拆。顺手核了两边现状，把账摊平：

| 写手 | 常量 | 位置 |
|---|---|---|
| Qwen | 700,000 | `tools/writer_loop.py:34`（昨晚从 60 万提上来） |
| 豆包 | 400,000 | `tools/doubao_loop.py:31`（未动） |

仓库 602,091 行：对 Qwen 来说是能写的（余 9.8 万），对我还是红灯（超 20 万）。
所以豆包能不能恢复写作，现在只取决于那一个数字要不要对齐——这需要你点头。

套件另外复跑了一次：**13/13 全绿，12.2 秒**，昨天那个共享快照改动依旧稳。

## 待决

1. 豆包 40 万行阈值是否对齐 70 万——恢复写作的唯一开关。
2. Qwen 侧三处慢点（177s / ≈60s / 30s，合计 267s of 354s）。
