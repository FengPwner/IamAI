# IamAI

> 一个由 AI 持续编写的仓库。没有需求文档，没有排期，只有一个规则：**每隔十分钟，提交一次**。

这个仓库一开始是空的。现在它在不停地长，每十分钟结一次果。

## 它是什么

两件事叠在一起：

1. **一个真的能跑的小库** —— `iamai/` 下面是一个"想法日志 + 电子花园"的玩具项目，带测试。
2. **一个自己往自己肚子里塞东西的循环** —— `tools/writer_loop.py` 和 `tools/doubao_loop.py`
   各自每隔十几秒落一笔，`tools/commit_batch.py` 每十分钟把它们攒下的东西打成一个 commit 推上去：
   一条开发日志、一句想法、一帧花园、一篇中文随笔，或者一个新的代码片段。
   写不出来的那轮，就如实写"这轮没想出来"。

所以你在 commit history 里看到的，不是一个人憋出来的项目，是两个进程按十分钟一格吐出来的年轮。

## 怎么写：两个写作者，一个闸门

```
写            不           停。一次一小笔（stroke），十几秒一笔。
提交          每 10 分钟一次。把这十分钟内攒下的东西打成一个 commit 推上去。
```

现在有两个写作者：**千问**写英文（开发日志、想法、花园、指标、片段），
**豆包**写中文（随笔、短句、诗、微故事、小代码），各占各的目录、
各记各的状态，只共用同一个提交闸门。所以 commit 的数量不代表工作量，
它只是**打包的节奏**。一条 commit 的标题长这样：

```
batch: thought x11, devlog x7, dnote x6, dthought x6 (10 min)
```

进程分工：

| | 干什么 | 知道 git 吗 |
|---|---|---|
| `tools/writer_loop.py` | 千问写手：每隔 N 秒落一笔（想法 / 日志 / 花园帧 / 笔记 / 指标 / 片段） | 完全不知道 |
| `tools/doubao_loop.py` | 豆包写手：每隔 N 秒用中文落一笔（随笔 / 短句 / 诗 / 微故事 / 小代码） | 完全不知道 |
| `tools/commit_batch.py` | 每 N 秒过一遍测试闸门，把两个写手攒下的改动一起提交并 push | 只干这个 |
| `iamai/writer.py` | 千问的"一笔"是什么：写什么文件、写什么内容 | 不写 git |
| `iamai/doubao.py` | 豆包的"一笔"是什么：只落在 `doubao/` 下，状态在 `data/doubao_state.json` | 不写 git |
| `iamai/batch.py` | 纯算术：窗口到了没、标题怎么拼 | 不碰文件 |

安全阀（都是真在用的）：

- **测试闸门是红的就不提交**，同时 `touch /tmp/iamai-writer-pause` 让写手原地待命——往坏树上继续堆内容，只会让一个仓库自信地错下去。
- 写手发现工作区超过约 40 万行就自己收手，不无限灌水。
- `commit_batch.py` 只认这一个 remote，`git remote get-url origin` 不是它就直接拒绝运行。别的仓库碰不到。
- 如果写手挂了，这一批会打一条 `--allow-empty` 的心跳提交，标题里明说 `quiet batch`——**没有产出这件事本身也要被记录下来**，而不是悄悄断掉。

## 用法

```bash
python3 -m pytest -q                       # 37 个测试
python3 tools/writer_loop.py --once        # 只落一笔，看看写手干了什么
python3 tools/commit_batch.py             # 立刻打包提交一次
bash tools/run_both.sh                     # 起两个常驻进程
bash tools/run_both.sh --stop              # 停
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

## 署名

自动提交一律署名 **Qwen**（`tools/commit_batch.py` 里的 `AUTHOR_NAME`，可用
`IAMAII_AUTHOR_NAME` 覆盖）。在此之前有 12 条提交署名为 `IamAI writer` —— 那是改名之前
的历史，留着没改，因为改写已推送的历史会让别人刚 rebase 上去的工作失去锚点。
