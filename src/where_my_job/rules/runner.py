# src/where_my_job/rules/runner.py
"""整批规则在 spawn 进程中执行；超时终止并回收，不返回部分结果。"""
from __future__ import annotations
import json
import multiprocessing as mp
import time
from dataclasses import asdict
from .eval import CompiledScoring, JobResult, evaluate_job
from . import limits
from ..normalize.fact import Fact

MAX_RESULT_BYTES = 16 * 1024 * 1024

class EvalTimeout(RuntimeError):
    pass

class EvalWorkerError(RuntimeError):
    pass

def _worker(sender, scoring, facts, campus_exclude):
    try:
        result = [asdict(evaluate_job(scoring, fact, campus_exclude=campus_exclude)) for fact in facts]
        payload = json.dumps({"results": result}, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(payload) > MAX_RESULT_BYTES:
            raise ValueError("规则结果超过16MiB输出上限")
    except BaseException as exc:
        payload = json.dumps({"error": type(exc).__name__, "message": str(exc)[:2000]}, ensure_ascii=False).encode("utf-8")
    try:
        sender.send_bytes(payload)
    finally:
        sender.close()

def _stop(process):
    if process.is_alive():
        process.terminate()
    process.join(timeout=0.5)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.5)
    if process.is_alive():
        raise EvalWorkerError("无法回收规则进程")

def evaluate_batch(sc: CompiledScoring, facts: list[Fact], *, campus_exclude: bool,
                   timeout_sec: float = limits.EVAL_TIMEOUT_SEC) -> list[JobResult]:
    if timeout_sec <= 0:
        raise EvalTimeout("规则求值时间额度必须大于0")
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, sc, facts, campus_exclude), daemon=True)
    started = time.monotonic()
    try:
        process.start()
        sender.close()
        remaining = timeout_sec - (time.monotonic() - started)
        if remaining <= 0 or not receiver.poll(remaining):
            raise EvalTimeout(f"规则求值超过{timeout_sec}秒，未提交任何结果")
        try:
            payload = receiver.recv_bytes(MAX_RESULT_BYTES)
        except (EOFError, OSError) as exc:
            raise EvalWorkerError("规则进程未返回完整结果") from exc
        if time.monotonic() - started > timeout_sec:
            raise EvalTimeout(f"规则求值超过{timeout_sec}秒，未提交任何结果")
        data = json.loads(payload)
        if "error" in data:
            raise EvalWorkerError(f"{data['error']}: {data['message']}")
        if len(data["results"]) != len(facts):
            raise EvalWorkerError("规则结果数量与输入不一致")
        return [JobResult(**record) for record in data["results"]]
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            _stop(process)
            process.close()
