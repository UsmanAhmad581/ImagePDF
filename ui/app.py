"""Main window (customtkinter)."""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageOps

from core import ocr, paths
from core.models import PageItem
from core.pagenum import detect_page_number, natural_key, order_pages
from core.pdfbuilder import Cancelled, build_pdf, count_frames, load_item

try:  # optional: drag files from Explorer onto the window
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BASES = (ctk.CTk, TkinterDnD.DnDWrapper)
    HAVE_DND = True
except Exception:  # pragma: no cover
    _BASES = (ctk.CTk,)
    HAVE_DND = False

IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
# junk files that live in image folders; not worth reporting when scanning a folder
IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
CARD_W, THUMB = 170, (150, 190)
ACCENT = "#2f7de1"
GOOD, WARN = "#2e9e5b", "#d98e04"


UNDO_LIMIT = 30


class _Card:
    """The widgets of one page card. Cards are created once per page and then only updated,
    so a click / move / rotate touches one or two cards instead of rebuilding all of them."""
    __slots__ = ("frame", "img", "title", "badge", "buttons",
                 "pos", "title_txt", "badge_key", "rot", "selected")

    def __init__(self):
        self.pos = self.title_txt = self.badge_key = self.rot = self.selected = None
        self.buttons = []


class App(*_BASES):
    def __init__(self):
        super().__init__()
        self.settings = paths.load_settings()
        ctk.set_appearance_mode(self.settings["appearance"])
        ctk.set_default_color_theme("blue")

        self.title("Image → PDF  •  OCR page organiser")
        self.geometry("1320x800")
        self.minsize(1050, 650)

        self.items = []
        self.sel = None
        self.q = queue.Queue()
        self.busy = False
        self.cancel_evt = threading.Event()
        self._pending_order = False
        self._cols = 0
        self._drag = None
        self._cards = {}           # PageItem.uid -> _Card
        self._card_of = {}         # card frame widget -> PageItem (for drag & drop)
        self._undo = []            # snapshots of the page list (order + membership)
        self._preview_key = None   # (uid, rotation) of the image shown in the preview
        self._text_key = None      # what the text box currently shows
        self._preview_img = None
        self._resize_job = None
        self._lang_applied = self.settings["language"]   # language the stored OCR belongs to
        self._lang_busy = False
        self._text_item = None     # item whose text is currently shown in the textbox
        # CTkLabel.configure(image=None) does NOT clear an image, so we swap in this
        # transparent placeholder instead (see _set_preview).
        self._blank_img = ctk.CTkImage(light_image=Image.new("RGBA", (1, 1), (0, 0, 0, 0)),
                                       dark_image=Image.new("RGBA", (1, 1), (0, 0, 0, 0)),
                                       size=(1, 1))

        if HAVE_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

        self.tess = paths.configure_tesseract()
        self.have_ocr = ocr.engine_available()

        self._build()
        self.bind("<Delete>", self._on_delete_key)
        self.bind("<Control-o>", lambda e: self.add_images())
        self.bind("<Control-z>", self._on_undo_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        if not self.have_ocr:
            self.after(400, self._warn_no_ocr)

    # ------------------------------------------------------------------ layout
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- sidebar
        side = ctk.CTkFrame(self, width=250, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        self._side = side
        # Packed FIRST: pack hands out space in packing order, so when the window is short
        # the other controls are clipped instead of this button disappearing.
        self.btn_pdf = ctk.CTkButton(side, text="📄  Create PDF", height=46,
                                     font=ctk.CTkFont(size=15, weight="bold"),
                                     fg_color=GOOD, hover_color="#237a46", command=self.create_pdf)
        self.btn_pdf.pack(side="bottom", fill="x", padx=16, pady=14)
        ctk.CTkLabel(side, text="Image → PDF", font=ctk.CTkFont(size=24, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(side, text="Read text, order pages, export PDF",
                     text_color=("gray40", "gray65")).pack(anchor="w", padx=20, pady=(0, 8))

        def btn(text, cmd, **kw):
            b = ctk.CTkButton(side, text=text, command=cmd, anchor="w", height=34, **kw)
            b.pack(fill="x", padx=16, pady=3)
            return b

        self.btn_add = btn("＋  Add images…", self.add_images)
        self.btn_folder = btn("📁  Add folder…", self.add_folder)
        self.btn_undo = btn("↶  Undo (Ctrl+Z)", self.undo, fg_color="#5a6b82")
        self.btn_undo.configure(state="disabled")
        ctk.CTkLabel(side, text="PROCESS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray40", "gray65")).pack(anchor="w", padx=20, pady=(8, 0))
        self.btn_ocr = btn("🔍  1. Read text (OCR)", self.run_ocr, fg_color="#5a6b82")
        self.btn_order = btn("🔢  2. Auto-order pages", self.auto_order, fg_color="#5a6b82")
        self.btn_txt = btn("📝  Export text (.txt)", self.export_text, fg_color="#5a6b82")

        ctk.CTkLabel(side, text="SETTINGS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray40", "gray65")).pack(anchor="w", padx=20, pady=(8, 0))
        ctk.CTkLabel(side, text="OCR language").pack(anchor="w", padx=20, pady=(4, 0))
        langs = ocr.languages() if self.have_ocr else ["eng"]
        self._known_langs = set(langs) if self.have_ocr else None
        self.lang = ctk.CTkComboBox(side, values=langs, command=self._lang_changed)
        self.lang.set(self.settings["language"])
        self.lang.pack(fill="x", padx=16, pady=2)
        # typing "eng+urd" never fires the dropdown command: apply on Enter / leaving the box
        for seq in ("<Return>", "<KP_Enter>", "<FocusOut>"):
            self.lang._entry.bind(seq, self._lang_changed, add="+")
        ctk.CTkLabel(side, text="PDF page size").pack(anchor="w", padx=20, pady=(6, 0))
        self.page_mode = ctk.CTkOptionMenu(side, values=["Fit to image", "A4 page (white margins)"])
        self.page_mode.set(self.settings["page_mode"])
        self.page_mode.pack(fill="x", padx=16, pady=2)
        self.sw_search = ctk.CTkSwitch(side, text="Searchable text in PDF")
        self.sw_search.pack(anchor="w", padx=20, pady=(8, 2))
        if self.settings["searchable"]:
            self.sw_search.select()
        self.sw_rot = ctk.CTkSwitch(side, text="Auto-fix sideways pages")
        self.sw_rot.pack(anchor="w", padx=20, pady=2)
        if self.settings["auto_rotate"]:
            self.sw_rot.select()
        ctk.CTkLabel(side, text="Theme").pack(anchor="w", padx=20, pady=(8, 0))
        self._theme_menu = ctk.CTkOptionMenu(side, values=["System", "Light", "Dark"],
                                             command=self._set_theme)
        self._theme_menu.pack(fill="x", padx=16, pady=2)
        self._theme_menu.set(self.settings["appearance"])

        # --- centre: thumbnail grid
        centre = ctk.CTkFrame(self, fg_color="transparent")
        centre.grid(row=0, column=1, sticky="nsew", padx=(10, 5), pady=10)
        centre.grid_rowconfigure(1, weight=1)
        centre.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(centre, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        self.lbl_count = ctk.CTkLabel(head, text="Pages", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_count.pack(side="left")
        ctk.CTkLabel(head, text="Drag a card to reorder  •  click to preview",
                     text_color=("gray40", "gray65")).pack(side="right")
        self.grid_frame = ctk.CTkScrollableFrame(centre, corner_radius=10)
        self.grid_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.empty_lbl = ctk.CTkLabel(
            self.grid_frame, text="\n\n🖼\n\nAdd images to get started\n"
            + ("(or drop files here)" if HAVE_DND else ""), font=ctk.CTkFont(size=16),
            text_color=("gray45", "gray60"))
        centre.bind("<Configure>", self._on_resize)

        # --- right: preview + text
        right = ctk.CTkFrame(self, width=340)
        right.grid(row=0, column=2, sticky="nsew", padx=(5, 10), pady=10)
        right.grid_propagate(False)
        ctk.CTkLabel(right, text="Preview", font=ctk.CTkFont(size=16, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        self.preview = ctk.CTkLabel(right, text="No page selected", width=312, height=330,
                                    fg_color=("gray85", "gray20"), corner_radius=8)
        self.preview.grid(row=1, column=0, padx=14, pady=4)
        self.info = ctk.CTkLabel(right, text="", anchor="w", justify="left")
        self.info.grid(row=2, column=0, sticky="ew", padx=14)
        ctk.CTkLabel(right, text="Recognised text", font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=3, column=0, sticky="nw", padx=14, pady=(8, 0))
        self.textbox = ctk.CTkTextbox(right, wrap="word", height=170)
        self.textbox.grid(row=4, column=0, sticky="nsew", padx=14, pady=(2, 14))
        # keep edits: save on every keystroke / paste and when focus leaves the box
        for seq in ("<KeyRelease>", "<<Paste>>", "<<Cut>>", "<FocusOut>"):
            self.textbox._textbox.bind(seq, self._commit_text, add="+")
        right.grid_rowconfigure(4, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # --- bottom status bar
        bar = ctk.CTkFrame(self, height=40, corner_radius=0)
        bar.grid(row=1, column=0, columnspan=3, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        self.status = ctk.CTkLabel(bar, text="Ready.", anchor="w", width=520)
        self.status.grid(row=0, column=0, padx=14, pady=8)
        self.progress = ctk.CTkProgressBar(bar)
        self.progress.set(0)
        self.progress.grid(row=0, column=1, sticky="ew", padx=10)
        self.btn_cancel = ctk.CTkButton(bar, text="Cancel", width=80, fg_color="#b23b3b",
                                        hover_color="#8f2e2e", command=self.cancel_evt.set)
        self.btn_cancel.grid(row=0, column=2, padx=10)
        self.btn_cancel.grid_remove()

        self.render_grid()
        self.after(50, self._fit_min_height)

    def _fit_min_height(self):
        """Raise the window's minimum height so the whole sidebar always fits."""
        try:
            self.update_idletasks()
            need = 0
            for w in self._side.winfo_children():
                pad = w.pack_info().get("pady", 0)
                pad = sum(int(x) for x in (pad if isinstance(pad, (tuple, list)) else (pad,)))
                need += w.winfo_reqheight() + pad
            need += self.status.master.winfo_reqheight()
            if hasattr(self, "_reverse_window_scaling"):
                need = self._reverse_window_scaling(need)
            self.minsize(1050, max(650, int(need) + 12))
        except Exception:
            pass

    # ------------------------------------------------------------------ helpers
    def set_status(self, text):
        self.status.configure(text=text)

    def _set_theme(self, mode):
        ctk.set_appearance_mode(mode)
        self.settings["appearance"] = mode

    def _lang_changed(self, _e=None):
        """Apply the language in the box. Returns True if it is usable (and now active).

        Stored OCR is only thrown away when the language really changed, and an invalid
        language (typo / not installed) is rejected instead of silently breaking OCR.
        """
        if self._lang_busy:
            return False
        new = "+".join(p.strip() for p in (self.lang.get() or "").split("+") if p.strip()) or "eng"
        if new == self._lang_applied:
            if self.lang.get() != new:
                self.lang.set(new)
            return True
        self._lang_busy = True
        try:
            old = self._lang_applied
            if self.busy:
                self.lang.set(old)
                self.set_status("Wait for the current task to finish before changing language.")
                return False
            if self._known_langs is not None:
                bad = [p for p in new.split("+") if p not in self._known_langs]
                if bad:
                    self.lang.set(old)
                    self.set_status(f"Language “{', '.join(bad)}” is not installed — keeping “{old}”.")
                    return False
            n_edit = sum(it.edited for it in self.items)
            if n_edit and not messagebox.askyesno(
                    "Change language?",
                    f"Changing the language discards the text of all pages, including your "
                    f"corrections on {n_edit} page(s). Continue?"):
                self.lang.set(old)
                return False
            self._lang_applied = new
            self.lang.set(new)
            for it in self.items:          # previous OCR belongs to the old language
                it.reset_ocr()
            self.render_grid()
            self.set_status(f"OCR language set to “{new}”. Run “Read text” again.")
            return True
        finally:
            self._lang_busy = False

    def _warn_no_ocr(self):
        messagebox.showwarning(
            "OCR engine not found",
            "Tesseract OCR was not found.\n\nYou can still arrange images and make a "
            "plain PDF, but reading text, auto-ordering and searchable PDFs need it.\n\n"
            "Install Tesseract (Windows: github.com/UB-Mannheim/tesseract/wiki) "
            "or use the installer version of this app, which includes it.")

    def _set_busy(self, busy):
        """While OCR / PDF export runs the page list must not change: the worker thread is
        reading and writing the same PageItems (rotating mid-OCR would attach text for the
        old orientation; rotating mid-export would change the page being built)."""
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_ocr, self.btn_order, self.btn_pdf, self.btn_txt,
                  self.btn_add, self.btn_folder):
            b.configure(state=state)
        for c in self._cards.values():
            self._set_card_buttons(c, state)
        self._update_undo_state()
        if busy:
            self.cancel_evt.clear()
            self.btn_cancel.grid()
        else:
            self.btn_cancel.grid_remove()

    @staticmethod
    def _set_card_buttons(card, state):
        for b in card.buttons:
            b.configure(state=state)

    def _blocked(self):
        """True (with a hint) when a page-changing action must wait for the running task."""
        if self.busy:
            self.set_status("Please wait for the current task to finish (or press Cancel) "
                            "before changing the pages.")
        return self.busy

    # ------------------------------------------------------------------ undo
    def _index_of(self, it):
        for i, x in enumerate(self.items):
            if x is it:
                return i
        return None

    def _push_undo(self):
        """Remember the current page list (order + which pages exist) before changing it.
        Page contents (rotation, OCR text, edits) are deliberately not rolled back."""
        snap = (list(self.items), self.items[self.sel] if self.sel is not None
                and self.sel < len(self.items) else None)
        if self._undo and len(self._undo[-1][0]) == len(snap[0]) and all(
                a is b for a, b in zip(self._undo[-1][0], snap[0])):
            return                                   # nothing changed since the last snapshot
        self._undo.append(snap)
        del self._undo[:-UNDO_LIMIT]
        self._update_undo_state()

    def _update_undo_state(self):
        self.btn_undo.configure(state="normal" if self._undo and not self.busy else "disabled")

    def undo(self):
        if self._blocked() or not self._undo:
            return
        self._commit_text()
        items, sel_item = self._undo.pop()
        self.items = items
        self.sel = self._index_of(sel_item) if sel_item is not None else None
        self._update_undo_state()
        self.render_grid()
        self.set_status("Undone: previous page order restored.")

    def _on_undo_key(self, _e=None):
        if self._typing_in_input():      # let the text box / language box handle its own Ctrl+Z
            return
        self.undo()

    # ------------------------------------------------------------------ adding
    @staticmethod
    def _norm(p):
        return paths.norm_path(p)

    def _add_paths(self, plist, scanning=False):
        """Add images. Multi-page TIFFs become one card per page. Anything skipped is
        reported (`scanning` = the paths came from a folder listing, so junk like
        Thumbs.db is ignored quietly)."""
        if self._blocked():
            return
        have = {(self._norm(it.path), it.frame) for it in self.items}
        unsupported, missing, dups, cands = [], [], [], []
        for p in plist:
            name = os.path.basename(p)
            if os.path.isdir(p):
                continue
            if not os.path.isfile(p):
                missing.append(name)
            elif not p.lower().endswith(IMAGE_TYPES):
                if not (scanning and name.lower() in IGNORED_NAMES):
                    unsupported.append(name)
            else:
                cands.append(p)
        new = []
        for p in sorted(cands, key=natural_key):
            n = count_frames(p)
            added = False
            for fr in range(n):
                key = (self._norm(p), fr)
                if key in have:
                    continue
                have.add(key)
                new.append(PageItem(os.path.normpath(p), frame=fr, frames=n))
                added = True
            if not added:
                dups.append(os.path.basename(p))
        if new:
            self._push_undo()
            self.items.extend(new)
            self.settings["last_dir"] = os.path.dirname(new[0].path)
            self.render_grid()

        skipped = len(unsupported) + len(missing) + len(dups)
        if new:
            note = f" ({skipped} file(s) skipped)" if skipped else ""
            self.set_status(f"Added {len(new)} page(s){note}. Next: Read text (OCR) → Auto-order.")
        elif dups and not (unsupported or missing):
            self.set_status(f"Nothing new: {len(dups)} file(s) were already added.")
        if unsupported or missing or not new:
            self._report_skipped(unsupported, missing, dups, bool(new))

    @staticmethod
    def _name_list(names, limit=8):
        shown = "\n".join("   • " + n for n in names[:limit])
        return shown + (f"\n   …and {len(names) - limit} more" if len(names) > limit else "")

    def _report_skipped(self, unsupported, missing, dups, some_added):
        parts = []
        if unsupported:
            parts.append(f"Unsupported file type ({len(unsupported)}):\n{self._name_list(unsupported)}")
        if missing:
            parts.append(f"Not found / not a file ({len(missing)}):\n{self._name_list(missing)}")
        if dups:
            parts.append(f"Already in the list ({len(dups)}):\n{self._name_list(dups)}")
        if not parts:
            return
        head = "Some files were not added." if some_added else "No pages were added."
        tail = ("\n\nSupported: PNG, JPG, TIFF (multi-page too), BMP, WebP.\n"
                "HEIC, GIF and PDF files must be converted to JPG/PNG first.") if unsupported else ""
        messagebox.showinfo("Files skipped", head + "\n\n" + "\n\n".join(parts) + tail)

    def add_images(self):
        if self._blocked():
            return
        files = filedialog.askopenfilenames(
            title="Select images", initialdir=self.settings.get("last_dir") or None,
            filetypes=[("Images", " ".join("*" + e for e in IMAGE_TYPES)), ("All files", "*.*")])
        if files:
            self._add_paths(files)

    def add_folder(self):
        if self._blocked():
            return
        d = filedialog.askdirectory(title="Select a folder of images",
                                    initialdir=self.settings.get("last_dir") or None)
        if d:
            self._add_paths([os.path.join(d, f) for f in os.listdir(d)], scanning=True)

    def _on_drop(self, event):
        if self._blocked():
            return
        files = self.tk.splitlist(event.data)
        flat, scanning = [], False
        for f in files:
            if os.path.isdir(f):
                scanning = True
                flat += [os.path.join(f, x) for x in os.listdir(f)]
            else:
                flat.append(f)
        self._add_paths(flat, scanning=scanning)

    # ------------------------------------------------------------------ grid
    def _thumb(self, it):
        """CTkImage of the page's thumbnail, rotated as needed. The decoded thumbnail is
        cached on the item; rotation is applied on the fly (never needs a re-decode)."""
        if it._thumb is None:
            try:
                with Image.open(it.path) as img:
                    if it.frame:
                        img.seek(it.frame)
                    img.draft("RGB", (THUMB[0] * 2, THUMB[1] * 2))
                    img = ImageOps.exif_transpose(img).convert("RGB")
                    img.thumbnail((THUMB[0] * 2, THUMB[1] * 2))
                    it._thumb = img
            except Exception:
                it._thumb = Image.new("RGB", THUMB, "gray")
        img = it._thumb
        if it.rotation:
            img = img.rotate(-it.rotation, expand=True)
        img = img.copy()
        img.thumbnail(THUMB)
        return ctk.CTkImage(light_image=img, dark_image=img, size=img.size)

    def _on_resize(self, _e=None):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._maybe_relayout)

    def _maybe_relayout(self):
        cols = self._calc_cols()
        if cols != self._cols:
            self.render_grid()

    def _calc_cols(self):
        w = self.grid_frame.winfo_width()
        return max(1, (w - 20) // (CARD_W + 14)) if w > 50 else 3

    def render_grid(self):
        """Bring the card grid in line with self.items.

        Cards are kept between calls: only pages that were added / removed get a widget
        created / destroyed, and for the rest only what actually changed (position, number,
        badge, border, picture) is touched. Rebuilding every card on each click made the UI
        take ~1 s per click with a few dozen pages.
        """
        live = {it.uid for it in self.items}
        for uid in [u for u in self._cards if u not in live]:
            card = self._cards.pop(uid)
            self._card_of.pop(card.frame, None)
            card.frame.destroy()
        n = len(self.items)
        text = f"Pages ({n})" if n else "Pages"
        if self.lbl_count.cget("text") != text:
            self.lbl_count.configure(text=text)
        if n == 0:
            self.sel = None
            self.empty_lbl.pack(expand=True, pady=80)
            self._show_selected()
            return
        self.empty_lbl.pack_forget()
        self._cols = self._calc_cols()
        if self.sel is not None and self.sel >= n:
            self.sel = n - 1
        for i, it in enumerate(self.items):
            card = self._cards.get(it.uid) or self._make_card(it)
            self._update_card(card, i, it)
        self._show_selected()

    def _make_card(self, it):
        """Create the (empty) widgets for one page; _update_card fills them in."""
        c = _Card()
        c.frame = ctk.CTkFrame(self.grid_frame, width=CARD_W, border_width=1,
                               border_color=("gray70", "gray35"))
        c.img = ctk.CTkLabel(c.frame, text="")
        c.img.pack(padx=8, pady=(8, 2))
        c.title = ctk.CTkLabel(c.frame, text="", font=ctk.CTkFont(size=12, weight="bold"))
        c.title.pack()
        c.badge = ctk.CTkLabel(c.frame, text="", font=ctk.CTkFont(size=11))
        c.badge.pack(pady=(0, 2))
        row = ctk.CTkFrame(c.frame, fg_color="transparent")
        row.pack(pady=(0, 8))
        # buttons act on the page itself (not a list position), so cards stay valid when
        # other pages are moved around
        state = "disabled" if self.busy else "normal"
        for sym, cmd in (("◀", lambda it=it: self.move_item(self._index_of(it), -1)),
                         ("⟳", lambda it=it: self.rotate_item(self._index_of(it))),
                         ("✕", lambda it=it: self.remove_item(self._index_of(it))),
                         ("▶", lambda it=it: self.move_item(self._index_of(it), 1))):
            b = ctk.CTkButton(row, text=sym, width=30, height=26, command=cmd, state=state,
                              fg_color=("gray75", "gray30"), text_color=("black", "white"),
                              hover_color=("gray65", "gray40"))
            b.pack(side="left", padx=2)
            c.buttons.append(b)
        self._cards[it.uid] = c
        self._card_of[c.frame] = it
        for w in (c.frame, c.img, c.title, c.badge):
            w.bind("<ButtonPress-1>", lambda e, it=it: self._press(it, e))
            w.bind("<B1-Motion>", self._motion)
            w.bind("<ButtonRelease-1>", self._release)
        return c

    def _update_card(self, c, i, it):
        pos = (i // self._cols, i % self._cols)
        if c.pos != pos:
            c.frame.grid(row=pos[0], column=pos[1], padx=7, pady=7, sticky="n")
            c.pos = pos
        if c.rot != it.rotation or c.rot is None:
            image = self._thumb(it)
            c.img.configure(image=image)
            c.rot = it.rotation
        suffix = f" [{it.frame + 1}/{it.frames}]" if it.frames > 1 else ""
        name = self._short(os.path.basename(it.path), max(6, 17 - len(suffix))) + suffix
        title = f"{i + 1}.  {name}"
        if c.title_txt != title:
            c.title.configure(text=title)
            c.title_txt = title
        if it.error:
            badge = ("cannot read image", "#c0392b")
        elif it.text is None:
            badge = ("text not read", ("gray45", "gray60"))
        elif it.page_no is None:
            badge = ("no page number found", WARN)
        else:
            badge = (f"detected page {it.page_no}", GOOD)
        if c.badge_key != badge:
            c.badge.configure(text=badge[0], text_color=badge[1])
            c.badge_key = badge
        selected = i == self.sel
        if c.selected != selected:
            c.frame.configure(border_width=3 if selected else 1,
                              border_color=ACCENT if selected else ("gray70", "gray35"))
            c.selected = selected

    @staticmethod
    def _short(name, n=17):
        """Shorten in the middle so the distinguishing end (IMG_0042.jpg) stays visible."""
        if len(name) <= n:
            return name
        keep = n - 1
        head = keep // 2
        return name[:head] + "…" + name[len(name) - (keep - head):]

    # drag to reorder
    def _press(self, it, e):
        self._commit_text()
        self.focus_set()
        self._drag = {"src": it, "x": e.x_root, "y": e.y_root, "moved": False}

    def _motion(self, e):
        d = self._drag
        if d and (abs(e.x_root - d["x"]) > 8 or abs(e.y_root - d["y"]) > 8):
            d["moved"] = True
            self.configure(cursor="fleur")

    def _release(self, e):
        d, self._drag = self._drag, None
        self.configure(cursor="")
        if not d:
            return
        src = self._index_of(d["src"])
        if src is None:
            return
        if not d["moved"]:
            self.select(src)
            return
        if self._blocked():
            return
        w = self.winfo_containing(e.x_root, e.y_root)
        dst = None
        while w is not None:
            if w in self._card_of:
                dst = self._index_of(self._card_of[w])
                break
            w = getattr(w, "master", None)
        if dst is not None and dst != src:
            self._push_undo()
            self.items.insert(dst, self.items.pop(src))
            self.sel = dst
            self.render_grid()

    # ------------------------------------------------------------------ item ops
    def select(self, i):
        if i is None or not 0 <= i < len(self.items):
            return
        self.sel = i
        self.render_grid()

    def move_item(self, i, delta):
        if i is None or self._blocked():
            return
        j = i + delta
        if 0 <= j < len(self.items):
            self._push_undo()
            self.items[i], self.items[j] = self.items[j], self.items[i]
            self.sel = j
            self.render_grid()

    def rotate_item(self, i):
        if i is None or self._blocked():
            return
        it = self.items[i]
        it.rotation = (it.rotation + 90) % 360
        it.reset_ocr()
        self.sel = i
        self.render_grid()

    def remove_item(self, i):
        if i is None or self._blocked():
            return
        self._push_undo()
        del self.items[i]
        self.sel = None if not self.items else min(i, len(self.items) - 1)
        self.render_grid()
        self.set_status(f"Page removed. {len(self.items)} page(s) left. (Ctrl+Z to undo)")

    def remove_selected(self):
        if self.sel is not None and not self.busy:
            self.remove_item(self.sel)

    def _typing_in_input(self):
        """True when keyboard focus is in a text/entry/combobox widget."""
        try:
            w = self.focus_get()
        except Exception:      # e.g. KeyError for combobox popdown windows
            return True
        return isinstance(w, (tk.Text, tk.Entry, ttk.Entry, ttk.Combobox))

    def _on_delete_key(self, _e=None):
        # <Delete> is bound on the root window, so it also fires while typing in the
        # text box / language box; only act on pages when focus is NOT in an input.
        if self._typing_in_input():
            return
        self.remove_selected()

    # ------------------------------------------------------------------ edited text
    def _commit_text(self, _e=None):
        """Store what is in the Recognised-text box back into its page."""
        it = self._text_item
        if it is None or it.text is None:
            return
        try:
            new = self.textbox.get("1.0", "end-1c")
        except Exception:
            return
        if new != it.text:
            it.text = new
            it.edited = True

    def _set_preview(self, image, text):
        """Show an image (or just text) in the preview label without leaving a stale image.

        CTkLabel.configure(image=None) leaves the previous Tk image attached; once that
        CTkImage is garbage-collected Tk raises 'image "pyimageN" doesn't exist'.
        """
        self.preview.configure(image=image or self._blank_img, text=text)
        self._preview_img = image          # keep a reference while it is displayed

    def _show_selected(self):
        """Show the selected page in the preview + text box. The (slow) image decode and the
        text box are only refreshed when the page, its rotation or its text state changed,
        so merely moving or re-selecting cards does not redo them."""
        self._commit_text()                # save edits to the page we are leaving
        if self.sel is None or self.sel >= len(self.items):
            self._text_item = None
            self._preview_key = self._text_key = None
            self.textbox.configure(state="normal")
            self.textbox.delete("1.0", "end")
            self._set_preview(None, "No page selected")
            self.info.configure(text="")
            self.textbox.configure(state="disabled")
            return
        it = self.items[self.sel]
        pn = "—" if it.page_no is None else it.page_no
        self.info.configure(text=f"{it.label}\nPosition {self.sel + 1} of "
                                 f"{len(self.items)}   •   Detected page number: {pn}")
        pkey = (it.uid, it.rotation)
        if pkey != self._preview_key:
            self._preview_key = pkey
            try:
                img = load_item(it)
                img.thumbnail((312, 330))
                self._set_preview(ctk.CTkImage(light_image=img, dark_image=img, size=img.size), "")
            except Exception as ex:
                self._set_preview(None, f"Cannot open image\n{ex}")
        tkey = (it.uid, it.rotation, it.text is None, it.error)
        if tkey == self._text_key:
            return                         # text box already shows this page (keep the cursor)
        self._text_key = tkey
        self._text_item = None
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        if it.error:
            self.textbox.insert("1.0", f"(this image could not be read)\n\n{it.error}")
            self.textbox.configure(state="disabled")
        elif it.text is None:
            # nothing to edit yet: show a hint and lock the box so it can't be "edited" and lost
            self.textbox.insert("1.0", "(text not read yet — click “Read text”)")
            self.textbox.configure(state="disabled")
        else:
            self.textbox.insert("1.0", it.text)
            self._text_item = it           # editable; _commit_text writes changes back

    # ------------------------------------------------------------------ OCR / order
    def _need_ocr(self):
        if not self.have_ocr:
            self._warn_no_ocr()
            return False
        if not self.items:
            messagebox.showinfo("No images", "Add some images first.")
            return False
        return True

    def run_ocr(self):
        if self._blocked() or not self._need_ocr() or not self._lang_changed():
            return
        self._commit_text()
        todo = [it for it in self.items if it.text is None]
        if not todo:
            self.set_status("All pages are already read.")
            if self._pending_order:
                self._pending_order = False
                self._apply_order()
            return
        self._start(self._ocr_worker, todo, self._lang_applied, self.sw_rot.get() == 1)

    def _ocr_worker(self, todo, lang, auto_rot):
        total, failed = len(todo), []
        try:
            for n, it in enumerate(todo, 1):
                if self.cancel_evt.is_set():
                    raise Cancelled()
                try:
                    img = load_item(it)
                    if auto_rot:
                        fix = ocr.detect_rotation(img)
                        if fix:
                            it.rotation = (it.rotation + fix) % 360
                            img = load_item(it)
                    it.text, it.page_no, it.text_layer = ocr.read_page_full(img, lang)
                    it.error = None
                except Cancelled:
                    raise
                except Exception as ex:      # skip this page, keep going
                    it.text, it.page_no, it.text_layer = "", None, None
                    it.error = f"{type(ex).__name__}: {ex}"
                    failed.append((it.label, it.error))
                self.q.put(("progress", n, total, f"Reading text {n}/{total}: {it.label}"))
            self.q.put(("ocr_done", failed, total))
        except Cancelled:
            self.q.put(("cancelled",))
        except Exception as ex:
            self.q.put(("error", str(ex)))

    def auto_order(self):
        if self._blocked() or not self.items:
            return
        if self.have_ocr and any(it.text is None for it in self.items):
            self._pending_order = True
            self.run_ocr()
            return
        self._apply_order()

    def _apply_order(self):
        sel_item = self.items[self.sel] if self.sel is not None else None
        ordered, method = order_pages(self.items)
        changed = any(a is not b for a, b in zip(ordered, self.items))
        if not changed:
            self.set_status("Pages are already in the right order. ✔" if method == "pages"
                            else "Order unchanged (not enough page numbers to do better).")
            return
        # Without (enough) page numbers the order comes from FILE NAMES, which throws away
        # any arrangement the user made by hand: ask first.
        if method != "pages" and not messagebox.askyesno(
                "Replace your page order?",
                "Page numbers were not found on every page, so the pages would be arranged "
                "by file name — this replaces the order you have now.\n\n"
                "(You can undo this with Ctrl+Z.)\n\nContinue?"):
            self.set_status("Auto-order cancelled — your order was not changed.")
            return
        self._push_undo()
        self.items = ordered
        if sel_item is not None:
            self.sel = self._index_of(sel_item)
        self.render_grid()
        n = sum(it.page_no is not None for it in self.items)
        undo = "  (Ctrl+Z to undo)"
        if method == "pages":
            self.set_status("Ordered by the page numbers found in the images. ✔" + undo)
        elif method == "mixed":
            self.set_status(f"Page numbers found on {n}/{len(self.items)} images; the others "
                            "(orange) kept their file-name position — please check them." + undo)
        else:
            self.set_status("Not enough page numbers found — ordered by file name. "
                            "Adjust by dragging cards." + undo)

    def export_text(self):
        if self._blocked() or not self.items:
            return
        self._commit_text()
        if any(it.text is None for it in self.items):
            messagebox.showinfo("Read text first", "Run “Read text (OCR)” before exporting.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="text.txt",
                                           initialdir=self.settings.get("last_dir") or None,
                                           filetypes=[("Text file", "*.txt")])
        if not out:
            return
        tmp = out + ".tmp"
        try:
            # write next to the target, then swap in, so a failure never leaves a half file
            with open(tmp, "w", encoding="utf-8") as f:
                for i, it in enumerate(self.items, 1):
                    body = f"[could not be read: {it.error}]" if it.error else (it.text or "").strip()
                    f.write(f"===== Page {i}  ({it.label}) =====\n{body}\n\n")
            os.replace(tmp, out)
        except Exception as ex:      # the windowed .exe has no console: always tell the user
            self.set_status("Could not save the text file.")
            messagebox.showerror(
                "Could not save text",
                f"The text could not be saved to:\n{out}\n\n"
                "Check that the folder exists and is writable, and that the file is not open "
                f"in another program.\n\n({type(ex).__name__}: {ex})")
            return
        finally:
            if os.path.exists(tmp):          # never leave name.txt.tmp behind
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        self.set_status(f"Text saved: {out}")

    # ------------------------------------------------------------------ PDF
    def create_pdf(self):
        if self._blocked():
            return
        self._commit_text()
        if not self.items:
            messagebox.showinfo("No images", "Add some images first.")
            return
        if not self._lang_changed():
            return
        searchable = self.sw_search.get() == 1
        if searchable and not self.have_ocr:
            if not messagebox.askyesno("OCR engine missing",
                                       "Searchable text needs Tesseract.\nCreate a plain image PDF instead?"):
                return
            searchable = False
        out = filedialog.asksaveasfilename(
            title="Save PDF as", defaultextension=".pdf", initialfile="document.pdf",
            initialdir=self.settings.get("last_dir") or None, filetypes=[("PDF", "*.pdf")])
        if not out:
            return
        self._start(self._pdf_worker, list(self.items), out, searchable,
                    self._lang_applied, self.page_mode.get())

    def _pdf_worker(self, items, out, searchable, lang, page_mode):
        try:
            skipped = build_pdf(items, out, searchable=searchable, lang=lang, page_mode=page_mode,
                                progress=lambda n, t, m: self.q.put(("progress", n, t, m)),
                                cancel=self.cancel_evt,
                                title=os.path.splitext(os.path.basename(out))[0])
            self.q.put(("pdf_done", out, [(it.label, why) for it, why in skipped]))
        except Cancelled:
            self.q.put(("cancelled",))
        except Exception as ex:
            self.q.put(("error", str(ex)))

    # ------------------------------------------------------------------ threads
    def _start(self, target, *args):
        self._set_busy(True)
        self.progress.set(0)
        threading.Thread(target=target, args=args, daemon=True).start()

    def _poll(self):
        try:
            while True:
                try:
                    msg = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_msg(msg)
                except Exception as ex:      # never let one bad message kill the loop
                    traceback.print_exc()
                    self._set_busy(False)
                    self._pending_order = False
                    try:
                        self.set_status(f"Error: {ex}")
                    except Exception:
                        pass
        finally:
            self.after(100, self._poll)

    def _handle_msg(self, msg):
        kind = msg[0]
        if kind == "progress":
            self.progress.set(msg[1] / msg[2])
            self.set_status(msg[3])
        elif kind == "ocr_done":
            self._set_busy(False)          # first, so the UI is usable whatever happens next
            self.progress.set(1)
            found = sum(it.page_no is not None for it in self.items)
            failed = msg[1] if len(msg) > 1 else []
            if failed:
                self.set_status(f"{len(failed)} page(s) could not be read (red badge); the rest are done.")
            else:
                self.set_status(f"Text read. Page numbers found on {found}/{len(self.items)} images.")
            self.render_grid()             # also picks up rotations changed by auto-fix
            if failed:
                head = ("None of the pages could be read:" if len(failed) == msg[2]
                        else f"{len(failed)} page(s) could not be read and were skipped:")
                messagebox.showwarning("Some pages could not be read", head + "\n\n" + "\n".join(
                    f"• {n}: {why}" for n, why in failed[:8])
                    + (f"\n…and {len(failed) - 8} more" if len(failed) > 8 else ""))
            if self._pending_order:
                self._pending_order = False
                self._apply_order()
        elif kind == "pdf_done":
            self._set_busy(False)
            self.progress.set(1)
            self.set_status(f"Saved: {msg[1]}")
            skipped = msg[2] if len(msg) > 2 else []
            note = ""
            if skipped:
                note = (f"\n\n⚠ {len(skipped)} page(s) were LEFT OUT because the image could not be read:\n"
                        + "\n".join(f"• {n}" for n, _ in skipped[:8])
                        + (f"\n…and {len(skipped) - 8} more" if len(skipped) > 8 else ""))
            if messagebox.askyesno("PDF created", f"Saved:\n{msg[1]}{note}\n\nOpen it now?"):
                self._open(msg[1])
        elif kind == "cancelled":
            self._set_busy(False)
            self._pending_order = False
            self.progress.set(0)
            self.set_status("Cancelled.")
        elif kind == "error":
            self._set_busy(False)
            self._pending_order = False
            self.set_status("Error.")
            messagebox.showerror("Error", msg[1])

    @staticmethod
    def _open(path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def _on_close(self):
        self.settings.update(language=self._lang_applied, searchable=self.sw_search.get() == 1,
                             page_mode=self.page_mode.get(), auto_rotate=self.sw_rot.get() == 1)
        paths.save_settings(self.settings)
        self.destroy()
