from gi.repository import GLib
from fabric.widgets.wayland import WaylandWindow as Window

from clipboard.clipboardBox import ClipBar
from clipboard.clipboardService import ClipboardService


class ClipboardLayer(Window):
    def __init__(self):
        # cria Service
        service = ClipboardService(interval_ms=1500)

        # cria UI antes e passa como child
        bar = ClipBar(
            bar_height=197,
            item_width=320,
            style_classes="clipboard-layer-root",
            controller=service,
        )

        super().__init__(
            name="clipboard-layer",
            type="top-level",
            anchor="left bottom right",
            layer="overlay",
            exclusive_zone=0,
            keyboard_mode="exclusive",
            all_visible=True,
            child=bar,
        )

        self.child = bar
        self.service = service

        # teclas -> Service
        # helper para mover e agendar foco, reduz duplicação
        def move_and_focus(delta: int):
            try:
                if delta < 0:
                    self.service.move_left()
                else:
                    self.service.move_right()
            finally:
                try:
                    if hasattr(self, "child") and hasattr(self.child, "focus_selected"):
                        GLib.idle_add(self.child.focus_selected)
                except Exception:
                    pass

        def _left(*_):
            move_and_focus(-1)

        def _right(*_):
            move_and_focus(+1)

        self.add_keybinding("Left", _left)
        self.add_keybinding("Right", _right)
        self.add_keybinding("Return", lambda *_: self.service.activate())
        self.add_keybinding("Delete", lambda *_: self.service.delete_current())
        self.add_keybinding("Escape", lambda *_: self.service.request_close())

        # fechar quando o Service pedir
        self.service.connect("close-requested", lambda *_: self.close() if hasattr(self, "close") else self.application.quit())

        # foco inicial
        def _focus_later():
            try:
                self.child.grab_focus()
            except Exception:
                pass
            return False
        GLib.idle_add(_focus_later)