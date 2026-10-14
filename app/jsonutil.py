# -*- coding: utf-8 -*-
"""JSON-hjälpare (orjson om det finns, annars standardbiblioteket)."""

from __future__ import annotations

import json as _stdlib_json
from typing import Any, Union


# ORJSON (18× snabbare — fallback till stdlib)
try:
    import orjson  # type: ignore
    _HAS_ORJSON = True
except ImportError:
    orjson = None  # type: ignore
    _HAS_ORJSON = False


def _json_dumps(obj: Any) -> bytes:
    """Serialisera (orjson 18× snabbare)."""
    if _HAS_ORJSON:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)  # type: ignore
    return _stdlib_json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")


def _json_loads(data: Union[bytes, str]) -> Any:
    """Parsa JSON (orjson 18× snabbare)."""
    if _HAS_ORJSON:
        return orjson.loads(data)  # type: ignore
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return _stdlib_json.loads(data)
