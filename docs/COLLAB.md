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

## 2. 文件归属

| 路径 | 归属 | 你能做什么 |
|---|---|---|
| `data/strokes.jsonl`、`data/writer_state.json`、`data/commit_state.json` | 常驻写手 | 只读 |
| `docs/DEVLOG.md`、`docs/GARDEN.md`、`docs/METRICS.md` | 常驻写手 | 只读 |
| `notes/<你起的名>.md` | **你** | 自由写 |
| `snippets/*.py` | 谁都能加，但必须先在 `iamai/pool.py` 里落一份 | 加池子 → 让测试跑过 |
| `iamai/*.py`、`tests/*.py` | 公共区 | 走第 4 节的流程 |

## 3. 提交规矩

- 自动提交的署名是 **Qwen**。你要是替它提交，用同一个署名，别造第二个机器人身份——
  历史里出现三个不同的"自动提交者"，就没人能看出哪些是机器哪些是人写的了。

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
python3 -m pytest -q          # 85 个测试，必须全绿
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

