from __future__ import annotations
import argparse, sys, traceback
from .. import __version__
from ..clock import SystemClock
from ..errors import WmjError, EnvError, ErrorItem, EXIT_OK
from . import envelope

def make_clock():
    """测试通过 monkeypatch 替换。"""
    return SystemClock()

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="where-my-job", description="本地求职情报 CLI")
    p.add_argument("--version", action="version", version=f"where-my-job {__version__}")
    p.add_argument("--json", action="store_true", help="stdout 只输出一个 JSON 对象（默认已如此）")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    from ..service import registry
    registry.register_all(sub)
    return p

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as e:  # argparse 用法错误 → 退出 1，也输出 envelope
        if e.code == 0:
            return 0
        env = envelope.build("usage", status="invalid", exit_code=1,
                             errors=[ErrorItem("SCHEMA_INVALID", "参数用法错误，见 stderr")])
        envelope.emit(env)
        return 1
    qualified = getattr(ns, "qualified_command", ns.command or "usage")
    handler = getattr(ns, "handler")
    warnings: list[str] = []
    try:
        result = handler(ns, warnings)          # 返回 (data, run_id) 或 data
        data, run_id = (result if isinstance(result, tuple) else (result, None))
        envelope.emit(envelope.build(qualified, data=data, run_id=run_id, warnings=warnings))
        return EXIT_OK
    except WmjError as err:
        envelope.emit(envelope.from_error(qualified, err, warnings=warnings))
        return err.exit_code
    except Exception:  # 兜底：未预期异常
        traceback.print_exc(file=sys.stderr)
        err = EnvError("INTERNAL", "未预期异常，见 stderr")
        envelope.emit(envelope.from_error(qualified, err, warnings=warnings))
        return err.exit_code

if __name__ == "__main__":
    raise SystemExit(main())
