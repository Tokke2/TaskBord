# -*- coding: utf-8 -*-
"""
no_console.py — inga svarta konsollfönster som blinkar förbi på Windows.

Appen körs med pythonw.exe (ingen konsol). Men varje gång den startar ett konsolprogram —
schtasks (autostart-kontroll), reg, powershell, pip … — öppnar Windows ett eget svart fönster
en kort stund. Här lägger vi flaggan CREATE_NO_WINDOW på ALLA subprocess-anrop (en enda plats),
så inget fönster visas. GUI-program (t.ex. Utforskaren) påverkas inte av flaggan.

Anropas allra först i main.pyw. På andra system än Windows görs ingenting.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any, Optional

CREATE_NO_WINDOW = 0x08000000
_MARK = "_ledgebord_no_console"
# Position för 'creationflags' i Popen.__init__(args, bufsize, executable, stdin, stdout, stderr,
# preexec_fn, close_fds, shell, cwd, env, universal_newlines, startupinfo, creationflags, …)
_CREATIONFLAGS_POS = 13


def install(popen_cls: Optional[Any] = None, *, windows: Optional[bool] = None) -> bool:
    """
    Gör att alla subprocess.Popen/run/check_output … startas utan konsolfönster.
    Returnerar True om patchen lades på (False: inte Windows eller redan gjort).
    ``popen_cls`` / ``windows`` finns för tester.
    """
    is_win = (sys.platform == "win32") if windows is None else windows
    if not is_win:
        return False
    cls = popen_cls or subprocess.Popen
    orig = cls.__init__
    if getattr(orig, _MARK, False):
        return False

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        # creationflags som positionsargument är ovanligt — då rör vi inte anropet.
        if len(args) <= _CREATIONFLAGS_POS:
            try:
                kwargs["creationflags"] = int(kwargs.get("creationflags", 0) or 0) | CREATE_NO_WINDOW
            except (TypeError, ValueError):
                pass
        orig(self, *args, **kwargs)

    setattr(__init__, _MARK, True)
    __init__.__wrapped__ = orig  # type: ignore[attr-defined]
    cls.__init__ = __init__  # type: ignore[method-assign]
    return True
