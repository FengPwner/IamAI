"""commit_entropy — measure diversity of commit messages via Shannon entropy.

a healthy repository produces varied, descriptive commit messages that
reflect genuine changes.  when entropy drops, it signals that the
writer is emitting templated or near-identical messages — a sign of
low-quality automated commits or a stuck generation loop.

entropy model
~~~~~~~~~~~~~

the module tokenises each commit message into words, builds a frequency
distribution over the most recent *n* messages, and computes the
normalised Shannon entropy:

    H = -Σ (p_i · log₂ p_i) / log₂(k)

where *k* is the vocabulary size.  the result is scaled to [0, 1]:
0 means every message is identical; 1 means maximum diversity.

entropy bands
~~~~~~~~~~~~~

===========  ===========  ================================================
band         entropy      meaning
===========  ===========  ================================================
rich         0.80 – 1.00  high diversity; messages are descriptive
healthy      0.60 – 0.80  normal variation
flat         0.40 – 0.60  noticeable repetition; templates dominating
stale        0.20 – 0.40  severe repetition; most messages alike
clone        0.00 – 0.20  near-identical messages; intervention needed
===========  ===========  ================================================

public api
~~~~~~~~~~

- ``tokenise(message)``           — lowercase word extraction
- ``shannon_entropy(tokens)``     — raw Shannon entropy in bits
- ``normalised_entropy(tokens)``  — entropy scaled to [0, 1]
- ``classify_entropy(h)``         — map a float to an entropy band
- ``analyse_commits(messages)``   — full analysis pipeline
- ``entropy_report(messages)``    — one-call convenience wrapper
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# band classification
# ---------------------------------------------------------------------------

_BANDS = [
    ("clone",   0.00, 0.20),
    ("stale",   0.20, 0.40),
    ("flat",    0.40, 0.60),
    ("healthy", 0.60, 0.80),
    ("rich",    0.80, 1.01),  # 1.01 to include 1.0
]


def classify_entropy(h: float) -> str:
    """Return the entropy band for a normalised entropy value.

    >>> classify_entropy(0.0)
    'clone'
    >>> classify_entropy(0.5)
    'flat'
    >>> classify_entropy(0.9)
    'rich'
    >>> classify_entropy(1.0)
    'rich'
    """
    for band, lo, hi in _BANDS:
        if lo <= h < hi:
            return band
    return "rich"  # fallback for h == 1.0 exactly at boundary


# ---------------------------------------------------------------------------
# tokenisation
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenise(message: str) -> List[str]:
    """Extract lowercase word tokens from a commit message.

    Punctuation and special characters are stripped.  Empty messages
    return an empty list.

    >>> tokenise("feat: add commit entropy module")
    ['feat', 'add', 'commit', 'entropy', 'module']
    >>> tokenise("")
    []
    >>> tokenise("!!!")
    []
    """
    return _WORD_RE.findall(message.lower())


# ---------------------------------------------------------------------------
# entropy computation
# ---------------------------------------------------------------------------


def shannon_entropy(tokens: List[str]) -> float:
    """Compute raw Shannon entropy in bits from a list of tokens.

    Returns 0.0 for an empty list or a list with a single unique token.

    >>> shannon_entropy(["a", "a", "a"])
    0.0
    >>> abs(shannon_entropy(["a", "b"]) - 1.0) < 1e-9
    True
    """
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    if total <= 1:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def normalised_entropy(tokens: List[str]) -> float:
    """Compute Shannon entropy normalised to [0, 1] by vocabulary size.

    Returns 0.0 when vocabulary size is 0 or 1 (no diversity possible).

    >>> normalised_entropy(["a", "a", "a"])
    0.0
    >>> abs(normalised_entropy(["a", "b"]) - 1.0) < 1e-9
    True
    """
    if not tokens:
        return 0.0
    vocab_size = len(set(tokens))
    if vocab_size <= 1:
        return 0.0
    raw = shannon_entropy(tokens)
    max_entropy = math.log2(vocab_size)
    if max_entropy == 0:
        return 0.0
    return min(raw / max_entropy, 1.0)


# ---------------------------------------------------------------------------
# commit analysis
# ---------------------------------------------------------------------------


def analyse_commits(messages: List[str], window: int = 20) -> Dict[str, Any]:
    """Analyse the entropy of the most recent *window* commit messages.

    Returns a dict with:

    - ``entropy``      — normalised entropy [0, 1]
    - ``band``         — entropy band name
    - ``vocab_size``   — number of unique tokens
    - ``total_tokens`` — total token count
    - ``top_tokens``   — 10 most common tokens with counts
    - ``sample_size``  — number of messages actually analysed
    - ``summary``      — human-readable one-liner

    ``messages`` should be ordered newest-first (as from ``git log``).
    """
    recent = messages[:window]
    all_tokens: List[str] = []
    for msg in recent:
        all_tokens.extend(tokenise(msg))

    h = normalised_entropy(all_tokens)
    band = classify_entropy(h)
    freq = Counter(all_tokens)

    return {
        "entropy": round(h, 4),
        "band": band,
        "vocab_size": len(freq),
        "total_tokens": len(all_tokens),
        "top_tokens": freq.most_common(10),
        "sample_size": len(recent),
        "summary": (
            f"{len(freq)} unique tokens over {len(all_tokens)} tokens "
            f"from {len(recent)} commits (entropy {h:.3f}, {band})"
        ),
    }


def entropy_report(
    messages: List[str],
    window: int = 20,
) -> Dict[str, Any]:
    """One-call convenience wrapper: analyse and return full report.

    Identical to ``analyse_commits`` but includes a ``recommendation``
    field suggesting corrective action when entropy is low.
    """
    result = analyse_commits(messages, window=window)

    recommendations = {
        "clone": "urgent: commit messages are nearly identical — "
                 "check for template loops or stuck writer state",
        "stale": "severe repetition detected — diversify commit "
                 "templates or rotate topic areas",
        "flat": "noticeable repetition — consider enriching commit "
                "descriptions with more context",
        "healthy": "message diversity is acceptable",
        "rich": "excellent diversity — messages are descriptive and varied",
    }

    result["recommendation"] = recommendations.get(result["band"], "")
    return result
