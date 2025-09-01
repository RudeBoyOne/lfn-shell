import logging
from fabric.core.service import Service, Signal
from fabric.utils.helpers import exec_shell_command_async

logger = logging.getLogger(__name__)


class PowerService(Service):
    """Service responsável por executar ações de energia.

    Centraliza side-effects / subprocessos. A UI (Box/Layer) só chama métodos deste Service.

    Métodos expostos:
    - lock_session
    - logout_session
    - reboot_system
    - shutdown_system
    """

    @Signal
    def close_requested(self) -> None: ...

    @Signal
    def action_executed(self, action: str) -> None: ...  # action: "lock"|"logout"|"reboot"|"shutdown"

    @Signal
    def action_failed(self, action: str, message: str) -> None: ...

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # helpers
    def _run(self, action: str, cmd: str):
        """Executa comando assíncrono e sinaliza resultado.

        Mantém interface simples; erros são logados e propagados via sinal.
        """
        try:
            exec_shell_command_async(cmd)
            self.action_executed(action)
        except Exception as e:  # proteção ampla para não quebrar UI
            logger.exception("power action failed: %s", action)
            self.action_failed(action, str(e))
        finally:
            # Fecha menu após qualquer ação (comportamento simples; pode evoluir no futuro)
            self.request_close()

    # ações públicas
    def lock_session(self):
        self._run("lock", "hyprlock")

    def logout_session(self):
        # Ajuste comando conforme compositor/WM; Hyprland usa hyprctl dispatch exit
        self._run("logout", "hyprctl dispatch exit")

    def reboot_system(self):
        self._run("reboot", "systemctl reboot")

    def shutdown_system(self):
        self._run("shutdown", "systemctl poweroff")

    # fechamento
    def request_close(self):
        self.close_requested()
