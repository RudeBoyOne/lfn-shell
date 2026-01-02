from fabric import Application
from actions.launch_widgets.widget_resolver import launch_widget


@Application.action("widget")
def launch_widget_action(name: str) -> str:
    """Ação invocável via fabric-cli/dbus para lançar um widget pelo nome.

    Uso (CLI):
      fabric-cli invoke lfn-shell widget clipboard
    """
    try:
        launch_widget(name)
        return f"launched {name}"
    except KeyError:
        return f"unknown widget: {name}"


__all__ = ["launch_widget_action"]
