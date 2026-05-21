from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from pymongo import MongoClient
from bson import ObjectId
import os
import requests

app = Flask(__name__)
app.secret_key = "mem-store-secret-key-2026"

mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client["mem_store"]

DASHBOARD_PASSWORD = "deaplo-_-100X#"
DISCORD_BOT_TOKEN  = os.getenv("DISCORD_TOKEN")

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def logged_in():
    return session.get("auth") == True

def get_username(user_id):
    try:
        r = requests.get(
            f"https://discord.com/api/v10/users/{user_id}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
            timeout=3
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("username", str(user_id))
    except Exception:
        pass
    return str(user_id)

# ─────────────────────────────────────────
#  LOGIN
# ─────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password")
        if password == DASHBOARD_PASSWORD:
            session["auth"] = True
            return redirect(url_for("index"))
        else:
            error = "Wrong password!"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─────────────────────────────────────────
#  MAIN DASHBOARD
# ─────────────────────────────────────────
@app.route("/")
def index():
    if not logged_in():
        return redirect(url_for("login"))

    total_tickets  = db["tickets"].count_documents({})
    total_orders   = db["leaderboard"].count_documents({})
    total_warnings = db["warnings"].count_documents({})

    # Leaderboard
    sellers = list(db["leaderboard"].find().sort("positive", -1).limit(10))
    leaderboard = []
    for s in sellers:
        total    = s.get("total", 0)
        positive = s.get("positive", 0)
        ratio    = round((positive / total) * 100) if total > 0 else 0
        username = get_username(s.get("seller_id", 0))
        leaderboard.append({
            "seller_id": s.get("seller_id"),
            "username":  username,
            "total":     total,
            "positive":  positive,
            "ratio":     ratio,
        })

    # Warnings
    warnings_raw = list(db["warnings"].find().sort("timestamp", -1).limit(20))
    warns = []
    for w in warnings_raw:
        warns.append({
            "id":      str(w["_id"]),
            "user_id": w.get("user_id"),
            "username": get_username(w.get("user_id", 0)),
            "reason":  w.get("reason"),
            "by":      get_username(w.get("by", 0)),
            "time":    w.get("timestamp").strftime("%Y-%m-%d %H:%M") if w.get("timestamp") else "N/A",
        })

    # Tickets
    tickets_raw = list(db["tickets"].find().sort("opened_at", -1).limit(20))
    tickets = []
    for t in tickets_raw:
        tickets.append({
            "user_id":   t.get("user_id"),
            "username":  get_username(t.get("user_id", 0)),
            "type":      t.get("type", "N/A"),
            "time":      t.get("opened_at").strftime("%Y-%m-%d %H:%M") if t.get("opened_at") else "N/A",
        })

    return render_template("index.html",
        total_tickets=total_tickets,
        total_orders=total_orders,
        total_warnings=total_warnings,
        leaderboard=leaderboard,
        warnings=warns,
        tickets=tickets,
    )

# ─────────────────────────────────────────
#  ACTIONS
# ─────────────────────────────────────────
@app.route("/delete_warning/<warning_id>", methods=["POST"])
def delete_warning(warning_id):
    if not logged_in():
        return redirect(url_for("login"))
    try:
        db["warnings"].delete_one({"_id": ObjectId(warning_id)})
    except Exception:
        pass
    return redirect(url_for("index"))

@app.route("/clear_warnings/<int:user_id>", methods=["POST"])
def clear_warnings(user_id):
    if not logged_in():
        return redirect(url_for("login"))
    db["warnings"].delete_many({"user_id": user_id})
    return redirect(url_for("index"))

@app.route("/reset_leaderboard", methods=["POST"])
def reset_leaderboard():
    if not logged_in():
        return redirect(url_for("login"))
    db["leaderboard"].delete_many({})
    db["config"].delete_one({"key": "leaderboard_message"})
    return redirect(url_for("index"))

@app.route("/api/stats")
def api_stats():
    if not logged_in():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "tickets":  db["tickets"].count_documents({}),
        "orders":   db["leaderboard"].count_documents({}),
        "warnings": db["warnings"].count_documents({}),
    })

# ─────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
