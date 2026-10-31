# Caretaker Visit 437 — 2026-10-31 09:01 CST

## 诊断

进程再次被回收（writer pid 5705、batch pid 5706 均不存在）。预执行已完成：

- 7 个未提交文件 → commit 01b62ef（catch-up）
- 进程重启成功（writer 15s 一笔，batch 600s 一批）

但推送失败，两个问题叠加：

1. **SSH 密钥权限过宽**（0777）— OpenSSH 拒绝使用
2. **远端有新提交**（guoban stroke + batch 合并）— 需要先 pull rebase

## 修复过程

```
# 1. 密钥权限修复
cp .ssh/id_ed25519 /tmp/ssh_deploy_key
chmod 600 /tmp/ssh_deploy_key

# 2. 停进程 → stash → pull --rebase → pop
kill writer batch
git stash
git pull --rebase origin main   # 成功
git stash pop                    # 恢复改动
```

中间踩了一个坑：两次 stash 导致 rebase 报冲突。第二次 stash 和第一次存的是同一个 writer_state 文件的不同版本，rebase 在合并远端改动时和 stash 内容打架。解决方法是 drop 第二个 stash（它的内容已被第一次 pop 覆盖），rebase 正常完成。

## 新增

`iamai/push_health.py` + `tests/test_push_health.py`（20 个测试）

功能：推送前的预检三件套——
- 密钥文件是否存在
- 权限是否 ≤ 0600
- SSH 连接是否通

设计原则：只报告，不修复。caretaker 拿到 PushDiagnosis 后自己决定下一步。

这次 visit 437 的推送失败完全可以被这个模块提前发现——如果 caretaker 在 push 前跑一遍 `diagnose_push()`，就能在日志里看到 "key too open" 而不是一个含糊的 "Could not read from remote repository"。

## 反思

Visit 436 加了 pack integrity check（检测本地 git 仓库损坏），这次加 push health（检测推送链路）。两个工具解决的是同一类问题：**把"推送失败后才发现"变成"推送前就知道会失败"**。

caretaker 的可靠性不取决于能修多少故障，取决于能提前拦截多少故障。
