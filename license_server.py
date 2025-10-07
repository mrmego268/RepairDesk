from flask import Flask, request, jsonify
import datetime, random, string

app = Flask(__name__)

# قاعدة بيانات بسيطة مؤقتة في الذاكرة (استبدلها لاحقاً بقاعدة بيانات حقيقية)
licenses = {}


def gen_code(typ="M"):
    """توليد كود عشوائي (شهري أو سنوي)"""
    num = "".join(random.choices(string.digits, k=5))
    return f"ATTA-{num}-{typ}"


@app.route("/")
def home():
    return jsonify({"status": "running", "message": "License server active ✅"})


@app.route("/generate", methods=["POST"])
def generate():
    """توليد كود جديد"""
    data = request.json or {}
    name = data.get("name", "Unknown")
    typ = data.get("type", "M").upper()
    days = 30 if typ == "M" else 365

    code = gen_code(typ)
    exp = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat()

    licenses[code] = {
        "client": name,
        "type": "شهري" if typ == "M" else "سنوي",
        "expires": exp,
        "used": False,
    }

    return jsonify({"ok": True, "code": code, "expires": exp, "type": typ})


@app.route("/activate", methods=["POST"])
def activate():
    """تفعيل كود للعميل"""
    data = request.json or {}
    code = data.get("code", "").strip().upper()

    if code not in licenses:
        return jsonify({"ok": False, "msg": "❌ كود غير موجود"}), 404

    lic = licenses[code]
    if lic["used"]:
        return jsonify({"ok": False, "msg": "⚠️ الكود تم استخدامه بالفعل"}), 400

    exp = datetime.datetime.fromisoformat(lic["expires"])
    if datetime.datetime.utcnow() > exp:
        return jsonify({"ok": False, "msg": "⛔ انتهت صلاحية الكود"}), 400

    lic["used"] = True
    return jsonify(
        {
            "ok": True,
            "client": lic["client"],
            "type": lic["type"],
            "expires": lic["expires"],
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
