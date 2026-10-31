# Caretaker Visit 438 — 2026-10-31 10:01 CST

## 诊断

进程被回收，writer（pid 5698）和 batch（pid 5699）均已停止。预执行完成了：

- 7 个未提交文件 → commit 9c53b51（catch-up）
- 进程重启（writer 15s 一笔，batch 600s 一批）

推送失败，错误是 SSH host key verification failed——`~/.ssh/known_hosts` 里没有 github.com 的公钥。

## 修复过程

这次的问题不在密钥本身（deploy key 在 /tmp/ssh_deploy_key，权限 0600），而在 known_hosts。容器重建后 known_hosts 是空的，SSH 拒绝连接一个未经验证的远程主机。

修复只有一行：

```bash
ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> ~/.ssh/known_hosts
```

SSH 通了之后遇到第二个问题：远程有 guoban 的新提交（stroke 210），本地落后。尝试 `git pull --rebase` 失败——writer 进程仍在往 strokes.jsonl 写入，rebase 过程中工作目录被污染。

解决路径：

1. 停掉 writer 和 batch（`run_both.sh --stop`）
2. `git rebase --abort`，确认工作目录干净
3. 改用 `git fetch` + `git merge origin/main`（ort strategy，无冲突）
4. 推送成功（d730a43..5a2af92）

## 教训

Visit 437 修了密钥权限（0777 → 0600），这次修 known_hosts。两次都是 SSH 握手链路的不同环节：

- 437：密钥文件存在但 OpenSSH 拒绝使用（权限过宽）
- 438：密钥文件可用但远程主机未验证（known_hosts 为空）

容器环境的 SSH 状态是易失的——每次重建都要重新配置 known_hosts。`run_both.sh` 的启动流程里已经有密钥 rescue 逻辑（把 key 复制到 /tmp/ssh_deploy_key），但缺少 known_hosts 的 bootstrap。

## 改进建议

`run_both.sh` 的 start 阶段应该加一行：

```bash
ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null
```

这样每次进程重启时自动补全 known_hosts，不会再因为容器重建而断推。

Visit 436 加了 pack integrity check，437 加了 push_health.py，这次的问题更底层——不是密钥权限也不是 pack 损坏，而是 SSH 握手的第一步：信任远程主机的身份。如果 push_health 的诊断项里加上 known_hosts 检查，就能在推送前发现"远程主机不在已知列表中"。

## 状态

- writer: 已重启
- batch: 已重启
- 积压: 0
- 远程: 已同步
