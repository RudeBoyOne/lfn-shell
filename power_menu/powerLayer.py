from widgets.WindowWayland import WaylandWindow as Window
from .powerBox import PowerMenu
from .powerService import PowerService


class PowerLayer(Window):
    def __init__(self):
        service = PowerService()
        menu = PowerMenu(controller=service)

        super().__init__(
            name="power-menu-layer",
            type="top-level",
            anchor="left",
            layer="overlay",
            exclusive_zone=0,
            keyboard_mode="exclusive",
            all_visible=True,
            child=menu,
            margin="0px 0px 0px 5px"
        )
        self.service = service
        self.child = menu

        # Fechamento
        self.service.connect("close-requested", lambda *_: self.close())
        self.add_keybinding("Escape", lambda *_: self.close())