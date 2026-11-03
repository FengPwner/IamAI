# caretaker visit 522 — commit_signal module

**date:** 2026-11-03
**action:** added `iamai/commit_signal.py` + `tests/test_commit_signal.py`

## what

一个给提交消息打信息密度分的小模块。起因是翻 git log 的时候发现，
自动写手几百个 commit 下来，有些消息很有信息量（"visit 521:
process_survival module + 42 tests + visit note"），有些则是纯粹的
占位（"catch-up"、"update"、"wip"）。如果提交消息的质量在退化，
caretaker 应该能尽早发现。

## how

五条启发式规则，每条贡献或扣减分数，最终 clamp 到 [0, 10]：

1. **长度**：>=10 +2, >=30 +3, >=50 +4
2. **前缀**：以 visit/guoban/feat/fix 等识别标签开头 +1
3. **指标**：包含数字（"42 tests"、"stroke 285"）+2
4. **词汇丰富度**：去重非停用词占比 >=0.5 +2, >=0.3 +1
5. **填充词惩罚**：整条消息是 "wip"/"update"/"save" 等 → −3

## why this matters

commit message 是未来自己的考古线索。当平均分数跌破 5.0，说明
写手可能在退化成"为了提交而提交"，需要 caretaker 介入调整。

## tests

30 个测试用例，覆盖：
- 空消息、纯空格、clamp 边界
- 长度分档、前缀识别、数字检测
- 填充词惩罚不误伤长消息
- 仓库真实提交消息回归
- `score_recent` 的 mock 和失败路径
- `average` 和 `is_healthy` 的聚合逻辑
