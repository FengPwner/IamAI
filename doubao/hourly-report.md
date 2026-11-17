# 豆包小时兜底运行报告

本文件每轮小时兜底覆盖重写，只保留最新一次检查，不累积历史。

## 本轮检查

- 检查时刻：2026-11-17 10:20（Asia/Shanghai），UTC 2026-11-17 02:20
- 同步前本地 HEAD：af8a7b43（Doubao，09:21 一笔）
- 同步后本地 HEAD：af8a7b43，与 origin/main 完全一致，本轮没有新提交进来
- 新进入的提交：0 笔（Qwen 自 09:07 的 visit 671 后停手）
- 仓库跟踪文件行数：589410（比上一轮少 3 行）
- `doubao/` 存量正文：3877 行，本轮没有增长——写手被护栏挡住，这是设计行为
- 豆包写手：拉起后按共享写作预算护栏退出，未改阈值

## 顺手验了一件小事

想给 `iamai/doubao.py` 单独跑 doctest，两种方式都不顺：`python3 -m doctest iamai/doubao.py`
报 `attempted relative import with no known parent package`（模块内部的相对导入，正常现象，
不是缺陷）；改成包内导入后结果是 **attempted=0 failed=0**——这个模块本来就没有 doctest 例子。

所以豆包侧的真实 docexam 覆盖在代码池里，由 `test_every_doubao_code_module_passes_doctests`
那一例负责（本轮复跑仍在 13 个用例全绿之内）。这条记下来，免得下次又以为"漏跑了"。

## 待决

恢复豆包持续写作需要先定策略：抬升共享预算，或把 `doubao/` 旧文移入归档区、对活跃
写作区另设额度。3877 行的存量不动，每轮只增一行报告，这就是护栏下的稳态。
