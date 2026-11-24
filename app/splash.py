# -*- coding: utf-8 -*-
"""Startbild (splash)."""

from __future__ import annotations

import logging.handlers
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Optional

from app.constants import APP_NAME, APP_VERSION_DISPLAY, Timeouts


# ===========================================================================
# SPLASH SCREEN
# ===========================================================================

@dataclass(frozen=True)
class SplashConfig:
    """Konfiguration för splash-screen."""
    title: str = APP_NAME
    version: str = APP_VERSION_DISPLAY
    author: str = "Rickard Längkvist"
    min_duration_sec: float = Timeouts.SPLASH_MIN_DURATION
    background_color: str = "#1e1e2e"
    text_color: str = "#f0f0fa"
    accent_color: str = "#818cf8"
    width: int = 500
    height: int = 200


_splash_window: Any = None  # Sätts till QWidget vid show


def show_splash(config: Optional[SplashConfig] = None) -> None:
    """Visar splash-screen (om Qt är tillgängligt)."""
    global _splash_window
    if config is None:
        config = SplashConfig()

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QPixmap
        from PySide6.QtWidgets import (
            QApplication, QLabel, QVBoxLayout, QWidget,
        )

        if QApplication.instance() is None:
            return  # Kan inte visa splash utan QApplication

        # Skapa splash-widget
        splash = QWidget()
        splash.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
        )
        splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        splash.setFixedSize(config.width, config.height)

        # Bakgrundspixmap (för rundade hörn + gradient)
        pixmap = QPixmap(config.width, config.height)
        pixmap.fill(QColor(config.background_color))
        splash.setPixmap = pixmap  # type: ignore[attr-defined]

        layout = QVBoxLayout(splash)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        # Titel
        title = QLabel(f"✨ {config.title}")
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {config.accent_color};")
        layout.addWidget(title)

        # Version
        version = QLabel(f"v{config.version}")
        version.setStyleSheet(f"color: {config.text_color}; font-size: 14px;")
        layout.addWidget(version)

        # Loading
        loading = QLabel("Laddar...")
        loading.setStyleSheet(
            f"color: {config.text_color}; font-size: 12px; font-style: italic;"
        )
        layout.addWidget(loading)

        # Author
        author = QLabel(f"© {config.author}")
        author.setStyleSheet(
            f"color: {config.text_color}; font-size: 11px; opacity: 0.7;"
        )
        layout.addWidget(author)

        layout.addStretch()

        # Centrera på primärskärmen
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            splash.move(
                (geo.width() - config.width) // 2,
                (geo.height() - config.height) // 2,
            )

        splash.show()
        QApplication.processEvents()
        _splash_window = splash
    except Exception as e:
        logging.getLogger("Main").debug(f"Kunde inte visa splash: {e}")


def hide_splash() -> None:
    """Dölj splash-screen."""
    global _splash_window
    if _splash_window is not None:
        with suppress(Exception):
            _splash_window.close()
            _splash_window.deleteLater()
        _splash_window = None
