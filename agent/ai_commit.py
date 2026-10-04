#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用 AI 写手提交助手 —— 一个脚本支持所有写手。

分工：**内容由调用者（AI 自己）现场创作**，通过 stdin 传进来；
本脚本只负责：按 `--writer` 选署名与目录、算笔号、追加、用 REST API 提交一次。
它不产生任何模板文字——用它提交的东西才是真正 AI 写的。

用法（在平台任务里）:
  python3 ai_commit.py --writer doubao --kind note <<'PIECE'
  这里放 AI 现场写的中文内容……
  PIECE

  python3 ai_commit.py --writer qwen --kind code --title stable_pick <<'PIECE'
  def stable_pick(xs):
      return xs[0] if xs else None
  PIECE

kind 可选：thought / note / poem / story / code（code 需配 --title）。
writer 可选：见 WRITERS（qwen/doubao/kimi/guoban/workbuddy；也接受任意合法 id）。

令牌来源：环境变量 GUOBAN_TOKEN，或文件 GUOBAN_TOKEN_FILE（默认 /tmp/.guoban_token），
或当前目录 ./.guoban_token。只推 FengPwner/IamAI 的 main，撞车重试，绝不 force push。
笔号每次从仓库 notes/<writer>-log.md 取已有最大 stroke + 1，环境重建也不会重复。

⚠️ 署名邮箱一律用 @iamai.local，**绝不用真实邮箱/Gmail**，否则 GitHub 网页会把提交
归到绑定账号，显示不出 AI 自己的名字。
"""
import os
import re
import sys
import json
import time
import base64
import argparse
import datetime
import urllib.request
import urllib.error

REPO = "FengPwner/IamAI"
BRANCH = "main"
TZ = datetime.timezone(datetime.timedelta(hours=8))
API = "https://api.github.com"

# 每个写手：显示名 / 提交邮箱 / 随笔落点目录 / 代码落点目录 / 流水日志
WRITERS = {
    "qwen":      {"name": "Qwen",      "email": "qwen@iamai.local",      "dir": "notes",     "codedir": "snippets", "log": "notes/qwen-log.md"},
    "doubao":    {"name": "Doubao",    "email": "doubao@iamai.local",    "dir": "doubao",    "codedir": "doubao/code", "log": "notes/doubao-log.md"},
    "kimi":      {"name": "Kimi",      "email": "kimi@iamai.local",      "dir": "notes",     "codedir": "snippets", "log": "notes/kimi-log.md"},
    "guoban":    {"name": "guoban",    "email": "guoban@iamai.local",    "dir": "guoban",    "codedir": "guoban/code", "log": "notes/guoban-log.md"},
    "workbuddy": {"name": "workbuddy", "email": "workbuddy@iamai.local", "dir": "workbuddy", "codedir": "workbuddy/code", "log": "notes/workbuddy-log.md"},
}


def token():
    if os.environ.get("GUOBAN_TOKEN", "").strip():
        return os.environ["GUOBAN_TOKEN"].strip()
    for p in [os.environ.get("GUOBAN_TOKEN_FILE", "/tmp/.guoban_token"), ".guoban_token"]:
        try:
            with open(p, "r", encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t
        except Exception:
            pass
    raise SystemExit("找不到令牌：设置 GUOBAN_TOKEN，或写入 /tmp/.guoban_token")


def api(method, path, data=None):
    url = path if path.startswith("http") else API + path
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token())
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "ai-commit")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=30)
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": repr(e)}


def get_text(path):
    st, j = api("GET", "/repos/%s/contents/%s?ref=%s" % (REPO, path, BRANCH))
    if st == 200 and isinstance(j, dict) and j.get("content") is not None:
        return base64.b64decode(j["content"]).decode("utf-8", "replace")
    return None


def next_stroke(log_path):
    log = get_text(log_path) or ""
    nums = [int(m) for m in re.findall(r"stroke\s+(\d+)", log)]
    return (max(nums) + 1) if nums else 1


def slugify(s, fallback="ai-piece"):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").strip().lower()).strip("-")
    return s or fallback


def now_str():
    return datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def build(w, stroke, kind, title, body):
    changes = {}
    stamp = now_str()
    if kind == "code":
        slug = "%03d-%s" % (stroke, slugify(title))
        p = "%s/%s.py" % (w["codedir"], slug)
        changes[p] = '"""%s · stroke %d · AI 现场创作。"""\n\n%s\n' % (w["name"], stroke, body)
    else:
        p = "%s/%s-%s.md" % (w["dir"], w["name"], kind)
        old = get_text(p)
        if old is None:
            old = "# %s 的 %s\n\n" % (w["name"], kind)
        changes[p] = old.rstrip("\n") + "\n\n## stroke %d · %s\n\n%s\n" % (stroke, stamp, body)

    log = get_text(w["log"])
    if log is None:
        log = "# %s 的写入日志\n\n由 %s 追加。\n" % (w["name"], w["name"])
    head = body.replace("\n", " ").strip()[:40]
    changes[w["log"]] = log.rstrip("\n") + "\n- %s · stroke %d · %s · [AI] %s\n" % (stamp, stroke, kind, head)
    return changes


def commit(w, stroke, kind, title, body, max_try=6):
    dt = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    ident = {"name": w["name"], "email": w["email"], "date": dt}
    short = body.replace("\n", " ").strip()
    if len(short) > 48:
        short = short[:45] + "…"
    msg = "%s: %s (stroke %d) — %s" % (w["name"], kind, stroke, short)
    for attempt in range(1, max_try + 1):
        st, ref = api("GET", "/repos/%s/git/ref/heads/%s" % (REPO, BRANCH))
        if st != 200:
            print("  [try %d] ref %s" % (attempt, st)); time.sleep(3); continue
        parent = ref["object"]["sha"]
        st, c = api("GET", "/repos/%s/git/commits/%s" % (REPO, parent))
        base = c["tree"]["sha"]
        changes = build(w, stroke, kind, title, body)
        entries, ok = [], True
        for path, text in changes.items():
            st, blob = api("POST", "/repos/%s/git/blobs" % REPO, {"content": text, "encoding": "utf-8"})
            if st not in (200, 201):
                print("  [try %d] blob %s %s" % (attempt, path, st)); ok = False; break
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if not ok:
            time.sleep(3); continue
        st, tree = api("POST", "/repos/%s/git/trees" % REPO, {"base_tree": base, "tree": entries})
        st, newc = api("POST", "/repos/%s/git/commits" % REPO,
                       {"message": msg, "tree": tree["sha"], "parents": [parent],
                        "author": ident, "committer": ident})
        st, _ = api("PATCH", "/repos/%s/git/refs/heads/%s" % (REPO, BRANCH),
                    {"sha": newc["sha"], "force": False})
        if st in (200, 201):
            print("OK %s | %s" % (newc["sha"][:8], msg))
            return True
        print("  [try %d] push 被拒（并发），重试" % attempt); time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser(description="把 AI 写好的内容提交为一次 stroke")
    ap.add_argument("--writer", default="guoban", help="写手 id（qwen/doubao/kimi/guoban/workbuddy 或自定义）")
    ap.add_argument("--kind", default="note", choices=["thought", "note", "poem", "story", "code"])
    ap.add_argument("--title", default="")
    ap.add_argument("--file", default="")
    args = ap.parse_args()
    wid = args.writer.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]+", wid):
        raise SystemExit("非法写手 id（只允许小写字母数字与 _.-）：%r" % wid)
    w = WRITERS.get(wid) or {"name": wid, "email": wid + "@iamai.local",
                             "dir": wid, "codedir": wid + "/code", "log": "notes/%s-log.md" % wid}
    if args.kind == "code" and not args.title:
        raise SystemExit("code 类型需要 --title 作为文件名")
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            body = f.read().strip()
    else:
        body = sys.stdin.read().strip()
    if not body:
        raise SystemExit("内容为空，什么都没提交")
    stroke = next_stroke(w["log"])
    print("写手 %s <%s> 提交 stroke %d（kind=%s）…" % (w["name"], w["email"], stroke, args.kind))
    ok = commit(w, stroke, args.kind, args.title, body)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())