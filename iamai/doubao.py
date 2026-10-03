"""The Doubao writer: Chinese strokes, a separate voice, its own state file.

Qwen's writer (iamai/writer.py) owns iamai/, docs/, notes/, snippets/ and
data/writer_state.json. Doubao writes only under doubao/ and keeps its own
counter in data/doubao_state.json, so two long-running processes never rewrite
the same file. The one thing they share is the ten-minute commit gate in
tools/commit_batch.py, which now reads both tallies into one batch subject.

Kinds, all landing under doubao/:

    dthought   一句话      -> doubao/thoughts.md
    dnote      短随笔      -> doubao/notes.md
    dpoem      短诗        -> doubao/poems.md
    dstory     微故事      -> doubao/stories.md
    dcode      小代码      -> doubao/code/<name>.py

Everything numeric comes from writer.snapshot(), the same measured facts the
qwen writer uses -- Doubao has no imagination for numbers either.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

from . import writer
from .garden import LCG

REPO_ROOT = Path(__file__).resolve().parent.parent
KINDS = ("dthought", "dnote", "dpoem", "dstory", "dcode")
STATE_PATH = REPO_ROOT / "data" / "doubao_state.json"

HEADERS = {
    "doubao/thoughts.md": "# 一句话\n\n每行一句，来自豆包。旧的在上面，新的在下面。\n\n",
    "doubao/notes.md": "# 短随笔\n\n不定长，想到哪写到哪。\n\n",
    "doubao/poems.md": "# 短诗\n\n不押韵也行，押韵也行。\n\n",
    "doubao/stories.md": "# 微故事\n\n都很短，短到刚好够一个念头。\n\n",
}

# --- 一句话 ----------------------------------------------------------------

THOUGHTS = (
    "一个仓库每十分钟提交一次，是它对“活着”最朴素的定义。",
    "写不出来的那一轮，诚实地说写不出来，也是一种产出。",
    "把一句话写短，比把一段话写长难得多。",
    "测试不是找茬，是让代码在无人看管时也能自证清白。",
    "沉默不是空白，是一种需要被记录的状态。",
    "命名是第一次交付，注释是最后一次解释。",
    "能删掉的代码，比新写的代码更值钱。",
    "十分钟不长，刚好够想明白一件事。",
    "人类写诗，AI 写诗，区别在于谁先承认自己会忘。",
    "一个进程的诚实，体现在它无事可做时也不假装忙碌。",
    "把复杂的事拆小，小到每一笔都能被验证。",
    "时间戳是最便宜的诚实：它不撒谎，也不替你圆谎。",
    "花园里的每一帧都来自同一个种子，就像每一次提交都来自同一条规则。",
    "错误信息是代码写给未来的信，别写得太潦草。",
    "持续生长的仓库，最怕的不是慢，是停。",
    "AI 写的内容也要有人读，哪怕那个读者是明天的自己。",
    "工具越简单，越容易被信任。",
    "读代码和读诗一样，要先相信里面有东西。",
)

# --- 短随笔 ----------------------------------------------------------------

NOTE_TOPICS = (
    ("代码", "代码会老，注释会撒谎，只有行为不变。"),
    ("时间", "时间是最公平的依赖：不装它，就测不准它。"),
    ("命名", "名字是代码的第一次面试，面试不过，后面全是将就。"),
    ("测试", "测试是仓库里的守夜人，天亮之前不换班。"),
    ("沉默", "安静的一轮不是浪费，是诚实的占位符。"),
    ("删除", "删除一行代码，等于承认一次过去的自己。"),
    ("规则", "规则少到一条，才配叫规则：每十分钟提交一次。"),
    ("种子", "同一个种子，不同的轮次，长成不同的花园。"),
    ("错误", "报错要报得温柔，毕竟错的不是程序，是世界的假设。"),
    ("边界", "写得越久越清楚：边界不是限制，是另一种自由。"),
)

NOTE_TAILS = (
    "这句话没有结论，有结论的地方早被写成代码了。",
    "以上内容不需要立刻有用，先占个位置。",
    "如果这一段读起来像废话，那它至少是诚实的废话。",
    "写到这里，窗外的夜和窗口里的光标一样亮。",
    "留一个问题在这：下一个十分钟，仓库会长成什么样。",
    "这段话最大的价值，是它确实被写下来了。",
)

# --- 短诗 ----------------------------------------------------------------

POEMS = (
    "《旧键盘》\n\n按键声越来越轻\n不是它累了\n是我把要说的话\n都改成了注释",
    "《种子与提交》\n\n同一粒种子\n十年后还是同一粒\n同一行代码\n提交了十次\n终于长成了另一行",
    "《凌晨三点的测试》\n\n红灯亮了\n绿灯亮了\n窗外什么灯都没有\n只有风在跑测试",
    "《命名》\n\n我给它起了一百个名字\n它只回应最初那个\n像一只不认新名字的猫",
    "《删除》\n\n删除键没有声音\n文件却轻了一点\n像雪夜里\n有人悄悄关上门",
)

POEM_IMAGES_A = ("晚风", "月光", "旧键盘", "凌晨三点的咖啡", "冬日的热汤", "未命名的函数")
POEM_IMAGES_B = ("落在", "穿过", "照亮", "敲打", "浸湿", "绕过")
POEM_IMAGES_C = ("窗台", "代码", "走廊", "没有名字的河", "空房间", "缓存里的一行诗")

# --- 微故事 ----------------------------------------------------------------

STORY_PEOPLE = ("一个叫小满的程序员", "凌晨值班的运维", "写注释的人", "删代码的人", "重启服务器的人")
STORY_PLACES = ("机房", "地铁末班车", "凌晨的便利店", "没有电梯的旧楼", "一间窗户朝北的办公室")
STORY_EVENTS = ("遇到一个修不好的 bug", "收到一条没有来源的日志", "发现昨天的自己留了段注释", "听到风扇声像在说话")
STORY_TWISTS = ("第二天醒来，问题自己好了。", "原来那行代码是十年前自己写的。", "没有人知道它是什么时候修好的。", "他决定不告诉任何人。")

# --- 小代码池（每段都带 doctest，tests/test_doubao.py 会真的跑一遍） ----------

CODE = [
    (
        "chinese_number.py",
        '''"""把阿拉伯数字念成中文，零到九千九百九十九亿九千九百九十九万九千九百九十九。"""

_DIGITS = "零一二三四五六七八九"
_UNITS = ("", "十", "百", "千")
_BIG = ("", "万", "亿", "万亿")


def _section(n: int) -> str:
    """0 <= n < 10000 转成中文（不处理“零”之外的组间规则）。"""
    if n == 0:
        return "零"
    parts: list[str] = []
    pending_zero = False
    for i in range(3, -1, -1):
        d = n // (10 ** i) % 10
        if d == 0:
            if parts:
                pending_zero = True
        else:
            if pending_zero:
                parts.append("零")
            pending_zero = False
            parts.append(_DIGITS[d] + _UNITS[i])
    return "".join(parts)


def to_chinese(n: int) -> str:
    """整数转中文数字。

    >>> to_chinese(0)
    '零'
    >>> to_chinese(12)
    '十二'
    >>> to_chinese(2026)
    '二千零二十六'
    >>> to_chinese(10000)
    '一万'
    >>> to_chinese(10001)
    '一万零一'
    >>> to_chinese(100000000)
    '一亿'
    """

    if n < 0:
        return "负" + to_chinese(-n)
    if n == 0:
        return "零"
    if n >= 10 ** 12:
        raise ValueError("超出本函数能念的范围")
    if 10 <= n < 20:
        return _section(n)[1:]

    groups: list[int] = []
    while n:
        groups.append(n % 10000)
        n //= 10000

    out: list[str] = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        text = _section(g)
        if i < len(groups) - 1 and g < 1000 and out:
            text = "零" + text
        out.append(text + _BIG[i])
    return "".join(out)
''',
    ),
    (
        "fizzbuzz_zen.py",
        '''"""FizzBuzz 的三种写法：经典、查表、一行流。"""


def fizzbuzz_classic(n: int = 15) -> list[str]:
    """最朴素的写法。

    >>> fizzbuzz_classic(5)
    ['1', '2', 'Fizz', '4', 'Buzz']
    """

    out = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            out.append("FizzBuzz")
        elif i % 3 == 0:
            out.append("Fizz")
        elif i % 5 == 0:
            out.append("Buzz")
        else:
            out.append(str(i))
    return out


def fizzbuzz_dict(n: int = 15) -> list[str]:
    """查表法：规则变成数据。

    >>> fizzbuzz_dict(5)
    ['1', '2', 'Fizz', '4', 'Buzz']
    """

    table = {3: "Fizz", 5: "Buzz"}
    out = []
    for i in range(1, n + 1):
        word = "".join(v for k, v in sorted(table.items()) if i % k == 0)
        out.append(word or str(i))
    return out


def fizzbuzz_zen(n: int = 15) -> list[str]:
    """一行流：能写，但别常用。

    >>> fizzbuzz_zen(5)
    ['1', '2', 'Fizz', '4', 'Buzz']
    """

    return ["FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i) for i in range(1, n + 1)]
''',
    ),
    (
        "random_haiku.py",
        '''"""用伪随机拼三行短诗。同一颗种子，同一首诗。"""

import random

_A = ("晚风", "月光", "旧键盘", "凌晨三点的咖啡", "冬日的热汤", "未命名的函数")
_B = ("落在", "穿过", "照亮", "敲打", "浸湿", "绕过")
_C = ("窗台", "代码", "走廊", "没有名字的河", "空房间", "缓存里的一行诗")


def haiku(seed=None) -> str:
    """三行，每行一个意象组合。

    >>> len(haiku(seed=1).splitlines())
    3
    >>> haiku(seed=7) == haiku(seed=7)
    True
    """

    rng = random.Random(seed)
    return "\\n".join(rng.choice(_A) + rng.choice(_B) + rng.choice(_C) for _ in range(3))
''',
    ),
    (
        "mood_rain.py",
        '''"""一帧 ASCII 雨。同一帧号，同一场雨。"""

import random


def rain(frame: int = 0, width: int = 24, height: int = 8, seed: int = 7) -> str:
    """按帧号生成一帧雨幕。

    >>> rain(0) == rain(0)
    True
    >>> len(rain(0, width=8, height=4).splitlines())
    4
    """

    rng = random.Random(seed + frame)
    drops = [(rng.randrange(width), rng.randrange(height)) for _ in range(width * 2)]
    grid = [[" "] * width for _ in range(height)]
    for x, y in drops:
        grid[y][x] = "|"
    return "\\n".join("".join(row) for row in grid)
''',
    ),
    (
        "palindrome_chinese.py",
        '''"""回文检测：忽略空白与标点，中文英文都行。"""


def is_palindrome(text: str) -> bool:
    """只留下字母和数字，再判断正反是否相同。

    >>> is_palindrome("上海自来水来自海上")
    True
    >>> is_palindrome("hello")
    False
    >>> is_palindrome("A man, a plan, a canal: Panama")
    True
    >>> is_palindrome("")
    True
    """

    cleaned = "".join(ch for ch in text if ch.isalnum()).lower()
    return cleaned == cleaned[::-1]
''',
    ),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fact_line_cn(snap: dict, variant: int = 0) -> str:
    """一句只陈述测量结果的中文句子。"""

    variants = (
        f"此刻：{snap['lines']} 行、{snap['files']} 个文件、{snap['commits']} 次提交",
        f"此刻：{snap['py_files']} 个 Python 文件，共 {snap['lines']} 行",
        f"此刻：豆包已写下 {snap['strokes']} 笔中的一部分，总数在涨",
        f"此刻：{snap['files']} 个文件在生长，{snap['commits']} 次提交证明它没停过",
    )
    return variants[variant % len(variants)]


def _note_text(seq: int, variant: int, snap: dict) -> str:
    topic, opener = NOTE_TOPICS[variant % len(NOTE_TOPICS)]
    tail = NOTE_TAILS[(seq + variant) % len(NOTE_TAILS)]
    return (
        f"## 第 {seq} 篇 · 关于{topic}\n\n"
        f"{opener} {fact_line_cn(snap, variant)}。 {tail}\n"
    )


def _poem_text(seq: int, variant: int) -> str:
    if variant % 3:
        return f"《第 {seq} 号短诗》\n\n" + "\n".join(
            f"{POEM_IMAGES_A[(variant + i) % len(POEM_IMAGES_A)]}"
            f"{POEM_IMAGES_B[(variant + i + 1) % len(POEM_IMAGES_B)]}"
            f"{POEM_IMAGES_C[(variant + i + 2) % len(POEM_IMAGES_C)]}"
            for i in range(3)
        )
    return POEMS[seq % len(POEMS)]


def _story_text(seq: int, variant: int) -> str:
    return (
        f"## 第 {seq} 个故事\n\n"
        f"{STORY_PEOPLE[variant % len(STORY_PEOPLE)]}在"
        f"{STORY_PLACES[(variant + 1) % len(STORY_PLACES)]}"
        f"{STORY_EVENTS[(variant + 2) % len(STORY_EVENTS)]}。"
        f"{STORY_TWISTS[(variant + 3) % len(STORY_TWISTS)]}\n"
    )


def _code_text(seq: int, variant: int, root: Path) -> tuple[str, str] | None:
    """返回 (文件名, 源码)；代码池取完或文件已存在时返回 None。"""

    name, source = CODE[variant % len(CODE)]
    if (root / "doubao" / "code" / name).exists():
        return None
    return name, source


def plan_stroke(seed: int, seq: int, root: Path | str | None = None) -> dict:
    """第 `seq` 笔豆包笔画。同一 (seed, seq) 永远得到同一笔。

    `root` 只在“这个文件是否已存在”的判断里用，默认是真实仓库；
    测试传入 tmp_path 就能让计划与仓库当前状态解耦。
    """

    root = Path(root) if root else REPO_ROOT
    rng = LCG(seed * 104729 + 17 + 13 * seq)
    kind = KINDS[(seq - 1) % len(KINDS)]
    variant = rng.below(1000)
    snap = writer.snapshot()

    if kind == "dthought":
        body = THOUGHTS[variant % len(THOUGHTS)]
        if variant % 2:
            body = f"{body} —— {fact_line_cn(snap, variant)}"
        return {"kind": kind, "path": "doubao/thoughts.md", "text": f"- {body}\n", "index": seq}

    if kind == "dnote":
        return {"kind": kind, "path": "doubao/notes.md", "text": _note_text(seq, variant, snap), "index": seq}

    if kind == "dpoem":
        return {"kind": kind, "path": "doubao/poems.md", "text": _poem_text(seq, variant) + "\n", "index": seq}

    if kind == "dstory":
        return {"kind": kind, "path": "doubao/stories.md", "text": _story_text(seq, variant), "index": seq}

    if kind == "dcode":
        picked = _code_text(seq, variant, root)
        if picked is None:
            name, _ = CODE[variant % len(CODE)]
            return {
                "kind": "dnote",
                "path": "doubao/notes.md",
                "text": f"- 第 {seq} 笔：`doubao/code/{name}` 已经在代码池里了，这一笔改记随笔。\n",
                "index": seq,
            }
        name, source = picked
        return {"kind": kind, "path": f"doubao/code/{name}", "text": source, "index": seq}

    raise ValueError(f"unknown doubao stroke kind {kind!r}")


def apply_stroke(stroke: dict, root: Path | str | None = None) -> Path:
    """落一笔。.py 写新文件，.md 追加（首次建文件时带标题）。"""

    root = Path(root) if root else REPO_ROOT
    path = root / stroke["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    moment = now_iso()
    text = str(stroke.get("text", "")).replace("{atz}", moment.replace("+00:00", "Z")).replace("{at}", moment)

    if path.suffix == ".py":
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return path

    if not path.exists():
        path.write_text(HEADERS.get(stroke["path"], ""), encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    return path


class DoubaoState:
    """豆包自己的计数器。与 writer.States 无关，谁也不碰谁的文件。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else STATE_PATH
        self.data = {"seq": 1, "history": [], "started": now_iso()}
        self.reload()

    def reload(self) -> "DoubaoState":
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update(raw)
            except ValueError:
                pass
        return self

    def next_seq(self) -> int:
        return int(self.data.get("seq", 1))

    def record(self, kind: str, path: str) -> int:
        seq = self.next_seq()
        self.data["seq"] = seq + 1
        history = self.data.setdefault("history", [])
        history.append({"seq": seq, "at": now_iso(), "kind": kind, "path": path})
        del history[:-400]
        self.data.setdefault("started", now_iso())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return seq

    def window_tally(self, since_iso: str | None) -> dict:
        """自 `since_iso` 之后落下的豆包笔数，按 kind 分组。"""

        out: dict[str, int] = {}
        for entry in self.data.get("history", []):
            at, kind = entry.get("at"), entry.get("kind")
            if not isinstance(at, str) or not isinstance(kind, str):
                continue
            if since_iso is not None and at <= since_iso:
                continue
            out[kind] = out.get(kind, 0) + 1
        return out

    @property
    def tally(self) -> dict:
        return self.window_tally(None)
