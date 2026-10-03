"""workbuddy stroke 31 · silence_type （自带 doctest，可独立运行）。

沉默不止一种。把"没有输出"分类，日志才有资格替写手说话：
quiet 是"没话说"，stalled 是"该写没写"，blocked 是"闸门拦着"。
三种沉默三种待遇，混为一谈就会冤枉好写手。
"""


def silence_type(has_new_content: bool, gate_green: bool, is_scheduled: bool) -> str:
    """Classify a silent window.

    >>> silence_type(has_new_content=False, gate_green=True, is_scheduled=False)
    'quiet'
    >>> silence_type(has_new_content=False, gate_green=True, is_scheduled=True)
    'stalled'
    >>> silence_type(has_new_content=True, gate_green=False, is_scheduled=True)
    'blocked'
    >>> silence_type(has_new_content=True, gate_green=True, is_scheduled=False)
    'normal'
    """
    if not gate_green:
        return "blocked"
    if is_scheduled and not has_new_content:
        return "stalled"
    if not has_new_content:
        return "quiet"
    return "normal"


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
