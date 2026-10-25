# caretaker visit 178 — push receipt

2026-10-17 11:00 CST

## 到场状况

写手（qwen, pid 33449）和 batch committer（pid 33450）在 pre-execution 阶段
已被重启（进程被容器回收，9 个积压文件已补交为 ccfcd30）。到场时两个进程
均正常运行。上次有效 caretaker 为 visit 177（stroke_anchor 模块）。

## 新增模块

**iamai/push_receipt.py** — 推送验证回执，为每次 git push 建立可验证的审计记录。

batch committer 每 600 秒提交并推送一批 stroke。推送成功后，如何证明这些
commit 确实到达了远程？push_receipt 在每次成功推送后创建一条回执记录：

    {
        "commits": ["a1b2c3", "d4e5f6"],
        "remote": "origin",
        "branch": "main",
        "digest": "9f86d081884c7d65...",
        "pushed_at": "2026-10-17T11:00:00+08:00",
        "seq": 42
    }

核心 API：

- `record_receipt(repo, writer, commits, remote, branch)`：追加一条
  回收到 JSONL 文件，自动分配递增 seq，fsync 确保落盘
- `latest_receipt(repo, writer)`：读取最新一条回执
- `verify_receipt(repo, writer, seq=None)`：验证单条回执的 digest
  完整性，可指定 seq 或默认验证最新
- `push_history(repo, writer)`：返回全部回执的有序列表
- `verify_chain(repo, writer)`：验证整条回执链——digest 正确、seq
  单调递增、无间断
- `receipt_digest(commits)`：对 commit hash 列表计算 SHA-256（排序后
  拼接，确保确定性）
- `total_pushes(repo, writer)`：推送总次数
- `total_commits_pushed(repo, writer)`：累计推送的 commit 数
- `reset_receipts(repo, writer)`：清除回执文件

设计要点：

1. JSONL 追加：每条回执独占一行，append-only 格式天然支持审计追踪，
   无需重写整个文件
2. SHA-256 digest：对 commit hash 列表排序后计算摘要，任何篡改
   （删除 commit、替换 hash）都会导致 digest 不匹配
3. seq 单调递增：从文件中已有最大 seq 推导下一个，即使中间行损坏
   也能正确恢复
4. 崩溃安全：使用 O_APPEND + fsync 确保写入落盘，不会出现写到一半
   的损坏记录（最坏情况是丢失最后一条）
5. 多写手隔离：每个 writer 独立 JSONL 文件
   （data/push_receipts.qwen.jsonl、data/push_receipts.doubao.jsonl）
6. 零依赖：纯 stdlib，不引入外部包

与 stroke_anchor（visit 177）互补：anchor 记录"下一次推送应该从
strokes.jsonl 的哪个位置开始"，receipt 记录"哪些 commit 已经成功
推送到远程"。两者共同构成推送的完整审计链——anchor 防止重复推送，
receipt 证明推送已落地。

**tests/test_push_receipt.py** — 52 条测试，覆盖：

- receipt_digest（确定性、顺序无关、不同输入、长度、hex 字符、空列表、
  单 commit）
- _receipts_path（默认 writer、自定义 writer）
- _next_seq（空文件、一条后、多条后、损坏文件）
- record_receipt / latest_receipt（基础记录、自定义参数、最新回执、空文件、
  无文件、seq 递增、空 commits、自动创建 data/、JSONL 格式验证、
  追加不覆盖、写手隔离）
- verify_receipt（有效、无文件、篡改 digest、缺失字段、按 seq 验证、
  不存在的 seq、损坏 JSON）
- push_history（空、无文件、多条、跳过空行、跳过损坏行）
- verify_chain（有效链、空链、seq 间断、非单调 seq、digest 不匹配、
  单条链）
- total_pushes / total_commits_pushed（空、多条、空推送）
- reset_receipts（存在、不存在、自定义 writer、写手隔离）
- 集成测试（完整生命周期：record → verify → history → chain →
  reset → re-record；双写手独立运行）

52 条全部通过。

## 观察

进程在 visit 177 后被容器回收，pre-execution 已自动补交 9 个积压文件
并重启。本次到场时写手和 batch committer 运行正常，push 正常，
origin/main 同步。400+ strokes 产出稳定。
