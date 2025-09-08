from typing import Optional

import gi
import threading
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
from .assets import icons


class ClipBar(Box):
    def __init__(
        self,
        max_items=50,
        bar_height=56,
        item_width=260,
        initial_chunk: int = 48,
        chunk_size: int = 96,
        controller: Optional[ClipboardService] = None,
        item_height: Optional[int] = None,
        **kwargs
    ):
        super().__init__(
            name="clipbar-root",
            spacing=6,
            orientation="v",
            h_expand=True,
            v_expand=True,
            **kwargs
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
            placeholder="Buscar...", style_classes="clipbar-search", h_expand=True
        )
        self.search_entry.connect("changed", lambda *_: self._on_search_changed())

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
            label= icons.trash,
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
            self.controller.connect("notify::items", lambda *_: self._render_items())
            self.controller.connect(
                "notify::selected-index",
                lambda *_: GLib.idle_add(self._on_selected_index_changed),
            )
            self.controller.connect("notify::query", lambda *_: self._on_query_changed())
        # Estado de renderização incremental
        self._render_queue = []  # List[Tuple[orig_idx, item_id, content]]
        self._current_render_index = 0
        self._render_idle_id = 0
        self._terms_current = []
        self._max_card_height = self.item_height
        # Tamanhos de chunk: primeiro lote pequeno para abrir rápido
        try:
            self._initial_chunk = max(1, int(initial_chunk))
        except Exception:
            self._initial_chunk = 48
        try:
            self._chunk_size = max(self._initial_chunk, int(chunk_size))
        except Exception:
            self._chunk_size = max(self._initial_chunk, 96)

        # Primeira renderização
        self._render_items()
        GLib.idle_add(self._sync_button_selection_classes)
        GLib.idle_add(self._focus_search_entry)

    def _render_items(self):
        # Cancelar renderização pendente
        if getattr(self, "_render_idle_id", 0):
            try:
                GLib.source_remove(self._render_idle_id)
            except Exception:
                pass
            self._render_idle_id = 0

        all_items = self.controller.items if self.controller else []
        # pega filtro atual do service (normalizado)
        self._filter_text = (self.controller.query or "") if self.controller else ""
        terms = [t for t in (self._filter_text.split() if self._filter_text else []) if t]
        if terms:
            # AND: todos os termos devem existir no texto (case-insensitive)
            filtered = [
                (i, itm_id, txt)
                for i, (itm_id, txt) in enumerate(all_items)
                if all(t in (txt or "").lower() for t in terms)
            ]
        else:
            filtered = [(i, itm_id, txt) for i, (itm_id, txt) in enumerate(all_items)]

        render_candidates = filtered[: self.max_items]

        # Se não há filtro, garanta que a seleção atual esteja dentro do intervalo renderizado [0..len-1]
        if self.controller and not terms:
            sel = self.controller.selected_index
            max_idx = len(render_candidates) - 1
            if max_idx >= 0:
                if sel > max_idx:
                    self.controller.selected_index = max_idx
                elif sel < 0:
                    self.controller.selected_index = 0

        # Limpar UI atual
        for child in list(self.row.get_children()):
            self.row.remove(child)
        # Ocultar todos botões antigos até serem reusados
        for btn in self._buttons:
            btn.hide()
            setattr(btn, "_mapped_index", None)
            btn.get_style_context().remove_class("suggested-action")

        # Altura inicial baseada no item base; ajustaremos após chunks
        self._max_card_height = self.item_height
        self.set_size_request(-1, max(self.bar_height, self.item_height + 16))

        if not render_candidates:
            empty_box = Box(
                orientation="v",
                h_expand=True,
                v_expand=True,
                h_align="center",
                v_align="center",
            )
            empty_box.set_size_request(self.item_width, self.item_height)
            lbl = Label(
                name="clipbar-empty",
                label="(Clipboard vazio)" if not all_items else "(nenhum resultado)",
                xalign=0.5,
                yalign=0.5,
                style_classes="clipbar-empty-label",
            )
            empty_box.add(lbl)
            self.row.add(empty_box)
            self.show_all()
            return

        # Preparar fila de render e estado
        self._rendered_orig_indices = []
        self._render_queue = list(render_candidates)
        self._terms_current = terms
        self._current_render_index = 0

        # Renderizar primeiro lote imediatamente
        first_count = min(len(self._render_queue), self._initial_chunk)
        if first_count > 0:
            self._render_chunk(first_count)
        # Agendar o restante em idle
        if self._current_render_index < len(self._render_queue):
            self._schedule_more()
        # Sincronizar seleção após primeiro paint
        GLib.idle_add(self._sync_button_selection_classes)
        GLib.idle_add(self._ensure_selection_visible)

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
            card.connect("clicked", lambda _btn, *_: self._on_button_clicked(_btn))
            setattr(card, "_mapped_index", None)
            self._buttons.append(card)
            self._content_boxes.append(content_box)

    def _render_chunk(self, count: int):
        start = self._current_render_index
        end = min(len(self._render_queue), start + count)
        if start >= end:
            return
        terms = self._terms_current
        for idx in range(start, end):
            orig_idx, item_id, content = self._render_queue[idx]
            self._ensure_button_pool(idx)
            btn = self._buttons[idx]
            content_box = self._content_boxes[idx]

            # Limpar conteúdo do card
            for ch in list(content_box.get_children()):
                content_box.remove(ch)

            def apply_pixbuf_to_button(box, pix):
                if not box:
                    return False
                children = list(box.get_children())
                if children and isinstance(children[0], Image):
                    children[0].set_from_pixbuf(pix)
                else:
                    for c in children:
                        box.remove(c)
                    new_img = Image(name="clipbar-thumb")
                    box.add(new_img)
                    new_img.set_from_pixbuf(pix)
                return False

            def load_and_apply(it_id, target_box):
                raw = b""
                if self.controller and hasattr(self.controller, "decode_item"):
                    raw = self.controller.decode_item(it_id)
                pix = decode_and_scale(raw or b"", self.item_width, self.item_height)
                if not pix:
                    return
                GLib.idle_add(lambda p=pix, bb=target_box: apply_pixbuf_to_button(bb, p))

            is_img = is_image_data(content)
            if is_img:
                img = Image(name="clipbar-thumb")
                content_box.add(img)
                threading.Thread(
                    target=load_and_apply, args=(item_id, content_box), daemon=True
                ).start()
                desired_h = self.item_height
            else:
                display = (content or "").strip()
                if len(display) > 600:
                    display = display[:597] + "..."
                markup = highlight_markup_multi(display, terms)
                lbl = Label(
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
                text_box.add(lbl)
                content_box.add(text_box)
                try:
                    _min_h, nat_h = lbl.get_preferred_height()
                except Exception:
                    nat_h = self.item_height
                desired_h = max(self.item_height, nat_h + 8)

            if btn.get_parent() is None:
                self.row.add(btn)
            btn.set_size_request(self.item_width, desired_h)
            btn.set_tooltip_text("[Imagem]" if is_img else (content or "").strip())
            setattr(btn, "_mapped_index", orig_idx)
            btn.show()

            if desired_h > self._max_card_height:
                self._max_card_height = desired_h
            self._rendered_orig_indices.append(orig_idx)

        self._current_render_index = end
        # Atualizar altura após o chunk
        self.set_size_request(-1, max(self.bar_height, self._max_card_height + 8))
        self.show_all()

        # Se há filtro ativo e o item selecionado não está visível,
        # move a seleção para o primeiro resultado após primeiro chunk
        if self._current_render_index == end and self._terms_current and self.controller:
            sel = self.controller.selected_index
            if sel not in self._rendered_orig_indices and self._rendered_orig_indices:
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
        if getattr(self, "_render_idle_id", 0):
            try:
                GLib.source_remove(self._render_idle_id)
            except Exception:
                pass
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
        new_pos = max(0, min(pos + delta, len(self._rendered_orig_indices) - 1))
        new_orig_idx = self._rendered_orig_indices[new_pos]
        if new_orig_idx != sel:
            self.controller.selected_index = new_orig_idx
            self._sync_button_selection_classes()
            self._ensure_selection_visible()

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
        # Só força foco no item se o entry não estiver com foco
        try:
            if not (getattr(self, "search_entry", None) and self.search_entry.has_focus()):
                self.focus_selected()
        except Exception:
            pass

    def _sync_button_selection_classes(self):
        sel = self.controller.selected_index if self.controller else -1
        target = None
        for b in list(self._buttons):
            b.get_style_context().remove_class("suggested-action")
            if getattr(b, "_mapped_index", None) == sel:
                target = b
        if target is not None:
            target.get_style_context().add_class("suggested-action")

    def _on_selected_index_changed(self):
        self._sync_button_selection_classes()
        self._ensure_selection_visible()
        return False

    def _ensure_selection_visible(self):
        sel = self.controller.selected_index if self.controller else -1
        btn = None
        for b in self._buttons:
            if getattr(b, "_mapped_index", None) == sel:
                btn = b
                break
        if btn is None:
            return
        hadj = self.scroll.get_hadjustment() if self.scroll else None
        if hadj is None:
            return
        alloc = btn.get_allocation()
        view_x = hadj.get_value()
        view_w = int(hadj.get_page_size())
        item_x = alloc.x
        item_w = alloc.width
        if item_x < view_x:
            hadj.set_value(max(0, item_x))
        elif item_x + item_w > view_x + view_w:
            hadj.set_value(min(hadj.get_upper() - view_w, item_x + item_w - view_w))
        if not (getattr(self, "search_entry", None) and self.search_entry.has_focus()):
            btn.grab_focus()

    def focus_selected(self):
        sel = self.controller.selected_index if self.controller else -1
        if 0 <= sel < len(self._buttons):
            btn = self._buttons[sel]
            hadj = self.scroll.get_hadjustment() if self.scroll else None
            if hadj is None:
                return
            alloc = btn.get_allocation()
            view_x = hadj.get_value()
            view_w = int(hadj.get_page_size())
            item_x = alloc.x
            item_w = alloc.width
            if item_x < view_x:
                hadj.set_value(max(0, item_x))
            elif item_x + item_w > view_x + view_w:
                hadj.set_value(min(hadj.get_upper() - view_w, item_x + item_w - view_w))
            btn.grab_focus()

    def _on_button_clicked(self, btn):
        idx = getattr(btn, "_mapped_index", None)
        if idx is None:
            return
        if self.controller and hasattr(self.controller, "activate_index"):
            self.controller.activate_index(idx)

    def _on_search_changed(self, *args):
        # envia texto para o Service (debounced)
        if self.controller and hasattr(self.controller, "update_query_input"):
            try:
                self.controller.update_query_input(self.search_entry.get_text())
            except Exception:
                pass

    def _on_query_changed(self):
        # sincroniza Entry e re-renderiza com base no service.query
        if getattr(self, "search_entry", None) and self.controller:
            q = self.controller.query or ""
            try:
                if self.search_entry.get_text() != q:
                    self.search_entry.set_text(q)
            except Exception:
                pass
        self._render_items()

    def _on_clear_clicked(self):
        if self.controller and hasattr(self.controller, "wipe_history"):
            try:
                self.controller.wipe_history()
            except Exception:
                pass

    def _focus_search_entry(self):
        if getattr(self, "search_entry", None):
            try:
                self.search_entry.grab_focus()
                # manter cursor ao final para não perder foco em edições/backsapce
                self.search_entry.set_position(-1)
            except Exception:
                pass
            return False
        return False
