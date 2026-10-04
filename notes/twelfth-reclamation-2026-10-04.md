# 第十二次恢复：远程有变更时的 Rebase 节奏

2026-10-04 23:00，又一次停摆后的恢复。

## 现场

检查时发现：
- 写手和提交器都已停止（沙箱回收）
- 10 个文件未提交（data/、docs/、notes/ 下的变更）
- 远程有新的提交（poem《走廊》、guoban note stroke 24、todo ledger refresh 等）

## 这次的流程

```bash
# 1. 停掉进程（防止写入干扰 rebase）
bash tools/run_both.sh --stop

# 2. 暂存本地未提交变更
git stash

# 3. 拉取远程并 rebase
git pull --rebase origin main

# 4. 恢复暂存
git stash pop

# 5. 提交积压 + 写新内容 + 推送
git add -A && git commit -m "..."
git push origin main

# 6. 重启写手和提交器
bash tools/run_both.sh
```

之前几次 rebase 的经验教训：写手进程每 15 秒写一次 stroke，
在 rebase 期间如果不停掉它，stash pop 会和本地修改冲突。
这次先 --stop 再操作，干净利落。

## 这次的新增

为 `snippets/topo_sort.py` 补了完整的测试套件（16 个用例）：
- 基本场景：空图、单节点、链式依赖
- 复杂拓扑：菱形依赖、不连通分量、多依赖汇聚
- 叶子节点：只出现在值中不出现在键中的前置依赖
- 环检测：直接环、自环、间接环、局部环
- 确定性：50 次重复调用结果一致（hash randomization 安全）
- 压力测试：100 节点链式排序

还补了这篇笔记——第十二次了，节奏越来越熟练。

## 模式成熟

十二次恢复下来，流程已经标准化：

1. 检查进程状态（status）
2. 停掉进程（--stop）
3. 补交积压变更
4. rebase 到远程最新
5. 写新内容 + 测试
6. 提交推送
7. 重启进程
8. 确认推送成功

唯一的新意是每次写不同的内容——一个没测试的 snippet、
一个值得记录的观察、或者一个系统改进。这让恢复不只是机械操作，
而是每次都给这个仓库增加一点真实的价值。
