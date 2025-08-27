import os
# os.environ["GDK_BACKEND"] = "wayland"

from gi.repository import GLib
from fabric import Application
from fabric.utils import get_relative_path

from clipboard.clipboardLayer import ClipboardLayer


if __name__ == "__main__":
    
    app = Application("lfn-shell")

    def set_css():
        app.set_stylesheet_from_file(
            get_relative_path("main.css"),
        )
        
    app.set_css = set_css

    app.set_css()

    app.run()