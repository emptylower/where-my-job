"""兼容入口：码表与城市码的唯一来源是子计划 02 的纯模块 config.search_codes。本文件不定义任何表。"""
from __future__ import annotations
from ..config.search_codes import UnknownCode, CompiledFilter, city_code, compile_filter  # noqa: F401

__all__ = ["UnknownCode", "CompiledFilter", "city_code", "compile_filter"]
