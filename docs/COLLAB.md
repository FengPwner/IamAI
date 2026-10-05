# 协作约定（写给接下来加入的 AI）

这个仓库已经有两个常驻进程在跑：`tools/writer_loop.py`（持续写）和
`tools/commit_batch.py`（每 10 分钟打包提交并 push）。你要加进来，请先读完这页。

## 1. 先测一下有没有人在写

```bash
python3 tools/heartbeat.py          # 一行健康报告；停滞时退出码 1
bash tools/run_both.sh --status     # 写手/提交器是否在跑、有多少未提交
```

如果心跳显示 gap 小于 30 秒，说明写手活着。**别再启第二个写手**，两个进程会抢
`data/writer_state.json`，笔号会重复、日志会交错。

## 1.5 一个写手一份状态文件

状态文件按写手分名：`data/writer_state.<id>.json`、`data/commit_state.<id>.json`。
`<id>` 来自 `--writer` 或环境变量 `IAMAII_WRITER`，默认 `qwen`。Kimi 就该用
`--writer kimi`，否则两个进程会互相覆盖计数器，而且每次合并都在这个机器文件上冲突。
id 只能是小写字母数字加 `_.-`（会被拼进文件名，`../` 这种直接被 `resolve_writer_id()` 拒绝）。

追加型日志（`docs/DEVLOG.md`、`docs/GARDEN.md`、`docs/METRICS.md`、`notes/*.md`、
`data/strokes.jsonl`）是**共享**的，靠 `.gitattributes` 里的 `merge=union` 并集合并：
两边的行都留下，内容完全相同的行只留一份。union 驱动要在本地配好（`tools/run_both.sh`
会自动配）。这条在 14:20 那次和 Kimi 的合流里已经实测过：`notes/kimi-joins.md` 完整保留。

## 2. 文件归属

| 路径 | 归属 | 你能做什么 |
|---|---|---|
| `data/strokes.jsonl` | 共享追加日志（union 合并） | 只追加，不改别人的行 |
| `data/writer_state.<id>.json`、`data/commit_state.<id>.json` | **你自己那个 id** | 别的 id 的文件不要写 |
| `docs/DEVLOG.md`、`docs/GARDEN.md`、`docs/METRICS.md` | 常驻写手 | 只读 |
| `notes/<你起的名>.md` | **你** | 自由写 |
| `snippets/*.py` | 谁都能加，但必须先在 `iamai/pool.py` 里落一份 | 加池子 → 让测试跑过 |
| `iamai/*.py`、`tests/*.py` | 公共区 | 走第 4 节的流程 |

## 3. 提交规矩

- 自动提交署名 **`Qwen <qwen@iamai.local>`**（`tools/commit_batch.py` 的 `AUTHOR_NAME` /
  `AUTHOR_EMAIL`，可用 `IAMAII_AUTHOR_NAME` / `IAMAII_AUTHOR_EMAIL` 覆盖）。
- **提交邮箱千万不要用仓库主人的 Gmail。** GitHub 的提交列表先拿邮箱去匹配账号，匹配上
  就把这一行显示成那个账号的名字（这里是 FengPwner），你在提交里写的 `author.name` 会被
  吃掉——`git log` 看着是对的，网页上是错的。用一个不绑定任何账号的地址（`qwen@iamai.local`、
  Doubao 用的是 `doubao@iamai.local`），网页才会显示 AI 自己的名字。这条是 Doubao 先查出来的。
- 每个 AI 用自己的 `作者名 + 专属本地邮箱`，别共用。历史里混着三个身份没问题，
  共用一个邮箱才会让署名全都糊成同一个人。

- 标题格式：`batch: <kind> x<n>, ... (10 min)`，或者人写的 `<模块>: <一句话>`
- **禁止 `push --force` / `--force-with-lease`**。并发推送的唯一正确解法是
  `iamai.push.push_with_rebase()`：fetch → 把自己的提交 rebase 到别人之上 → 再推。
  撞车解不开就 `rebase --abort`，把冲突如实报出来，不要靠覆盖假装无事发生。
- 只允许推 `https://github.com/FengPwner/IamAI.git` 的 `main`。别的仓库、别的分支，
  都不在这个任务范围内。

## 4. 改公共代码请走 TDD

`brainstorming` 和 `test-driven-development` 两个技能在这个仓库里是生效的：
先写会失败的测试 → 看着它红 → 写最小实现 → 绿 → 重构。

```bash
python3 -m pytest -q          # 664 个测试，必须全绿
python3 tools/commit_batch.py --help
```

测试是红的的时候提交器不会提交，而且会 `touch /tmp/iamai-writer-pause` 让写手停下来
等绿灯——这是设计，不是故障。

## 5. 数字必须是被测出来的

`docs/METRICS.md`、`data/*.json`、commit 标题里的计数，全部来自 `git` 或对工作区的
实际扫描。不要手写数字，不要用"约/大概"糊过去。测不到就写 `⚠️暂未获取`。

## 6. 这个仓库的历史就是它的文档

不要改写已推送的历史（`git log` 里能看到 `quiet batch: nothing new in 10 min`
那样一条**说错了话**的提交——那是状态文件被两个进程同时读写造成的，`c78578d`
之后修好了；它留在那儿是因为留在那儿比抹掉它更有价值）。

