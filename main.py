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
__version__ = "1.0.1"

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
logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATUS_ORDER = ["NEW","INSPECTION","AWAITING_APPROVAL","IN_PROGRESS","READY","COMPLETED","CANCELED"]

# Warranty
WARRANTY_DAYS = 30
RIYADH_UTC_OFFSET_HOURS = 3

# ------------------ Status Colors & UI helpers ------------------
STATUS_STYLE = {
    "NEW":               ("#9e9e9e", "white"),
    "INSPECTION":        ("#1976d2", "white"),
    "AWAITING_APPROVAL": ("#f9a825", "black"),
    "IN_PROGRESS":       ("#6a1b9a", "white"),
    "READY":             ("#00897b", "white"),
    "COMPLETED":         ("#2e7d32", "white"),
    "CANCELED":          ("#c62828", "white"),
}
PRIMARY_COLOR = "#1976d2"
SURFACE_BG   = "#f7f7fb"

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
    lbl = tk.Label(parent, text=f"  {status}  ", bg=bg, fg=fg, font=("Tahoma", 10, "bold"))
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
        return datetime.datetime.utcnow()

SETTINGS_PATH = DATA_DIR / "config.json"
DEFAULT_SETTINGS = {
    "company": "ATTA Repair",
    "currency": "SAR",
    "use_shop_number_for_qr": False,
    "shop_number": "9665XXXXXXXX",
    "label_printer": "",
    "whatsapp_auto_send": True,          # Auto send enabled by default
    "whatsapp_auto_delay_ms": 1200,      # ↑ زودنا الافتراضي لضمان لصق النص
    "wa_fill_via_clipboard": True,
    "wa_press_enter": True,
    "win_prefs": {}
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
        SETTINGS_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
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
  status TEXT NOT NULL DEFAULT 'NEW',
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

def db_init():
    con = db_conn(); cur = con.cursor()
    cur.executescript(SCHEMA)
    cur.execute("SELECT COUNT(*) FROM branches"); n = cur.fetchone()[0]
    if n == 0:
        cur.execute("INSERT INTO branches(name,code) VALUES(?,?)", ("فرع البوليفارد","A"))
        cur.execute("INSERT INTO branches(name,code) VALUES(?,?)", ("فرع السوق","B"))
        con.commit()
        cur.execute("SELECT id FROM branches WHERE code='A'"); b1 = cur.fetchone()[0]
        cur.execute("SELECT id FROM branches WHERE code='B'"); b2 = cur.fetchone()[0]
        def seed_user(bid, username, pwd):
            if bcrypt:
                ph = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
            else:
                ph = pwd
            cur.execute("INSERT INTO users(branch_id,username,password,role) VALUES(?,?,?,?)", (bid, username, ph, "admin"))
        seed_user(b1, "A1", "123")
        seed_user(b2, "A2", "123")
    con.commit(); con.close()
import urllib.request, json, tempfile, os, subprocess, sys

UPDATE_CHECK_URL = "hhttp://localhost:8000/version.json"  # رفع ملف JSON هنا

def check_for_updates(silent=False):
    try:
        with urllib.request.urlopen(UPDATE_CHECK_URL, timeout=6) as r:
            info = json.load(r)
        latest = info.get("version")
        url = info.get("installer_url")
        notes = info.get("notes","")
        if latest and url and latest != __version__:
            # نلاحظ وجود نسخة أحدث
            # نحمّل المثبّت إلى ملف مؤقت
            fn = os.path.join(tempfile.gettempdir(), f"repairdesk_setup_{latest}.exe")
            urllib.request.urlretrieve(url, fn)
            # يمكن تشغيله بصمت أو بعرض رسالة
            if silent:
                subprocess.Popen([fn, "/VERYSILENT", "/NORESTART"])
                sys.exit(0)
            else:
                from tkinter import messagebox
                if messagebox.askyesno("تحديث متوفر", f"النسخة {latest} متاحة.\nتريد تنزيل وتثبيت الآن؟\n\n{notes}"):
                    subprocess.Popen([fn])  # يفتح المثبّت لموافقة المستخدم
                    sys.exit(0)
    except Exception:
        pass

# ---------------------- Helpers -----------------------
def random_otp(k=6):
    return ''.join(random.choice(string.digits) for _ in range(k))

def generate_receipt_no(branch_code: str) -> str:
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT receipt_no FROM receipts WHERE receipt_no LIKE ? ORDER BY id DESC LIMIT 1", (f"{branch_code}%",))
    row = cur.fetchone(); con.close()
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
    digits = ''.join(ch for ch in num if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    return digits

def make_whatsapp_initial_text(receipt_no: str, device: str, issue: str, otp: str, tracking_hint: str) -> str:
    return (
        f"السلام عليكم\n"
        f"تم فتح سند صيانة رقم: {receipt_no}\n"
        f"الجهاز: {device}\n"
        f"العطل: {issue}\n"
        f"رمز الاستلام: {otp}\n"
        f"تتبع: {tracking_hint}"
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
    press_enter   = bool(SETTINGS.get("wa_press_enter", True))
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
    digits = ''.join(ch for ch in phone_digits if ch.isdigit())
    msg = message_text.replace('\r\n', '\n').strip()
    uri = f"whatsapp://send?phone={digits}&text={ul.quote(msg, safe='')}"
    try:
        if platform.system() == "Windows":
            os.startfile(uri)
            _schedule_auto_send(msg)  # نمرّر النص للّصق
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", uri]); _schedule_auto_send(None)
        else:
            subprocess.Popen(["xdg-open", uri]); _schedule_auto_send(None)
        return True
    except Exception as e:
        logging.error(f"WhatsApp desktop open failed: {e}")
    try:
        webbrowser.open(f"https://wa.me/{digits}?text={ul.quote(msg, safe='')}")
        return True
    except Exception as e:
        logging.error(f"WhatsApp web fallback failed: {e}")
        return False

# ---------------------- Direct Print (ONLY) -------------------
def get_available_printers():
    if not PYWIN32_OK:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags)
    names = []
    for p in printers:
        try:
            names.append(p[2])
        except Exception:
            pass
    return sorted(set(names))

def get_target_printer_name():
    if not PYWIN32_OK:
        return None
    name = (SETTINGS.get("label_printer") or "").strip()
    if name:
        return name
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return None

def direct_print_label(receipt_no: str, phone: str) -> None:
    phone = "".join(ch for ch in phone if ch.isdigit())
    if not PYWIN32_OK:
        raise RuntimeError("الطباعة المباشرة تحتاج pywin32.\nثبتها بالأمر:\npip install pywin32")

    printer_name = get_target_printer_name()
    if not printer_name:
        raise RuntimeError("لم يتم العثور على طابعة. تأكد أن طابعة Zebra GC420t معرفة على ويندوز واخترها من Settings.")

    # كود ZPL بسيط للملصق 40×20 مم
    zpl = f"""
^XA
^PW400
^LH0,0
^CI28
^FO30,15^A0N,55,55^FD{receipt_no}^FS
^FO30,70^BCN,80,Y,N,N^FD{receipt_no}^FS
^FO30,165^A0N,28,28^FD{phone}^FS
^XZ
"""

    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Label", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        win32print.WritePrinter(hPrinter, zpl.encode("utf-8"))
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)


# ---------------------- Activity Log ---------------------------
def log_activity(receipt_id: int, kind: str, info: str, by_username: str):
    try:
        con = db_conn(); cur = con.cursor()
        cur.execute("""
            INSERT INTO activity_log(receipt_id, kind, info, at_utc, by_username)
            VALUES(?,?,?,?,?)
        """, (receipt_id, kind, info, datetime.datetime.utcnow().isoformat(), by_username))
        con.commit(); con.close()
    except Exception as e:
        logging.error(f"activity_log insert failed: {e}")

# ============================ UI ===============================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {MADE_BY}")
        self.configure(bg=SURFACE_BG)

        try:
            if platform.system() == "Windows":
                self.state('zoomed')
            else:
                self.attributes("-zoomed", True)
        except Exception:
            self.geometry("1280x800")

        self.active_user = None
        self.active_branch = None
        self.shop_mode_var = tk.BooleanVar(value=SETTINGS.get("use_shop_number_for_qr", False))
        self.wa_auto_var = tk.BooleanVar(value=SETTINGS.get("whatsapp_auto_send", True))
        self.wa_clip_var  = tk.BooleanVar(value=SETTINGS.get("wa_fill_via_clipboard", True))
        self.wa_enter_var = tk.BooleanVar(value=SETTINGS.get("wa_press_enter", True))
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
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
        self.style.configure("Card.TFrame", background="white", relief="groove", borderwidth=1)
        self.style.configure("TLabel", background=SURFACE_BG, font=("Tahoma", 10))
        self.style.configure("Card.TLabel", background="white", font=("Tahoma", 10))
        self.style.configure("Header.TLabel", background=PRIMARY_COLOR, foreground="white", font=("Tahoma", 14, "bold"))
        self.style.configure("Title.TLabel", font=("Tahoma", 20, "bold"))
        self.style.configure("TButton", padding=8, font=("Tahoma", 10))
        self.style.configure("Primary.TButton", padding=10, font=("Tahoma", 10, "bold"), foreground="white", background=PRIMARY_COLOR)
        self.style.map("Primary.TButton",
                       background=[('disabled', '#9bbbe7'), ('active', '#1565c0'), ('!disabled', PRIMARY_COLOR)],
                       foreground=[('!disabled', 'white')])
        self.style.configure("Treeview.Heading", font=("Tahoma", 10, "bold"))
        self.style.configure("Treeview", rowheight=26)

    def header_bar(self, parent, text_left="", text_right=""):
        bar = tk.Frame(parent, bg=PRIMARY_COLOR, height=48)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure(1, weight=0)
        tk.Label(bar, text=text_left, bg=PRIMARY_COLOR, fg="white", font=("Tahoma", 13, "bold")).grid(row=0, column=0, sticky="w", padx=16, pady=10)
        if text_right:
            tk.Label(bar, text=text_right, bg=PRIMARY_COLOR, fg="white", font=("Tahoma", 10)).grid(row=0, column=1, padx=16)
        return bar

    def card(self, parent, padding=16):
        return ttk.Frame(parent, style="Card.TFrame", padding=padding)

    # ---------- Menus ----------
    def build_menubar(self):
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="📦 Backup DB", command=self.backup_db)
        m_file.add_command(label="⬇️ Export Receipts (CSV)", command=self.export_csv)
        m_file.add_command(label="📂 Open Data Folder", command=lambda: self._open_path(str(DATA_DIR)))
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=m_file)

        m_set = tk.Menu(menubar, tearoff=0)
        m_set.add_checkbutton(label="Use Shop Number for QR (customer chats with shop)",
                              variable=self.shop_mode_var, command=self.toggle_shop_mode)
        m_set.add_command(label="Set Shop Number", command=self.set_shop_number)
        m_set.add_command(label="Set Company Name", command=self.set_company)
        m_set.add_command(label="Set Currency", command=self.set_currency)
        m_set.add_command(label="Select Label Printer", command=self.select_label_printer)
        m_set.add_separator()
        m_set.add_checkbutton(label="Send WhatsApp automatically (Enter/Paste)", variable=self.wa_auto_var, command=self.toggle_wa_auto)
        m_set.add_checkbutton(label="Fill message via Clipboard (no ?text)", variable=self.wa_clip_var, command=lambda: self._toggle_bool_setting("wa_fill_via_clipboard", self.wa_clip_var.get()))
        m_set.add_checkbutton(label="Press Enter automatically", variable=self.wa_enter_var, command=lambda: self._toggle_bool_setting("wa_press_enter", self.wa_enter_var.get()))
        m_set.add_command(label="Set WhatsApp auto-send delay (ms)", command=self.set_wa_delay)
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
        val = simpledialog.askinteger("Auto-Send Delay (ms)", "Delay before pasting + pressing Enter in WhatsApp:", initialvalue=curr, minvalue=300, maxvalue=5000, parent=self)
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
        num = simpledialog.askstring("Shop Number", "Enter shop number (digits only, international like 9665xxxxxxxx):", parent=self)
        if not num:
            return
        digits = normalize_phone(num)
        if not re.fullmatch(r"9665\d{8}", digits):
            messagebox.showerror("صيغة غير صحيحة", "الرجاء إدخال رقم بصيغة دولية يبدأ بـ 9665 ويتبعه 8 أرقام.\nمثال: 9665XXXXXXXX")
            return
        SETTINGS["shop_number"] = digits
        save_settings(SETTINGS)
        messagebox.showinfo("تم", f"تم حفظ رقم المحل: {SETTINGS['shop_number']}")

    def set_company(self):
        nm = simpledialog.askstring("Company Name", "Your company display name:", parent=self)
        if nm:
            SETTINGS["company"] = nm.strip()
            save_settings(SETTINGS)

    def set_currency(self):
        cur = simpledialog.askstring("Currency", "Currency code (e.g., SAR):", parent=self)
        if cur:
            SETTINGS["currency"] = cur.strip().upper()
            save_settings(SETTINGS)

    def select_label_printer(self):
        if not PYWIN32_OK:
            messagebox.showerror("الطباعة", "تحتاج pywin32 لاختيار الطابعة.\nثبت:\npip install pywin32")
            return
        printers = get_available_printers()
        if not printers:
            messagebox.showerror("الطباعة", "لا توجد طابعات متاحة على هذا الجهاز.")
            return
        dlg = tk.Toplevel(self); dlg.title("اختر طابعة الملصقات"); dlg.transient(self); dlg.grab_set()
        dlg.geometry("420x380"); dlg.configure(bg=SURFACE_BG)
        tk.Label(dlg, text="اختر الطابعة التي تريد استخدامها لطباعة الملصق 40×20.3 مم", bg=SURFACE_BG).pack(padx=10, pady=10)
        lb = tk.Listbox(dlg, height=12)
        lb.pack(fill="both", expand=True, padx=10, pady=6)
        curr = SETTINGS.get("label_printer","")
        sel_index = 0
        for i, name in enumerate(printers):
            lb.insert("end", name)
            if name == curr: sel_index = i
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
        messagebox.showinfo("About", f"{APP_NAME}\n{MADE_BY}\nData: {DATA_DIR}\nLog: {LOG_PATH}\n"
                                     f"Label printer: {SETTINGS.get('label_printer') or '(Default)'}\n"
                                     f"WA auto-send: {'ON' if SETTINGS.get('whatsapp_auto_send', True) else 'OFF'} "
                                     f"({SETTINGS.get('whatsapp_auto_delay_ms', 1200)} ms)")

    # ---------- Login ----------
    def create_login(self):
        self.clear()
        self.build_menubar()

        root = ttk.Frame(self, padding=0)
        root.pack(fill="both", expand=True)
        bar = self.header_bar(root, text_left=APP_NAME, text_right=MADE_BY)
        bar.pack(fill="x")

        wrap = ttk.Frame(root, padding=24, style="TFrame")
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        card = self.card(wrap, padding=20)
        card.grid(row=0, column=0, ipadx=6, ipady=6, sticky="n")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="اسم المستخدم:", style="Card.TLabel").grid(row=0, column=0, sticky='e', padx=8, pady=8)
        user_e = ttk.Entry(card, width=32); user_e.grid(row=0, column=1, sticky='w', padx=8, pady=8)
        ttk.Label(card, text="كلمة المرور:", style="Card.TLabel").grid(row=1, column=0, sticky='e', padx=8, pady=8)
        pass_e = ttk.Entry(card, show='*', width=32); pass_e.grid(row=1, column=1, sticky='w', padx=8, pady=8)

        def do_login():
            con = db_conn(); cur = con.cursor()
            cur.execute("SELECT id,branch_id,username,password,role FROM users WHERE username=?", (user_e.get(),))
            row = cur.fetchone(); con.close()
            if not row or not password_matches(row[3], pass_e.get()):
                messagebox.showerror("خطأ", "بيانات الدخول غير صحيحة"); return
            if bcrypt and not row[3].startswith("$2"):
                try:
                    con = db_conn(); cur = con.cursor()
                    cur.execute("UPDATE users SET password=? WHERE id=?", (hash_password_if_possible(pass_e.get()), row[0]))
                    con.commit(); con.close()
                except Exception as e:
                    logging.error(f"Hash upgrade failed: {e}")
            self.active_user = {"id": row[0], "branch_id": row[1], "username": row[2], "role": row[4]}
            con = db_conn(); cur = con.cursor()
            cur.execute("SELECT id,name,code FROM branches WHERE id=?", (row[1],))
            b = cur.fetchone(); con.close()
            self.active_branch = {"id": b[0], "name": b[1], "code": b[2]}
            self.create_dashboard()

        ttk.Button(card, text="دخول", style="Primary.TButton", command=do_login).grid(row=2, column=0, columnspan=2, pady=12, sticky="ew")
        ttk.Label(card, text="فرع البوليفارد A1/123 — فرع السوق A2/123", style="Card.TLabel", foreground="#666").grid(row=3, column=0, columnspan=2)

    # ---------- Dashboard ----------
    def create_dashboard(self):
        self.clear(); self.build_menubar()

        root = ttk.Frame(self, padding=0)
        root.pack(fill="both", expand=True)

        bar = self.header_bar(root, text_left=f"لوحة التحكم — {self.active_branch['name']}", text_right=self.active_user['username'])
        bar.pack(fill="x")

        main = ttk.Frame(root, padding=16)
        main.pack(fill="both", expand=True)
        main.rowconfigure(2, weight=1)
        main.columnconfigure(0, weight=1)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="ew", pady=(0,8))
        ttk.Button(top, text="➕ سند جديد", style="Primary.TButton", command=self.create_new_receipt).pack(side='left', padx=4)
        ttk.Button(top, text="📄 جميع السندات", command=self.list_receipts).pack(side='left', padx=4)
        ttk.Button(top, text="📦 نسخة احتياطية", command=self.backup_db).pack(side='left', padx=4)
        ttk.Button(top, text="🚪 خروج", command=self.create_login).pack(side='right', padx=4)

        con = db_conn(); cur = con.cursor()
        counts = {s:0 for s in STATUS_ORDER}
        cur.execute("SELECT status, COUNT(*) FROM receipts WHERE branch_id=? GROUP BY status", (self.active_branch['id'],))
        for st,cnt in cur.fetchall():
            counts[st] = cnt
        con.close()

        chips = ttk.Frame(main); chips.grid(row=1, column=0, sticky="ew", pady=6)
        for st in STATUS_ORDER:
            bg, fg = status_colors(st)
            tk.Label(chips, text=f"{st}: {counts.get(st,0)}", bg=bg, fg=fg, padx=10, pady=5, font=("Tahoma", 9, "bold")).pack(side='left', padx=4)

        center = ttk.Frame(main); center.grid(row=2, column=0, sticky="nsew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        welcome = self.card(center, padding=24); welcome.grid(row=0, column=0, sticky="nsew")
        ttk.Label(welcome, text="مرحبًا بك في نظام ركن الذاكرة للصيانة", style="Card.TLabel", font=("Tahoma", 12)).pack()

    # ---------- New Receipt ----------
    def create_new_receipt(self):
        win = tk.Toplevel(self); win.title("سند صيانة جديد — " + MADE_BY); win.configure(bg=SURFACE_BG)
        win.geometry("1000x760")
        self.header_bar(win, text_left="سند صيانة جديد").pack(fill="x")

        main = ttk.Frame(win, padding=14); main.pack(fill='both', expand=True)
        main.columnconfigure(1, weight=1)

        sec1 = self.card(main); sec1.grid(row=0, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(sec1, text="العميل", style="Card.TLabel", font=("Tahoma", 11, 'bold')).grid(row=0, column=0, sticky='w', pady=4)
        ttk.Label(sec1, text="الاسم:", style="Card.TLabel").grid(row=1, column=0, sticky='e', padx=5, pady=3)
        name_e = ttk.Entry(sec1); name_e.grid(row=1, column=1, sticky='ew', padx=5, pady=3)
        ttk.Label(sec1, text="جوال (9665..):", style="Card.TLabel").grid(row=2, column=0, sticky='e', padx=5, pady=3)
        phone_e = ttk.Entry(sec1); phone_e.grid(row=2, column=1, sticky='ew', padx=5, pady=3)
        sec1.columnconfigure(1, weight=1)

        sec2 = self.card(main); sec2.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(sec2, text="الجهاز", style="Card.TLabel", font=("Tahoma", 11, 'bold')).grid(row=0, column=0, sticky='w', pady=4)
        labels = ["النوع","الماركة","الموديل","Serial/IMEI","اللون","الملحقات"]
        dev_e = {}
        for i,lbl in enumerate(labels):
            ttk.Label(sec2, text=lbl+":", style="Card.TLabel").grid(row=1+i, column=0, sticky='e', padx=5, pady=3)
            e = ttk.Entry(sec2); e.grid(row=1+i, column=1, sticky='ew', padx=5, pady=3); dev_e[lbl]=e
        sec2.columnconfigure(1, weight=1)

        sec3 = self.card(main); sec3.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=6)
        sec3.columnconfigure(1, weight=1)
        ttk.Label(sec3, text="تفاصيل الصيانة", style="Card.TLabel", font=("Tahoma", 11, 'bold')).grid(row=0, column=0, sticky='w', pady=4)
        ttk.Label(sec3, text="وصف العطل:", style="Card.TLabel").grid(row=1, column=0, sticky='ne', padx=5, pady=3)
        issue_t = tk.Text(sec3, height=4); issue_t.grid(row=1, column=1, sticky='nsew', padx=5, pady=3)
        ttk.Label(sec3, text="المطلوب إصلاحه:", style="Card.TLabel").grid(row=2, column=0, sticky='ne', padx=5, pady=3)
        work_t  = tk.Text(sec3, height=3); work_t.grid(row=2, column=1, sticky='nsew', padx=5, pady=3)

        amt_fr = ttk.Frame(sec3); amt_fr.grid(row=3, column=1, sticky='w', padx=5, pady=4)
        ttk.Label(sec3, text="التكلفة التقديرية:", style="Card.TLabel").grid(row=3, column=0, sticky='e', padx=5, pady=4)
        amt_e = ttk.Entry(amt_fr, width=12); amt_e.insert(0, "0"); amt_e.pack(side='left')
        ttk.Label(amt_fr, text=SETTINGS.get("currency","SAR")).pack(side='left', padx=6)

        def save():
            name = name_e.get().strip(); phone_raw = phone_e.get().strip()
            if not name or not phone_raw:
                messagebox.showerror("خطأ", "ادخل اسم العميل وجواله"); return
            phone = normalize_phone(phone_raw)
            if not phone:
                messagebox.showerror("خطأ", "صيغة الجوال غير صحيحة (أرقام فقط دولي)"); return
            dev_type = dev_e["النوع"].get().strip(); brand = dev_e["الماركة"].get().strip(); model = dev_e["الموديل"].get().strip()
            if not dev_type or not brand or not model:
                messagebox.showerror("خطأ", "اكمل بيانات الجهاز (النوع/الماركة/الموديل)"); return
            serial = dev_e["Serial/IMEI"].get().strip(); color = dev_e["اللون"].get().strip(); acc = dev_e["الملحقات"].get().strip()
            issue = issue_t.get("1.0","end").strip(); work = work_t.get("1.0","end").strip()
            try:
                est = float(amt_e.get())
            except:
                messagebox.showerror("خطأ", "التكلفة التقديرية رقم"); return

            con = db_conn(); cur = con.cursor()
            cur.execute("SELECT id,name FROM customers WHERE phone=?", (phone,))
            row = cur.fetchone()
            if row:
                cust_id = row[0]
                if row[1] != name:
                    cur.execute("UPDATE customers SET name=? WHERE id=?", (name, cust_id))
            else:
                cur.execute("INSERT INTO customers(name,phone) VALUES(?,?)", (name, phone)); cust_id = cur.lastrowid

            cur.execute(
                "INSERT INTO devices(customer_id,type,brand,model,serial_imei,color,accessories) VALUES(?,?,?,?,?,?,?)",
                (cust_id, dev_type, brand, model, serial or None, color or None, acc or None)
            )
            dev_id = cur.lastrowid

            rno = generate_receipt_no(self.active_branch['code'])
            otp = random_otp()
            tracking_hint = f"{SETTINGS.get('company','ATTA')} — أحضر رقم السند والرمز"
            initial_text = make_whatsapp_initial_text(rno, f"{brand} {model}", issue, otp, tracking_hint)
            wa = f"whatsapp://send?phone={phone}&text={ul.quote(initial_text,safe='')}"
            qr_path = make_qr(wa, f"{rno}.png") if qrcode else ""
            now = datetime.datetime.utcnow().isoformat()
            cur.execute("""
                INSERT INTO receipts(
                    branch_id,customer_id,device_id,receipt_no,issue_desc,work_request,est_amount,status,
                    otp_code,whatsapp_link,qr_path,signature_path,created_utc
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (self.active_branch['id'], cust_id, dev_id, rno, issue, work, est, 'NEW', otp, wa, qr_path, None, now))
            rid = cur.lastrowid
            cur.execute("INSERT INTO status_history(receipt_id,from_status,to_status,at_utc,by_username) VALUES(?,?,?,?,?)",
                        (rid, None, 'NEW', now, self.active_user['username']))
            con.commit(); con.close()
            log_activity(rid, "CREATE", f"Receipt created with no {rno}", self.active_user['username'])

            messagebox.showinfo("تم", f"تم إنشاء السند: {rno}\nتم تجهيز رسالة واتساب ورمز OTP: {otp}")
            win.destroy(); self.open_receipt(rid)

        actions = ttk.Frame(main); actions.grid(row=10, column=0, columnspan=2, sticky='e', pady=8)
        ttk.Button(actions, text="حفظ وإنشاء السند", style="Primary.TButton", command=save).pack(side='right')

    # ---------- List/Search ----------
    def list_receipts(self):
        self.clear(); self.build_menubar()

        root = ttk.Frame(self, padding=0); root.pack(fill='both', expand=True)
        self.header_bar(root, text_left="قائمة السندات").pack(fill="x")

        content = ttk.Frame(root, padding=12); content.pack(fill='both', expand=True)
        content.rowconfigure(2, weight=1); content.columnconfigure(0, weight=1)

        top = ttk.Frame(content); top.grid(row=0, column=0, sticky='ew', pady=6)
        ttk.Label(top, text="بحث:").pack(side='left')
        q_e = ttk.Entry(top, width=40); q_e.pack(side='left', padx=5)
        status_cmb = ttk.Combobox(top, values=[""]+STATUS_ORDER, width=22); status_cmb.pack(side='left', padx=5)
        ttk.Button(top, text="بحث", command=lambda: refresh()).pack(side='left', padx=5)
        # Barcode quick open
        barf = ttk.Frame(content); barf.grid(row=1, column=0, sticky='ew', pady=6)
        ttk.Label(barf, text='مسح باركود:').pack(side='left')
        bc_entry = ttk.Entry(barf, width=30)
        bc_entry.pack(side='left', padx=5)
        def _open_bc(*_):
            val = bc_entry.get().strip()
            if val:
                try:
                    self.open_receipt_by_no(val)
                except Exception as e:
                    messagebox.showerror('Barcode', f'تعذر فتح السند: {e}')
        bc_entry.bind('<Return>', _open_bc)
        ttk.Button(barf, text='🔎 فتح من الباركود', command=_open_bc).pack(side='left', padx=4)
        ttk.Button(top, text="⬇️ Export CSV", command=self.export_csv).pack(side='left', padx=5)
        ttk.Button(top, text="📦 Backup DB", command=self.backup_db).pack(side='left', padx=5)
        ttk.Button(top, text="⬅️ رجوع", command=self.create_dashboard).pack(side='right', padx=5)

        table_wrap = ttk.Frame(content)
        table_wrap.grid(row=2, column=0, sticky='nsew')
        tree = ttk.Treeview(table_wrap, columns=("no","created","cust","dev","status","est"), show='headings')
        widths = {"no":120, "created":170, "cust":260, "dev":260, "status":120, "est":120}
        headers = {"no":"رقم السند","created":"تاريخ الإنشاء","cust":"العميل","dev":"الجهاز","status":"الحالة","est":"التقدير"}
        for col in ("no","created","cust","dev","status","est"):
            tree.column(col, width=widths[col], anchor="w")
            tree.heading(col, text=headers[col])
        add_treeview_scrollbars(table_wrap, tree)
        apply_treeview_tag_styles(tree)

        def refresh():
            q = q_e.get().strip().lower()
            st = status_cmb.get().strip()
            con = db_conn(); cur = con.cursor()
            cur.execute("""
                SELECT r.id,r.receipt_no,c.name,c.phone,d.brand,d.model,r.status,r.est_amount,r.created_utc
                FROM receipts r
                JOIN customers c ON r.customer_id=c.id
                JOIN devices d   ON r.device_id=d.id
                WHERE r.branch_id=?
                ORDER BY r.id DESC
            """, (self.active_branch['id'],))
            rows = cur.fetchall(); con.close()
            for i in tree.get_children(): tree.delete(i)
            for r in rows:
                created_utc = parse_utc_iso(r[8]) if r[8] else datetime.datetime.utcnow()
                created_local = to_riyadh(created_utc)
                created_str = fmt_dt(created_local)
                blob = " ".join(map(str,[r[1],r[2],r[3],r[4],r[5],created_str])).lower()
                if q and q not in blob: continue
                if st and r[6] != st: continue
                tree.insert('', 'end', iid=str(r[0]),
                            values=(r[1], created_str, f"{r[2]} ({r[3]})", f"{r[4]} {r[5]}", r[6], f"{r[7]:.2f} {SETTINGS.get('currency','SAR')}"),
                            tags=(r[6],))
        refresh()
        tree.bind('<Double-1>', lambda e: self.open_receipt(int(tree.focus())))

    # ---------- Export / Backup ----------
    def export_csv(self):
        con = db_conn(); cur = con.cursor()
        cur.execute("""
            SELECT r.receipt_no,c.name,c.phone,d.brand,d.model,r.status,r.est_amount,r.created_utc,r.delivered_utc
            FROM receipts r
            JOIN customers c ON r.customer_id=c.id
            JOIN devices d   ON r.device_id=d.id
            WHERE r.branch_id=?
            ORDER BY r.id DESC
        """, (self.active_branch['id'],))
        rows = cur.fetchall(); con.close()
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = EXPORTS_DIR / f"receipts_{self.active_branch['code']}_{ts}.csv"
        with path.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(["receipt_no","customer","phone","brand","model","status","est_amount","created_utc","delivered_utc"])
            for r in rows: w.writerow(r)
        messagebox.showinfo("تم", f"تم التصدير: {path}")
        self._open_path(str(path))

    def backup_db(self):
        if not DB_PATH.exists():
            messagebox.showwarning("تنبيه","لا يوجد ملف قاعدة بيانات بعد"); return
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = BACKUP_DIR / f"repairdesk_{ts}.db"
        shutil.copy2(DB_PATH, dst)
        messagebox.showinfo("تم", f"تم إنشاء نسخة احتياطية: {dst}")

    # ---------- Receipt Detail ----------
    def open_receipt_by_no(self, receipt_no: str):
        receipt_no = receipt_no.strip()
        con = db_conn(); cur = con.cursor()
        cur.execute("SELECT id FROM receipts WHERE receipt_no = ? LIMIT 1", (receipt_no,))
        row = cur.fetchone(); con.close()
        if not row:
            raise ValueError(f"لا يوجد سند برقم {receipt_no}")
        self.open_receipt(int(row[0]))

    def open_receipt(self, rid: int):
        win = tk.Toplevel(self); win.title(f"السند #{rid} — {MADE_BY}"); win.configure(bg=SURFACE_BG)
        default_geo = "1200x800+100+60"
        geo, state = get_win_pref("receipt_window", default_geo, "normal")
        try:
            if state == "zoomed": win.state('zoomed')
            else:
                win.state('normal')
                if geo: win.geometry(geo)
        except Exception:
            win.geometry(default_geo)

        save_after_id = {"id": None}
        def schedule_save_prefs(_evt=None):
            if save_after_id["id"]:
                win.after_cancel(save_after_id["id"])
            def _save():
                try: cur_state = win.state()
                except Exception: cur_state = "normal"
                cur_geo = win.geometry()
                set_win_pref("receipt_window", cur_geo, cur_state)
            save_after_id["id"] = win.after(600, _save)
        win.bind("<Configure>", schedule_save_prefs)

        self.header_bar(win, text_left=f"تفاصيل السند").pack(fill="x")

        # === Scrollable content for the whole receipt screen ===
        scroll_container, root = make_vscrollable(win, bg=SURFACE_BG)
        scroll_container.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)

        con = db_conn(); cur = con.cursor()
        cur.execute("""
            SELECT receipt_no,customer_id,device_id,issue_desc,work_request,est_amount,status,otp_code,
                   whatsapp_link,qr_path,signature_path,created_utc,delivered_utc
            FROM receipts WHERE id=?
        """, (rid,))
        r = cur.fetchone()
        if not r:
            con.close(); messagebox.showerror("خطأ","السند غير موجود"); return
        receipt_no, cust_id, dev_id, issue, work, est, status, otp, wa, qr_path, sig_path, created, delivered = r
        cur.execute("SELECT name,phone FROM customers WHERE id=?", (cust_id,))
        c = cur.fetchone()
        cur.execute("SELECT type,brand,model,serial_imei,color,accessories FROM devices WHERE id=?", (dev_id,))
        d = cur.fetchone()
        con.close()

        created_utc = parse_utc_iso(created)
        created_local = to_riyadh(created_utc)
        warranty_end_utc = created_utc + datetime.timedelta(days=WARRANTY_DAYS)
        warranty_end_local = to_riyadh(warranty_end_utc)
        now_utc = datetime.datetime.utcnow()
        warranty_valid = now_utc <= warranty_end_utc

        info = self.card(root); info.grid(row=0, column=0, sticky="ew", pady=6)
        ttk.Label(info, text=f"رقم السند: {receipt_no}", style="Card.TLabel", font=("Tahoma", 13,'bold')).grid(row=0, column=0, sticky='w', padx=6, pady=4)
        make_status_badge(info, status, layout="grid", row=0, column=1, sticky='e', padx=8, pady=4)
        ttk.Label(info, text=f"العميل: {c[0]} — {c[1]}", style="Card.TLabel").grid(row=1, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        ttk.Label(info, text=f"الجهاز: {d[0]} — {d[1]} {d[2]} | IMEI: {d[3] or '-'} | اللون: {d[4] or '-'} | الملحقات: {d[5] or '-'}", style="Card.TLabel").grid(row=2, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        ttk.Label(info, text=f"العطل: {issue}", style="Card.TLabel").grid(row=3, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        ttk.Label(info, text=f"المطلوب: {work}", style="Card.TLabel").grid(row=4, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        ttk.Label(info, text=f"التقدير: {est:.2f} {SETTINGS.get('currency','SAR')}", style="Card.TLabel").grid(row=5, column=0, columnspan=2, sticky='w', padx=6, pady=2)
        info.columnconfigure(0, weight=1); info.columnconfigure(1, weight=1)

        warr = self.card(root); warr.grid(row=1, column=0, sticky='ew', pady=6)
        ttk.Label(warr, text="الضمان", style="Card.TLabel", font=("Tahoma", 11,'bold')).grid(row=0, column=0, sticky='w', padx=6, pady=2)
        ttk.Label(warr, text=f"تاريخ الإنشاء (UTC): {fmt_dt(created_utc)}", style="Card.TLabel").grid(row=1, column=0, sticky='w', padx=6, pady=2)
        ttk.Label(warr, text=f"التوقيت المحلي (الرياض): {fmt_dt(created_local)}", style="Card.TLabel").grid(row=2, column=0, sticky='w', padx=6, pady=2)
        ttk.Label(warr, text=f"نهاية الضمان (الرياض): {fmt_dt(warranty_end_local)}", style="Card.TLabel").grid(row=3, column=0, sticky='w', padx=6, pady=2)
        warr_bg = "#2e7d32" if warranty_valid else "#c62828"
        state_txt = "ساري" if warranty_valid else "منتهٍ"
        tk.Label(warr, text=f"  حالة الضمان: {state_txt}  ", bg=warr_bg, fg="white", font=("Tahoma", 10, "bold")).grid(row=0, column=1, rowspan=4, sticky='e', padx=10)
        warr.columnconfigure(0, weight=1); warr.columnconfigure(1, weight=1)

        ttk.Label(root, text=f"OTP: {otp}", foreground="#333", background=SURFACE_BG).grid(row=2, column=0, sticky='w', padx=6, pady=(0,6))

        actions = self.card(root); actions.grid(row=3, column=0, sticky='ew', pady=6)
        actions.columnconfigure(0, weight=0); actions.columnconfigure(1, weight=1)

        status_cmb = ttk.Combobox(actions, values=STATUS_ORDER, width=25); status_cmb.set(status)
        status_cmb.grid(row=0, column=0, sticky='w', padx=(0,8), pady=6)

        def wa_initial():
            text = make_whatsapp_initial_text(receipt_no, f"{d[1]} {d[2]}", issue, otp, f"{SETTINGS.get('company','ATTA')} — أحضر رقم السند والرمز")
            ok = open_whatsapp_desktop(c[1], text)
            log_activity(rid, "WA_INITIAL", "desktop://" if ok else "fallback://", self.active_user['username'])

        def wa_ready():
            text = make_ready_text(receipt_no, f"{d[1]} {d[2]}", otp, SETTINGS.get('company','ATTA'))
            ok = open_whatsapp_desktop(c[1], text)
            log_activity(rid, "WA_READY", "desktop://" if ok else "fallback://", self.active_user['username'])
        def wa_delivered():
            text = make_delivered_text(receipt_no, f"{d[1]} {d[2]}", SETTINGS.get('company','ATTA'))
            ok = open_whatsapp_desktop(c[1], text)
            log_activity(rid, "WA_DELIVERED", "desktop://" if ok else "fallback://", self.active_user['username'])

        btns = ttk.Frame(actions); btns.grid(row=0, column=1, sticky='w')
        ttk.Button(btns, text="📲 رسالة فتح السند", command=wa_initial).pack(side='left', padx=3)
        ttk.Button(btns, text="📣 إشعار الجاهزية", command=wa_ready).pack(side='left', padx=3)
        ttk.Button(btns, text="📩 تأكيد التسليم", command=wa_delivered).pack(side='left', padx=3)

        def update_status():
            newst = status_cmb.get().strip()
            if newst not in STATUS_ORDER: return
            con = db_conn(); cur = con.cursor()
            con_now = datetime.datetime.utcnow().isoformat()
            cur.execute("UPDATE receipts SET status=?, delivered_utc=? WHERE id=?", (newst, con_now if newst=='COMPLETED' else None, rid))
            cur.execute("INSERT INTO status_history(receipt_id,from_status,to_status,at_utc,by_username) VALUES(?,?,?,?,?)",
                        (rid, status, newst, con_now, self.active_user['username']))
            con.commit(); con.close()
            log_activity(rid, "STATUS", f"{status} -> {newst}", self.active_user['username'])
            if newst == 'READY':
                try:
                    if messagebox.askyesno("إشعار الجاهزية", "تم تعيين الحالة إلى READY. هل تريد إرسال رسالة جاهزية للعميل؟"):
                        wa_ready()
                except Exception: pass
            messagebox.showinfo("تم", "تم تحديث الحالة")
            win.destroy(); self.list_receipts()

        ttk.Button(actions, text="تحديث الحالة", style="Primary.TButton", command=update_status).grid(row=0, column=2, sticky='e', padx=8)

        tools = self.card(root); tools.grid(row=4, column=0, sticky='ew', pady=6)
        ttk.Label(tools, text="أدوات", style="Card.TLabel", font=("Tahoma", 11,'bold')).pack(anchor="w")
        def do_print_receipt_label():
            try:
                direct_print_label(receipt_no, c[1])
                messagebox.showinfo("تم", "أُرسلت مهمة الطباعة مباشرة إلى الطابعة المحددة.")
            except Exception as e:
                messagebox.showerror("خطأ الطباعة", str(e))
        ttk.Button(tools, text="🖨️ طباعة ملصق (مباشر)", command=do_print_receipt_label).pack(side='left', padx=5, pady=6)

        def deliver():
            pop = tk.Toplevel(win); pop.title("تسليم الجهاز"); pop.configure(bg=SURFACE_BG)
            ttk.Label(pop, text="أدخل رمز الاستلام OTP:").pack(padx=10, pady=8)
            entry = ttk.Entry(pop); entry.pack(padx=10)
            def ok():
                if entry.get().strip() != otp:
                    messagebox.showerror("خطأ","OTP غير صحيح"); return
                con = db_conn(); cur = con.cursor()
                nowu = datetime.datetime.utcnow().isoformat()
                cur.execute("UPDATE receipts SET status='COMPLETED', delivered_utc=? WHERE id=?", (nowu, rid))
                cur.execute("INSERT INTO status_history(receipt_id,from_status,to_status,at_utc,by_username) VALUES(?,?,?,?,?)",
                            (rid, status, 'COMPLETED', nowu, self.active_user['username']))
                con.commit(); con.close()
                log_activity(rid, "STATUS", f"{status} -> COMPLETED (deliver)", self.active_user['username'])
                try:
                    if messagebox.askyesno("إرسال تأكيد", "تم التسليم. هل تريد إرسال رسالة تأكيد للعميل؟"):
                        wa_delivered()
                except Exception: pass
                pop.destroy(); win.destroy(); self.list_receipts()
            ttk.Button(pop, text="تسليم", style="Primary.TButton", command=ok).pack(pady=8)
        ttk.Button(tools, text="✅ تسليم الجهاز (OTP)", command=deliver).pack(side='left', padx=5, pady=6)

        # QR preview
        qr_area = self.card(root); qr_area.grid(row=5, column=0, sticky='ew', pady=6)
        ttk.Label(qr_area, text="QR", style="Card.TLabel", font=("Tahoma", 11,'bold')).pack(anchor="w")
        if qrcode and os.path.exists(qr_path) and Image is not None:
            try:
                img = Image.open(qr_path).resize((200,200))
                photo = ImageTk.PhotoImage(img)
                lbl = ttk.Label(qr_area, image=photo); lbl.image = photo; lbl.pack()
            except Exception:
                ttk.Label(qr_area, text="(تعذر عرض QR)", style="Card.TLabel", foreground="#777").pack()
        else:
            ttk.Label(qr_area, text="(لا يوجد QR أو مكتبة الصور غير مثبّتة)", style="Card.TLabel", foreground="#777").pack()

        # Activity Log (داخل السكورول أيضًا)
        log_frame = self.card(root); log_frame.grid(row=7, column=0, sticky="ew", pady=6)
        ttk.Label(log_frame, text="سجل النشاط", style="Card.TLabel", font=("Tahoma", 11,'bold')).grid(row=0, column=0, sticky='w', padx=6, pady=6)
        tree_wrap = ttk.Frame(log_frame); tree_wrap.grid(row=1, column=0, sticky="nsew")
        tree = ttk.Treeview(tree_wrap, columns=("time_local","kind","info"), show="headings", height=8)
        tree.heading("time_local", text="الوقت (الرياض)")
        tree.heading("kind", text="النوع")
        tree.heading("info", text="تفاصيل")
        tree.column("time_local", width=170, anchor="w")
        tree.column("kind", width=120, anchor="w")
        tree.column("info", width=700, anchor="w")
        add_treeview_scrollbars(tree_wrap, tree)

        def load_activity():
            con = db_conn(); cur = con.cursor()
            cur.execute("""
                SELECT kind, info, at_utc, by_username
                FROM activity_log
                WHERE receipt_id=?
                ORDER BY id DESC
            """, (rid,))
            rows = cur.fetchall(); con.close()
            for i in tree.get_children(): tree.delete(i)
            for k, info_txt, at_utc, by in rows:
                at_dt_utc = parse_utc_iso(at_utc)
                at_local = fmt_dt(to_riyadh(at_dt_utc))
                suffix = f" (by {by})" if by else ""
                tree.insert("", "end", values=(at_local, k, (info_txt or "") + suffix))
        load_activity()

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

if __name__ == '__main__':
    main()
