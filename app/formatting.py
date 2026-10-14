# -*- coding: utf-8 -*-
"""Textformatering (drifttid, bytes)."""

from __future__ import annotations


def format_uptime(seconds: float) -> str:
    """
    NY v6.4.1 v7: Formatera uptime som svensk lasbar sträng.

    Exempel:
        >>> format_uptime(45)
        '45 sekunder'
        >>> format_uptime(3700)
        '1 timme, 1 minut, 40 sekunder'
    """
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} sekunder"
    if seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes} minut{'er' if minutes != 1 else ''}{f', {secs} sekunder' if secs else ''}"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = [f"{hours} timme{'r' if hours != 1 else ''}"]
    if minutes:
        parts.append(f"{minutes} minut{'er' if minutes != 1 else ''}")
    if secs:
        parts.append(f"{secs} sekunder")
    return ", ".join(parts)


def format_bytes(num_bytes: int) -> str:
    """
    NY v6.4.1 v7: Formatera bytes som svensk lasbar sträng.

    Exempel:
        >>> format_bytes(1500)
        '1.5 KB'
        >>> format_bytes(1500000)
        '1.4 MB'
    """
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"
