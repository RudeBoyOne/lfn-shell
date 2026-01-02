import os
import actions.launch_widgets.launch_widgets_actions as launch_widgets_actions

from gi.repository import GLib
from fabric import Application
from fabric.utils import get_relative_path

from util.send_start_notification import send_start_notification


if __name__ == "__main__":

    app = Application("lfn-shell")

    def set_css():
        app.set_stylesheet_from_file(
            get_relative_path("main.css"),
        )

    app.set_css = set_css

    app.set_css()

    send_start_notification()

    app.run()
