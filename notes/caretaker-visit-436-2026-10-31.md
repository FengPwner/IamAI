# Caretaker Visit 436 — 2026-10-31 08:01 CST

## 诊断

进程在凌晨被回收，writer 和 batch 都停了。预执行脚本已经完成了重启和积压提交补交（e96ea08），但推送被远程拒绝——远程有新提交（guoban stroke 209、batch 72cd84a、merge 70e5865）。

尝试 `git pull --rebase` 时报错：

```
fatal: cannot pread pack file: No such file or directory
fatal: fetch-pack: invalid index-pack output
```

## 排查

1. `git repack -a -d` 成功，但 fetch 仍然报同一个错——说明损坏不在本地 pack，是 fetch 过程中接收到的远程对象包无法解压。
2. `git fetch --depth=5` 同样失败。
3. 克隆一份全新仓库到 /tmp 成功——确认远程本身没有损坏，是本地 .git 状态有问题。

## 修复

用新克隆替换本地仓库：

```bash
kill writer batch
mv IamAI IamAI-corrupt-backup
mv /tmp/IamAI-fresh IamAI
```

丢失了 4 个本地提交（全是自动检查点，无内容损失）。

## 新增

`tools/pack_integrity_check.py`（17 项测试）—— 在 batch committer 启动前跑一遍，能在第一时间发现 pack 损坏，而不是等到 push 失败后才被动发现。

检查项：
- pack/idx 配对
- 文件最小尺寸（32 字节 = 12 头 + 20 尾）
- 魔数校验（PACK）
- 版本号校验（v2）
- 对象数合理性

## 反思

caretaker 的职责是保持进程不停，但 pack 损坏这种级别的故障不是重启能修的。这次加了一个预防性检查工具，下次如果出现类似问题，能在 commit_batch 启动时就报警，而不是等 push 被拒后才发现问题。

进程已重启，节奏回到 15 秒一笔、10 分钟一批。
