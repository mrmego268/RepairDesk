# ATTA RepairDesk Pro – Tkinter (WhatsApp Desktop + Direct Printing Only + Modern UI)
# -----------------------------------------------------------------------------
# - WhatsApp Desktop opens directly (whatsapp://send) + Auto-Send (اختياري)
# - Auto-paste (Clipboard) + Ctrl+V ثم Enter لضمان إرسال النص حتى لو واتساب تجاهل ?text=
# - Direct print ONLY via pywin32 (بدون PDF)
# - اختيار طابعة الملصقات من الإعدادات (مع حفظ)
# - Modern UI (header, cards, theme)
# - Window size/state persist
# - Activity Log
# - تفاصيل السند قابلة للتمرير (سكرول كامل)
# -----------------------------------------------------------------------------

import os, sys, sqlite3, random, string, datetime, json, csv, shutil, logging, re, subprocess, platform, urllib.parse as ul, webbrowser, threading, time
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


def flash_saved(status_bar, win, text="✅ تم حفظ بيانات التكلفة/الدفع", ms=1800):
    """Show a quick toast on the status bar and keep the window visible."""
    try:
        for _w in status_bar.pack_slaves():
            if getattr(_w, "_flash", False):
                _w.destroy()
    except Exception:
        pass
    try:
        lbl = ttk.Label(status_bar, text=text, style="TLabel")
        lbl._flash = True
        lbl.pack(side="right", padx=8)
        win.after(ms, lbl.destroy)
    except Exception:
        pass
    # Ensure the window stays visible and focused
    try:
        win.deiconify()
        win.lift()
        win.focus_force()
        win.attributes("-topmost", True)
        win.after(120, lambda: win.attributes("-topmost", False))
    except Exception:
        pass


# -------------------- Optional deps --------------------
try:
    import qrcode
    from PIL import Image, ImageTk
except Exception:
    qrcode = None
    Image = None
    ImageTk = None

try:
    import bcrypt
except Exception:
    bcrypt = None

# pywin32 for direct print + window automation
try:
    import win32print, win32ui, win32gui, win32api, win32con

    PYWIN32_OK = True
except Exception:
    PYWIN32_OK = False

# NEW: clipboard for reliable paste to WhatsApp
try:
    import win32clipboard as wcb
except Exception:
    wcb = None


# -------------------- PDF (ReportLab) + Arabic shaping (optional) --------------------
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
    )
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import getSampleStyleSheet

    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    ARABIC_OK = True
except Exception:
    ARABIC_OK = False


def ar_text(s):
    """Return Arabic-shaped + bidi-corrected text if libs available, else as-is."""
    if s is None:
        return ""
    t = str(s)
    if ARABIC_OK:
        try:
            return get_display(arabic_reshaper.reshape(t))
        except Exception:
            return t
    return t


def register_ar_font():
    """Try to register a legible Arabic font from common Windows locations. Returns internal font name or None."""
    if not REPORTLAB_OK:
        return None
    candidates = [
        ("Tahoma", r"C:\\Windows\\Fonts\\tahoma.ttf"),
        ("ArialUni", r"C:\\Windows\\Fonts\\arialuni.ttf"),
        ("Arial", r"C:\\Windows\\Fonts\\arial.ttf"),
        ("SegoeUI", r"C:\\Windows\\Fonts\\segoeui.ttf"),
        ("NotoNaskhArabic", r"C:\\Windows\\Fonts\\NotoNaskhArabic-Regular.ttf"),
        ("Amiri", r"C:\\Windows\\Fonts\\Amiri-Regular.ttf"),
    ]
    for name, path in candidates:
        try:
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont("ARFont", path))
                return "ARFont"
        except Exception:
            pass
    return None


# --- Windows HiDPI fix ---
try:
    if platform.system() == "Windows":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

APP_NAME = "ATTA RepairDesk Pro"
MADE_BY = "صنع بواسطة محمد عطا"

DATA_DIR = Path.home() / "Documents" / "RepairDeskDesktop"
DB_PATH = DATA_DIR / "repairdesk.db"
QR_DIR = DATA_DIR / "qr"
EXPORTS_DIR = DATA_DIR / "exports"
BACKUP_DIR = DATA_DIR / "backups"
for d in (DATA_DIR, QR_DIR, EXPORTS_DIR, BACKUP_DIR):
    d.mkdir(parents=True, exist_ok=True)

LOG_PATH = DATA_DIR / "app.log"
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

STATUS_ORDER = [
    "جديد",
    "قيد الفحص",
    "بانتظار الموافقة",
    "قيد الإصلاح",
    "جاهز للاستلام",
    "تم التسليم",
    "ملغي",
]

# Warranty
WARRANTY_DAYS = 30
RIYADH_UTC_OFFSET_HOURS = 3

# ------------------ Status Colors & UI helpers ------------------
STATUS_STYLE = {
    "جديد": ("#9e9e9e", "white"),
    "قيد الفحص": ("#1976d2", "white"),
    "بانتظار الموافقة": ("#f9a825", "black"),
    "قيد الإصلاح": ("#6a1b9a", "white"),
    "جاهز للاستلام": ("#7e57c2", "white"),
    "تم التسليم": ("#2e7d32", "white"),
    "ملغي": ("#c62828", "white"),
}
PRIMARY_COLOR = "#141414"
SURFACE_BG = "#f7f7fb"


def status_colors(status: str):
    return STATUS_STYLE.get(status, ("#9e9e9e", "white"))


def apply_treeview_tag_styles(tree: ttk.Treeview):
    for st, (bg, fg) in STATUS_STYLE.items():
        try:
            tree.tag_configure(st, background=bg, foreground=fg)
        except Exception:
            pass


def make_status_badge(parent, status: str, layout="pack", **kwargs):
    bg, fg = status_colors(status)
    lbl = tk.Label(
        parent, text=f"  {status}  ", bg=bg, fg=fg, font=("Tahoma", 10, "bold")
    )
    if layout == "grid":
        lbl.grid(**kwargs)
    else:
        lbl.pack(**kwargs)
    return lbl


def add_treeview_scrollbars(container: ttk.Frame, tree: ttk.Treeview):
    vsb = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    container.rowconfigure(0, weight=1)
    container.columnconfigure(0, weight=1)


# ---------- Scrollable Frame Helper (عمودي) ----------
def make_vscrollable(parent, bg=SURFACE_BG):
    container = tk.Frame(parent, bg=bg)
    canvas = tk.Canvas(container, bg=bg, highlightthickness=0)
    vbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    vbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = ttk.Frame(canvas, padding=12)
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_config(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    inner.bind("<Configure>", _on_inner_config)

    def _on_canvas_config(event):
        canvas.itemconfig(inner_id, width=event.width)

    canvas.bind("<Configure>", _on_canvas_config)

    def _mw(e):
        if hasattr(e, "delta") and e.delta:
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        else:
            canvas.yview_scroll(-1 if getattr(e, "num", 5) == 4 else 1, "units")

    canvas.bind("<MouseWheel>", _mw)
    canvas.bind("<Button-4>", _mw)
    canvas.bind("<Button-5>", _mw)
    return container, inner


# Warranty helpers
def to_riyadh(dt_utc: datetime.datetime) -> datetime.datetime:
    return dt_utc + datetime.timedelta(hours=RIYADH_UTC_OFFSET_HOURS)


def fmt_dt(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def parse_utc_iso(iso_str: str) -> datetime.datetime:
    try:
        s = (iso_str or "").replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return datetime.datetime.now(datetime.UTC)


SETTINGS_PATH = DATA_DIR / "config.json"
DEFAULT_SETTINGS = {
    "company": "ATTA Repair",
    "currency": "SAR",
    "use_shop_number_for_qr": False,
    "shop_number": "9665XXXXXXXX",
    "label_printer": "",
    "whatsapp_auto_send": True,  # Auto send enabled by default
    "whatsapp_auto_delay_ms": 1200,  # ↑ زودنا الافتراضي لضمان لصق النص
    "wa_fill_via_clipboard": True,
    "wa_press_enter": True,
    "win_prefs": {},
}


# ------------------------- Settings -------------------------
def load_settings():
    if SETTINGS_PATH.exists():
        try:
            d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            d.setdefault("win_prefs", {})
            d.setdefault("label_printer", "")
            d.setdefault("whatsapp_auto_send", True)
            d.setdefault("whatsapp_auto_delay_ms", 1200)
            d.setdefault("wa_fill_via_clipboard", True)
            d.setdefault("wa_press_enter", True)
            return d
        except Exception as e:
            logging.error(f"Failed to read settings: {e}")
    return DEFAULT_SETTINGS.copy()


def save_settings(s):
    try:
        SETTINGS_PATH.write_text(
            json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logging.error(f"Failed to save settings: {e}")


SETTINGS = load_settings()


def get_win_pref(key, default_geometry=None, default_state="normal"):
    prefs = SETTINGS.get("win_prefs", {})
    w = prefs.get(key, {})
    geo = w.get("geometry", default_geometry)
    st = w.get("state", default_state)
    return geo, st


def set_win_pref(key, geometry, state):
    if "win_prefs" not in SETTINGS:
        SETTINGS["win_prefs"] = {}
    SETTINGS["win_prefs"][key] = {"geometry": geometry, "state": state}
    save_settings(SETTINGS)


# ------------------------- DB -------------------------
def db_conn():
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS branches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  branch_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  password TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin'
);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS devices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL,
  type TEXT NOT NULL,
  brand TEXT NOT NULL,
  model TEXT NOT NULL,
  serial_imei TEXT,
  color TEXT,
  accessories TEXT
);
CREATE TABLE IF NOT EXISTS receipts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  branch_id INTEGER NOT NULL,
  customer_id INTEGER NOT NULL,
  device_id INTEGER NOT NULL,
  receipt_no TEXT NOT NULL,
  issue_desc TEXT NOT NULL,
  work_request TEXT NOT NULL,
  est_amount REAL NOT NULL DEFAULT 0,
  approved_amount REAL,
  device_state TEXT,
  status TEXT NOT NULL DEFAULT 'جديد',
  otp_code TEXT NOT NULL,
  whatsapp_link TEXT,
  qr_path TEXT,
  signature_path TEXT,
  created_utc TEXT NOT NULL,
  delivered_utc TEXT
);
CREATE TABLE IF NOT EXISTS status_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  receipt_id INTEGER NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  at_utc TEXT NOT NULL,
  by_username TEXT
);
CREATE TABLE IF NOT EXISTS activity_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  receipt_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  info TEXT,
  at_utc TEXT NOT NULL,
  by_username TEXT
);
"""


def db_migrate():
    """Ensure new payment columns exist on receipts table."""
    con = db_conn()
    cur = con.cursor()
    cur.execute("PRAGMA table_info(receipts)")
    cols = {row[1] for row in cur.fetchall()}
    # approved_amount already in schema, but ensure it exists (older DBs)
    if "approved_amount" not in cols:
        try:
            cur.execute("ALTER TABLE receipts ADD COLUMN approved_amount REAL")
        except Exception:
            pass
    # paid fields
    if "paid_flag" not in cols:
        try:
            cur.execute(
                "ALTER TABLE receipts ADD COLUMN paid_flag INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass
    if "paid_amount" not in cols:
        try:
            cur.execute(
                "ALTER TABLE receipts ADD COLUMN paid_amount REAL NOT NULL DEFAULT 0"
            )
        except Exception:
            pass
    if "paid_utc" not in cols:
        try:
            cur.execute("ALTER TABLE receipts ADD COLUMN paid_utc TEXT")
        except Exception:
            pass
    if "payment_method" not in cols:
        try:
            cur.execute("ALTER TABLE receipts ADD COLUMN payment_method TEXT")
        except Exception:
            pass
    if "device_state" not in cols:
        try:
            cur.execute("ALTER TABLE receipts ADD COLUMN device_state TEXT")
        except Exception:
            pass
    con.commit()
    con.close()


def db_init():
    con = db_conn()
    cur = con.cursor()
    cur.executescript(SCHEMA)
    con.commit()
    # Run migrations to add new columns if missing
    db_migrate()
    cur.execute("SELECT COUNT(*) FROM branches")
    n = cur.fetchone()[0]
    if n == 0:
        cur.execute(
            "INSERT INTO branches(name,code) VALUES(?,?)", ("فرع البوليفارد", "A")
        )
        cur.execute("INSERT INTO branches(name,code) VALUES(?,?)", ("فرع السوق", "B"))
        con.commit()
        cur.execute("SELECT id FROM branches WHERE code='A'")
        b1 = cur.fetchone()[0]
        cur.execute("SELECT id FROM branches WHERE code='B'")
        b2 = cur.fetchone()[0]

        def seed_user(bid, username, pwd):
            if bcrypt:
                ph = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
            else:
                ph = pwd
            cur.execute(
                "INSERT INTO users(branch_id,username,password,role) VALUES(?,?,?,?)",
                (bid, username, ph, "admin"),
            )

        seed_user(b1, "A1", "123")
        seed_user(b2, "A2", "123")
    con.commit()
    con.close()


# ---------------------- Helpers -----------------------
def random_otp(k=6):
    return "".join(random.choice(string.digits) for _ in range(k))


def generate_receipt_no(branch_code: str) -> str:
    con = db_conn()
    cur = con.cursor()
    cur.execute(
        "SELECT receipt_no FROM receipts WHERE receipt_no LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{branch_code}%",),
    )
    row = cur.fetchone()
    con.close()
    seq = 1
    if row and row[0]:
        m = re.search(r"(\d+)$", row[0])
        if m:
            try:
                seq = int(m.group(1)) + 1
            except Exception:
                seq = 1
    return f"{branch_code}{seq:04d}"


def normalize_phone(num: str) -> str:
    digits = "".join(ch for ch in num if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def make_whatsapp_initial_text(
    receipt_no: str,
    device: str,
    issue: str,
    otp: str,
    tracking_hint: str,
    device_state: str | None = None,
) -> str:
    """
    توليد رسالة واتساب احترافية لفتح السند مع تنسيق وأيقونات.
    """
    state_line = f"\n💡 حالة الجهاز: *{device_state}*" if device_state else ""
    return (
        f"📱✨ *مرحبًا بك في متجر {SETTINGS.get('company', 'Memory Corner')}* ✨\n\n"
        f"📄 *تم فتح سند صيانة جديد*\n"
        f"🔢 رقم السند: *{receipt_no}*\n"
        f"📱 الجهاز: *{device}*\n"
        f"⚙️ العطل: *{issue}*"
        f"{state_line}\n"
        f"🔑 رمز الاستلام (OTP): *{otp}*\n\n"
        f"📍 {tracking_hint}\n"
        f"نشكر ثقتك بنا ❤️"
    )


def make_ready_text(receipt_no: str, device: str, otp: str, company: str) -> str:
    return (
        f"السلام عليكم\n"
        f"تم الانتهاء من صيانة جهازك ({device}).\n"
        f"رقم السند: {receipt_no}\n"
        f"رمز الاستلام (OTP): {otp}\n"
        f"يمكنك الاستلام خلال أوقات العمل. — {company}"
    )


def make_delivered_text(receipt_no: str, device: str, company: str) -> str:
    return (
        f"السلام عليكم\n"
        f"تم تسليم جهازك ({device}) بنجاح.\n"
        f"رقم السند: {receipt_no}\n"
        f"شاكرين زيارتكم — {company}"
    )


def make_qr(data: str, filename: str) -> str:
    if qrcode is None:
        return ""
    img = qrcode.make(data)
    path = QR_DIR / filename
    img.save(path)
    return str(path)


def hash_password_if_possible(pw: str) -> str:
    if bcrypt is None:
        return pw
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def password_matches(stored: str, supplied: str) -> bool:
    try:
        if stored and stored.startswith("$2"):
            if bcrypt is None:
                return False
            return bcrypt.checkpw(supplied.encode(), stored.encode())
        return stored == supplied
    except Exception as e:
        logging.error(f"Password check error: {e}")
        return False


# ---------------------- WhatsApp Desktop (+ Auto-Send) ----------------------
# IMPORTANT: نعتمد على لصق النص من الحافظة + Enter لضمان الإرسال حتى لو واتساب تجاهل ?text=


def _try_focus_whatsapp_window() -> bool:
    """يحاول إحضار نافذة WhatsApp للأمام."""
    if not PYWIN32_OK or platform.system() != "Windows":
        return False
    hwnd_found = None

    def _enum(hwnd, _):
        nonlocal hwnd_found
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd) or ""
        if "WhatsApp" in title:
            hwnd_found = hwnd
            return False
        return True

    try:
        win32gui.EnumWindows(_enum, None)
        if hwnd_found:
            try:
                win32gui.SetForegroundWindow(hwnd_found)
            except Exception:
                pass
            return True
    except Exception as e:
        logging.error(f"EnumWindows error: {e}")
    return False


def _press_enter():
    """يضغط Enter باستخدام pywin32."""
    if not PYWIN32_OK or platform.system() != "Windows":
        return
    try:
        win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
        time.sleep(0.02)
        win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception as e:
        logging.error(f"press enter failed: {e}")


def _set_clipboard_text(txt: str) -> bool:
    """ضبط نص Unicode في الحافظة."""
    if not wcb:
        return False
    try:
        wcb.OpenClipboard()
        wcb.EmptyClipboard()
        # CF_UNICODETEXT = 13
        wcb.SetClipboardData(13, txt)
        return True
    except Exception as e:
        logging.error(f"clipboard set failed: {e}")
        return False
    finally:
        try:
            wcb.CloseClipboard()
        except Exception:
            pass


def _press_keys_paste():
    if not PYWIN32_OK or platform.system() != "Windows":
        return
    try:
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        VK_V = 0x56
        win32api.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.01)
        win32api.keybd_event(VK_V, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception as e:
        logging.error(f"paste only failed: {e}")


def _press_keys_paste_then_enter():
    """Ctrl+V ثم Enter."""
    if not PYWIN32_OK or platform.system() != "Windows":
        return
    try:
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        VK_V = 0x56
        win32api.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.01)
        win32api.keybd_event(VK_V, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        _press_enter()
    except Exception as e:
        logging.error(f"paste+enter failed: {e}")


def _schedule_auto_send(paste_text: str | None):
    """جدوِل لصق/إرسال الرسالة بعد فتح واتساب."""
    if platform.system() != "Windows":
        return
    if not SETTINGS.get("whatsapp_auto_send", True):
        return

    use_clipboard = bool(SETTINGS.get("wa_fill_via_clipboard", True))
    press_enter = bool(SETTINGS.get("wa_press_enter", True))
    delay_ms = int(SETTINGS.get("whatsapp_auto_delay_ms", 1200))

    def worker():
        if use_clipboard and paste_text and wcb:
            _set_clipboard_text(paste_text)

        time.sleep(max(0, delay_ms) / 1000.0)

        for _ in range(12):
            if _try_focus_whatsapp_window():
                time.sleep(0.15)
                if use_clipboard and paste_text and wcb:
                    if press_enter:
                        _press_keys_paste_then_enter()
                    else:
                        _press_keys_paste()
                else:
                    if press_enter:
                        _press_enter()
                return
            time.sleep(0.35)

        # محاولة أخيرة حتى لو ما قدر يركز النافذة
        if use_clipboard and paste_text and wcb:
            if press_enter:
                _press_keys_paste_then_enter()
            else:
                _press_keys_paste()
        else:
            if press_enter:
                _press_enter()

    threading.Thread(target=worker, daemon=True).start()


def open_whatsapp_desktop(phone_digits: str, message_text: str) -> bool:
    """
    يفتح WhatsApp Desktop مع نص مُعبّأ مسبقًا (قدر الإمكان) + يلصق النص تلقائيًا.
    """
    digits = "".join(ch for ch in phone_digits if ch.isdigit())
    msg = message_text.replace("\r\n", "\n").strip()
    uri = f"whatsapp://send?phone={digits}&text={ul.quote(msg, safe='')}"
    try:
        if platform.system() == "Windows":
            os.startfile(uri)
            _schedule_auto_send(msg)  # نمرّر النص للّصق
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", uri])
            _schedule_auto_send(None)
        else:
            subprocess.Popen(["xdg-open", uri])
            _schedule_auto_send(None)
        return True
    except Exception as e:
        logging.error(f"WhatsApp desktop open failed: {e}")
    try:
        webbrowser.open(f"https://wa.me/{digits}?text={ul.quote(msg, safe='')}")
        return True
    except Exception as e:
        logging.error(f"WhatsApp web fallback failed: {e}")
        return False


# ---------------------- Activity Log ---------------------------
def log_activity(receipt_id: int, kind: str, info: str, by_username: str):
    try:
        con = db_conn()
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO activity_log(receipt_id, kind, info, at_utc, by_username)
            VALUES(?,?,?,?,?)
        """,
            (
                receipt_id,
                kind,
                info,
                datetime.datetime.now(datetime.UTC).isoformat(),
                by_username,
            ),
        )
        con.commit()
        con.close()
    except Exception as e:
        logging.error(f"activity_log insert failed: {e}")


# ============================ UI ===============================
class App(tk.Tk):

    def print_label_browser(self, receipt_no: str, phone: str):
        """
        افتح ورقة طباعة عبر المتصفح بحجم 40×22 مم تحتوي على رقم السند ورقم جوال العميل.
        """
        try:
            from pathlib import Path
            import webbrowser, html

            # نضمن أرقام فقط للجوال
            digits = "".join(ch for ch in str(phone) if ch.isdigit())
            html_text = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>Label {receipt_no}</title>
<style>
  @page {{ size: 40mm 22mm; margin: 0; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{ width: 40mm; height: 22mm; display: flex; align-items: center; justify-content: center; }}
  .label {{ width: 40mm; height: 22mm; box-sizing: border-box; padding: 2mm; display: flex; flex-direction: column; justify-content: center; font-family: Tahoma, Arial, sans-serif; }}
  .line1 {{ font-size: 14pt; font-weight: 700; line-height: 1.05; }}
  .line2 {{ font-size: 9pt; font-weight: 600; line-height: 1.05; }}
  .small {{ font-size: 8pt; opacity: .8; margin-top: 1mm; }}
</style>
</head>
<body>
  <div class="label">
    <div class="line1">سند: {html.escape(str(receipt_no))}</div>
    <div class="line2">{html.escape(digits)}</div>
    <div class="small">{html.escape(SETTINGS.get("company","ركن الذاكرة"))}</div>
  </div>
<script>
  window.onload = function() {{
    setTimeout(function() {{ window.print(); }}, 50);
  }};
</script>
</body>
</html>"""
            # احفظ في exports
            from pathlib import Path

            exports_dir = Path(globals().get("EXPORTS_DIR"))
            exports_dir.mkdir(parents=True, exist_ok=True)
            out = exports_dir / f"label_{receipt_no}.html"
            out.write_text(html_text, encoding="utf-8")
            # افتح في المتصفح الافتراضي
            webbrowser.open(out.as_uri())
        except Exception as e:
            try:
                from tkinter import messagebox

                messagebox.showerror(
                    "طباعة الملصق", f"تعذر فتح ورقة الطباعة عبر المتصفح:\\n{e}"
                )
            except Exception:
                pass

    def __init__(self):
        super().__init__()

        self.title(f"{APP_NAME} — {MADE_BY}")
        self.configure(bg=SURFACE_BG)

        try:
            if platform.system() == "Windows":
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except Exception:
            self.geometry("1280x800")
        # Restore main window geometry/state if saved
        try:
            geo, st = get_win_pref("main_window", None, "zoomed")
            if st == "zoomed":
                self.state("zoomed")
            else:
                self.state("normal")
                if geo:
                    self.geometry(geo)
        except Exception:
            pass

        # Auto-save geometry/state with debounce
        _save_id = {"id": None}

        def schedule_save_main(_evt=None):
            if _save_id["id"]:
                self.after_cancel(_save_id["id"])

            def _do():
                try:
                    cur_state = self.state()
                except Exception:
                    cur_state = "normal"
                set_win_pref("main_window", self.geometry(), cur_state)

            _save_id["id"] = self.after(600, _do)

        self.bind("<Configure>", schedule_save_main)

        self.active_user = None
        self.active_branch = None
        self.shop_mode_var = tk.BooleanVar(
            value=SETTINGS.get("use_shop_number_for_qr", False)
        )
        self.wa_auto_var = tk.BooleanVar(value=SETTINGS.get("whatsapp_auto_send", True))
        self.wa_clip_var = tk.BooleanVar(
            value=SETTINGS.get("wa_fill_via_clipboard", True)
        )
        self.wa_enter_var = tk.BooleanVar(value=SETTINGS.get("wa_press_enter", True))
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.init_styles()
        self.create_login()

    def init_styles(self):
        try:
            self.option_add("*Font", "Tahoma 10")
        except Exception:
            pass
        self.style.configure(".", background=SURFACE_BG)
        self.style.configure("TFrame", background=SURFACE_BG)
        self.style.configure(
            "Card.TFrame", background="white", relief="groove", borderwidth=1
        )
        self.style.configure("TLabel", background=SURFACE_BG, font=("Tahoma", 10))
        self.style.configure("Card.TLabel", background="white", font=("Tahoma", 10))
        self.style.configure(
            "Header.TLabel",
            background=PRIMARY_COLOR,
            foreground="white",
            font=("Tahoma", 14, "bold"),
        )
        self.style.configure("Title.TLabel", font=("Tahoma", 20, "bold"))
        self.style.configure("TButton", padding=8, font=("Tahoma", 10))
        self.style.configure(
            "Primary.TButton",
            padding=10,
            font=("Tahoma", 10, "bold"),
            foreground="white",
            background=PRIMARY_COLOR,
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("disabled", "#9bbbe7"),
                ("active", "#1565c0"),
                ("!disabled", PRIMARY_COLOR),
            ],
            foreground=[("!disabled", "white")],
        )
        self.style.configure("Treeview.Heading", font=("Tahoma", 10, "bold"))
        self.style.configure("Treeview", rowheight=26)

    def header_bar(self, parent, text_left="", text_right=""):
        bar = tk.Frame(parent, bg=PRIMARY_COLOR, height=48)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure(1, weight=0)
        tk.Label(
            bar,
            text=text_left,
            bg=PRIMARY_COLOR,
            fg="white",
            font=("Tahoma", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=10)
        if text_right:
            tk.Label(
                bar, text=text_right, bg=PRIMARY_COLOR, fg="white", font=("Tahoma", 10)
            ).grid(row=0, column=1, padx=16)
        return bar

    def card(self, parent, padding=16):
        return ttk.Frame(parent, style="Card.TFrame", padding=padding)

    # ---------- Menus ----------
    def build_menubar(self):
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="📦 Backup DB", command=self.backup_db)
        m_file.add_command(label="⬇️ Export Receipts (CSV)", command=self.export_csv)
        m_file.add_command(
            label="📂 Open Data Folder", command=lambda: self._open_path(str(DATA_DIR))
        )
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=m_file)

        m_set = tk.Menu(menubar, tearoff=0)
        m_set.add_checkbutton(
            label="Use Shop Number for QR (customer chats with shop)",
            variable=self.shop_mode_var,
            command=self.toggle_shop_mode,
        )
        m_set.add_command(label="Set Shop Number", command=self.set_shop_number)
        m_set.add_command(label="Set Company Name", command=self.set_company)
        m_set.add_command(label="Set Currency", command=self.set_currency)
        m_set.add_separator()
        m_set.add_checkbutton(
            label="Send WhatsApp automatically (Enter/Paste)",
            variable=self.wa_auto_var,
            command=self.toggle_wa_auto,
        )
        m_set.add_separator()
        m_set.add_checkbutton(
            label="فعله لو الرسالة ماتترسل (اطفيه لو الرسال تترسل مرتين)",
            variable=self.wa_clip_var,
            command=lambda: self._toggle_bool_setting(
                "wa_fill_via_clipboard", self.wa_clip_var.get()
            ),
        )
        m_set.add_separator()
        m_set.add_checkbutton(
            label="Press Enter automatically",
            variable=self.wa_enter_var,
            command=lambda: self._toggle_bool_setting(
                "wa_press_enter", self.wa_enter_var.get()
            ),
        )
        m_set.add_command(
            label="Set WhatsApp auto-send delay (ms)", command=self.set_wa_delay
        )
        menubar.add_cascade(label="Settings", menu=m_set)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="About", command=self.about)
        menubar.add_cascade(label="Help", menu=m_help)
        self.config(menu=menubar)

    def _toggle_bool_setting(self, key, val):
        SETTINGS[key] = bool(val)
        save_settings(SETTINGS)

    def toggle_wa_auto(self):
        SETTINGS["whatsapp_auto_send"] = bool(self.wa_auto_var.get())
        save_settings(SETTINGS)

    def set_wa_delay(self):
        try:
            curr = int(SETTINGS.get("whatsapp_auto_delay_ms", 1200))
        except Exception:
            curr = 1200
        val = simpledialog.askinteger(
            "Auto-Send Delay (ms)",
            "Delay before pasting + pressing Enter in WhatsApp:",
            initialvalue=curr,
            minvalue=300,
            maxvalue=5000,
            parent=self,
        )
        if val:
            SETTINGS["whatsapp_auto_delay_ms"] = int(val)
            save_settings(SETTINGS)

    def _open_path(self, p):
        try:
            if platform.system() == "Windows":
                os.startfile(p)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception:
            pass

    def toggle_shop_mode(self):
        SETTINGS["use_shop_number_for_qr"] = bool(self.shop_mode_var.get())
        save_settings(SETTINGS)

    def set_shop_number(self):
        num = simpledialog.askstring(
            "Shop Number",
            "Enter shop number (digits only, international like 9665xxxxxxxx):",
            parent=self,
        )
        if not num:
            return
        digits = normalize_phone(num)
        if not re.fullmatch(r"9665\d{8}", digits):
            messagebox.showerror(
                "صيغة غير صحيحة",
                "الرجاء إدخال رقم بصيغة دولية يبدأ بـ 9665 ويتبعه 8 أرقام.\nمثال: 9665XXXXXXXX",
            )
            return
        SETTINGS["shop_number"] = digits
        save_settings(SETTINGS)
        messagebox.showinfo("تم", f"تم حفظ رقم المحل: {SETTINGS['shop_number']}")

    def set_company(self):
        nm = simpledialog.askstring(
            "Company Name", "Your company display name:", parent=self
        )
        if nm:
            SETTINGS["company"] = nm.strip()
            save_settings(SETTINGS)

    def set_currency(self):
        cur = simpledialog.askstring(
            "Currency", "Currency code (e.g., SAR):", parent=self
        )
        if cur:
            SETTINGS["currency"] = cur.strip().upper()
            save_settings(SETTINGS)

    def select_label_printer(self):
        if not PYWIN32_OK:
            messagebox.showerror(
                "الطباعة", "تحتاج pywin32 لاختيار الطابعة.\nثبت:\npip install pywin32"
            )
            return
        printers = get_available_printers()
        if not printers:
            messagebox.showerror("الطباعة", "لا توجد طابعات متاحة على هذا الجهاز.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("اختر طابعة الملصقات")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("420x380")
        dlg.configure(bg=SURFACE_BG)
        tk.Label(
            dlg,
            text="اختر الطابعة التي تريد استخدامها لطباعة الملصق 40×20.3 مم",
            bg=SURFACE_BG,
        ).pack(padx=10, pady=10)
        lb = tk.Listbox(dlg, height=12)
        lb.pack(fill="both", expand=True, padx=10, pady=6)
        curr = SETTINGS.get("label_printer", "")
        sel_index = 0
        for i, name in enumerate(printers):
            lb.insert("end", name)
            if name == curr:
                sel_index = i
        lb.selection_set(sel_index)

        def ok():
            try:
                choice = lb.get(lb.curselection())
            except Exception:
                choice = None
            if choice:
                SETTINGS["label_printer"] = choice
                save_settings(SETTINGS)
                messagebox.showinfo("تم", f"تم اختيار الطابعة:\n{choice}")
            dlg.destroy()

        ttk.Button(dlg, text="حفظ", style="Primary.TButton", command=ok).pack(pady=8)

    def about(self):
        messagebox.showinfo(
            "About",
            f"{APP_NAME}\n{MADE_BY}\nData: {DATA_DIR}\nLog: {LOG_PATH}\n"
            f"Label printer: {SETTINGS.get('label_printer') or '(Default)'}\n"
            f"WA auto-send: {'ON' if SETTINGS.get('whatsapp_auto_send', True) else 'OFF'} "
            f"({SETTINGS.get('whatsapp_auto_delay_ms', 1200)} ms)",
        )

    # ---------- Login ----------
    def create_login(self):
        self.clear()
        self.build_menubar()
        self.configure(bg="#f7f7fb")

        root = ttk.Frame(self, padding=0, style="TFrame")
        root.pack(fill="both", expand=True)

        # الحاوية في منتصف الشاشة
        container = ttk.Frame(root, style="TFrame")
        container.place(relx=0.5, rely=0.5, anchor="center")

        # Canvas لرسم الكرت بزوايا دائرية
        canvas = tk.Canvas(
            container, width=500, height=400, bg="#f7f7fb", highlightthickness=0
        )
        canvas.pack()
        radius = 30
        x1, y1, x2, y2 = 10, 10, 490, 390
        canvas.create_polygon(
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            smooth=True,
            fill="white",
            outline="#ddd",
        )

        # الكرت الأبيض الداخلي
        card = tk.Frame(container, bg="white")
        card.place(x=35, y=35, width=430, height=330)

        # العنوان
        tk.Label(
            card,
            text="تسجيل الدخول",
            bg="white",
            fg="#2f2f4f",
            font=("Tahoma", 18, "bold"),
        ).pack(pady=(15, 20))

        # تحميل بيانات التذكر السابقة (إن وجدت)
        saved_user = SETTINGS.get("remember_user", "")
        saved_pass = SETTINGS.get("remember_pass", "")
        remember_checked = tk.BooleanVar(value=bool(saved_user and saved_pass))

        # إدخال اسم المستخدم
        user_e = ttk.Entry(card, width=34, justify="center")
        user_e.insert(0, saved_user or "مثال: name@domain.com")
        if not saved_user:
            user_e.bind("<FocusIn>", lambda e: user_e.delete(0, "end"))
        user_e.pack(ipady=6, pady=6)

        # إدخال كلمة المرور
        pass_e = ttk.Entry(card, show="*", width=34, justify="center")
        if saved_pass:
            pass_e.insert(0, saved_pass)
        else:
            pass_e.insert(0, "كلمة المرور")
            pass_e.bind("<FocusIn>", lambda e: pass_e.delete(0, "end"))
        pass_e.pack(ipady=6, pady=6)

        # مربع تذكرني
        ttk.Checkbutton(card, text="تذكرني", variable=remember_checked).pack(
            pady=(5, 10)
        )

        # إعداد زر الدخول البنفسجي
        style = ttk.Style()
        style.configure(
            "Purple.TButton",
            background="#1565c0",
            foreground="white",
            font=("Tahoma", 11, "bold"),
            padding=10,
            relief="flat",
        )
        style.map("Purple.TButton", background=[("active", "#086100")])

        def do_login():
            username = user_e.get().strip()
            password = pass_e.get().strip()

            con = db_conn()
            cur = con.cursor()
            cur.execute(
                "SELECT id,branch_id,username,password,role FROM users WHERE username=?",
                (username,),
            )
            row = cur.fetchone()
            con.close()
            if not row or not password_matches(row[3], password):
                messagebox.showerror("خطأ", "بيانات الدخول غير صحيحة")
                return

            # حفظ بيانات المستخدم النشط
            self.active_user = {
                "id": row[0],
                "branch_id": row[1],
                "username": row[2],
                "role": row[4],
            }
            con = db_conn()
            cur = con.cursor()
            cur.execute("SELECT id,name,code FROM branches WHERE id=?", (row[1],))
            b = cur.fetchone()
            con.close()
            self.active_branch = {"id": b[0], "name": b[1], "code": b[2]}

            # إذا تم اختيار "تذكرني"
            if remember_checked.get():
                SETTINGS["remember_user"] = username
                SETTINGS["remember_pass"] = password
            else:
                SETTINGS["remember_user"] = ""
                SETTINGS["remember_pass"] = ""
            save_settings(SETTINGS)

            self.create_dashboard()

        ttk.Button(card, text="التالي", style="Purple.TButton", command=do_login).pack(
            fill="x", padx=30, pady=(20, 10)
        )

        tk.Label(
            card,
            text="فرع البوليفارد A1/123 — فرع السوق A2/123",
            bg="white",
            fg="#888",
            font=("Tahoma", 9),
        ).pack(pady=(8, 4))

    # ---------- Dashboard ----------
    def create_dashboard(self):
        self.clear()
        self.build_menubar()

        root = ttk.Frame(self, padding=0)
        root.pack(fill="both", expand=True)

        bar = self.header_bar(
            root,
            text_left=f"لوحة التحكم — {self.active_branch['name']}",
            text_right=self.active_user["username"],
        )
        bar.pack(fill="x")

        main = ttk.Frame(root, padding=16)
        main.pack(fill="both", expand=True)
        main.rowconfigure(3, weight=1)
        main.columnconfigure(0, weight=1)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(
            top,
            text="➕ سند جديد",
            style="Primary.TButton",
            command=self.create_new_receipt,
        ).pack(side="left", padx=4)
        ttk.Button(top, text="📄 جميع السندات", command=self.list_receipts).pack(
            side="left", padx=4
        )
        ttk.Button(
            top, text="📊 تقرير اليوم (المدفوع)", command=self.show_daily_paid_report
        ).pack(side="left", padx=4)
        ttk.Button(top, text="📦 نسخة احتياطية", command=self.backup_db).pack(
            side="left", padx=4
        )
        ttk.Button(top, text="🚪 خروج", command=self.create_login).pack(
            side="right", padx=4
        )

        # ====== الإحصائيات ======
        con = db_conn()
        cur = con.cursor()

        # عدد كل حالة
        counts = {s: 0 for s in STATUS_ORDER}
        cur.execute(
            "SELECT status, COUNT(*) FROM receipts WHERE branch_id=? GROUP BY status",
            (self.active_branch["id"],),
        )
        for st, cnt in cur.fetchall():
            counts[st] = cnt

        # تحديد نطاق اليوم الحالي (حسب توقيت الرياض)
        today_local = to_riyadh(datetime.datetime.now(datetime.UTC)).date()

        start_utc = datetime.datetime(
            today_local.year, today_local.month, today_local.day
        ) - datetime.timedelta(hours=RIYADH_UTC_OFFSET_HOURS)
        end_utc = start_utc + datetime.timedelta(days=1)

        # ===== عدد السندات اليوم (بدون الملغاة) =====
        cur.execute(
            """
            SELECT COUNT(*) FROM receipts
            WHERE branch_id=? 
              AND datetime(REPLACE(created_utc,'T',' ')) >= datetime(?)
              AND datetime(REPLACE(created_utc,'T',' ')) < datetime(?)
              AND status!='ملغي'
        """,
            (
                self.active_branch["id"],
                start_utc.isoformat().replace("T", " "),
                end_utc.isoformat().replace("T", " "),
            ),
        )
        receipts_today = cur.fetchone()[0] or 0

        # ===== عدد المدفوعات اليوم =====
        cur.execute(
            """
            SELECT COUNT(*) FROM receipts
            WHERE branch_id=?
              AND paid_flag=1
              AND datetime(REPLACE(paid_utc,'T',' ')) >= datetime(?)
              AND datetime(REPLACE(paid_utc,'T',' ')) < datetime(?)
        """,
            (
                self.active_branch["id"],
                start_utc.isoformat().replace("T", " "),
                end_utc.isoformat().replace("T", " "),
            ),
        )
        paid_today = cur.fetchone()[0] or 0

        # ===== إجمالي المبالغ المدفوعة اليوم =====
        cur.execute(
            """
            SELECT COALESCE(SUM(paid_amount),0) FROM receipts
            WHERE branch_id=?
              AND paid_flag=1
              AND datetime(REPLACE(paid_utc,'T',' ')) >= datetime(?)
              AND datetime(REPLACE(paid_utc,'T',' ')) < datetime(?)
        """,
            (
                self.active_branch["id"],
                start_utc.isoformat().replace("T", " "),
                end_utc.isoformat().replace("T", " "),
            ),
        )
        total_paid_today = cur.fetchone()[0] or 0.0

        con.close()

        # ====== عرض بطاقات الإحصائيات ======
        stats = ttk.Frame(main)
        stats.grid(row=1, column=0, sticky="ew", pady=6)
        stats.columnconfigure((0, 1, 2), weight=1)

        card1 = self.card(stats, padding=18)
        card1.grid(row=0, column=0, sticky="nsew", padx=6)
        ttk.Label(card1, text="🧾 عدد السندات اليوم", font=("Tahoma", 11, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            card1,
            text=f"{receipts_today}",
            font=("Tahoma", 18, "bold"),
            foreground="#1565c0",
        ).pack(anchor="center")

        card2 = self.card(stats, padding=18)
        card2.grid(row=0, column=1, sticky="nsew", padx=6)
        ttk.Label(
            card2, text="💰 عدد السندات المدفوعة اليوم", font=("Tahoma", 11, "bold")
        ).pack(anchor="w")
        ttk.Label(
            card2,
            text=f"{paid_today}",
            font=("Tahoma", 18, "bold"),
            foreground="#2e7d32",
        ).pack(anchor="center")

        card3 = self.card(stats, padding=18)
        card3.grid(row=0, column=2, sticky="nsew", padx=6)
        ttk.Label(
            card3, text="💵 إجمالي المبالغ المدفوعة اليوم", font=("Tahoma", 11, "bold")
        ).pack(anchor="w")
        ttk.Label(
            card3,
            text=f"{total_paid_today:.2f} {SETTINGS.get('currency','SAR')}",
            font=("Tahoma", 17, "bold"),
            foreground="#4e342e",
        ).pack(anchor="center")

        # ====== عدادات الحالات ======
        chips = ttk.Frame(main)
        chips.grid(row=2, column=0, sticky="ew", pady=6)
        for st in STATUS_ORDER:
            bg, fg = status_colors(st)
            tk.Label(
                chips,
                text=f"{st}: {counts.get(st,0)}",
                bg=bg,
                fg=fg,
                padx=10,
                pady=5,
                font=("Tahoma", 9, "bold"),
            ).pack(side="left", padx=4)

        # ====== الترحيب ======
        center = ttk.Frame(main)
        center.grid(row=3, column=0, sticky="nsew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        welcome = self.card(center, padding=24)
        welcome.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            welcome,
            text="مرحبًا بك في نظام ركن الذاكرة للصيانة",
            style="Card.TLabel",
            font=("Tahoma", 12),
        ).pack()

    # ---------- New Receipt ----------
    def create_new_receipt(self):
        self.clear()
        self.build_menubar()
        self.configure(bg="#f4f6f8")

        # ===== العنوان =====

        header = self.header_bar(self, text_left="📄 سند صيانة جديد")
        header.pack(fill="x", pady=(6, 0))

        # زر رجوع (يمين وباللون الأحمر الفاتح)
        back_btn = tk.Button(
            header,
            text="⬅️ رجوع",
            bg="#e74c3c",
            fg="white",
            activebackground="#c0392b",
            activeforeground="white",
            relief="flat",
            font=("Tahoma", 10, "bold"),
            cursor="hand2",
            padx=12,
            pady=4,
            command=self.list_receipts,
            borderwidth=0,
        )
        back_btn.grid(row=0, column=1, sticky="e", padx=15, pady=6)

        main = ttk.Frame(self, padding=14)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)

        # ===== placeholder دوال =====
        def set_placeholder(entry, text):
            entry.insert(0, text)
            entry.config(foreground="#b3b3b3")

            def on_focus_in(_):
                if entry.get() == text:
                    entry.delete(0, "end")
                    entry.config(foreground="black")

            def on_focus_out(_):
                if not entry.get().strip():
                    entry.insert(0, text)
                    entry.config(foreground="#b3b3b3")

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)

        def set_placeholder_textbox(textbox, text):
            textbox.insert("1.0", text)
            textbox.config(foreground="#b3b3b3")

            def on_focus_in(_):
                if textbox.get("1.0", "end-1c") == text:
                    textbox.delete("1.0", "end")
                    textbox.config(foreground="black")

            def on_focus_out(_):
                if not textbox.get("1.0", "end-1c").strip():
                    textbox.insert("1.0", text)
                    textbox.config(foreground="#b3b3b3")

            textbox.bind("<FocusIn>", on_focus_in)
            textbox.bind("<FocusOut>", on_focus_out)

        # ===== بيانات العميل =====
        sec1 = self.card(main)
        sec1.grid(row=0, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Label(
            sec1, text="👤 العميل", style="Card.TLabel", font=("Tahoma", 11, "bold")
        ).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(sec1, text="الاسم:", style="Card.TLabel").grid(
            row=1, column=0, sticky="e", padx=5, pady=3
        )
        name_var = tk.StringVar()
        name_e = ttk.Entry(sec1, textvariable=name_var)
        name_e.grid(row=1, column=1, sticky="ew", padx=5, pady=3)
        set_placeholder(name_e, "اكتب اسم العميل")

        ttk.Label(sec1, text="جوال (9665..):", style="Card.TLabel").grid(
            row=2, column=0, sticky="e", padx=5, pady=3
        )
        phone_var = tk.StringVar(value="966")
        phone_e = ttk.Entry(sec1, textvariable=phone_var)
        phone_e.grid(row=2, column=1, sticky="ew", padx=5, pady=3)
        phone_err = tk.Label(
            sec1, text="", fg="red", bg="white", font=("Tahoma", 8, "bold")
        )
        phone_err.grid(row=3, column=1, sticky="w", padx=5)
        sec1.columnconfigure(1, weight=1)

        def validate_phone(*_):
            ph = phone_var.get().strip()
            if not ph.startswith("966") or len(ph) < 11:
                phone_err.config(text="❌ رقم غير صحيح (يبدأ بـ 9665...)")
            else:
                phone_err.config(text="")

        phone_e.bind("<KeyRelease>", validate_phone)

        # ===== بيانات الجهاز =====
        sec2 = self.card(main)
        sec2.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Label(
            sec2, text="💻 الجهاز", style="Card.TLabel", font=("Tahoma", 11, "bold")
        ).grid(row=0, column=0, sticky="w", pady=4)
        labels = {
            "النوع": "اكتب نوع الجهاز",
            "الماركة": "مثلاً: Apple, Samsung",
            "الموديل": "اكتب موديل الجهاز",
            "Serial/IMEI": "اكتب الرقم التسلسلي إن وجد",
            "اللون": "اكتب اللون",
            "الملحقات": "اكتب الملحقات المستلمة مع الجهاز",
        }
        dev_e = {}
        for i, (lbl, placeholder) in enumerate(labels.items()):
            ttk.Label(sec2, text=lbl + ":", style="Card.TLabel").grid(
                row=1 + i, column=0, sticky="e", padx=5, pady=3
            )
            e = ttk.Entry(sec2)
            set_placeholder(e, placeholder)
            e.grid(row=1 + i, column=1, sticky="ew", padx=5, pady=3)
            dev_e[lbl] = e
        sec2.columnconfigure(1, weight=1)

        ttk.Label(sec2, text="حالة الجهاز:", style="Card.TLabel").grid(
            row=7, column=0, sticky="e", padx=5, pady=3
        )
        device_state_var = tk.StringVar(value="لا يعمل")
        device_state_cmb = ttk.Combobox(
            sec2,
            textvariable=device_state_var,
            values=["يعمل", "لا يعمل"],
            state="readonly",
        )
        device_state_cmb.grid(row=7, column=1, sticky="w", padx=5, pady=3)

        # ===== تفاصيل الصيانة =====
        sec3 = self.card(main)
        sec3.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=10)
        sec3.columnconfigure(1, weight=1)
        ttk.Label(
            sec3,
            text="🧰 تفاصيل الصيانة",
            style="Card.TLabel",
            font=("Tahoma", 11, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(sec3, text="وصف العطل:", style="Card.TLabel").grid(
            row=1, column=0, sticky="ne", padx=5, pady=3
        )
        issue_t = tk.Text(sec3, height=4)
        set_placeholder_textbox(issue_t, "اكتب وصف العطل هنا")
        issue_t.grid(row=1, column=1, sticky="nsew", padx=5, pady=3)

        ttk.Label(sec3, text="المطلوب إصلاحه:", style="Card.TLabel").grid(
            row=2, column=0, sticky="ne", padx=5, pady=3
        )
        work_t = tk.Text(sec3, height=3)
        set_placeholder_textbox(work_t, "اكتب المطلوب إصلاحه هنا")
        work_t.grid(row=2, column=1, sticky="nsew", padx=5, pady=3)

        amt_fr = ttk.Frame(sec3)
        amt_fr.grid(row=3, column=1, sticky="w", padx=5, pady=4)
        ttk.Label(sec3, text="التكلفة التقديرية:", style="Card.TLabel").grid(
            row=3, column=0, sticky="e", padx=5, pady=4
        )
        amt_e = ttk.Entry(amt_fr, width=12)
        amt_e.insert(0, "0")
        amt_e.pack(side="left")
        ttk.Label(amt_fr, text=SETTINGS.get("currency", "SAR")).pack(
            side="left", padx=6
        )

        # ===== خيار إرسال واتساب =====
        wa_send_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            main, text="📲 إرسال رسالة واتساب بعد الإنشاء", variable=wa_send_var
        ).grid(row=9, column=0, sticky="w", padx=5, pady=5)

        # ===== شريط الحفظ السفلي =====
        footer = tk.Frame(self, bg="white", height=60, relief="raised", bd=1)
        footer.pack(side="bottom", fill="x")
        save_btn = tk.Button(
            footer,
            text="💾 حفظ وإنشاء السند",
            bg="#27ae60",
            fg="white",
            activebackground="#219150",
            activeforeground="white",
            relief="flat",
            font=("Tahoma", 10, "bold"),
            cursor="hand2",
            padx=18,
            pady=6,
            borderwidth=0,
            command=lambda: save(),
        )
        save_btn.place(relx=0.5, rely=0.5, anchor="center")

        # ===== دالة الحفظ =====
        def save():
            name = name_var.get().strip()
            phone_raw = phone_var.get().strip()
            if not name or name == "اكتب اسم العميل":
                messagebox.showerror("خطأ", "ادخل اسم العميل")
                return
            if not phone_raw.startswith("966") or len(phone_raw) < 11:
                messagebox.showerror("خطأ", "صيغة الجوال غير صحيحة (يبدأ بـ 9665...)")
                return
            phone = normalize_phone(phone_raw)

            dev_type = dev_e["النوع"].get().strip()
            brand = dev_e["الماركة"].get().strip()
            model = dev_e["الموديل"].get().strip()
            if not dev_type or not brand or not model:
                messagebox.showerror(
                    "خطأ", "اكمل بيانات الجهاز (النوع/الماركة/الموديل)"
                )
                return

            serial = dev_e["Serial/IMEI"].get().strip()
            color = dev_e["اللون"].get().strip()
            acc = dev_e["الملحقات"].get().strip()
            device_state = device_state_var.get().strip() or None
            issue = issue_t.get("1.0", "end").strip()
            work = work_t.get("1.0", "end").strip()
            try:
                est = float(amt_e.get())
            except:
                messagebox.showerror("خطأ", "التكلفة التقديرية رقم")
                return

            con = db_conn()
            cur = con.cursor()
            cur.execute("SELECT id,name FROM customers WHERE phone=?", (phone,))
            row = cur.fetchone()
            if row:
                cust_id = row[0]
                if row[1] != name:
                    cur.execute(
                        "UPDATE customers SET name=? WHERE id=?", (name, cust_id)
                    )
            else:
                cur.execute(
                    "INSERT INTO customers(name,phone) VALUES(?,?)", (name, phone)
                )
                cust_id = cur.lastrowid

            cur.execute(
                "INSERT INTO devices(customer_id,type,brand,model,serial_imei,color,accessories) VALUES(?,?,?,?,?,?,?)",
                (
                    cust_id,
                    dev_type,
                    brand,
                    model,
                    serial or None,
                    color or None,
                    acc or None,
                ),
            )
            dev_id = cur.lastrowid

            rno = generate_receipt_no(self.active_branch["code"])
            otp = random_otp()
            tracking_hint = f"{SETTINGS.get('company','ATTA')} — أحضر رقم السند والرمز"
            initial_text = make_whatsapp_initial_text(
                rno, f"{brand} {model}", issue, otp, tracking_hint, device_state
            )
            wa = f"whatsapp://send?phone={phone}&text={ul.quote(initial_text,safe='')}"
            qr_path = make_qr(wa, f"{rno}.png") if qrcode else ""
            now = datetime.datetime.now(datetime.UTC).isoformat()

            cur.execute(
                """
                INSERT INTO receipts(
                    branch_id,customer_id,device_id,receipt_no,issue_desc,work_request,est_amount,approved_amount,device_state,status,
                    otp_code,whatsapp_link,qr_path,signature_path,created_utc,paid_flag,paid_amount,paid_utc,payment_method
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    self.active_branch["id"],
                    cust_id,
                    dev_id,
                    rno,
                    issue,
                    work,
                    est,
                    None,
                    device_state,
                    "جديد",
                    otp,
                    wa,
                    qr_path,
                    None,
                    now,
                    0,
                    0.0,
                    None,
                    None,
                ),
            )
            rid = cur.lastrowid
            cur.execute(
                "INSERT INTO status_history(receipt_id,from_status,to_status,at_utc,by_username) VALUES(?,?,?,?,?)",
                (rid, None, "جديد", now, self.active_user["username"]),
            )
            con.commit()
            con.close()
            log_activity(
                rid,
                "CREATE",
                f"Receipt created with no {rno}",
                self.active_user["username"],
            )

            if wa_send_var.get():
                open_whatsapp_desktop(phone, initial_text)

            messagebox.showinfo(
                "تم", f"تم إنشاء السند: {rno}\nتم تجهيز رسالة واتساب ورمز OTP: {otp}"
            )
            self.list_receipts()
            self.open_receipt(rid)

    # ---------- List/Search ----------
    def list_receipts(self):
        import datetime, tkinter as tk
        from tkinter import ttk, messagebox

        self.clear()
        self.build_menubar()

        # خلفية ناعمة حديثة
        self.configure(bg="#f2f4f7")

        root = ttk.Frame(self, padding=0)
        root.pack(fill="both", expand=True)
        self.header_bar(root, text_left="📋 قائمة السندات").pack(fill="x")

        # ===== إعداد الأنماط =====
        style = ttk.Style()
        style.theme_use("clam")

        # شكل البطاقات (Card)
        style.configure("Card.TFrame", background="white", relief="flat")

        # الأزرار المودرن
        style.configure(
            "Modern.TButton",
            font=("Tahoma", 10, "bold"),
            padding=8,
            borderwidth=0,
            relief="flat",
            background="#e0e5eb",
            foreground="#333",
            focuscolor=style.lookup("TFrame", "background"),
        )
        style.map("Modern.TButton", background=[("active", "#cfd6de")])

        # زر أساسي (Primary)
        style.configure(
            "Primary.TButton",
            font=("Tahoma", 10, "bold"),
            padding=10,
            borderwidth=0,
            relief="flat",
            background="#1976d2",
            foreground="white",
        )
        style.map("Primary.TButton", background=[("active", "#0d47a1")])

        # ===== محتوى الصفحة =====
        page = tk.Canvas(root, bg="#f2f4f7", highlightthickness=0)
        page.pack(fill="both", expand=True)

        # البطاقة 1: شريط الأدوات
        toolbar_card = ttk.Frame(page, style="Card.TFrame")
        toolbar_card.pack(fill="x", padx=25, pady=(15, 10))
        toolbar = ttk.Frame(toolbar_card, padding=10, style="Card.TFrame")
        toolbar.pack(fill="x")

        ttk.Button(
            toolbar,
            text="🆕 سند جديد",
            style="Primary.TButton",
            command=self.create_new_receipt,
        ).pack(side="left", padx=5)
        ttk.Button(
            toolbar, text="🔄 تحديث", style="Modern.TButton", command=lambda: refresh()
        ).pack(side="left", padx=5)
        ttk.Button(
            toolbar, text="⬇️ تصدير CSV", style="Modern.TButton", command=self.export_csv
        ).pack(side="left", padx=5)
        ttk.Button(
            toolbar,
            text="📦 نسخ احتياطي",
            style="Modern.TButton",
            command=self.backup_db,
        ).pack(side="left", padx=5)
        ttk.Button(
            toolbar,
            text="⬅️ رجوع",
            style="Modern.TButton",
            command=self.create_dashboard,
        ).pack(side="right", padx=5)

        # البطاقة 2: البحث
        search_card = ttk.Frame(page, style="Card.TFrame")
        search_card.pack(fill="x", padx=25, pady=(0, 15))
        top = ttk.Frame(search_card, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="بحث:", font=("Tahoma", 10)).pack(side="left")
        q_e = ttk.Entry(top, width=40)
        q_e.pack(side="left", padx=5, ipady=3)
        status_cmb = ttk.Combobox(
            top, values=[""] + STATUS_ORDER, width=22, state="readonly"
        )
        status_cmb.pack(side="left", padx=5)
        paid_cmb = ttk.Combobox(
            top, values=["الكل", "مدفوع", "غير مدفوع"], width=12, state="readonly"
        )
        paid_cmb.set("الكل")
        paid_cmb.pack(side="left", padx=5)
        ttk.Label(top, text="مسح باركود:", font=("Tahoma", 10)).pack(
            side="left", padx=(15, 0)
        )
        bc_entry = ttk.Entry(top, width=20)
        bc_entry.pack(side="left", padx=5, ipady=3)

        def _open_bc(*_):
            val = bc_entry.get().strip()
            if val:
                try:
                    self.open_receipt_by_no(val)
                    bc_entry.delete(0, "end")
                    bc_entry.focus_set()
                except Exception as e:
                    messagebox.showerror("Barcode", f"تعذر فتح السند: {e}")

        bc_entry.bind("<Return>", _open_bc)
        ttk.Button(
            top, text="🔎", style="Modern.TButton", width=3, command=_open_bc
        ).pack(side="left")

        # البطاقة 3: الجدول
        table_card = ttk.Frame(page, style="Card.TFrame")
        table_card.pack(fill="both", expand=True, padx=25, pady=(0, 15))
        table_wrap = ttk.Frame(table_card)
        table_wrap.pack(fill="both", expand=True, padx=10, pady=10)

        tree = ttk.Treeview(
            table_wrap,
            columns=("no", "created", "cust", "dev", "status", "est", "paid"),
            show="headings",
            height=22,
        )

        widths = {
            "no": 120,
            "created": 170,
            "cust": 260,
            "dev": 260,
            "status": 120,
            "est": 120,
            "paid": 100,
        }
        headers = {
            "no": "رقم السند",
            "created": "تاريخ الإنشاء",
            "cust": "العميل",
            "dev": "الجهاز",
            "status": "الحالة",
            "est": "التقدير",
            "paid": "الدفع",
        }
        for col in headers:
            tree.column(col, width=widths[col], anchor="w")
            tree.heading(col, text=headers[col])

        add_treeview_scrollbars(table_wrap, tree)
        apply_treeview_tag_styles(tree)

        # قائمة منبثقة
        menu = tk.Menu(tree, tearoff=0)
        menu.add_command(label="📄 فتح السند", command=lambda: open_selected())
        menu.add_command(
            label="🖨️ طباعة",
            command=lambda: self.print_label_browser(tree.set(tree.focus(), "no")),
        )
        menu.add_separator()
        menu.add_command(label="🔁 تحديث", command=lambda: refresh())

        def show_context_menu(event):
            try:
                tree.selection_set(tree.identify_row(event.y))
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        tree.bind("<Button-3>", show_context_menu)

        # بحث فوري
        def delayed_refresh(_=None):
            if hasattr(self, "_rf_id"):
                self.after_cancel(self._rf_id)
            self._rf_id = self.after(600, refresh)

        q_e.bind("<KeyRelease>", delayed_refresh)
        status_cmb.bind("<<ComboboxSelected>>", lambda e: refresh())
        paid_cmb.bind("<<ComboboxSelected>>", lambda e: refresh())

        # تحميل جزئي (Pagination)
        PAGE_SIZE = 100
        current_page = {"num": 0}
        all_rows_cache = []

        nav_frame = ttk.Frame(page, style="Card.TFrame", padding=8)
        nav_frame.pack(fill="x", padx=25, pady=(0, 20))
        prev_btn = ttk.Button(
            nav_frame,
            text="⬅️ السابق",
            style="Modern.TButton",
            command=lambda: change_page(-1),
        )
        next_btn = ttk.Button(
            nav_frame,
            text="التالي ➡️",
            style="Modern.TButton",
            command=lambda: change_page(1),
        )
        page_lbl = ttk.Label(nav_frame, text="صفحة 1", width=15, anchor="center")
        prev_btn.pack(side="left", padx=4)
        next_btn.pack(side="right", padx=4)
        page_lbl.pack(side="right")

        def change_page(delta):
            np = current_page["num"] + delta
            max_pages = max(1, (len(all_rows_cache) + PAGE_SIZE - 1) // PAGE_SIZE)
            if 0 <= np < max_pages:
                current_page["num"] = np
                display_page()

        def display_page():
            for i in tree.get_children():
                tree.delete(i)
            start = current_page["num"] * PAGE_SIZE
            end = start + PAGE_SIZE
            subset = all_rows_cache[start:end]
            for r in subset:
                insert_row(r)
            page_lbl.config(text=f"صفحة {current_page['num']+1}")

        # فتح السند
        def open_selected(*_):
            sel = tree.focus()
            if sel:
                try:
                    self.open_receipt(int(sel))
                except Exception as e:
                    messagebox.showerror("فتح السند", f"تعذر فتح السند: {e}")

        tree.bind("<Return>", open_selected)
        tree.bind("<Double-1>", open_selected)

        # إدخال الصفوف
        def insert_row(r):
            created_utc = (
                parse_utc_iso(r[8]) if r[8] else datetime.datetime.now(datetime.UTC)
            )
            created_local = to_riyadh(created_utc)
            created_str = fmt_dt(created_local)
            paid_flag = int(r[9] or 0)
            paid_txt = "مدفوع" if paid_flag == 1 else "غير مدفوع"

            paid_style = (
                {"background": "#c8e6c9"}
                if paid_flag == 1
                else {"background": "#ffcdd2"}
            )
            tree.tag_configure(f"paid_{paid_flag}", **paid_style)

            tree.insert(
                "",
                "end",
                iid=str(r[0]),
                values=(
                    r[1],
                    created_str,
                    f"{r[2]} ({r[3]})",
                    f"{r[4]} {r[5]}",
                    r[6],
                    f"{r[7]:.2f} {SETTINGS.get('currency','SAR')}",
                    paid_txt,
                ),
                tags=(r[6], f"paid_{paid_flag}"),
            )

        # التحديث
        def refresh():
            nonlocal all_rows_cache
            q = q_e.get().strip().lower()
            st = status_cmb.get().strip()
            paid_filter = paid_cmb.get().strip()

            con = db_conn()
            cur = con.cursor()
            cur.execute(
                """
                SELECT r.id,r.receipt_no,c.name,c.phone,d.brand,d.model,
                       r.status,r.est_amount,r.created_utc,
                       COALESCE(r.paid_flag,0) AS paid_flag
                FROM receipts r
                JOIN customers c ON r.customer_id=c.id
                JOIN devices d   ON r.device_id=d.id
                WHERE r.branch_id=?
                ORDER BY r.id DESC
                """,
                (self.active_branch["id"],),
            )
            rows = cur.fetchall()
            con.close()

            result = []
            for r in rows:
                created_utc = (
                    parse_utc_iso(r[8]) if r[8] else datetime.datetime.now(datetime.UTC)
                )
                created_local = to_riyadh(created_utc)
                created_str = fmt_dt(created_local)
                blob = " ".join(
                    map(str, [r[1], r[2], r[3], r[4], r[5], created_str])
                ).lower()
                if q and q not in blob:
                    continue
                if st and r[6] != st:
                    continue
                paid_flag = int(r[9] or 0)
                if paid_filter == "مدفوع" and paid_flag != 1:
                    continue
                if paid_filter == "غير مدفوع" and paid_flag != 0:
                    continue
                result.append(r)

            all_rows_cache = result
            current_page["num"] = 0
            display_page()

        refresh()

    # ---------- Export / Backup ----------
    def export_csv(self):
        con = db_conn()
        cur = con.cursor()
        cur.execute(
            """
            SELECT r.receipt_no,c.name,c.phone,d.brand,d.model,r.status,r.est_amount,r.created_utc,r.delivered_utc
            FROM receipts r
            JOIN customers c ON r.customer_id=c.id
            JOIN devices d   ON r.device_id=d.id
            WHERE r.branch_id=?
            ORDER BY r.id DESC
        """,
            (self.active_branch["id"],),
        )
        rows = cur.fetchall()
        con.close()
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = EXPORTS_DIR / f"receipts_{self.active_branch['code']}_{ts}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "receipt_no",
                    "customer",
                    "phone",
                    "brand",
                    "model",
                    "status",
                    "est_amount",
                    "created_utc",
                    "delivered_utc",
                ]
            )
            for r in rows:
                w.writerow(r)
        messagebox.showinfo("تم", f"تم التصدير: {path}")
        self._open_path(str(path))

    def backup_db(self):
        if not DB_PATH.exists():
            messagebox.showwarning("تنبيه", "لا يوجد ملف قاعدة بيانات بعد")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = BACKUP_DIR / f"repairdesk_{ts}.db"
        shutil.copy2(DB_PATH, dst)
        messagebox.showinfo("تم", f"تم إنشاء نسخة احتياطية: {dst}")

    # ---------- Receipt Detail ----------
    def open_receipt_by_no(self, receipt_no: str):
        receipt_no = receipt_no.strip()
        con = db_conn()
        cur = con.cursor()
        cur.execute(
            "SELECT id FROM receipts WHERE receipt_no = ? LIMIT 1", (receipt_no,)
        )
        row = cur.fetchone()
        con.close()
        if not row:
            raise ValueError(f"لا يوجد سند برقم {receipt_no}")
        self.open_receipt(int(row[0]))

    def open_receipt(self, rid: int):
        """
        نافذة تفاصيل السند — أقسام قابلة للطي + حفظ الأبعاد + تمرير بالعجلة
        """
        import datetime, os, tkinter as tk
        from tkinter import ttk, messagebox

        win = tk.Toplevel(self)
        win.title(f"تفاصيل السند #{rid}")
        win.configure(bg=SURFACE_BG)

        # --- استعادة أبعاد النافذة المحفوظة ---
        default_geo = "1200x800+100+60"
        geo, state = get_win_pref("receipt_window", default_geo, "normal")
        try:
            if state == "zoomed":
                win.state("zoomed")
            else:
                win.state("normal")
                win.geometry(geo or default_geo)
        except Exception:
            win.geometry(default_geo)

        # --- حفظ الأبعاد تلقائيًا عند التغيير ---
        save_after_id = {"id": None}

        def schedule_save_prefs(_evt=None):
            if save_after_id["id"]:
                win.after_cancel(save_after_id["id"])

            def _save():
                try:
                    cur_state = win.state()
                except Exception:
                    cur_state = "normal"
                cur_geo = win.geometry()
                set_win_pref("receipt_window", cur_geo, cur_state)

            save_after_id["id"] = win.after(600, _save)

        win.bind("<Configure>", schedule_save_prefs)

        self.header_bar(win, text_left="📋 تفاصيل السند").pack(fill="x")

        # --- دالة إنشاء قسم قابل للطي ---
        # --- دالة إنشاء قسم قابل للطي ---
        def make_section(parent, title, build_fn, opened=False):
            container = ttk.Frame(parent, style="Card.TFrame", padding=4)
            container.pack(fill="x", pady=4)

            # الألوان للحالات
            CLOSED_COLOR = "#e0e0e0"  # رمادي فاتح
            OPEN_COLOR = "#1565c0"  # أزرق هادي

            # ترويسة القسم
            header = tk.Frame(
                container, bg=OPEN_COLOR if opened else CLOSED_COLOR, cursor="hand2"
            )
            header.pack(fill="x")

            arrow = tk.Label(
                header,
                text="▼" if opened else "▶",
                bg=OPEN_COLOR if opened else CLOSED_COLOR,
                fg="white" if opened else "black",
                font=("Tahoma", 11, "bold"),
            )
            arrow.pack(side="right", padx=8, pady=4)

            title_lbl = tk.Label(
                header,
                text=title,
                bg=OPEN_COLOR if opened else CLOSED_COLOR,
                fg="white" if opened else "black",
                font=("Tahoma", 11, "bold"),
            )
            title_lbl.pack(side="left", padx=8, pady=4)

            # محتوى القسم
            body = ttk.Frame(container, padding=8)
            build_fn(body)
            if opened:
                body.pack(fill="x")

            def toggle(_=None):
                if body.winfo_manager():
                    # إغلاق
                    body.pack_forget()
                    arrow.config(text="▶", bg=CLOSED_COLOR, fg="black")
                    title_lbl.config(bg=CLOSED_COLOR, fg="black")
                    header.config(bg=CLOSED_COLOR)
                else:
                    # فتح
                    body.pack(fill="x")
                    arrow.config(text="▼", bg=OPEN_COLOR, fg="white")
                    title_lbl.config(bg=OPEN_COLOR, fg="white")
                    header.config(bg=OPEN_COLOR)

            for w in (header, title_lbl, arrow):
                w.bind("<Button-1>", toggle)

            return container

        # --- جلب بيانات السند ---
        con = db_conn()
        cur = con.cursor()
        cur.execute(
            """
            SELECT r.receipt_no, c.name, c.phone, d.brand, d.model, d.serial_imei,
                   r.est_amount, COALESCE(r.approved_amount,r.est_amount),
                   COALESCE(r.paid_amount,0.0), COALESCE(r.paid_flag,0),
                   COALESCE(r.payment_method,''), r.device_state,
                   r.issue_desc, r.work_request, r.created_utc, r.status,
                   r.otp_code, r.qr_path, r.delivered_utc
            FROM receipts r
            JOIN customers c ON r.customer_id=c.id
            JOIN devices d   ON r.device_id=d.id
            WHERE r.id=?""",
            (rid,),
        )
        r = cur.fetchone()
        con.close()
        if not r:
            messagebox.showerror("خطأ", "السند غير موجود")
            return

        (
            receipt_no,
            cust_name,
            cust_phone,
            brand,
            model,
            serial,
            est,
            approved,
            paid,
            paid_flag,
            pay_method,
            device_state,
            issue,
            work,
            created_utc,
            status,
            otp,
            qr_path,
            delivered_utc,
        ) = r

        created_dt = parse_utc_iso(created_utc)
        created_local = to_riyadh(created_dt)
        warranty_end = created_dt + datetime.timedelta(days=WARRANTY_DAYS)
        from datetime import datetime, UTC

        warranty_valid = datetime.now().replace(tzinfo=None) <= warranty_end.replace(
            tzinfo=None
        )

        # --- Scrollable container ---
        scroll_container, root = make_vscrollable(win, bg=SURFACE_BG)
        scroll_container.pack(fill="both", expand=True)

        # --- سطر الحالة في الأعلى ---
        def update_status_label():
            balance = (approved or est) - (paid or 0)
            if balance <= 0.01:
                status_lbl.config(
                    text=f"🟢 مدفوع بالكامل — لا يوجد رصيد متبقٍ.",
                    fg="#0b6e0b",
                    bg="#e8f5e9",
                )
            else:
                status_lbl.config(
                    text=f"🔴 غير مدفوع — الرصيد المتبقي: {balance:.2f}",
                    fg="#b00020",
                    bg="#ffebee",
                )

        status_lbl = tk.Label(
            root, font=("Tahoma", 11, "bold"), anchor="w", padx=10, pady=6
        )
        status_lbl.pack(fill="x", pady=(4, 2))
        update_status_label()

        # 💰 قسم الدفع
        def build_payment(body):
            PAY_TOL = 0.01
            approved_var = tk.StringVar(value=f"{approved:.2f}")
            paid_var = tk.StringVar(value=f"{paid:.2f}")
            method_var = tk.StringVar(value=pay_method)

            ttk.Label(body, text=f"العميل: {cust_name} — {cust_phone}").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=3
            )
            ttk.Label(body, text="التكلفة النهائية المعتمدة:").grid(
                row=1, column=0, sticky="e", padx=6, pady=4
            )
            ttk.Entry(body, width=16, textvariable=approved_var).grid(
                row=1, column=1, sticky="w", padx=6
            )
            ttk.Label(body, text="المبلغ المدفوع:").grid(
                row=2, column=0, sticky="e", padx=6, pady=4
            )
            ttk.Entry(body, width=16, textvariable=paid_var).grid(
                row=2, column=1, sticky="w", padx=6
            )
            ttk.Label(body, text="طريقة الدفع:").grid(
                row=3, column=0, sticky="e", padx=6, pady=4
            )
            ttk.Combobox(
                body,
                textvariable=method_var,
                width=18,
                values=["نقدي", "مدى", "بطاقة ائتمانية", "تحويل بنكي", "أخرى"],
            ).grid(row=3, column=1, sticky="w", padx=6)

            toast_lbl = tk.Label(
                body, bg="#c8e6c9", fg="#1b5e20", font=("Tahoma", 9, "bold"), anchor="w"
            )
            toast_lbl.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=3)
            toast_lbl.grid_remove()

            def show_toast(msg):
                toast_lbl.config(text=f"✅ {msg}")
                toast_lbl.grid()
                body.after(2000, toast_lbl.grid_remove)

            def save_payment():
                nonlocal approved, paid
                try:
                    appr = float(approved_var.get() or 0)
                    p = float(paid_var.get() or 0)
                    is_paid = 1 if (appr - p) <= PAY_TOL else 0
                    con2 = db_conn()
                    cur2 = con2.cursor()
                    cur2.execute(
                        """
                        UPDATE receipts SET approved_amount=?, paid_amount=?, paid_flag=?,
                            paid_utc = CASE WHEN ?=1 THEN datetime('now') ELSE NULL END,
                            payment_method=? WHERE id=?
                    """,
                        (appr, p, is_paid, is_paid, method_var.get(), rid),
                    )
                    con2.commit()
                    con2.close()
                    approved, paid = appr, p
                    update_status_label()
                    show_toast("تم حفظ بيانات الدفع بنجاح")
                except Exception as e:
                    messagebox.showerror("خطأ", f"تعذر الحفظ:\n{e}")

            ttk.Button(
                body,
                text="💾 حفظ التكلفة/الدفع",
                style="Primary.TButton",
                command=save_payment,
            ).grid(row=5, column=0, columnspan=2, sticky="e", pady=8)

        make_section(
            root, f"💰 التكلفة والدفع — العميل {cust_name}", build_payment, opened=False
        )

        # 📋 بيانات السند (مع OTP)
        def build_info(body):
            ttk.Label(
                body, text=f"رقم السند: {receipt_no}", font=("Tahoma", 11, "bold")
            ).pack(anchor="w")
            ttk.Label(body, text=f"العميل: {cust_name} — {cust_phone}").pack(anchor="w")
            ttk.Label(
                body, text=f"الجهاز: {brand} {model} — IMEI: {serial or '-'}"
            ).pack(anchor="w")
            ttk.Label(body, text=f"العطل: {issue}").pack(anchor="w")
            ttk.Label(body, text=f"المطلوب: {work}").pack(anchor="w")
            ttk.Label(
                body,
                text=f"🔑 رمز الاستلام (OTP): {otp}",
                font=("Tahoma", 10, "bold"),
                foreground="#1565c0",
            ).pack(anchor="w", pady=(4, 0))

        make_section(root, "📋 بيانات السند", build_info, opened=True)

        # 🧰 الأدوات والإجراءات
        def build_tools_actions(body):
            toast = tk.Label(
                body, bg="#c8e6c9", fg="#1b5e20", font=("Tahoma", 9, "bold"), anchor="w"
            )
            toast.pack(fill="x", pady=(0, 6))
            toast.pack_forget()

            def show_toast(msg):
                toast.config(text=f"✅ {msg}")
                toast.pack(fill="x", pady=(0, 6))
                body.after(2000, toast.pack_forget)

            top_row = ttk.Frame(body)
            top_row.pack(fill="x", pady=(0, 8))

            def wa_initial():
                text = make_whatsapp_initial_text(
                    receipt_no,
                    f"{brand} {model}",
                    issue,
                    otp,
                    f"{SETTINGS.get('company','ATTA')} — أحضر رقم السند والرمز",
                    device_state,
                )
                open_whatsapp_desktop(cust_phone, text)
                show_toast("تم إرسال رسالة فتح السند")

            def send_ready():
                text = make_ready_text(
                    receipt_no, f"{brand} {model}", otp, SETTINGS.get("company", "ATTA")
                )
                open_whatsapp_desktop(cust_phone, text)
                show_toast("تم إرسال إشعار الجاهزية")

                # ✅ بعد إرسال الإشعار، حدّث حالة السند إلى "جاهز للاستلام"
                try:
                    import datetime
                    from datetime import UTC

                    now_utc = datetime.datetime.now(UTC).isoformat()
                    prev_status = status

                    con = db_conn()
                    cur = con.cursor()
                    cur.execute(
                        "UPDATE receipts SET status=? WHERE id=?",
                        ("جاهز للاستلام", rid),
                    )
                    cur.execute(
                        """
                        INSERT INTO status_history(receipt_id, from_status, to_status, at_utc, by_username)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            rid,
                            prev_status,
                            "جاهز للاستلام",
                            now_utc,
                            self.active_user["username"],
                        ),
                    )
                    con.commit()
                    con.close()
                    show_toast("تم تغيير حالة السند إلى جاهز للاستلام ✅")
                except Exception as e:
                    messagebox.showerror("خطأ", f"فشل تحديث الحالة:\n{e}")

            ttk.Button(top_row, text="📲 رسالة فتح السند", command=wa_initial).pack(
                side="left", padx=4
            )
            ttk.Button(top_row, text="📣 إشعار الجاهزية", command=send_ready).pack(
                side="left", padx=4
            )

            ttk.Button(
                top_row,
                text="🖨️ طباعة ملصق مباشر",
                command=lambda: self.print_label_browser(receipt_no, cust_phone),
            ).pack(side="left", padx=4)

            separator = ttk.Separator(body, orient="horizontal")
            separator.pack(fill="x", pady=(8, 4))

            bottom_row = ttk.Frame(body)
            bottom_row.pack(fill="x")

            def deliver_device():
                if ((approved or est) - (paid or 0)) > 0.01:
                    messagebox.showwarning(
                        "تنبيه", "لا يمكن التسليم إلا بعد سداد كامل المبلغ."
                    )
                    return

                pop = tk.Toplevel(win)
                pop.title("تسليم الجهاز")
                pop.configure(bg=SURFACE_BG)
                ttk.Label(pop, text="أدخل رمز الاستلام (OTP):").pack(padx=10, pady=8)
                entry = ttk.Entry(pop)
                entry.pack(padx=10)

                def ok():
                    if entry.get().strip() != str(otp).strip():
                        messagebox.showerror("خطأ", "رمز OTP غير صحيح")
                        return

                    from datetime import datetime

                    nowu = datetime.now(datetime.UTC).isoformat()

                    conx = db_conn()
                    curx = conx.cursor()
                    curx.execute(
                        "UPDATE receipts SET status='تم التسليم', delivered_utc=? WHERE id=?",
                        (nowu, rid),
                    )
                    conx.commit()
                    conx.close()
                    update_status_label()
                    pop.destroy()
                    show_toast("تم تسليم الجهاز بنجاح")

                    win.after(200, lambda: ask_send_confirmation())

                def ask_send_confirmation():
                    if messagebox.askyesno(
                        "إرسال تأكيد", "هل تريد إرسال رسالة تأكيد تسليم للعميل؟"
                    ):
                        try:
                            msg = (
                                f"✅ تم تسليم جهازك بنجاح.\n\n"
                                f"رقم السند: {receipt_no}\n"
                                f"الجهاز: {brand} {model}\n"
                                f"نشكر ثقتك في {SETTINGS.get('company', 'ركن الذاكرة')} 🌹"
                            )
                            open_whatsapp_desktop(cust_phone, msg)
                            show_toast("تم إرسال رسالة تأكيد التسليم")
                        except Exception as e:
                            messagebox.showerror("خطأ", f"تعذر إرسال الرسالة:\n{e}")

                ttk.Button(
                    pop, text="تأكيد التسليم", style="Primary.TButton", command=ok
                ).pack(pady=8)

            style = ttk.Style()
            style.configure(
                "Deliver.TButton",
                background="#2e7d32",
                foreground="white",
                font=("Tahoma", 10, "bold"),
                padding=6,
            )

            deliver_btn = ttk.Button(
                bottom_row,
                text="✅ تسليم الجهاز (OTP)",
                style="Deliver.TButton",
                command=deliver_device,
            )
            deliver_btn.pack(side="left", padx=(4, 10))

            ttk.Label(
                bottom_row,
                text="🟢 يُستخدم عند تسليم الجهاز للعميل",
                foreground="#2e7d32",
                font=("Tahoma", 9),
            ).pack(side="left", pady=(2, 0))

        make_section(root, "🧰 الأدوات والإجراءات", build_tools_actions, opened=True)

        # ⚙️ حالة السند
        # ⚙️ حالة السند
        def build_status_section(body):
            ttk.Label(body, text="تغيير حالة السند:", font=("Tahoma", 10, "bold")).pack(
                anchor="w", pady=(0, 4)
            )

            status_var = tk.StringVar(value=status)
            cmb = ttk.Combobox(
                body,
                textvariable=status_var,
                values=STATUS_ORDER,
                width=25,
                state="readonly",
            )
            cmb.pack(anchor="w", padx=6, pady=4)

            def update_status():
                new_status = status_var.get().strip()
                if not new_status or new_status == status:
                    messagebox.showinfo("تنبيه", "لم يتم تغيير الحالة.")
                    return
                from datetime import datetime, UTC

                now_utc = datetime.now(UTC).isoformat()
                con = db_conn()
                cur = con.cursor()
                cur.execute(
                    "UPDATE receipts SET status=?, delivered_utc=? WHERE id=?",
                    (new_status, now_utc if new_status == "تم التسليم" else None, rid),
                )
                cur.execute(
                    """
                    INSERT INTO status_history(receipt_id,from_status,to_status,at_utc,by_username)
                    VALUES(?,?,?,?,?)
                """,
                    (rid, status, new_status, now_utc, self.active_user["username"]),
                )
                con.commit()
                con.close()
                update_status_label()
                messagebox.showinfo("تم", "تم تحديث حالة السند بنجاح.")

            ttk.Button(
                body,
                text="🔄 تحديث الحالة",
                style="Primary.TButton",
                command=update_status,
            ).pack(anchor="e", padx=6, pady=(6, 4))

        make_section(root, "⚙️ حالة السند", build_status_section, opened=False)

        # 🛡️ الضمان
        def build_warranty(body):
            ttk.Label(body, text=f"تاريخ الإنشاء: {fmt_dt(created_local)}").pack(
                anchor="w"
            )
            ttk.Label(
                body, text=f"نهاية الضمان: {fmt_dt(to_riyadh(warranty_end))}"
            ).pack(anchor="w")
            ttk.Label(
                body, text=f"الحالة: {'ساري ✅' if warranty_valid else 'منتهٍ ❌'}"
            ).pack(anchor="w")

        warr_title = "🛡️ الضمان — ساري ✅" if warranty_valid else "🛡️ الضمان — منتهٍ ❌"
        make_section(root, warr_title, build_warranty, opened=False)

        # 🔳 كود QR
        def build_qr(body):
            if os.path.exists(qr_path):
                try:
                    from PIL import Image, ImageTk

                    img = Image.open(qr_path).resize((200, 200))
                    ph = ImageTk.PhotoImage(img)
                    lbl = ttk.Label(body, image=ph)
                    lbl.image = ph
                    lbl.pack()
                except Exception:
                    ttk.Label(body, text="(تعذر عرض QR)").pack()
            else:
                ttk.Label(body, text="(لا يوجد QR)").pack()

        make_section(root, "🔳 كود QR", build_qr, opened=False)

        # 🧾 سجل النشاط
        def build_log(body):
            tree = ttk.Treeview(
                body, columns=("الوقت", "النوع", "الوصف"), show="headings", height=6
            )
            for col in ("الوقت", "النوع", "الوصف"):
                tree.heading(col, text=col)
                tree.column(col, width=220 if col == "الوصف" else 140, anchor="w")
            tree.pack(fill="x", expand=True)
            con = db_conn()
            cur = con.cursor()
            cur.execute(
                """
                SELECT kind, info, at_utc, by_username FROM activity_log
                WHERE receipt_id=? ORDER BY id DESC
            """,
                (rid,),
            )
            for kind, info, at_utc, by in cur.fetchall():
                dt_local = fmt_dt(to_riyadh(parse_utc_iso(at_utc)))
                tree.insert(
                    "", "end", values=(dt_local, kind, f"{info or ''} (by {by})")
                )
            con.close()

        make_section(root, "🧾 سجل النشاط", build_log, opened=False)

    def show_daily_paid_report(self):
        """
        نافذة تقرير يومي احترافية:
        - اختيار تاريخ اليوم المطلوب.
        - جدول مفصل للسندات المدفوعة فقط في ذلك اليوم (بحسب وقت الدفع).
        - إجمالي المدفوع + عدد السندات.
        - تصدير PDF عربي منسق داخل جدول.
        """

        # ===== Helpers for date logic (local Riyadh) =====
        def local_date_bounds_utc(date_obj):
            start_local = datetime.datetime(
                date_obj.year, date_obj.month, date_obj.day, 0, 0, 0
            )
            end_local = start_local + datetime.timedelta(days=1)
            start_utc = start_local - datetime.timedelta(hours=RIYADH_UTC_OFFSET_HOURS)
            end_utc = end_local - datetime.timedelta(hours=RIYADH_UTC_OFFSET_HOURS)
            return start_utc, end_utc

        def fetch_rows_for_date(d_obj):
            s_utc, e_utc = local_date_bounds_utc(d_obj)
            con = db_conn()
            cur = con.cursor()
            try:
                cur.execute(
                    """
                    SELECT r.receipt_no,
                           COALESCE(r.paid_amount,0.0),
                           r.paid_utc,
                           COALESCE(r.payment_method,''),
                           c.name, c.phone,
                           d.brand, d.model
                    FROM receipts r
                    JOIN customers c ON r.customer_id=c.id
                    JOIN devices d   ON r.device_id=d.id
                    WHERE r.branch_id=? AND COALESCE(r.paid_flag,0)=1
                      AND r.paid_utc IS NOT NULL AND r.paid_utc>=? AND r.paid_utc<?
                    ORDER BY r.paid_utc ASC
                    """,
                    (self.active_branch["id"], s_utc.isoformat(), e_utc.isoformat()),
                )
                rows = cur.fetchall()
            except Exception:
                rows = []
            finally:
                con.close()

            fixed = []
            for no, amt, ts, method, cname, phone, brand, model in rows:
                try:
                    ts_local = fmt_dt(to_riyadh(parse_utc_iso(ts))) if ts else ""
                except Exception:
                    ts_local = ts or ""
                fixed.append(
                    (no, amt, ts_local, method, cname, phone, f"{brand} {model}")
                )
            return fixed

        # ===== Refresh table =====
        def refresh_table():
            try:
                y, m, d = map(int, date_var.get().split("-"))
                d_obj = datetime.date(y, m, d)
            except Exception:
                messagebox.showerror("تاريخ غير صالح", "أدخل التاريخ بصيغة YYYY-MM-DD")
                return

            rows = fetch_rows_for_date(d_obj)
            for i in tree.get_children():
                tree.delete(i)

            total = 0.0
            for no, amt, ts_local, method, cname, phone, devtxt in rows:
                total += amt or 0.0
                tree.insert(
                    "",
                    "end",
                    values=(
                        no,
                        f"{(amt or 0):.2f}",
                        method or "-",
                        ts_local,
                        f"{cname} ({phone})",
                        devtxt,
                    ),
                )

            total_var.set(
                f"الإجمالي: {total:.2f} {SETTINGS.get('currency','SAR')} — عدد السندات: {len(rows)}"
            )

        def prev_day():
            try:
                y, m, d = map(int, date_var.get().split("-"))
                d_obj = datetime.date(y, m, d) - datetime.timedelta(days=1)
            except Exception:
                d_obj = (
                    to_riyadh(datetime.datetime.now(datetime.UTC))
                ).date() - datetime.timedelta(days=1)
            date_var.set(d_obj.strftime("%Y-%m-%d"))
            refresh_table()

        def next_day():
            try:
                y, m, d = map(int, date_var.get().split("-"))
                d_obj = datetime.date(y, m, d) + datetime.timedelta(days=1)
            except Exception:
                d_obj = (
                    to_riyadh(datetime.datetime.now(datetime.UTC))
                ).date() + datetime.timedelta(days=1)
            date_var.set(d_obj.strftime("%Y-%m-%d"))
            refresh_table()

        def today():
            d_obj = (to_riyadh(datetime.datetime.now(datetime.UTC))).date()
            date_var.set(d_obj.strftime("%Y-%m-%d"))
            refresh_table()

        # ===== PDF Export =====
        def export_pdf():
            if not REPORTLAB_OK:
                messagebox.showerror(
                    "PDF",
                    "حزمة ReportLab غير مثبتة.\nثبتها:\npip install reportlab arabic-reshaper python-bidi",
                )
                return

            try:
                y, m, d = map(int, date_var.get().split("-"))
                d_obj = datetime.date(y, m, d)
            except Exception:
                messagebox.showerror("تاريخ غير صالح", "أدخل التاريخ بصيغة YYYY-MM-DD")
                return

            rows = fetch_rows_for_date(d_obj)
            if not rows:
                messagebox.showinfo("PDF", "لا توجد قيود مدفوعة في هذا اليوم.")
                return

            # ✅ تسجيل خط عربي من النظام (يدعم التوصيل الكامل)
            font_name = register_ar_font()
            if not font_name:
                font_name = "Helvetica"  # احتياطي لو فشل التحميل

            # ===== بناء الجدول =====
            headers = [
                ar_text("رقم السند"),
                ar_text("المبلغ"),
                ar_text("طريقة الدفع"),
                ar_text("وقت الدفع (الرياض)"),
                ar_text("العميل"),
                ar_text("الجهاز"),
            ]
            data = [headers]

            total = 0.0
            for no, amt, ts_local, method, cname, phone, devtxt in rows:
                total += amt or 0.0
                data.append(
                    [
                        ar_text(no),
                        ar_text(f"{(amt or 0):.2f}"),
                        ar_text(method or "-"),
                        ar_text(ts_local),
                        ar_text(f"{cname} ({phone})"),
                        ar_text(devtxt),
                    ]
                )
            data.append(
                [
                    ar_text("الإجمالي"),
                    ar_text(f"{total:.2f} {SETTINGS.get('currency','SAR')}"),
                    "",
                    "",
                    "",
                    "",
                ]
            )

            # ===== مسار الملف =====
            pdf_name = f"daily_paid_{self.active_branch['code']}_{d_obj.strftime('%Y%m%d')}.pdf"
            pdf_path = str(EXPORTS_DIR / pdf_name)

            # ===== إعداد التصميم =====
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.platypus import (
                Spacer,
                Paragraph,
                Table,
                TableStyle,
                SimpleDocTemplate,
            )

            doc = SimpleDocTemplate(
                pdf_path,
                pagesize=A4,
                rightMargin=30,
                leftMargin=30,
                topMargin=30,
                bottomMargin=18,
            )

            # ✅ تنسيق العناوين بالعربي
            title_style = ParagraphStyle(
                name="Title",
                alignment=1,  # وسط
                fontName=font_name,
                fontSize=15,
                leading=22,
                spaceAfter=10,
                textColor=colors.HexColor("#222222"),
            )

            # ===== الجدول =====
            tbl = Table(data, repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("FONT", (0, 0), (-1, -1), font_name, 10),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8f5e9")),
                        ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#2e7d32")),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )

            # ===== المحتوى =====
            elements = [
                Paragraph(
                    ar_text(
                        f"📱 {SETTINGS.get('company','ركن الذاكرة للاتصالات')} — التقرير اليومي"
                    ),
                    title_style,
                ),
                Spacer(1, 10),
                Paragraph(
                    ar_text(f"تاريخ التقرير: {d_obj.strftime('%Y-%m-%d')}"), title_style
                ),
                Spacer(1, 12),
                tbl,
            ]

            try:
                doc.build(elements)
            except Exception as e:
                messagebox.showerror("PDF", f"تعذر إنشاء PDF:\n{e}")
                return

            messagebox.showinfo("PDF", f"تم إنشاء الملف:\n{pdf_path}")
            try:
                self._open_path(pdf_path)
            except Exception:
                pass

        # ===== Build window =====
        win = tk.Toplevel(self)
        win.title("التقرير اليومي — المدفوع فقط")
        win.configure(bg=SURFACE_BG)
        self.header_bar(win, text_left="التقرير اليومي (المدفوع فقط)").pack(fill="x")

        top = ttk.Frame(win, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="التاريخ (YYYY-MM-DD):").pack(side="right", padx=6)
        date_var = tk.StringVar(
            value=to_riyadh(datetime.datetime.now(datetime.UTC))
            .date()
            .strftime("%Y-%m-%d")
        )
        ttk.Entry(top, textvariable=date_var, width=14).pack(side="right")
        ttk.Button(top, text="اليوم", command=today).pack(side="right", padx=4)
        ttk.Button(top, text="◀ اليوم السابق", command=prev_day).pack(
            side="right", padx=4
        )
        ttk.Button(top, text="اليوم التالي ▶", command=next_day).pack(
            side="right", padx=4
        )
        ttk.Button(
            top, text="عرض", style="Primary.TButton", command=refresh_table
        ).pack(side="left", padx=4)
        ttk.Button(top, text="🖨️ تصدير PDF", command=export_pdf).pack(
            side="left", padx=4
        )

        # ===== Table =====
        table_wrap = ttk.Frame(win, padding=10)
        table_wrap.pack(fill="both", expand=True)
        cols = ("no", "amt", "method", "paid_local", "customer", "device")
        headers = {
            "no": "رقم السند",
            "amt": "المبلغ",
            "method": "طريقة الدفع",
            "paid_local": "وقت الدفع (الرياض)",
            "customer": "العميل",
            "device": "الجهاز",
        }
        tree = ttk.Treeview(table_wrap, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=headers[c])
            tree.column(
                c, width=160 if c in ("customer", "device") else 120, anchor="w"
            )

        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        # ===== Footer =====
        bottom = ttk.Frame(win, padding=10)
        bottom.pack(fill="x")
        total_var = tk.StringVar(value="—")
        ttk.Label(bottom, textvariable=total_var, font=("Tahoma", 10, "bold")).pack(
            anchor="w"
        )

        refresh_table()

    # ---------- Utils ----------
    def clear(self):
        for w in self.winfo_children():
            w.destroy()


# ---------------------- main --------------------------
def main():
    try:
        db_init()
    except Exception as e:
        logging.exception("DB init error")
        messagebox.showerror("DB Error", str(e))
        return
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
