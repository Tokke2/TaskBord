# -*- coding: utf-8 -*-
"""
edge_dock.py — geometrin bakom "dockning vid skärmkant": dra fönstret mot en kant så glider det ut
och visas igen när musen nuddar kanten. Ren matematik (ingen Qt) så allt går att testa.

Rektanglar är (x, y, w, h) i logiska skärmkoordinater. Kanter: "left", "right", "top"
(inte "bottom" — där ligger aktivitetsfältet).
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Set, Tuple

Rect = Tuple[int, int, int, int]
Point = Tuple[int, int]

EDGES: Tuple[str, ...] = ("left", "right", "top")
SNAP_PX = 14        # så nära kanten (eller över den) vid släpp → dockas
PEEK_PX = 5         # så mycket av fönstret syns kvar när det är gömt
SPAN_TOL = 16       # musen får vara så mycket utanför fönstrets sida längs kanten och ändå visa det
KEEP_MARGIN = 24    # musen får vara så långt utanför det synliga fönstret utan att det gömmer sig


def right(r: Rect) -> int:
    return r[0] + r[2]


def bottom(r: Rect) -> int:
    return r[1] + r[3]


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return min(a1, b1) - max(a0, b0)


def intersection_area(a: Rect, b: Rect) -> int:
    w = _overlap(a[0], right(a), b[0], right(b))
    h = _overlap(a[1], bottom(a), b[1], bottom(b))
    return w * h if w > 0 and h > 0 else 0


def screen_for(rect: Rect, screens: Sequence[Rect]) -> Optional[Rect]:
    """Skärmen som fönstret till största delen ligger på (annars den med mitten närmast)."""
    if not screens:
        return None
    best = max(screens, key=lambda s: intersection_area(rect, s))
    if intersection_area(rect, best) > 0:
        return best
    cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
    return min(screens, key=lambda s: (s[0] + s[2] // 2 - cx) ** 2 + (s[1] + s[3] // 2 - cy) ** 2)


def outer_edges(screen: Rect, screens: Iterable[Rect]) -> Set[str]:
    """Kanter på ``screen`` som INTE gränsar mot en annan skärm — bara där får fönstret gömmas
    (annars skulle det synas på grannskärmen)."""
    edges = set(EDGES)
    for o in screens:
        if o == screen:
            continue
        v = _overlap(screen[1], bottom(screen), o[1], bottom(o)) > 0
        h = _overlap(screen[0], right(screen), o[0], right(o)) > 0
        if v and o[0] < screen[0] and right(o) >= screen[0] - 1:
            edges.discard("left")
        if v and right(o) > right(screen) and o[0] <= right(screen) + 1:
            edges.discard("right")
        if h and o[1] < screen[1] and bottom(o) >= screen[1] - 1:
            edges.discard("top")
    return edges


def detect_edge(rect: Rect, screen: Rect, allowed: Iterable[str] = EDGES, snap: int = SNAP_PX) -> Optional[str]:
    """Vilken kant fönstret är dragit mot (None = ingen). Fönstret måste vara märkbart mindre än skärmen."""
    allowed = set(allowed)
    dist = {
        "left": rect[0] - screen[0],
        "right": right(screen) - right(rect),
        "top": rect[1] - screen[1],
    }
    if rect[2] > screen[2] * 0.8:  # för brett för att dockas åt sidan
        dist.pop("left"), dist.pop("right")
    if rect[3] > screen[3] * 0.9:
        dist.pop("top", None)
    cand = [(d, e) for e, d in dist.items() if e in allowed and d <= snap]
    return min(cand)[1] if cand else None


def shown_rect(rect: Rect, screen: Rect, edge: str) -> Rect:
    """Fönstret liggande kant i kant mot skärmkanten (och inom skärmen längs kanten)."""
    x, y, w, h = rect
    if edge == "left":
        x = screen[0]
    elif edge == "right":
        x = right(screen) - w
    elif edge == "top":
        y = screen[1]
    else:
        raise ValueError(edge)
    if edge in ("left", "right"):
        y = max(screen[1], min(y, bottom(screen) - h))
    else:
        x = max(screen[0], min(x, right(screen) - w))
    return (x, y, w, h)


def hidden_rect(shown: Rect, screen: Rect, edge: str, peek: int = PEEK_PX) -> Rect:
    """Fönstret gömt utanför kanten med ``peek`` px kvar synliga."""
    x, y, w, h = shown
    if edge == "left":
        x = screen[0] - w + peek
    elif edge == "right":
        x = right(screen) - peek
    elif edge == "top":
        y = screen[1] - h + peek
    else:
        raise ValueError(edge)
    return (x, y, w, h)


def reveal_hit(cursor: Point, shown: Rect, screen: Rect, edge: str,
               depth: int = PEEK_PX, tol: int = SPAN_TOL) -> bool:
    """Nuddar musen kanten på det ställe där fönstret är dockat?"""
    cx, cy = cursor
    if not (screen[0] <= cx < right(screen) and screen[1] <= cy < bottom(screen)):
        return False
    if edge == "left":
        return cx < screen[0] + depth and shown[1] - tol <= cy < bottom(shown) + tol
    if edge == "right":
        return cx >= right(screen) - depth and shown[1] - tol <= cy < bottom(shown) + tol
    if edge == "top":
        return cy < screen[1] + depth and shown[0] - tol <= cx < right(shown) + tol
    return False


def keep_shown(cursor: Point, shown: Rect, margin: int = KEEP_MARGIN) -> bool:
    """Är musen på/nära det synliga fönstret (då ska det inte gömmas)?"""
    cx, cy = cursor
    return (shown[0] - margin <= cx < right(shown) + margin
            and shown[1] - margin <= cy < bottom(shown) + margin)


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def lerp_point(a: Point, b: Point, t: float) -> Point:
    e = ease_out_cubic(t)
    return (round(a[0] + (b[0] - a[0]) * e), round(a[1] + (b[1] - a[1]) * e))
