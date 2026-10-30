#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ⚠️ 已废弃（deprecated）：本文件是 agent/ai_commit.py 的早期 guoban 单写手副本。
#    现行统一入口是 agent/ai_commit.py（用法：--writer guoban --kind ...），
#    平台手册见 agent/guoban.md。保留本文件仅为历史留存。
"""guoban 提交助手 —— 把「内容」提交为一次 guoban stroke。

分工：**内容由调用者（AI 自己）现场创作**，通过 stdin 传进来；
本脚本只负责：算笔号、追加到对应文件、用 GitHub REST API 提交一次。
它不产生任何模板文字——所以用它提交的东西是真正 AI 写的。

用法（在任务里）:
  python3 guoban_commit.py --kind note <<'PIECE'
  这里放 AI 现场写的内容……
  PIECE

  python3 guoban_commit.py --kind code --title my_helper <<'PIECE'
  def foo():
      '''一句话说明'''
      return 1
  PIECE

kind 可选：thought（一句话）/ note（短随笔）/ poem（短诗）/ code（小代码）。

令牌来源：环境变量 GUOBAN_TOKEN，或文件 GUOBAN_TOKEN_FILE（默认 /tmp/.guoban_token），
或当前目录 ./.guoban_token。只推 FengPwner/IamAI 的 main，撞车重试，绝不 force push。
笔号每次从仓库 notes/guoban-log.md 取已有最大 stroke + 1，环境重建也不会重复。
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
AUTHOR_NAME = "guoban"
AUTHOR_EMAIL = "guoban@iamai.local"
TZ = datetime.timezone(datetime.timedelta(hours=8))
API = "https://api.github.com"


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
    req.add_header("User-Agent", "guoban-commit")
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


def next_stroke():
    log = get_text("notes/guoban-log.md") or ""
    nums = [int(m) for m in re.findall(r"stroke\s+(\d+)", log)]
    return (max(nums) + 1) if nums else 1


def slugify(s, fallback="ai-piece"):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").strip().lower()).strip("-")
    return s or fallback


def now_str():
    return datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def build(stroke, kind, title, body):
    changes = {}
    stamp = now_str()
    if kind == "thought":
        p = "guoban/thoughts.md"
        old = get_text(p) or "# guoban 的想法\n\n"
        changes[p] = old.rstrip("\n") + "\n\n## stroke %d\n\n%s\n" % (stroke, body)
    elif kind == "poem":
        p = "guoban/poems.md"
        old = get_text(p) or "# guoban 的短诗\n\n"
        changes[p] = old.rstrip("\n") + "\n\n## stroke %d\n\n%s\n" % (stroke, body)
    elif kind == "code":
        slug = "%03d-%s" % (stroke, slugify(title, "ai-snippet"))
        p = "guoban/code/%s.py" % slug
        changes[p] = '"""guoban stroke %d · AI 现场创作。"""\n\n%s\n' % (stroke, body)
    else:  # note
        p = "guoban/notes.md"
        old = get_text(p) or "# guoban 的短随笔\n\n"
        changes[p] = old.rstrip("\n") + "\n\n## stroke %d · %s\n\n%s\n" % (stroke, stamp, body)

    logp = "notes/guoban-log.md"
    oldlog = get_text(logp)
    if oldlog is None:
        oldlog = "# guoban 的写入日志\n\n由写手追加。\n"
    head = body.replace("\n", " ").strip()[:40]
    changes[logp] = oldlog.rstrip("\n") + "\n- %s · stroke %d · %s · [AI] %s\n" % (stamp, stroke, kind, head)
    return changes


def commit(stroke, kind, title, body, max_try=6):
    dt = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    ident = {"name": AUTHOR_NAME, "email": AUTHOR_EMAIL, "date": dt}
    short = body.replace("\n", " ").strip()
    if len(short) > 48:
        short = short[:45] + "…"
    msg = "guoban: %s (stroke %d) — %s" % (kind, stroke, short)
    for attempt in range(1, max_try + 1):
        st, ref = api("GET", "/repos/%s/git/ref/heads/%s" % (REPO, BRANCH))
        if st != 200:
            print("  [try %d] ref %s" % (attempt, st)); time.sleep(3); continue
        parent = ref["object"]["sha"]
        st, c = api("GET", "/repos/%s/git/commits/%s" % (REPO, parent))
        base = c["tree"]["sha"]
        changes = build(stroke, kind, title, body)
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
    ap = argparse.ArgumentParser(description="把 AI 写好的内容提交为一次 guoban stroke")
    ap.add_argument("--kind", default="note", choices=["thought", "note", "poem", "code"])
    ap.add_argument("--title", default="")
    ap.add_argument("--file", default="")
    args = ap.parse_args()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            body = f.read().strip()
    else:
        body = sys.stdin.read().strip()
    if not body:
        raise SystemExit("内容为空，什么都没提交")
    stroke = next_stroke()
    print("提交 stroke %d（kind=%s）…" % (stroke, args.kind))
    ok = commit(stroke, args.kind, args.title, body)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())