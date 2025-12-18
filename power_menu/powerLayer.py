from gi.repository import GLib

from widgets.WindowWayland import WaylandWindow as Window
from power_menu.powerBox import PowerMenu
from power_menu.powerService import PowerService
from util.singleton_layer import SingletonLayerMixin


class PowerLayer(SingletonLayerMixin, Window):
    def __init__(self):
        if not self._prepare_singleton():
            return

        service = PowerService()
        menu = PowerMenu(controller=service)

        super().__init__(
            title="power-menu",
            name="power-menu-layer",
            type="top-level",
            anchor="left",
            layer="overlay",
            exclusive_zone=0,
            keyboard_mode="exclusive",
            all_visible=True,
            child=menu,
            margin="0px 0px 0px 5px",
        )
        self.service = service
        self.child = menu

        self._register_singleton_cleanup()

        def _focus_later():
            try:
                self.child.grab_focus()
            except (AttributeError, RuntimeError):
                pass
            return False

        GLib.idle_add(_focus_later)

        # Fechamento
        self.service.connect("close-requested", lambda *_: self.close())
        self.add_keybinding("Escape", lambda *_: self.close())
