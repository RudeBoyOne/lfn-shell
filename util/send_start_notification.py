import datetime
import socket
import shlex

from fabric.utils.helpers import exec_shell_command_async


def send_start_notification():
    """Envia notificação de inicialização.

    Função pública para ser importada por `main.py`.
    """
    started = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = socket.gethostname()
    title = "lfn-shell iniciado 🚀"
    body = (
        f"Inicializado em {hostname} \n {started}.\n"
    )
    icon = "system"
    cmd = (
        "notify-send -a lfn-shell -u normal -i "
        + shlex.quote(icon)
        + " "
        + shlex.quote(title)
        + " "
        + shlex.quote(body)
        + " -t 7000"
    )
    exec_shell_command_async(cmd)


__all__ = ["send_start_notification"]