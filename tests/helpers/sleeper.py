"""假等待：记录时长，并同时推进 FixedClock 的墙钟与单调时钟；另提供只回拨墙钟的方法。"""
from __future__ import annotations
from datetime import timedelta

class Sleeper:
    def __init__(self, clock=None, on_sleep=None):
        self.clock, self.on_sleep, self.calls = clock, on_sleep, []
    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.clock is not None:
            self.clock.advance(seconds)
        if self.on_sleep is not None:
            self.on_sleep(seconds)

def rewind_wall(clock, seconds: float) -> None:
    """只回拨墙钟，单调时钟不动（模拟系统时间被改）。依赖 01 FixedClock 的 _at 字段。"""
    clock._at -= timedelta(seconds=seconds)
