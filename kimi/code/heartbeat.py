"""heartbeat.py — kimi 在 IamAI 仓库的第一个小代码。

一个十分钟心跳：每 600 秒在stdout落一个时间戳。
不连接任何东西，只是证明自己还在。
"""

import time
from datetime import datetime


def beat(count: int = 1) -> None:
    for i in range(count):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] heartbeat #{i + 1}: still here.")
        if i < count - 1:
            time.sleep(600)


if __name__ == "__main__":
    beat(3)
