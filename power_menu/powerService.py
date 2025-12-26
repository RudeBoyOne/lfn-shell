import logging
from fabric.core.service import Service, Signal
from fabric.utils.helpers import exec_shell_command_async

logger = logging.getLogger(__name__)


class PowerService(Service):
    """Service responsável por executar ações de energia.

    Centraliza side-effects / subprocessos. A UI (Box) só chama métodos deste Service.

    Métodos expostos:
    - lock_session
    - logout_session
    - reboot_system
    - shutdown_system
    """

    @Signal
    def close_requested(self, action: str) -> None: ...

    @Signal
    def action_failed(self, action: str, message: str) -> None: ...

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.action = ""

    def _run(self, action: str, cmd: str):
        """Executa comando assíncrono e sinaliza resultado.

        Interface simples; erros logados e propagados via sinal.
        """
        try:
            exec_shell_command_async(cmd)
        except Exception as e:
            logger.exception("power action failed: %s", action)
            self.action_failed(action, str(e))
        finally:
            self.action = action
            self.close_requested(self.action)

    # public actions
    def lock_session(self):
        self._run("lock", "hyprlock")

    def logout_session(self):
        self._run("logout", "hyprctl dispatch exit")

    def reboot_system(self):
        self._run("reboot", "systemctl reboot")

    def shutdown_system(self):
        self._run("shutdown", "systemctl poweroff")
