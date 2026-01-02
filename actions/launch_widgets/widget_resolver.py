from __future__ import annotations

from typing import Any

from clipboard.clipboardLayer import ClipboardLayer
from launcher.launcherLayer import LauncherLayer
from power_menu.powerLayer import PowerLayer


_WIDGET_MAP: dict[str, Any] = {
    "clipboard": ClipboardLayer,
    "launcher": LauncherLayer,
    "power_menu": PowerLayer,
}


def launch_widget(name: str, *args, **kwargs):
    """Instancia e retorna a layer/widget correspondente a `name`.

    Levanta `KeyError` se `name` não for conhecido.
    """
    key = name.lower().strip()
    if key not in _WIDGET_MAP:
        raise KeyError(f"widget não encontrado: {name}")
    cls = _WIDGET_MAP[key]
    return cls(*args, **kwargs)


__all__ = ["launch_widget"]
