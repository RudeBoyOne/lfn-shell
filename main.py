import os
os.environ["GDK_BACKEND"] = "wayland"

from gi.repository import GLib
from fabric import Application

from clipboard.clipboardLayer import ClipboardLayer

# optional: hot-reload styles during development
try:
    from styles.reload import start_styles_monitor
except Exception:
    start_styles_monitor = None


if __name__ == "__main__":
    app = Application("clipboard", ClipboardLayer())
    # start watching styles if available
    if start_styles_monitor:
        try:
            start_styles_monitor(app, style_path="./styles/style.css", debounce_ms=250)
        except Exception:
            pass
    app.run()