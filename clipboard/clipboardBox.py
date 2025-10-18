import logging
import threading
from typing import Optional
from gi.repository import GLib, Gtk

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.entry import Entry
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow

from clipboard.clipboardService import ClipboardService
from clipboard.components.image_preview import is_image_data, decode_and_scale
from clipboard.components.search import highlight_markup_multi
from clipboard.components.clipbar_support import (
    adjust_selection_for_candidates,
    build_render_candidates,
    extract_terms,
)
from .assets import icons


logger = logging.getLogger(__name__)


class ClipBar(Box):
    @staticmethod
    def _coerce_chunk(value, minimum: int, fallback: int) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return fallback

    def __init__(
        self,
        max_items=50,
        bar_height=56,
        item_width=260,
        initial_chunk: int = 48,
        chunk_size: int = 96,
        controller: Optional[ClipboardService] = None,
        item_height: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(
            name="clipbar-root",
            spacing=6,
            orientation="v",
            h_expand=True,
            v_expand=True,
            **kwargs,
        )

        self.bar_height = bar_height
        self.item_width = item_width
        self.item_height = item_height or max(56, self.bar_height - 4)
        self.max_items = max_items

        self.row = Box(
            name="clipbar-row",
            orientation="h",
            spacing=16,
            h_expand=False,
            v_expand=True,
            h_align="fill",
            v_align="fill",
            style_classes="clipbar-row-padding",
        )
        self.scroll = ScrolledWindow(
            name="clipbar-scroll",
            child=self.row,
            h_expand=True,
            v_expand=True,
            h_align="fill",
            v_align="fill",
            propagate_width=False,
            propagate_height=False,
        )
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)

        self.search_entry = Entry(
            placeholder="Buscar...",
            style_classes="clipbar-search",
            h_expand=True,
        )
        self.search_entry.connect(
            "changed",
            lambda *_: self._on_search_changed(),
        )

        # Header: busca + botão de limpar histórico
        header_box = Box(
            orientation="h",
            spacing=6,
            h_expand=True,
            h_align="center",
        )
        header_box.add(self.search_entry)
        self.clear_btn = Button(
            name="clipbar-clear",
            label=icons.trash,
            tooltip_text="Limpar histórico",
            size=30,
        )
        self.clear_btn.connect("clicked", lambda *_: self._on_clear_clicked())
        header_box.add(self.clear_btn)
        self.add(header_box)
        self.add(self.scroll)
        self.set_size_request(-1, self.bar_height)

        self._buttons = []
        self._content_boxes = []
        self._rendered_orig_indices = []
        self._filter_text = ""

        self.controller = controller
        if self.controller:
            self.controller.connect(
                "notify::items",
                lambda *_: self._render_items(),
            )
            self.controller.connect(
                "notify::selected-index",
                lambda *_: GLib.idle_add(self._on_selected_index_changed),
            )
            self.controller.connect(
                "notify::query",
                lambda *_: self._on_query_changed(),
            )
        # Estado de renderização incremental
        self._render_queue = []  # List[Tuple[orig_idx, item_id, content]]
        self._current_render_index = 0
        self._render_idle_id = 0
        self._terms_current = []
        self._max_card_height = self.item_height
        # Tamanhos de chunk: primeiro lote pequeno para abrir rápido
        self._initial_chunk = self._coerce_chunk(initial_chunk, 1, 48)
        raw_chunk = self._coerce_chunk(chunk_size, 1, 96)
        self._chunk_size = max(self._initial_chunk, raw_chunk)

        # Primeira renderização
        self._render_items()
        GLib.idle_add(self._sync_button_selection_classes)
        GLib.idle_add(self._focus_search_entry)

    def _render_items(self):
        self._cancel_pending_render()

        all_items = self.controller.items if self.controller else []
        self._filter_text = ""
        if self.controller:
            self._filter_text = self.controller.query or ""
        terms = extract_terms(self._filter_text)
        render_candidates = build_render_candidates(
            all_items,
            terms,
            self.max_items,
        )

        if self.controller:
            new_selection = adjust_selection_for_candidates(
                self.controller.selected_index,
                render_candidates,
                enforce_bounds=not terms,
            )
            if new_selection != self.controller.selected_index:
                self.controller.selected_index = new_selection

        self._reset_button_pool()
        self._max_card_height = self.item_height
        self.set_size_request(-1, max(self.bar_height, self.item_height + 16))

        if not render_candidates:
            self._render_empty_state(bool(all_items))
            return

        self._render_queue = list(render_candidates)
        self._terms_current = terms
        self._current_render_index = 0
        self._rendered_orig_indices = []

        first_batch = min(len(self._render_queue), self._initial_chunk)
        if first_batch:
            self._render_chunk(first_batch)
        if self._current_render_index < len(self._render_queue):
            self._schedule_more()

        GLib.idle_add(self._sync_button_selection_classes)
        GLib.idle_add(self._ensure_selection_visible)

    def _cancel_pending_render(self):
        if self._render_idle_id:
            GLib.source_remove(self._render_idle_id)
            self._render_idle_id = 0

    def _reset_button_pool(self):
        for child in list(self.row.get_children()):
            self.row.remove(child)
        for btn in self._buttons:
            btn.hide()
            setattr(btn, "_mapped_index", None)
            btn.get_style_context().remove_class("suggested-action")

    def _render_empty_state(self, has_items: bool):
        empty_box = Box(
            orientation="v",
            h_expand=True,
            v_expand=True,
            h_align="center",
            v_align="center",
        )
        empty_box.set_size_request(self.item_width, self.item_height)
        message = "(nenhum resultado)" if has_items else "(Clipboard vazio)"
        lbl = Label(
            name="clipbar-empty",
            label=message,
            xalign=0.5,
            yalign=0.5,
            style_classes="clipbar-empty-label",
        )
        empty_box.add(lbl)
        self.row.add(empty_box)
        self.show_all()

    def _ensure_button_pool(self, up_to_index: int):
        while len(self._buttons) <= up_to_index:
            content_box = Box(
                orientation="v",
                spacing=6,
                h_expand=False,
                v_expand=True,
                h_align="fill",
                v_align="center",
            )
            content_box.set_size_request(max(1, self.item_width - 8), -1)
            card = Button(
                name="clipbar-item",
                child=content_box,
                v_expand=False,
                v_align="center",
                style_classes="clipbar-item",
            )
            card.set_can_focus(True)
            card.connect(
                "clicked",
                lambda _btn, *_: self._on_button_clicked(_btn),
            )
            setattr(card, "_mapped_index", None)
            self._buttons.append(card)
            self._content_boxes.append(content_box)

    def _clear_box(self, container: Box) -> None:
        for child in list(container.get_children()):
            container.remove(child)

    def _render_item(self, queue_index: int) -> None:
        orig_idx, item_id, content = self._render_queue[queue_index]
        self._ensure_button_pool(queue_index)
        btn = self._buttons[queue_index]
        container = self._content_boxes[queue_index]
        self._clear_box(container)

        is_image = is_image_data(content)
        if is_image:
            desired_height = self._render_image_preview(item_id, container)
            tooltip = "[Imagem]"
        else:
            desired_height = self._render_text_preview(
                content,
                container,
                self._terms_current,
            )
            tooltip = (content or "").strip()

        if btn.get_parent() is None:
            self.row.add(btn)

        btn.set_size_request(self.item_width, desired_height)
        btn.set_tooltip_text(tooltip)
        setattr(btn, "_mapped_index", orig_idx)
        btn.show()

        self._max_card_height = max(self._max_card_height, desired_height)
        self._rendered_orig_indices.append(orig_idx)

    def _render_image_preview(self, item_id: str, target_box: Box) -> int:
        image = Image(name="clipbar-thumb")
        target_box.add(image)
        self._load_pixbuf_async(item_id, target_box)
        return self.item_height

    def _render_text_preview(
        self,
        content: str,
        container: Box,
        terms,
    ) -> int:
        display = (content or "").strip()
        if len(display) > 600:
            display = f"{display[:597]}..."
        markup = highlight_markup_multi(display, terms)
        label = Label(
            name="clipbar-text",
            markup=markup,
            justification="left",
            ellipsization="none",
            line_wrap="word-char",
            h_align="fill",
            v_align="start",
        )
        text_box = Box(
            orientation="v",
            h_expand=False,
            v_expand=False,
            h_align="fill",
            v_align="fill",
        )
        text_box.set_size_request(max(1, self.item_width - 16), -1)
        text_box.add(label)
        container.add(text_box)

        if hasattr(label, "get_preferred_height"):
            _, nat_height = label.get_preferred_height()
        else:
            nat_height = self.item_height
        return max(self.item_height, nat_height + 8)

    def _load_pixbuf_async(self, item_id: str, target_box: Box) -> None:
        if not (self.controller and hasattr(self.controller, "decode_item")):
            return

        def _worker():
            raw = self.controller.decode_item(item_id) or b""
            pix = decode_and_scale(
                raw,
                self.item_width,
                self.item_height,
            )
            if pix:
                GLib.idle_add(self._apply_pixbuf_to_box, target_box, pix)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_pixbuf_to_box(self, target_box: Box, pix) -> bool:
        if not target_box:
            return False
        for child in target_box.get_children():
            if isinstance(child, Image):
                child.set_from_pixbuf(pix)
                return False
        self._clear_box(target_box)
        image = Image(name="clipbar-thumb")
        image.set_from_pixbuf(pix)
        target_box.add(image)
        return False

    def _button_for_index(self, index: int) -> Optional[Button]:
        for button in self._buttons:
            if getattr(button, "_mapped_index", None) == index:
                return button
        return None

    def _scroll_button_into_view(self, button: Button) -> None:
        hadj = self.scroll.get_hadjustment() if self.scroll else None
        if hadj is None:
            return
        allocation = button.get_allocation()
        view_start = hadj.get_value()
        view_width = int(hadj.get_page_size())
        item_start = allocation.x
        item_width = allocation.width
        if item_start < view_start:
            hadj.set_value(max(0, item_start))
        else:
            item_end = item_start + item_width
            view_end = view_start + view_width
            if item_end > view_end:
                upper = max(0, hadj.get_upper() - view_width)
                hadj.set_value(min(upper, item_end - view_width))

    def _focus_button(self, button: Button) -> None:
        if self._entry_has_focus():
            return
        try:
            button.grab_focus()
        except (AttributeError, RuntimeError):
            pass

    def _focus_selected_if_needed(self) -> None:
        if self._entry_has_focus():
            return
        self.focus_selected()

    def _render_chunk(self, count: int):
        start = self._current_render_index
        end = min(len(self._render_queue), start + count)
        if start >= end:
            return
        for idx in range(start, end):
            self._render_item(idx)

        self._current_render_index = end
        self.set_size_request(
            -1,
            max(self.bar_height, self._max_card_height + 8),
        )
        self.show_all()

        if self._terms_current and self.controller and self._rendered_orig_indices:
            selected = self.controller.selected_index
            if selected not in self._rendered_orig_indices:
                self.controller.selected_index = self._rendered_orig_indices[0]

    def _render_more(self):
        remaining = len(self._render_queue) - self._current_render_index
        if remaining <= 0:
            self._render_idle_id = 0
            return False
        count = min(self._chunk_size, remaining)
        self._render_chunk(count)
        still = (len(self._render_queue) - self._current_render_index) > 0
        if not still:
            self._render_idle_id = 0
        return still

    def _schedule_more(self):
        if self._render_idle_id:
            GLib.source_remove(self._render_idle_id)
        self._render_idle_id = GLib.idle_add(self._render_more)

    def _move_within_filtered(self, delta: int):
        if not self.controller:
            return
        sel = self.controller.selected_index
        if sel < 0 or not self._rendered_orig_indices:
            return
        # posição do índice selecionado dentro dos renderizados
        try:
            pos = self._rendered_orig_indices.index(sel)
        except ValueError:
            # se o selecionado não está visível, vai para o começo/fim
            pos = 0 if delta > 0 else len(self._rendered_orig_indices) - 1
        # clamp estrito dentro do intervalo renderizado
        new_pos = max(
            0,
            min(pos + delta, len(self._rendered_orig_indices) - 1),
        )
        new_orig_idx = self._rendered_orig_indices[new_pos]
        if new_orig_idx != sel:
            self.controller.selected_index = new_orig_idx

    # Navegação pública usada pelo Layer
    def navigate(self, delta: int):
        # Sempre respeita o subconjunto atualmente renderizado
        ctl = self.controller
        if self._rendered_orig_indices:
            self._move_within_filtered(delta)
        else:
            # fallback: delega ao Service apenas se não há nada renderizado
            if not ctl:
                return
            if delta < 0:
                ctl.move_left()
            else:
                ctl.move_right()
        self._focus_selected_if_needed()

    def _sync_button_selection_classes(self):
        sel = self.controller.selected_index if self.controller else -1
        for button in self._buttons:
            button.get_style_context().remove_class("suggested-action")
        target = self._button_for_index(sel)
        if target is not None:
            target.get_style_context().add_class("suggested-action")

    def _on_selected_index_changed(self):
        self._sync_button_selection_classes()
        self._ensure_selection_visible()
        return False

    def _ensure_selection_visible(self):
        if not self.controller:
            return
        btn = self._button_for_index(self.controller.selected_index)
        if btn is None:
            return
        self._scroll_button_into_view(btn)
        self._focus_button(btn)

    def focus_selected(self):
        if not self.controller:
            return
        btn = self._button_for_index(self.controller.selected_index)
        if btn is None:
            return
        self._scroll_button_into_view(btn)
        self._focus_button(btn)

    def _entry_has_focus(self) -> bool:
        entry = getattr(self, "search_entry", None)
        return bool(entry and entry.has_focus())

    def _on_button_clicked(self, btn):
        idx = getattr(btn, "_mapped_index", None)
        if idx is None:
            return
        if self.controller and hasattr(self.controller, "activate_index"):
            self.controller.activate_index(idx)

    def _on_search_changed(self, *_unused):
        # envia texto para o Service (debounced)
        entry = getattr(self, "search_entry", None)
        if not entry or not self.controller:
            return
        if hasattr(self.controller, "update_query_input"):
            self.controller.update_query_input(entry.get_text())

    def _on_query_changed(self):
        # sincroniza Entry e re-renderiza com base no service.query
        entry = getattr(self, "search_entry", None)
        if not entry or not self.controller:
            self._render_items()
            return

        query_text = self.controller.query or ""
        try:
            current_text = entry.get_text()
        except RuntimeError:
            return

        if current_text != query_text:
            try:
                entry.set_text(query_text)
            except RuntimeError:
                logger.debug("failed to sync query entry", exc_info=True)
        self._render_items()

    def _on_clear_clicked(self):
        if not self.controller or not hasattr(self.controller, "wipe_history"):
            return
        self.controller.wipe_history()

    def _focus_search_entry(self):
        entry = getattr(self, "search_entry", None)
        if not entry:
            return False
        try:
            entry.grab_focus()
            # manter cursor ao final para não perder foco em edições
            entry.set_position(-1)
        except (AttributeError, RuntimeError):
            logger.debug("focus entry failed", exc_info=True)
        return False
