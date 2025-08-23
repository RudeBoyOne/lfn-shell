from typing import Optional, List, Tuple
import re
import sys

import gi
try:
    gi.require_version("GdkPixbuf", "2.0")
except Exception:
    pass
try:
    gi.require_version("Gtk", "3.0")
except Exception:
    # if Gtk already loaded (e.g. Gtk 4), allow fallback and hope the runtime is compatible
    pass
from gi.repository import GdkPixbuf, GLib, Gtk
from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.entry import Entry
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow

from clipboard.clipboardService import ClipboardService


class ClipBar(Box):
    def __init__(self, max_items=50, bar_height=56, item_width=260, controller: Optional[ClipboardService] = None, item_height: Optional[int] = None, **kwargs):
        super().__init__(
            name="clipbar-root",
            spacing=6,
            orientation="v",
            h_expand=True,
            v_expand=True,
            **kwargs,
        )

        # configurações básicas
        self.bar_height = bar_height
        self.item_width = item_width
        self.item_height = item_height or max(56, self.bar_height - 4)
        self.max_items = max_items

        # linha de itens
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

        # scroller
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
        try:
            self.scroll.set_overlay_scrolling(False)
        except Exception:
            pass

        # campo de busca (centralizado, com debounce e foco ao abrir)
        self.search_entry = Entry(placeholder="Buscar...", style_classes="clipbar-search", h_expand=True)
        self.search_entry.connect("changed", lambda *_: self._schedule_search_update())
        # wrapper leve para centralizar horizontalmente sem alterar estilos globais
        search_wrap = Box(orientation="h", h_expand=True, h_align="center", children=[self.search_entry])

        # montar layout
        self.add(search_wrap)
        self.add(self.scroll)
        self.set_size_request(-1, self.bar_height)

        # estado UI
        self._buttons = []
        self._content_boxes = []
        self._rendered_orig_indices = []
        self._filter_text = ""
        self._search_debounce_id = 0

        # integra com o Service
        self.controller = controller
        if self.controller:
            self.controller.connect("notify::items", lambda *_: self._render_items())
            self.controller.connect("notify::selected-index", lambda *_: self._apply_selection_styles())

        # render inicial e foco
        self._render_items()
        try:
            GLib.idle_add(self._focus_search_entry)
        except Exception:
            try:
                self.search_entry.grab_focus()
            except Exception:
                pass

    def _render_items(self):
        # preservar foco do campo de busca (se houver) antes de reconstruir
        try:
            self._search_was_focused = bool(getattr(self, "search_entry", None) and self.search_entry.has_focus())
        except Exception:
            self._search_was_focused = False

        # limpa
        self.row.children = []
        self._buttons.clear()
        self._content_boxes.clear()

        # coleta itens do service e aplica filtro (case-insensitive)
        all_items = (self.controller.items if self.controller else [])
        if self._filter_text:
            filtered = [(i, itm_id, txt) for i, (itm_id, txt) in enumerate(all_items) if self._filter_text in (txt or "").lower()]
        else:
            filtered = [(i, itm_id, txt) for i, (itm_id, txt) in enumerate(all_items)]

        # aplicar limite de max_items
        render_candidates = filtered[: self.max_items]

        # calcular altura desejada para os items de texto (wrap)
        # heurística: calcular número de linhas aproximado a partir do comprimento do texto
        max_text_lines = 0
        if render_candidates:
            chars_per_line = max(20, max(10, self.item_width // 8))
            for _, _, content in render_candidates:
                if not self._is_image_data(content):
                    display_len = len((content or "").strip())
                    lines = min(6, max(1, (display_len // chars_per_line) + 1))
                    if lines > max_text_lines:
                        max_text_lines = lines

        # se houver textos que demandam mais linhas, aumentamos a altura dos cards e do bar
        if max_text_lines > 1:
            line_height = 18  # px aproximado por linha para o tamanho de fonte atual
            computed_item_height = max(self.item_height, max_text_lines * line_height + 24)
        else:
            computed_item_height = self.item_height

        # ajustar a altura do clipbar (visual) para acomodar os cards maiores
        try:
            self.set_size_request(-1, max(self.bar_height, computed_item_height + 16))
        except Exception:
            pass

        if not render_candidates:
            msg = "(Clipboard vazio)" if not all_items else "(nenhum resultado)"
            # Mantém a altura do clipbar estável: adiciona uma caixa placeholder
            # que ocupa o mesmo espaço dos cards e centraliza a mensagem.
            empty_box = Box(
                orientation="v",
                h_expand=True,
                v_expand=True,
                h_align="center",
                v_align="center",
            )
            try:
                # solicita espaço similar ao tamanho computado dos items
                empty_box.set_size_request(self.item_width, computed_item_height)
            except Exception:
                pass
            lbl = Label(
                name="clipbar-empty",
                label=msg,
                xalign=0.5,
                yalign=0.5,
                style_classes="clipbar-empty-label",
            )
            try:
                empty_box.add(lbl)
            except Exception:
                empty_box.children = [lbl]
            self.row.add(empty_box)
            self.show_all()
            # restaurar foco no campo de busca se ele estava ativo antes da render
            try:
                if getattr(self, "_search_was_focused", False):
                    GLib.idle_add(lambda: (self.search_entry.grab_focus(), False)[1])
            except Exception:
                pass
            return
        # reset mapping
        # Reuse existing buttons/widgets where possible to avoid focus loss.
        self._rendered_orig_indices = []

        # Ensure we have enough button widgets allocated
        needed = len(render_candidates)
        while len(self._buttons) < needed:
            # create placeholder content box and button
            placeholder_box = Box(orientation="v", spacing=6, h_expand=True, v_expand=True, h_align="center", v_align="center")
            new_btn = Button(name="clipbar-item", child=placeholder_box, v_expand=False, v_align="center")
            new_btn.set_can_focus(True)
            # append but don't add to row yet; we'll manage visibility below
            self._buttons.append(new_btn)
            self._content_boxes.append(placeholder_box)

        # Update or add buttons according to render_candidates
        for idx, (orig_idx, item_id, content) in enumerate(render_candidates):
            is_img = self._is_image_data(content)
            btn = self._buttons[idx]
            content_box = self._content_boxes[idx]

            # clear current children of content_box
            try:
                for child in list(content_box.get_children()):
                    try:
                        content_box.remove(child)
                    except Exception:
                        pass
            except Exception:
                pass

            if is_img:
                img = Image(name="clipbar-thumb")
                try:
                    content_box.add(img)
                except Exception:
                    # fallback: set child directly
                    content_box.children = [img]
                # load preview async
                try:
                    self._load_image_preview_async(item_id, btn)
                except Exception:
                    pass
            else:
                display = (content or "").strip()
                if len(display) > 600:
                    display = display[:597] + "..."
                lbl = Label(name="clipbar-text", label=display, ellipsization="end", wrap=True, xalign=0.5, yalign=0.5, style_classes="clipbar-text-label")
                try:
                    content_box.add(lbl)
                except Exception:
                    content_box.children = [lbl]

            # ensure button is added to row and visible
            try:
                if btn.get_parent() is None:
                    self.row.add(btn)
                btn.set_size_request(self.item_width, computed_item_height)
                btn.set_tooltip_text("[Imagem]" if is_img else (content or "").strip())
                # update onclick to point to the correct original index
                try:
                    btn.connect("clicked", lambda _btn, _i=orig_idx: (self.controller.activate_index(_i) if self.controller else None))
                except Exception:
                    # Some Button implementations accept on_clicked in constructor only
                    pass
                try:
                    btn.show()
                except Exception:
                    pass
            except Exception:
                pass

            self._rendered_orig_indices.append(orig_idx)

        # hide any leftover buttons
        for j in range(len(render_candidates), len(self._buttons)):
            try:
                self._buttons[j].hide()
            except Exception:
                pass

        self.show_all()
        self._apply_selection_styles()

        # restaurar foco no campo de busca se ele estava ativo antes da render
        try:
            if getattr(self, "_search_was_focused", False):
                # agendar via idle para não interromper o fluxo de eventos atual
                GLib.idle_add(lambda: (self.search_entry.grab_focus(), False)[1])
        except Exception:
            pass

    def _apply_selection_styles(self):
        sel = self.controller.selected_index if self.controller else -1
        for i, (btn, content) in enumerate(zip(self._buttons, self._content_boxes)):
            ctx = btn.get_style_context()
            if i == sel:
                ctx.add_class("suggested-action")
                content.style = "padding: 8px; border-radius: 8px; background-color: rgba(255,255,255,0.12);"
            else:
                ctx.remove_class("suggested-action")
                content.style = "padding: 8px; border-radius: 8px;"
        # rola a scroll view para mostrar o item selecionado (se houver)
        try:
            if 0 <= sel < len(self._buttons):
                btn = self._buttons[sel]
                # certifica-se que o botão está visível horizontalmente
                hadj = self.scroll.get_hadjustment()
                alloc = btn.get_allocation()
                view_x = hadj.get_value()
                view_w = int(hadj.get_page_size())
                item_x = alloc.x
                item_w = alloc.width
                # se item está à esquerda do view ou à direita, ajuste
                if item_x < view_x:
                    hadj.set_value(max(0, item_x))
                elif item_x + item_w > view_x + view_w:
                    hadj.set_value(min(hadj.get_upper() - view_w, item_x + item_w - view_w))
                # garantir foco no botão selecionado
                try:
                    # se o campo de busca estiver focado, não roube o foco do usuário
                    if getattr(self, "search_entry", None) and self.search_entry.has_focus():
                        pass
                    else:
                        btn.grab_focus()
                except Exception:
                    pass
        except Exception:
            pass

    def focus_selected(self):
        """Traz o item selecionado à vista e foca o botão correspondente.

        Separado de `_apply_selection_styles` para permitir agendamento via
        `GLib.idle_add` quando necessário (por exemplo, depois de um key event).
        """
        try:
            sel = self.controller.selected_index if self.controller else -1
            if 0 <= sel < len(self._buttons):
                btn = self._buttons[sel]
                hadj = self.scroll.get_hadjustment()
                alloc = btn.get_allocation()
                view_x = hadj.get_value()
                view_w = int(hadj.get_page_size())
                item_x = alloc.x
                item_w = alloc.width
                if item_x < view_x:
                    hadj.set_value(max(0, item_x))
                elif item_x + item_w > view_x + view_w:
                    hadj.set_value(min(hadj.get_upper() - view_w, item_x + item_w - view_w))
                try:
                    btn.grab_focus()
                except Exception:
                    pass
        except Exception:
            pass

    def _is_image_data(self, content: str) -> bool:
        return (
            content.startswith("data:image/")
            or content.startswith("\x89PNG")
            or content.startswith("GIF8")
            or content.startswith("\xff\xd8\xff")
            or re.match(r"^\s*<img\s+", content) is not None
            or ("binary" in content.lower() and any(ext in content.lower() for ext in ["jpg", "jpeg", "png", "bmp", "gif"]))
        )

    def _load_image_preview_async(self, item_id, button):
        def load():
            try:
                # Decodifica via controller apenas; não executar subprocess aqui.
                raw = None
                if self.controller and hasattr(self.controller, "decode_item"):
                    try:
                        raw = self.controller.decode_item(item_id)
                    except Exception as e:
                        # falha ao decodificar no controller -> não carregar preview
                        print(f"[clipbar] controller.decode_item falhou: {e}", file=sys.stderr)
                        raw = None

                # se não obtemos bytes válidos, aborta sem chamar subprocess
                if not raw:
                    return False

                loader = GdkPixbuf.PixbufLoader()
                if isinstance(raw, str):
                    raw = raw.encode("utf-8", errors="ignore")
                loader.write(raw)
                loader.close()
                pixbuf = loader.get_pixbuf()

                padding = 16
                # limitar preview ao tamanho do card (largura menos padding, altura menos espaço para texto)
                max_w = max(1, self.item_width - padding)
                max_h = max(1, self.item_height - 48)
                w, h = pixbuf.get_width(), pixbuf.get_height()
                scale = min(max_w / w, max_h / h, 1.0)
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                pixbuf = pixbuf.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)

                box = button.get_child()
                if box and box.get_children():
                    img = box.get_children()[0]
                    if isinstance(img, Image):
                        img.set_from_pixbuf(pixbuf)
            except Exception as e:
                print(f"[clipbar] erro carregando preview: {e}", file=sys.stderr)
            return False
        GLib.idle_add(load)

    def _on_search_changed(self, *args):
        """Handler chamado quando o texto de busca muda; atualiza o filtro e re-renderiza."""
        # obter texto em lowercase para busca case-insensitive
        try:
            text = (self.search_entry.get_text() or "").strip().lower()
        except Exception:
            text = ""
        # armazenar e atualizar view na thread principal
        self._filter_text = text
        # re-renderiza (proteção leve para evitar crashes durante digitação)
        try:
            self._render_items()
        except Exception:
            pass

    def _schedule_search_update(self, debounce_ms: int = 300):
        """Agenda um timeout debounced para aplicar o filtro da busca.

        Se já houver um timeout agendado, cancela e re-agenda.
        """
        try:
            # remove qualquer agendamento anterior
            if getattr(self, "_search_debounce_id", 0):
                try:
                    GLib.source_remove(self._search_debounce_id)
                except Exception:
                    pass
            # agenda novo timeout
            self._search_debounce_id = GLib.timeout_add(int(debounce_ms), self._perform_debounced_search)
        except Exception:
            # fallback: chamada direta sem debounce
            GLib.idle_add(self._on_search_changed)

    def _perform_debounced_search(self):
        """Executa a atualização de busca agendada. Retorna False para não repetir a timeout."""
        try:
            self._on_search_changed()
        except Exception:
            pass
        # reset id e evitar re-execução
        try:
            self._search_debounce_id = 0
        except Exception:
            pass
        return False

    def _focus_search_entry(self):
        """Tenta focar o campo de busca; usado via GLib.idle_add após criação."""
        try:
            if hasattr(self, "search_entry") and self.search_entry:
                self.search_entry.grab_focus()
                return False
        except Exception:
            pass
        return False