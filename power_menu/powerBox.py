from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.label import Label

from .assets import icons
from .powerService import PowerService


class PowerMenu(Box):
    """Box (UI) do menu de energia.

    CONTRATO: nenhuma chamada de subprocess aqui; delega tudo ao PowerService.
    """

    def __init__(self, controller: PowerService, orientation: str = "v", **kwargs):
        super().__init__(
            name="power-menu",
            orientation=orientation,
            spacing=17,
            v_align="center",
            h_align="center",
            visible=True,
            **kwargs,
        )

        self.service = controller

        self.btn_lock = Button(
            name="power-menu-button",
            child=Label(markup=icons.lock),
            on_clicked=lambda *_: self.service.lock_session(),
            h_expand=False,
            v_expand=False,
            h_align="center",
            v_align="center",
        )
        self.btn_logout = Button(
            name="power-menu-button",
            child=Label(markup=icons.logout),
            on_clicked=lambda *_: self.service.logout_session(),
            h_expand=False,
            v_expand=False,
            h_align="center",
            v_align="center",
        )
        self.btn_reboot = Button(
            name="power-menu-button",
            child=Label(markup=icons.reboot),
            on_clicked=lambda *_: self.service.reboot_system(),
            h_expand=False,
            v_expand=False,
            h_align="center",
            v_align="center",
        )
        self.btn_shutdown = Button(
            name="power-menu-button",
            child=Label(markup=icons.shutdown),
            on_clicked=lambda *_: self.service.shutdown_system(),
            h_expand=False,
            v_expand=False,
            h_align="center",
            v_align="center",
        )

        for btn in [
            self.btn_lock,
            self.btn_logout,
            self.btn_reboot,
            self.btn_shutdown,
        ]:
            self.add(btn)

        self.show_all()
