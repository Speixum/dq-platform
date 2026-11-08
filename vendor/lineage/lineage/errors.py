"""异常类型。错误信息一律使用 ASCII，避免控制台编码问题。"""

from __future__ import annotations


class LineageError(Exception):
    """血缘库的统一异常。"""


class LineageFormatError(LineageError):
    """输入文件不是合法的血缘/目录 JSON。"""
