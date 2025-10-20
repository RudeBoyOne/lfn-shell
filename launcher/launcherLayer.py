from gi.repository import GLib

from widgets.WindowWayland import WaylandWindow as Window
from util.singleton_layer import SingletonLayerMixin

from launcher.launcherBox import LauncherBox
from launcher.launcherService import LauncherService


class LauncherLayer(SingletonLayerMixin, Window):
    def __init__(self):
        if not self._prepare_singleton():
            return

        service = LauncherService()
        box = LauncherBox(controller=service)

        super().__init__(
            name="launcher-layer",
            anchor="top",
            layer="overlay",
            exclusive_zone=0,
            keyboard_mode="exclusive",
            all_visible=True,
            child=box,
            margin="300px 0px 0px 0px",
        )
        self.service = service
        self.child = box
        self._register_singleton_cleanup()

        def _focus_later():
            try:
                self.child.grab_focus()
            except (AttributeError, RuntimeError):
                pass
            return False

        GLib.idle_add(_focus_later)

        self.add_keybinding("Down", lambda *_: self.child.navigate(1))
        self.add_keybinding("Up", lambda *_: self.child.navigate(-1))
        self.add_keybinding(
            "Return",
            lambda *_: self.service.launch_selected(),
        )
        self.add_keybinding("Escape", lambda *_: self._close_launcher())
        self.service.connect(
            "close-requested",
            lambda *_: self._close_launcher(),
        )

    def _close_launcher(self):
        self.service.cancel_pending_query()
        if hasattr(self, "close"):
            self.close()
        else:
            self.application.quit()
