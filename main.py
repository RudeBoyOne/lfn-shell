import os
os.environ["GDK_BACKEND"] = "wayland"

from gi.repository import GLib
from fabric import Application

from clipboard.clipboardLayer import ClipboardLayer


if __name__ == "__main__":
    app = Application("clipboard", ClipboardLayer())
    app.run()