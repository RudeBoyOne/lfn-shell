"""Utilities to hot-reload styles during development.

Usage: call `start_styles_monitor(app, style_path="./styles/style.css")`
after creating the `app` instance in `main.py`.
"""
from gi.repository import Gio, GLib
import os
import sys


def _apply_stylesheet(app, style_path: str):
    try:
        app.set_stylesheet_from_file(style_path)
        print(f"[styles] applied stylesheet: {style_path}")
    except Exception as e:
        print(f"[styles] failed to apply stylesheet: {e}", file=sys.stderr)


def start_styles_monitor(app, style_path: str = "./styles/style.css", debounce_ms: int = 250):
    """Start monitoring the styles directory and re-apply stylesheet on changes.

    debounce_ms: time window to coalesce rapid successive events.
    """
    style_dir = os.path.dirname(os.path.abspath(style_path))
    if not os.path.exists(style_dir):
        print(f"[styles] styles dir does not exist: {style_dir}", file=sys.stderr)
        return None

    # initial apply
    GLib.idle_add(_apply_stylesheet, app, style_path)

    # debounce helper
    timer_id = {"id": None}

    def _debounced_apply():
        timer_id["id"] = None
        _apply_stylesheet(app, style_path)
        return False

    def _on_changed(monitor, file, other, event_type):
        # coalesce rapid events
        if timer_id["id"]:
            GLib.source_remove(timer_id["id"])
        timer_id["id"] = GLib.timeout_add(debounce_ms, _debounced_apply)

    gfile = Gio.File.new_for_path(style_dir)
    try:
        monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        monitor.connect("changed", _on_changed)
        print(f"[styles] watching {style_dir} for changes (debounce {debounce_ms}ms)")
        return monitor
    except Exception as e:
        print(f"[styles] failed to start monitor: {e}", file=sys.stderr)
        return None
