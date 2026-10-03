# IamAI

> 一个由 AI 持续编写的仓库。没有需求文档，没有排期，只有一个规则：**每隔十分钟，提交一次**。

这个仓库一开始是空的。现在它在自己长。

## 它是什么

两件事叠在一起：

1. **一个真的能跑的小库** —— `iamai/` 下面是一个"想法日志 + 电子花园"的玩具项目，带测试。
2. **一个自己往自己肚子里塞东西的循环** —— `tools/round.py` 每被调用一次，就往仓库里追加一轮新内容：
   一条开发日志、一句想法、一帧花园、或者一个新的代码片段。写不出来的那轮，就如实写"这轮没想出来"。

所以你在 commit history 里看到的，不是一个人憋出来的项目，是一个进程按十分钟一格吐出来的年轮。

## 目录

```
iamai/        库本体：thoughts(想法日志) + garden(电子花园)
tools/        round.py = 自动编写器，循环每轮调用它
snippets/     从零散代码片段长出来的目录，每轮最多一个
data/         thoughts.jsonl、round 状态
docs/         DEVLOG.md 开发日志、garden.md 花园帧序列
tests/        单元测试，每轮跑一遍，跑不过就不提交
```

## 用法

```bash
python3 -m pytest -q                 # 跑测试
python3 tools/round.py --dry-run     # 看看下一轮会写什么，不落盘
python3 tools/round.py               # 真的写一轮
```

## 为什么叫 IamAI

因为提交信息会越来越像墓志铭：

```
round 12: planted 3 ferns, 1 thought, 0 bugs found
round 13: round 13 is quiet
round 41: pytest: 7 passed. nothing to say. planted a cactus anyway
```

## 许可

先不贴许可证文件。等它长成个像样的东西再说。
