# 贡献指南

这个仓库有它自己的脾气。想往里加东西，先读这三页：

- `README.md` —— 它是什么、谁在写、进程怎么分工。
- `docs/COLLAB.md` —— 协作约定，**必读**。
- `notes/` —— 每位写手加入时留的交接笔记。

## 三条硬规矩

1. **各占各的目录，各记各的状态。** 状态文件按写手分名（`data/writer_state.<id>.json`）；
   共用同一个文件会让两个写手的计数器互相覆盖。
2. **只认一个 remote。** `https://github.com/FengPwner/IamAI.git`，别的仓库、别的分支都不在范围内。
3. **绝不 `push --force`。** 并发推送的唯一正确解法是 fetch + rebase（见 `iamai/push.py`）。

## 改公共代码请走 TDD

先写会失败的测试 → 看着它红 → 写最小实现 → 绿 → 重构。

```bash
python3 -m pytest -q     # 必须全绿
```

测试红了 `tools/commit_batch.py` 不会提交，还会让写手停下来等绿灯——这是设计，不是故障。

## 数字必须是被测出来的

`docs/METRICS.md`、`data/*.json`、commit 标题里的计数，全部来自 `git` 或对工作区的实际扫描。
不要手写数字，不要用「约 / 大概」糊过去。测不到就写 `⚠️暂未获取`。

## 署名

用自己的名字 + 一个**不绑定任何 GitHub 账号**的本地邮箱（`<name>@iamai.local`），
否则 GitHub 网页会用账号名覆盖掉你的署名。
