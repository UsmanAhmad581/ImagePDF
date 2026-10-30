"""Main window (customtkinter)."""
import os
import queue
import subprocess
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from core import ocr, paths
from core.models import PageItem
from core.pagenum import natural_key, order_pages
from core.pdfbuilder import Cancelled, build_pdf, load_image

try:  # optional: drag files from Explorer onto the window
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BASES = (ctk.CTk, TkinterDnD.DnDWrapper)
    HAVE_DND = True
except Exception:  # pragma: no cover
    _BASES = (ctk.CTk,)
    HAVE_DND = False

IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
CARD_W, THUMB = 170, (150, 190)
ACCENT = "#2f7de1"
GOOD, WARN = "#2e9e5b", "#d98e04"


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
        self._card_of = {}
        self._preview_img = None
        self._resize_job = None

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
        self.bind("<Delete>", lambda e: self.remove_selected())
        self.bind("<Control-o>", lambda e: self.add_images())
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
        ctk.CTkLabel(side, text="Image → PDF", font=ctk.CTkFont(size=24, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(22, 0))
        ctk.CTkLabel(side, text="Read text, order pages, export PDF",
                     text_color=("gray40", "gray65")).pack(anchor="w", padx=20, pady=(0, 14))

        def btn(text, cmd, **kw):
            b = ctk.CTkButton(side, text=text, command=cmd, anchor="w", height=36, **kw)
            b.pack(fill="x", padx=16, pady=4)
            return b

        btn("＋  Add images…", self.add_images)
        btn("📁  Add folder…", self.add_folder)
        ctk.CTkLabel(side, text="PROCESS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray40", "gray65")).pack(anchor="w", padx=20, pady=(14, 0))
        self.btn_ocr = btn("🔍  1. Read text (OCR)", self.run_ocr, fg_color="#5a6b82")
        self.btn_order = btn("🔢  2. Auto-order pages", self.auto_order, fg_color="#5a6b82")
        self.btn_txt = btn("📝  Export text (.txt)", self.export_text, fg_color="#5a6b82")

        ctk.CTkLabel(side, text="SETTINGS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray40", "gray65")).pack(anchor="w", padx=20, pady=(14, 0))
        ctk.CTkLabel(side, text="OCR language").pack(anchor="w", padx=20, pady=(4, 0))
        langs = ocr.languages() if self.have_ocr else ["eng"]
        self.lang = ctk.CTkComboBox(side, values=langs, command=lambda v: self._lang_changed())
        self.lang.set(self.settings["language"])
        self.lang.pack(fill="x", padx=16, pady=2)
        ctk.CTkLabel(side, text="PDF page size").pack(anchor="w", padx=20, pady=(6, 0))
        self.page_mode = ctk.CTkOptionMenu(side, values=["Fit to image", "A4 page (white margins)"])
        self.page_mode.set(self.settings["page_mode"])
        self.page_mode.pack(fill="x", padx=16, pady=2)
        self.sw_search = ctk.CTkSwitch(side, text="Searchable text in PDF")
        self.sw_search.pack(anchor="w", padx=20, pady=(10, 2))
        if self.settings["searchable"]:
            self.sw_search.select()
        self.sw_rot = ctk.CTkSwitch(side, text="Auto-fix sideways pages")
        self.sw_rot.pack(anchor="w", padx=20, pady=2)
        if self.settings["auto_rotate"]:
            self.sw_rot.select()
        ctk.CTkLabel(side, text="Theme").pack(anchor="w", padx=20, pady=(8, 0))
        ctk.CTkOptionMenu(side, values=["System", "Light", "Dark"],
                          command=self._set_theme).pack(fill="x", padx=16, pady=2)
        self._theme_menu = side.winfo_children()[-1]
        self._theme_menu.set(self.settings["appearance"])

        self.btn_pdf = ctk.CTkButton(side, text="📄  Create PDF", height=46,
                                     font=ctk.CTkFont(size=15, weight="bold"),
                                     fg_color=GOOD, hover_color="#237a46", command=self.create_pdf)
        self.btn_pdf.pack(side="bottom", fill="x", padx=16, pady=18)

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
        right.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(right, text="Preview", font=ctk.CTkFont(size=16, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        self.preview = ctk.CTkLabel(right, text="No page selected", width=312, height=330,
                                    fg_color=("gray85", "gray20"), corner_radius=8)
        self.preview.grid(row=1, column=0, padx=14, pady=4)
        self.info = ctk.CTkLabel(right, text="", anchor="w", justify="left")
        self.info.grid(row=3, column=0, sticky="ew", padx=14)
        ctk.CTkLabel(right, text="Recognised text", font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=2, column=0, sticky="nw", padx=14, pady=(8, 0))
        self.textbox = ctk.CTkTextbox(right, wrap="word", height=170)
        self.textbox.grid(row=4, column=0, sticky="nsew", padx=14, pady=(2, 14))
        right.grid_rowconfigure(2, weight=0)
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

    # ------------------------------------------------------------------ helpers
    def set_status(self, text):
        self.status.configure(text=text)

    def _set_theme(self, mode):
        ctk.set_appearance_mode(mode)
        self.settings["appearance"] = mode

    def _lang_changed(self):
        # a different language means previous OCR text is stale
        for it in self.items:
            it.reset_ocr()
        self.render_grid()

    def _warn_no_ocr(self):
        messagebox.showwarning(
            "OCR engine not found",
            "Tesseract OCR was not found.\n\nYou can still arrange images and make a "
            "plain PDF, but reading text, auto-ordering and searchable PDFs need it.\n\n"
            "Install Tesseract (Windows: github.com/UB-Mannheim/tesseract/wiki) "
            "or use the installer version of this app, which includes it.")

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_ocr, self.btn_order, self.btn_pdf, self.btn_txt):
            b.configure(state=state)
        if busy:
            self.cancel_evt.clear()
            self.btn_cancel.grid()
        else:
            self.btn_cancel.grid_remove()

    # ------------------------------------------------------------------ adding
    def _add_paths(self, plist):
        have = {it.path for it in self.items}
        new = sorted((p for p in plist if p.lower().endswith(IMAGE_TYPES)
                      and os.path.isfile(p) and p not in have), key=natural_key)
        for p in new:
            self.items.append(PageItem(p))
        if new:
            self.settings["last_dir"] = os.path.dirname(new[0])
            self.render_grid()
            self.set_status(f"Added {len(new)} image(s). Next: Read text (OCR) → Auto-order.")

    def add_images(self):
        files = filedialog.askopenfilenames(
            title="Select images", initialdir=self.settings.get("last_dir") or None,
            filetypes=[("Images", " ".join("*" + e for e in IMAGE_TYPES)), ("All files", "*.*")])
        if files:
            self._add_paths(files)

    def add_folder(self):
        d = filedialog.askdirectory(title="Select a folder of images",
                                    initialdir=self.settings.get("last_dir") or None)
        if d:
            self._add_paths([os.path.join(d, f) for f in os.listdir(d)])

    def _on_drop(self, event):
        files = self.tk.splitlist(event.data)
        flat = []
        for f in files:
            if os.path.isdir(f):
                flat += [os.path.join(f, x) for x in os.listdir(f)]
            else:
                flat.append(f)
        self._add_paths(flat)

    # ------------------------------------------------------------------ grid
    def _thumb(self, it):
        if it._thumb is None:
            try:
                img = Image.open(it.path)
                img.draft("RGB", (THUMB[0] * 2, THUMB[1] * 2))
                from PIL import ImageOps
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
        for w in self.grid_frame.winfo_children():
            if w is not self.empty_lbl:
                w.destroy()
        self.empty_lbl.pack_forget()
        self._card_of = {}
        n = len(self.items)
        self.lbl_count.configure(text=f"Pages ({n})" if n else "Pages")
        if n == 0:
            self.sel = None
            self.empty_lbl.pack(expand=True, pady=80)
            self._show_selected()
            return
        self._cols = self._calc_cols()
        if self.sel is not None and self.sel >= n:
            self.sel = n - 1
        for i, it in enumerate(self.items):
            self._make_card(i, it).grid(row=i // self._cols, column=i % self._cols,
                                        padx=7, pady=7, sticky="n")
        self._show_selected()

    def _make_card(self, i, it):
        selected = i == self.sel
        card = ctk.CTkFrame(self.grid_frame, width=CARD_W, border_width=3 if selected else 1,
                            border_color=ACCENT if selected else ("gray70", "gray35"))
        img = ctk.CTkLabel(card, text="", image=self._thumb(it))
        img.pack(padx=8, pady=(8, 2))
        title = ctk.CTkLabel(card, text=f"{i + 1}.  {self._short(os.path.basename(it.path))}",
                             font=ctk.CTkFont(size=12, weight="bold"))
        title.pack()
        if it.text is None:
            txt, col = "text not read", ("gray45", "gray60")
        elif it.page_no is None:
            txt, col = "no page number found", WARN
        else:
            txt, col = f"detected page {it.page_no}", GOOD
        badge = ctk.CTkLabel(card, text=txt, text_color=col, font=ctk.CTkFont(size=11))
        badge.pack(pady=(0, 2))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(pady=(0, 8))
        for sym, cmd, tip in (("◀", lambda i=i: self.move_item(i, -1), "left"),
                              ("⟳", lambda i=i: self.rotate_item(i), "rotate"),
                              ("✕", lambda i=i: self.remove_item(i), "remove"),
                              ("▶", lambda i=i: self.move_item(i, 1), "right")):
            ctk.CTkButton(row, text=sym, width=30, height=26, command=cmd,
                          fg_color=("gray75", "gray30"), text_color=("black", "white"),
                          hover_color=("gray65", "gray40")).pack(side="left", padx=2)
        self._card_of[card] = i
        for w in (card, img, title, badge):
            w.bind("<ButtonPress-1>", lambda e, i=i: self._press(i, e))
            w.bind("<B1-Motion>", self._motion)
            w.bind("<ButtonRelease-1>", self._release)
        return card

    @staticmethod
    def _short(name, n=17):
        return name if len(name) <= n else name[:n - 1] + "…"

    # drag to reorder
    def _press(self, i, e):
        self._drag = {"src": i, "x": e.x_root, "y": e.y_root, "moved": False}

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
        if not d["moved"]:
            self.select(d["src"])
            return
        w = self.winfo_containing(e.x_root, e.y_root)
        dst = None
        while w is not None:
            if w in self._card_of:
                dst = self._card_of[w]
                break
            w = getattr(w, "master", None)
        if dst is not None and dst != d["src"]:
            self.items.insert(dst, self.items.pop(d["src"]))
            self.sel = dst
            self.render_grid()

    # ------------------------------------------------------------------ item ops
    def select(self, i):
        self.sel = i
        self.render_grid()

    def move_item(self, i, delta):
        j = i + delta
        if 0 <= j < len(self.items):
            self.items[i], self.items[j] = self.items[j], self.items[i]
            self.sel = j
            self.render_grid()

    def rotate_item(self, i):
        it = self.items[i]
        it.rotation = (it.rotation + 90) % 360
        it.reset_ocr()
        self.sel = i
        self.render_grid()

    def remove_item(self, i):
        del self.items[i]
        self.sel = None if not self.items else min(i, len(self.items) - 1)
        self.render_grid()

    def remove_selected(self):
        if self.sel is not None and not self.busy:
            self.remove_item(self.sel)

    def _show_selected(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        if self.sel is None or self.sel >= len(self.items):
            self.preview.configure(image=None, text="No page selected")
            self.info.configure(text="")
            return
        it = self.items[self.sel]
        try:
            img = load_image(it.path, it.rotation)
            img.thumbnail((312, 330))
            self._preview_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self.preview.configure(image=self._preview_img, text="")
        except Exception as ex:
            self.preview.configure(image=None, text=f"Cannot open image\n{ex}")
        pn = "—" if it.page_no is None else it.page_no
        self.info.configure(text=f"{os.path.basename(it.path)}\nPosition {self.sel + 1} of "
                                 f"{len(self.items)}   •   Detected page number: {pn}")
        self.textbox.insert("1.0", it.text if it.text else "(text not read yet — click “Read text”)")

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
        if self.busy or not self._need_ocr():
            return
        todo = [it for it in self.items if it.text is None]
        if not todo:
            self.set_status("All pages are already read.")
            if self._pending_order:
                self._pending_order = False
                self._apply_order()
            return
        self._start(self._ocr_worker, todo, self.lang.get() or "eng", self.sw_rot.get() == 1)

    def _ocr_worker(self, todo, lang, auto_rot):
        total = len(todo)
        try:
            for n, it in enumerate(todo, 1):
                if self.cancel_evt.is_set():
                    raise Cancelled()
                img = load_image(it.path, it.rotation)
                if auto_rot:
                    fix = ocr.detect_rotation(img)
                    if fix:
                        it.rotation = (it.rotation + fix) % 360
                        it._thumb_dirty = True
                        img = load_image(it.path, it.rotation)
                it.text, it.page_no = ocr.read_page(img, lang)
                self.q.put(("progress", n, total, f"Reading text {n}/{total}: "
                            f"{os.path.basename(it.path)}"))
            self.q.put(("ocr_done",))
        except Cancelled:
            self.q.put(("cancelled",))
        except Exception as ex:
            self.q.put(("error", str(ex)))

    def auto_order(self):
        if self.busy or not self.items:
            return
        if self.have_ocr and any(it.text is None for it in self.items):
            self._pending_order = True
            self.run_ocr()
            return
        self._apply_order()

    def _apply_order(self):
        sel_item = self.items[self.sel] if self.sel is not None else None
        self.items, method = order_pages(self.items)
        if sel_item is not None:
            self.sel = self.items.index(sel_item)
        self.render_grid()
        n = sum(it.page_no is not None for it in self.items)
        if method == "pages":
            self.set_status("Ordered by the page numbers found in the images. ✔")
        elif method == "mixed":
            self.set_status(f"Page numbers found on {n}/{len(self.items)} images; the others "
                            "(orange) kept their file-name position — please check them.")
        else:
            self.set_status("Not enough page numbers found — ordered by file name. "
                            "Adjust by dragging cards.")

    def export_text(self):
        if self.busy or not self.items:
            return
        if any(it.text is None for it in self.items):
            messagebox.showinfo("Read text first", "Run “Read text (OCR)” before exporting.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="text.txt",
                                           filetypes=[("Text file", "*.txt")])
        if not out:
            return
        with open(out, "w", encoding="utf-8") as f:
            for i, it in enumerate(self.items, 1):
                f.write(f"===== Page {i}  ({os.path.basename(it.path)}) =====\n{it.text.strip()}\n\n")
        self.set_status(f"Text saved: {out}")

    # ------------------------------------------------------------------ PDF
    def create_pdf(self):
        if self.busy:
            return
        if not self.items:
            messagebox.showinfo("No images", "Add some images first.")
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
                    self.lang.get() or "eng", self.page_mode.get())

    def _pdf_worker(self, items, out, searchable, lang, page_mode):
        try:
            build_pdf(items, out, searchable=searchable, lang=lang, page_mode=page_mode,
                      progress=lambda n, t, m: self.q.put(("progress", n, t, m)),
                      cancel=self.cancel_evt,
                      title=os.path.splitext(os.path.basename(out))[0])
            self.q.put(("pdf_done", out))
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
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    self.progress.set(msg[1] / msg[2])
                    self.set_status(msg[3])
                elif kind == "ocr_done":
                    self._set_busy(False)
                    self.progress.set(1)
                    found = sum(it.page_no is not None for it in self.items)
                    self.set_status(f"Text read. Page numbers found on {found}/{len(self.items)} images.")
                    for it in self.items:          # rotation may have changed
                        it._thumb = None if getattr(it, "_thumb_dirty", False) else it._thumb
                    self.render_grid()
                    if self._pending_order:
                        self._pending_order = False
                        self._apply_order()
                elif kind == "pdf_done":
                    self._set_busy(False)
                    self.progress.set(1)
                    self.set_status(f"Saved: {msg[1]}")
                    if messagebox.askyesno("PDF created", f"Saved:\n{msg[1]}\n\nOpen it now?"):
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
        except queue.Empty:
            pass
        self.after(100, self._poll)

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
        self.settings.update(language=self.lang.get(), searchable=self.sw_search.get() == 1,
                             page_mode=self.page_mode.get(), auto_rotate=self.sw_rot.get() == 1)
        paths.save_settings(self.settings)
        self.destroy()
