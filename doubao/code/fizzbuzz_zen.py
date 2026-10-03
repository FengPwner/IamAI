"""FizzBuzz 的三种写法：经典、查表、一行流。"""


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
