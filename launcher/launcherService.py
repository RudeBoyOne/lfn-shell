import logging
import unicodedata
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from fabric.core.service import Property, Service, Signal
from fabric.utils import DesktopApp, get_desktop_applications

from launcher.components.query_models import QueryAction
from launcher.components.query_router import route_special_query


logger = logging.getLogger(__name__)


class LauncherService(Service):
    @Property(list, flags="read-write")
    def items(self) -> list:
        return self._items

    def _set_items(self, value: list):
        if value == getattr(self, "_items", []):
            return
        self._items = value

    items = items.setter(_set_items)

    @Property(int, flags="read-write")
    def selected_index(self) -> int:
        return self._selected_index

    def _set_selected_index(self, value: int):
        if value == getattr(self, "_selected_index", -1):
            return
        self._selected_index = value

    selected_index = selected_index.setter(_set_selected_index)

    @Property(str, flags="read-write")
    def query(self) -> str:
        return self._query

    def _set_query(self, value: str):
        normalized = (value or "").strip()
        if normalized == getattr(self, "_query", ""):
            return
        self._query = normalized
        self._rebuild_items()

    query = query.setter(_set_query)

    @Signal
    def close_requested(self) -> None: ...

    def __init__(self, include_hidden: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._items: List[Tuple[str, str]] = []
        self._selected_index: int = -1
        self._query: str = ""
        self._query_pending: str = ""
        self._query_timer_id: Optional[int] = None
        self._query_debounce_ms = 200
        self._include_hidden = include_hidden
        self._all_apps: List[DesktopApp] = []
        self._apps_by_id: Dict[str, DesktopApp] = {}
        self._icon_cache: Dict[Tuple[str, int], Optional[object]] = {}
        self._special_actions: Dict[str, QueryAction] = {}
        self.refresh_apps()

    def refresh_apps(self) -> None:
        try:
            apps = get_desktop_applications(
                include_hidden=self._include_hidden,
            )
        except (GLib.Error, RuntimeError, ValueError):
            logger.exception(
                "failed to enumerate desktop applications",
            )
            apps = []

        self._all_apps = apps
        self._rebuild_items()

    def update_query_input(self, text: str) -> None:
        pending = (text or "").strip()
        if (
            pending == getattr(self, "_query_pending", "")
            and self._query_timer_id is not None
        ):
            return
        self._query_pending = pending
        if self._query_timer_id is not None:
            try:
                GLib.source_remove(self._query_timer_id)
            except (RuntimeError, ValueError):
                pass
            self._query_timer_id = None

        def _apply():
            self._query_timer_id = None
            if self._query != self._query_pending:
                self.query = self._query_pending
            return False

        self._query_timer_id = GLib.timeout_add(
            self._query_debounce_ms,
            _apply,
        )

    def move_selection(self, delta: int) -> None:
        if not self._items:
            return
        current = self._selected_index
        if current < 0:
            current = 0 if delta >= 0 else len(self._items) - 1
        new_index = max(0, min(current + delta, len(self._items) - 1))
        if new_index != self._selected_index:
            self.selected_index = new_index

    def launch_selected(self) -> None:
        if self._selected_index < 0 or self._selected_index >= len(self._items):
            return
        app_id, _ = self._items[self._selected_index]
        self.launch_by_id(app_id)

    def launch_by_id(self, app_id: str) -> None:
        action = self._special_actions.get(app_id)
        if action is not None:
            self._execute_special_action(action)
            return
        if app_id.startswith("__special__"):
            logger.debug("no action mapped for special id %s", app_id)
            return
        app = self._apps_by_id.get(app_id)
        if app is None:
            logger.debug("no application mapped for id %s", app_id)
            return
        try:
            app.launch()
        except (GLib.Error, RuntimeError, OSError):
            logger.exception("failed to launch application %s", app_id)
            return
        self.request_close()

    def request_close(self) -> None:
        self.close_requested()

    def _execute_special_action(self, action: QueryAction) -> None:
        if action.kind == "web-search":
            self._perform_web_search(action.payload.get("term", ""))
            return
        if action.kind == "calc-result":
            self._handle_calc_action(action.payload)
            return
        logger.debug("unknown special action kind %s", action.kind)

    def _perform_web_search(self, term: str) -> None:
        normalized = (term or "").strip()
        if not normalized:
            return
        encoded = quote_plus(normalized)
        uri = f"https://www.google.com/search?q={encoded}"
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except (GLib.Error, RuntimeError, ValueError):
            logger.exception("failed to open web search for %s", normalized)
            return
        self.request_close()

    def _handle_calc_action(self, payload: Dict[str, str]) -> None:
        result = (payload.get("result") or "").strip()
        if not result:
            return
        if not self._copy_to_clipboard(result):
            logger.debug("unable to copy calculation result to clipboard")
        self.request_close()

    @staticmethod
    def _copy_to_clipboard(text: str) -> bool:
        display = Gdk.Display.get_default()
        if display is None:
            return False
        clipboard = Gtk.Clipboard.get_default(display)
        if clipboard is None:
            return False
        try:
            clipboard.set_text(text, -1)
            clipboard.store()
        except (RuntimeError, ValueError):
            return False
        return True

    def get_app_details(self, app_id: str) -> Dict[str, str]:
        app = self._apps_by_id.get(app_id)
        if app is None:
            return {}
        return {
            "description": app.description or "",
            "generic_name": app.generic_name or "",
            "executable": app.executable or "",
        }

    def get_icon_pixbuf(self, app_id: str, size: int = 48):
        cache_key = (app_id, size)
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        app = self._apps_by_id.get(app_id)
        if app is None:
            return None
        pixbuf = self._load_icon_pixbuf(app, size)
        self._icon_cache[cache_key] = pixbuf
        return pixbuf

    def _normalized_terms(self) -> List[str]:
        if not self._query:
            return []
        raw_terms = (self._query or "").split()
        normalized_terms = [self._normalize_text(term) for term in raw_terms]
        return [term for term in normalized_terms if term]

    def _rebuild_items(self) -> None:
        special = route_special_query(self._query)
        self._special_actions = dict(special.actions)

        if special.consume:
            self._apps_by_id = {}
            special_items = list(special.items)
            self.items = special_items
            if not special_items:
                self.selected_index = -1
            elif self._selected_index < 0 or self._selected_index >= len(special_items):
                self.selected_index = 0
            return

        prefix_items = list(special.items) if special.items else []
        terms = self._normalized_terms()
        seen: Dict[str, int] = {}
        items: List[Tuple[str, str]] = []
        mapping: Dict[str, DesktopApp] = {}

        if not terms:
            self._apps_by_id = {}
            self.items = prefix_items
            if prefix_items:
                self.selected_index = 0
            else:
                self.selected_index = -1
                logger.debug("launcher service: cleared items (empty query)")
            return

        for idx, app in enumerate(self._all_apps):
            base_id = (
                app.name
                or app.command_line
                or app.executable
                or app.display_name
                or f"app-{idx}"
            )
            app_id = self._deduplicate_id(base_id, seen)
            primary_labels = self._normalized_primary_labels(app)
            fallback_labels = self._normalized_secondary_labels(app)
            search_labels: List[str] = primary_labels or fallback_labels
            if not search_labels:
                continue
            if not all(any(term in label for label in search_labels) for term in terms):
                continue
            display = (
                app.display_name
                or app.generic_name
                or app.name
                or app.executable
                or app.command_line
                or app_id
            )
            items.append((app_id, display))
            mapping[app_id] = app

        combined_items = prefix_items + items

        self._apps_by_id = mapping
        self.items = combined_items
        logger.debug(
            "launcher service: query=%r matched %d apps",
            self._query,
            len(items),
        )

        if not combined_items:
            self.selected_index = -1
            return
        if self._selected_index < 0 or self._selected_index >= len(combined_items):
            self.selected_index = 0

    @staticmethod
    def _deduplicate_id(base: str, seen: Dict[str, int]) -> str:
        candidate = base or "app"
        if candidate not in seen:
            seen[candidate] = 1
            return candidate
        seen[candidate] += 1
        suffixed = f"{candidate}-{seen[candidate]}"
        while suffixed in seen:
            seen[candidate] += 1
            suffixed = f"{candidate}-{seen[candidate]}"
        seen[suffixed] = 1
        return suffixed

    def cancel_pending_query(self) -> None:
        if self._query_timer_id is None:
            return
        try:
            GLib.source_remove(self._query_timer_id)
        except (RuntimeError, ValueError):
            pass
        self._query_timer_id = None

    def _load_icon_pixbuf(
        self,
        app: DesktopApp,
        size: int,
    ):
        pixbuf = self._try_theme_icon(app, size)
        if pixbuf is not None:
            return pixbuf
        pixbuf = self._try_file_icon(app, size)
        if pixbuf is not None:
            return pixbuf
        try:
            return app.get_icon_pixbuf(size=size)
        except (GLib.Error, RuntimeError, ValueError):
            logger.debug("failed to load icon for %s", app.name, exc_info=True)
            return None

    @staticmethod
    def _try_theme_icon(app: DesktopApp, size: int):
        try:
            return app.get_icon_pixbuf(size=size, default_icon=None)
        except (GLib.Error, RuntimeError, ValueError):
            return None

    @staticmethod
    def _try_file_icon(app: DesktopApp, size: int):
        icon = getattr(app, "icon", None)
        if not isinstance(icon, Gio.FileIcon):
            return None
        file_obj = icon.get_file()
        if file_obj is None:
            return None
        path = file_obj.get_path()
        if not path:
            return None
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path,
                width=size,
                height=size,
                preserve_aspect_ratio=True,
            )
            setattr(app, "_pixbuf", pixbuf)
            return pixbuf
        except (GLib.Error, RuntimeError, ValueError):
            logger.debug("failed to read icon file %s", path, exc_info=True)
            return None

    @staticmethod
    def _normalize_text(value: Optional[str]) -> str:
        if not value:
            return ""
        decomposed = unicodedata.normalize("NFD", value)
        stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
        return stripped.casefold()

    def _normalized_primary_labels(self, app: DesktopApp) -> List[str]:
        labels = [app.display_name, app.name]
        return [
            normalized
            for normalized in (self._normalize_text(label) for label in labels if label)
            if normalized
        ]

    def _normalized_secondary_labels(self, app: DesktopApp) -> List[str]:
        labels = [app.generic_name, app.executable, app.command_line]
        return [
            normalized
            for normalized in (self._normalize_text(label) for label in labels if label)
            if normalized
        ]
