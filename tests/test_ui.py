"""GUI behaviour tests. Skipped automatically where Tk / a display is unavailable."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from PIL import Image, ImageDraw

pytest.importorskip("customtkinter")
tk = pytest.importorskip("tkinter")
from tkinter import filedialog, messagebox


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))          # don't touch real settings
    import ui.app as A
    try:
        a = A.App()
    except tk.TclError:
        pytest.skip("no display available")
    a.withdraw()
    answers = {"yes": True}
    monkeypatch.setattr(messagebox, "askyesno", lambda *x, **k: answers["yes"])
    monkeypatch.setattr(messagebox, "showinfo", lambda *x, **k: None)
    monkeypatch.setattr(messagebox, "showwarning", lambda *x, **k: None)
    a.answers = answers
    a.errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *x, **k: a.errors.append(x))
    yield a
    a.destroy()


def _pages(folder, n):
    out = []
    for i in range(n):
        p = os.path.join(folder, f"p{i + 1:02d}.png")
        im = Image.new("RGB", (600, 800), "white")
        ImageDraw.Draw(im).text((20, 20), f"page {i + 1}", fill="black")
        im.save(p); out.append(p)
    return out


def _wait(app, cond, t=60):
    end = time.time() + t
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_cards_are_reused_not_rebuilt(app, tmp_path):
    app._add_paths(_pages(str(tmp_path), 5))
    frames = {it.uid: app._cards[it.uid].frame for it in app.items}
    app.select(2); app.move_item(2, 1); app.rotate_item(0)
    assert all(app._cards[it.uid].frame is frames[it.uid] for it in app.items)
    assert [app._cards[it.uid].title_txt.split(".")[0] for it in app.items] == list("12345")


def test_same_file_is_not_added_twice(app, tmp_path):
    p = _pages(str(tmp_path), 1)[0]
    app._add_paths([p]); app._add_paths([os.path.join(str(tmp_path), ".", os.path.basename(p))])
    assert len(app.items) == 1


def test_pages_locked_while_task_runs(app, tmp_path):
    app._add_paths(_pages(str(tmp_path), 3))
    app._set_busy(True)                       # what starting OCR / export does
    ids = [it.uid for it in app.items]
    app.rotate_item(0); app.move_item(0, 1); app.remove_item(1); app.undo()
    app._add_paths(_pages(str(tmp_path), 4))
    assert [it.uid for it in app.items] == ids and app.items[0].rotation == 0
    assert all(str(b.cget("state")) == "disabled" for c in app._cards.values() for b in c.buttons)
    app._set_busy(False)
    app.rotate_item(0)
    assert app.items[0].rotation == 90


def test_undo_restores_order_and_removed_pages(app, tmp_path):
    app._add_paths(_pages(str(tmp_path), 4))
    before = list(app.items)
    app.move_item(0, 1); app.remove_item(0)
    assert len(app.items) == 3
    app.undo(); app.undo()
    assert len(app.items) == 4 and all(a is b for a, b in zip(app.items, before))


def test_auto_order_by_names_asks_and_can_be_undone(app, tmp_path):
    app._add_paths(_pages(str(tmp_path), 4))
    for it in app.items:
        it.text, it.page_no = "x", None                  # OCR found no page numbers
    app.items.reverse(); app.render_grid()
    manual = list(app.items)
    app.answers["yes"] = False
    app.auto_order()
    assert all(a is b for a, b in zip(app.items, manual))          # declined: untouched
    app.answers["yes"] = True
    app.auto_order()
    assert [os.path.basename(i.path) for i in app.items] == sorted(os.path.basename(i.path) for i in manual)
    app.undo()
    assert all(a is b for a, b in zip(app.items, manual))


def test_export_text_reports_write_failure(app, tmp_path, monkeypatch):
    app._add_paths(_pages(str(tmp_path), 2))
    for it in app.items:
        it.text = "hello"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **k: str(tmp_path / "nope" / "t.txt"))
    app.export_text()
    assert len(app.errors) == 1 and "Could not save" in app.status.cget("text")
    good = tmp_path / "t.txt"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **k: str(good))
    app.export_text()
    assert "hello" in good.read_text(encoding="utf-8") and not (tmp_path / "t.txt.tmp").exists()


def test_status_updates_after_remove(app, tmp_path):
    app._add_paths(_pages(str(tmp_path), 3))
    assert "Added 3" in app.status.cget("text")
    app.remove_item(0)
    assert "Added" not in app.status.cget("text")
    assert "2 page(s) left" in app.status.cget("text")


def test_long_names_stay_distinguishable(app):
    a = app._short("DSC_20240101_123456_0042.jpg")
    b = app._short("DSC_20240101_123456_0043.jpg")
    assert a != b and len(a) <= 17 and a.endswith("0042.jpg")
    assert app._short("short.png") == "short.png"


def test_rotate_updates_item_and_clears_ocr(app, tmp_path):
    app._add_paths(_pages(str(tmp_path), 2))
    app.items[0].text = "x"
    app.rotate_item(0)
    assert app.items[0].rotation == 90 and app.items[0].text is None
    for _ in range(3):
        app.rotate_item(0)
    assert app.items[0].rotation == 0


def test_heading_sits_directly_above_text_box(app):
    import customtkinter as ctk
    heads = [w for w in app.textbox.master.winfo_children()
             if isinstance(w, ctk.CTkLabel) and "Recognised" in w.cget("text")]
    assert heads, "heading not found"
    assert int(heads[0].grid_info()["row"]) + 1 == int(app.textbox.grid_info()["row"])
