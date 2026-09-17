"""websocket-client 连接替身：send() 时调用 responder(msg) 得到要依次入队的消息（事件在前，回复在后）。"""
from __future__ import annotations
import json
from collections import deque
import websocket

class FakeWS:
    def __init__(self, responder):
        self.responder, self.sent, self.inbox, self.closed, self.timeout = responder, [], deque(), False, None
    def send(self, raw: str) -> None:
        msg = json.loads(raw)
        self.sent.append(msg)
        for out in self.responder(msg) or []:
            self.inbox.append(json.dumps(out))
    def push(self, msg: dict) -> None:
        self.inbox.append(json.dumps(msg))
    def recv(self) -> str:
        if not self.inbox:
            raise websocket.WebSocketTimeoutException("idle")
        return self.inbox.popleft()
    def settimeout(self, t) -> None:
        self.timeout = t
    def close(self) -> None:
        self.closed = True

class Ticker:
    """每次读取前进 step 秒的单调时钟，避免测试真实等待。"""
    def __init__(self, step: float = 0.25):
        self.t, self.step = 0.0, step
    def __call__(self) -> float:
        self.t += self.step
        return self.t
