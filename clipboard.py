from typing import Optional, List, Tuple
import re
import subprocess
import sys

from gi.repository import GdkPixbuf, GLib, Gtk
from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow

from clipboardService import ClipboardService


class ClipBar(Box):
    def __init__(self, max_items=50, bar_height=56, item_width=260, controller: Optional[ClipboardService] = None, **kwargs):
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
        self.max_items = max_items

        # linha de itens (não expandir horizontal para permitir overflow)
        self.row = Box(
            name="clipbar-row",
            orientation="h",
            spacing=6,
            h_expand=False,
            v_expand=True,
            h_align="fill",
            v_align="fill",
        )

        # ScrolledWindow com barras visíveis
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
        # barras horizontais visíveis quando necessário; sem overlay
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        try:
            self.scroll.set_overlay_scrolling(False)
        except Exception:
            pass

        self.add(self.scroll)
        self.set_size_request(-1, self.bar_height)

        # estado UI
        self._buttons: List[Button] = []
        self._content_boxes: List[Box] = []

        # integra com o Service
        self.controller = controller
        if self.controller:
            self.controller.connect("notify::items", lambda *_: self._render_items())
            self.controller.connect("notify::selected-index", lambda *_: self._apply_selection_styles())

        # render inicial
        self._render_items()

    def _render_items(self):
        # limpa
        self.row.children = []
        self._buttons.clear()
        self._content_boxes.clear()

        items = (self.controller.items if self.controller else [])[: self.max_items]

        if not items:
            self.row.add(Label(name="clipbar-empty", label="(Clipboard vazio)"))
            self.show_all()
            return

        for idx, (item_id, content) in enumerate(items):
            is_img = self._is_image_data(content)

            if is_img:
                content_box = Box(
                    orientation="h",
                    spacing=6,
                    children=[
                        Image(name="clipbar-thumb"),
                        Label(name="clipbar-text", label="[Imagem]", ellipsization="end"),
                    ],
                    style="padding: 8px; border-radius: 8px;",
                )
            else:
                display = content.strip()
                if len(display) > 80:
                    display = display[:77] + "..."
                content_box = Box(
                    orientation="h",
                    children=[Label(name="clipbar-text", label=display, ellipsization="end")],
                    style="padding: 8px; border-radius: 8px;",
                )

            btn = Button(
                name="clipbar-item",
                child=content_box,
                tooltip_text="[Imagem]" if is_img else content.strip(),
                on_clicked=lambda *_, i=idx: (self.controller.activate_index(i) if self.controller else None),
                v_expand=True,
                v_align="fill",
            )
            btn.set_size_request(self.item_width, -1)
            btn.set_can_focus(True)

            self.row.add(btn)
            self._buttons.append(btn)
            self._content_boxes.append(content_box)

            if is_img:
                self._load_image_preview_async(item_id, btn)

        self.show_all()
        self._apply_selection_styles()

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
                result = subprocess.run(["cliphist", "decode", item_id], capture_output=True, check=True)
                loader = GdkPixbuf.PixbufLoader()
                loader.write(result.stdout)
                loader.close()
                pixbuf = loader.get_pixbuf()

                padding = 12
                max_size = max(1, min(72, self.bar_height - padding))
                w, h = pixbuf.get_width(), pixbuf.get_height()
                if w > h:
                    nw, nh = max_size, int(h * (max_size / w))
                else:
                    nh, nw = max_size, int(w * (max_size / h))
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