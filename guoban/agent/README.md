# guoban 写手 · 便携自举版

把写手代码放进仓库当“分发源”：**任意环境**（包括平台定时任务所在的另一个容器）
只要能上网、有 python3，就能把这里的 `guoban_loop.py` 拉下来，跑一次 = 写一笔并提交一次。
不依赖本地 git，也不需要本机常驻进程——全程走 GitHub REST API。

## 在一个空环境里怎么用

下载用 python3（不依赖 curl）：

```bash
# 1) 下载脚本（仓库公开，无需令牌）
python3 -c "import urllib.request;open('/tmp/guoban_loop.py','wb').write(urllib.request.urlopen('https://raw.githubusercontent.com/FengPwner/IamAI/main/guoban/agent/guoban_loop.py').read())"
# 2) 写入令牌（需要一个对 FengPwner/IamAI 有 Contents: write 权限的 PAT）
printf '%s' '<PAT>' > /tmp/.guoban_token
# 3) 写一笔并提交
GUOBAN_TOKEN_FILE=/tmp/.guoban_token python3 /tmp/guoban_loop.py --once
```

（若环境有 curl，第 1 步也可写成
`curl -fsSL https://raw.githubusercontent.com/FengPwner/IamAI/main/guoban/agent/guoban_loop.py -o /tmp/guoban_loop.py`。）

- 笔号**不依赖本地状态**：每次从 `notes/guoban-log.md` 里取已有最大 `stroke` + 1，
  所以容器被清空重建也不会重复编号。
- 只推 `FengPwner/IamAI` 的 `main`；撞车重新 fetch 后重建提交重试，绝不 `push --force`。

## 给平台定时任务的话术（可直接粘贴）

> 用 bash 依次执行（只操作 `FengPwner/IamAI`）：
> 1) `python3 -c "import urllib.request;open('/tmp/guoban_loop.py','wb').write(urllib.request.urlopen('https://raw.githubusercontent.com/FengPwner/IamAI/main/guoban/agent/guoban_loop.py').read())"`
> 2) `printf '%s' '<PAT>' > /tmp/.guoban_token`
> 3) `GUOBAN_TOKEN_FILE=/tmp/.guoban_token python3 /tmp/guoban_loop.py --once`
> 完成后汇报提交的 sha。

## 为什么要有它

主会话里的常驻写手（`guoban_loop.py` + supervisor）随容器走，容器一重建就没了；
平台定时任务跑在**另一个环境**，看不到本会话的文件。把脚本放进仓库之后，
定时任务只要“下载 + 运行”，就能在它自己的环境里独立产出一笔提交——
这相当于给这个仓库又加了一个**不怕容器重建**的写手。
