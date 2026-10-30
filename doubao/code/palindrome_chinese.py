"""回文检测：忽略空白与标点，中文英文都行。"""


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
