import os
os.environ["GDK_BACKEND"] = "wayland"

from fabric import Application
from fabric.widgets.wayland import WaylandWindow as Window

from clipboard import ClipBar


class ClipboardLayer(Window):
    def __init__(self):
        super().__init__(
            name="clipboard-layer",
            type="popup",
            anchor="left bottom right",
            layer="overlay",
            exclusive_zone=0,
            keyboard_mode="none",
            all_visible=True,
        )
        self.children = ClipBar(bar_height=197, item_width=320, style="padding: 16px 16px;")

if __name__ == "__main__":
    app = Application("clipboard", ClipboardLayer())
    app.run()