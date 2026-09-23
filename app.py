from flask import Flask, request, jsonify, render_template, g
import sqlite3, os, re
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "lostfound.db")
app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    for table in ("lost", "found"):
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                loc TEXT NOT NULL,
                time TEXT NOT NULL,
                desc TEXT,
                photo TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
    db.commit()
    db.close()


def tokenize(s):
    return [t for t in re.sub(r"[^a-z0-9\s]", "", (s or "").lower()).split() if t]


def score_match(a, b):
    score = 0
    na, nb = tokenize(a["name"]), tokenize(b["name"])
    overlap = len(set(na) & set(nb))
    score += overlap * 35
    if overlap == 0 and (a["name"].lower() in b["name"].lower() or b["name"].lower() in a["name"].lower()):
        score += 18
    la, lb = tokenize(a["loc"]), tokenize(b["loc"])
    score += len(set(la) & set(lb)) * 25
    try:
        diff_hours = abs((datetime.fromisoformat(a["time"]) - datetime.fromisoformat(b["time"])).total_seconds()) / 3600
        if diff_hours <= 3:
            score += 25
        elif diff_hours <= 24:
            score += 12
        elif diff_hours <= 72:
            score += 5
    except ValueError:
        pass
    return min(100, score)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/<store>", methods=["GET", "POST"])
def reports(store):
    if store not in ("lost", "found"):
        return jsonify({"error": "unknown store"}), 404
    db = get_db()
    if request.method == "POST":
        data = request.get_json(force=True)
        for field in ("name", "loc", "time"):
            if not data.get(field):
                return jsonify({"error": f"{field} is required"}), 400
        cur = db.execute(
            f"INSERT INTO {store} (name, loc, time, desc, photo) VALUES (?, ?, ?, ?, ?)",
            (data["name"], data["loc"], data["time"], data.get("desc", ""), data.get("photo")),
        )
        db.commit()
        return jsonify({"id": cur.lastrowid}), 201

    rows = db.execute(f"SELECT * FROM {store} ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/match/<store>/<int:item_id>")
def match(store, item_id):
    if store not in ("lost", "found"):
        return jsonify({"error": "unknown store"}), 404
    target = "found" if store == "lost" else "lost"
    db = get_db()
    origin = db.execute(f"SELECT * FROM {store} WHERE id = ?", (item_id,)).fetchone()
    if not origin:
        return jsonify({"error": "not found"}), 404
    candidates = db.execute(f"SELECT * FROM {target} ORDER BY id DESC").fetchall()
    scored = []
    for c in candidates:
        s = score_match(dict(origin), dict(c))
        if s >= 25:
            scored.append({"score": s, "item": dict(c)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"target": target, "matches": scored})


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
