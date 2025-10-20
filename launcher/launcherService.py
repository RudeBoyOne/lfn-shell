import logging
import unicodedata
from typing import Dict, List, Optional, Tuple

from gi.repository import GLib

from fabric.core.service import Property, Service, Signal
from fabric.utils import DesktopApp, get_desktop_applications


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
        try:
            pixbuf = app.get_icon_pixbuf(size=size)
        except (GLib.Error, RuntimeError, ValueError):
            logger.debug("failed to load icon for %s", app_id, exc_info=True)
            pixbuf = None
        self._icon_cache[cache_key] = pixbuf
        return pixbuf

    def _normalized_terms(self) -> List[str]:
        if not self._query:
            return []
        raw_terms = (self._query or "").split()
        normalized_terms = [self._normalize_text(term) for term in raw_terms]
        return [term for term in normalized_terms if term]

    def _rebuild_items(self) -> None:
        terms = self._normalized_terms()
        seen: Dict[str, int] = {}
        items: List[Tuple[str, str]] = []
        mapping: Dict[str, DesktopApp] = {}

        if not terms:
            self._apps_by_id = {}
            self.items = []
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
            if terms:
                if not search_labels:
                    continue
                if not all(
                    any(term in label for label in search_labels) for term in terms
                ):
                    continue
            elif not search_labels:
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

        self._apps_by_id = mapping
        self.items = items
        logger.debug(
            "launcher service: query=%r matched %d apps",
            self._query,
            len(items),
        )

        if not items:
            self.selected_index = -1
            return
        if self._selected_index < 0 or self._selected_index >= len(items):
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
