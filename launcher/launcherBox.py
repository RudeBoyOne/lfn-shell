import logging
from typing import Optional

from gi.repository import GLib, Gtk

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.entry import Entry
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow

from launcher.launcherService import LauncherService


logger = logging.getLogger(__name__)


class LauncherBox(Box):
    def __init__(
        self,
        controller: Optional[LauncherService] = None,
        icon_size: int = 32,
        **kwargs,
    ):
        super().__init__(
            name="launcher-root",
            orientation="v",
            spacing=8,
            h_expand=True,
            v_expand=False,
            **kwargs,
        )

        self.service = controller
        self.icon_size = icon_size

        self.search_entry = Entry(
            name="launcher-search",
            placeholder="Buscar aplicativos...",
            h_expand=True,
            size=50,
        )
        self.search_entry.connect("changed", self._on_search_changed)
        self.search_entry.connect("activate", self._on_entry_activate)

        header = Box(
            orientation="h",
            spacing=8,
            h_expand=True,
            h_align="fill",
        )
        header.add(self.search_entry)

        self.viewport = Box(
            name="launcher-list",
            orientation="v",
            spacing=6,
            h_expand=True,
            v_expand=True,
            h_align="fill",
            v_align="fill",
        )

        self.scroll = ScrolledWindow(
            name="launcher-scroll",
            child=self.viewport,
            h_expand=True,
            v_expand=False,
            h_align="fill",
            v_align="fill",
            propagate_width=False,
            propagate_height=False,
        )
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._max_visible_rows = 4
        self._row_height = max(self.icon_size + 17, 64)

        self.add(header)
        self.add(self.scroll)

        self._buttons = []

        # ensure consistent width even before results render
        self.set_size_request(420, -1)

        if self.service:
            self.service.connect(
                "notify::items",
                lambda *_: self._render_items(),
            )
            self.service.connect(
                "notify::selected-index",
                lambda *_: GLib.idle_add(self._sync_selection),
            )
            self.service.connect(
                "notify::query",
                lambda *_: self._on_query_changed(),
            )

        self._render_items()
        GLib.idle_add(self._focus_entry)

    def navigate(self, delta: int) -> None:
        if not self.service:
            return
        self.service.move_selection(delta)
        GLib.idle_add(self._ensure_selection_visible)

    def _focus_entry(self) -> bool:
        if not self.search_entry:
            return False
        try:
            self.search_entry.grab_focus()
            self.search_entry.set_position(-1)
        except (AttributeError, RuntimeError):
            logger.debug("launcher search focus failed", exc_info=True)
        return False

    def _on_search_changed(self, entry: Entry, *_args) -> None:
        if not self.service:
            return
        text = entry.get_text() if hasattr(entry, "get_text") else ""
        self.service.update_query_input(text)

    def _on_entry_activate(self, _entry: Entry, *_args) -> None:
        if not self.service:
            return
        if hasattr(self.service, "launch_selected"):
            self.service.launch_selected()

    def _on_query_changed(self) -> None:
        if not self.service or not self.search_entry:
            return
        if hasattr(self.search_entry, "get_text"):
            current = self.search_entry.get_text()
        else:
            current = ""
        desired = self.service.query
        if current == desired:
            return
        try:
            self.search_entry.set_text(desired)
            self.search_entry.set_position(-1)
        except RuntimeError:
            logger.debug("failed to sync launcher query", exc_info=True)

    def _render_items(self) -> None:
        items = self.service.items if self.service else []
        logger.debug("launcher box: rendering %d items", len(items))
        for child in list(self.viewport.get_children()):
            self.viewport.remove(child)
        self._buttons = []

        query_active = bool(self.service and (self.service.query or ""))
        if query_active:
            if hasattr(self.scroll, "set_visible"):
                self.scroll.set_visible(True)
            else:
                self.scroll.show()
        else:
            if hasattr(self.scroll, "set_visible"):
                self.scroll.set_visible(False)
            else:
                self.scroll.hide()
            self.queue_resize()
            return

        item_count = len(items)
        visible_rows = max(
            1,
            min(item_count if item_count else 0, self._max_visible_rows),
        )
        desired_height = self._row_height * visible_rows
        try:
            self.scroll.set_min_content_height(desired_height)
        except AttributeError:
            self.scroll.set_size_request(-1, desired_height)
        self.scroll.set_vexpand(item_count > self._max_visible_rows)

        if not items:
            self._render_empty_state()
            self.show_all()
            return

        for index, (app_id, display) in enumerate(items):
            button = self._build_button(app_id, display, index)
            self.viewport.add(button)
            self._buttons.append(button)

        self.show_all()
        self._sync_selection()
        self._ensure_selection_visible()

    def _render_empty_state(self) -> None:
        container = Box(
            orientation="v",
            h_expand=True,
            v_expand=True,
            h_align="center",
            v_align="center",
        )
        label = Label(
            name="launcher-empty",
            label=self._empty_message(),
            h_align="center",
            v_align="center",
        )
        container.add(label)
        self.viewport.add(container)

    def _build_button(self, app_id: str, title: str, index: int) -> Button:
        icon = Image(name="launcher-item-icon")
        content = Box(
            name="launcher-item-box",
            orientation="h",
            spacing=8,
            h_expand=True,
            v_expand=False,
            h_align="fill",
            v_align="center",
        )
        content.add(icon)
        title_label = Label(
            name="launcher-item-title",
            label=title,
            ellipsization="end",
            h_expand=True,
            h_align="fill",
        )
        content.add(title_label)

        button = Button(
            name="launcher-item",
            child=content,
            h_expand=True,
            v_expand=False,
            h_align="fill",
            v_align="center",
        )
        button.connect("clicked", lambda btn, *_: self._on_button_clicked(btn))
        setattr(button, "_launcher_index", index)
        setattr(button, "_launcher_app_id", app_id)

        pixbuf = self._load_icon(app_id)
        if pixbuf is not None:
            try:
                icon.set_from_pixbuf(pixbuf)
            except AttributeError:
                pass
        else:
            try:
                icon.set_from_icon_name(
                    "application-x-executable",
                    Gtk.IconSize.BUTTON,
                )
            except AttributeError:
                pass

        return button

    def _load_icon(self, app_id: str):
        if not self.service:
            return None
        return self.service.get_icon_pixbuf(app_id, size=self.icon_size)

    def _empty_message(self) -> str:
        if not self.service or not self.service.query:
            return "Digite para buscar aplicativos"
        return "Nenhum aplicativo encontrado"

    def _sync_selection(self) -> bool:
        selected = self.service.selected_index if self.service else -1
        for button in self._buttons:
            button.get_style_context().remove_class("launcher-item-selected")
        if selected < 0 or selected >= len(self._buttons):
            return False
        target = self._buttons[selected]
        target.get_style_context().add_class("launcher-item-selected")
        self._focus_button(target)
        return False

    def _focus_button(self, button: Button) -> None:
        if self.search_entry and self.search_entry.has_focus():
            return
        try:
            button.grab_focus()
        except (AttributeError, RuntimeError):
            pass

    def _ensure_selection_visible(self) -> bool:
        if not self.service:
            return False
        index = self.service.selected_index
        if index < 0 or index >= len(self._buttons):
            return False
        button = self._buttons[index]
        adjustment = self.scroll.get_vadjustment()
        if adjustment is None:
            return False
        allocation = button.get_allocation()
        view_start = adjustment.get_value()
        view_height = adjustment.get_page_size()
        item_start = allocation.y
        item_end = allocation.y + allocation.height
        if item_start < view_start:
            adjustment.set_value(max(0, item_start))
        elif item_end > view_start + view_height:
            adjustment.set_value(
                min(
                    item_end - view_height,
                    adjustment.get_upper() - view_height,
                ),
            )
        return False

    def _on_button_clicked(self, button: Button) -> None:
        if not self.service:
            return
        index = getattr(button, "_launcher_index", -1)
        if index < 0:
            return
        self.service.selected_index = index
        self.service.launch_selected()
