from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timezone
import os
import requests

app = Flask(__name__)
app.secret_key = "mem-store-secret-2026-xX"

mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client["mem_store"]

DASHBOARD_PASSWORD = "deaplo-_-100X#"
DISCORD_BOT_TOKEN  = os.getenv("DISCORD_TOKEN")

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def logged_in():
    return session.get("auth") == True

def require_login():
    if not logged_in():
        return redirect(url_for("login"))
    return None

def get_username(user_id):
    if not user_id:
        return "Unknown"
    try:
        r = requests.get(
            f"https://discord.com/api/v10/users/{user_id}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
            timeout=3
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("global_name") or data.get("username", str(user_id))
    except Exception:
        pass
    return str(user_id)

def fmt_time(ts):
    if not ts:
        return "N/A"
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M")
    return str(ts)

# ─────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if logged_in():
        return redirect(url_for("home"))
    error = None
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["auth"] = True
            return redirect(url_for("home"))
        error = "Wrong password!"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─────────────────────────────────────────
#  HOME
# ─────────────────────────────────────────
@app.route("/")
def home():
    if not logged_in(): return redirect(url_for("login"))

    stats = {
        "tickets":  db["tickets"].count_documents({}),
        "orders":   db["leaderboard"].count_documents({}),
        "warnings": db["warnings"].count_documents({}),
        "logs":     db["logs"].count_documents({}),
    }

    # Top sellers
    top = list(db["leaderboard"].find().sort("positive", -1).limit(3))
    top_sellers = []
    for s in top:
        total    = s.get("total", 0)
        positive = s.get("positive", 0)
        ratio    = round((positive / total) * 100) if total > 0 else 0
        top_sellers.append({
            "username": get_username(s.get("seller_id")),
            "positive": positive,
            "total":    total,
            "ratio":    ratio,
        })

    # Recent logs
    recent_logs = list(db["logs"].find().sort("timestamp", -1).limit(5))
    for l in recent_logs:
        l["time"] = fmt_time(l.get("timestamp"))
        l.pop("_id", None)

    return render_template("home.html", stats=stats, top_sellers=top_sellers, recent_logs=recent_logs)

# ─────────────────────────────────────────
#  TICKETS
# ─────────────────────────────────────────
@app.route("/tickets")
def tickets():
    if not logged_in(): return redirect(url_for("login"))

    tickets_raw = list(db["tickets"].find().sort("opened_at", -1).limit(50))
    tickets = []
    for t in tickets_raw:
        tickets.append({
            "id":       str(t["_id"]),
            "username": get_username(t.get("user_id")),
            "user_id":  t.get("user_id"),
            "type":     t.get("type", "N/A"),
            "seller":   get_username(t.get("seller_id")) if t.get("seller_id") else "Unclaimed",
            "time":     fmt_time(t.get("opened_at")),
        })

    stats = {
        "total":   db["tickets"].count_documents({}),
        "sell":    db["tickets"].count_documents({"type": "Sell"}),
        "buy":     db["tickets"].count_documents({"type": "Buy"}),
        "partner": db["tickets"].count_documents({"type": "Partner"}),
    }

    return render_template("tickets.html", tickets=tickets, stats=stats)

# ─────────────────────────────────────────
#  MARKETPLACE
# ─────────────────────────────────────────
@app.route("/marketplace")
def marketplace():
    if not logged_in(): return redirect(url_for("login"))

    sellers = list(db["leaderboard"].find().sort("positive", -1).limit(20))
    leaderboard = []
    for i, s in enumerate(sellers):
        total    = s.get("total", 0)
        positive = s.get("positive", 0)
        ratio    = round((positive / total) * 100) if total > 0 else 0
        leaderboard.append({
            "rank":      i + 1,
            "id":        str(s["_id"]),
            "seller_id": s.get("seller_id"),
            "username":  get_username(s.get("seller_id")),
            "total":     total,
            "positive":  positive,
            "negative":  total - positive,
            "ratio":     ratio,
        })

    return render_template("marketplace.html", leaderboard=leaderboard)

@app.route("/reset_leaderboard", methods=["POST"])
def reset_leaderboard():
    if not logged_in(): return redirect(url_for("login"))
    db["leaderboard"].delete_many({})
    db["config"].delete_one({"key": "leaderboard_message"})
    return redirect(url_for("marketplace"))

@app.route("/delete_seller/<seller_id>", methods=["POST"])
def delete_seller(seller_id):
    if not logged_in(): return redirect(url_for("login"))
    try:
        db["leaderboard"].delete_one({"_id": ObjectId(seller_id)})
    except Exception:
        pass
    return redirect(url_for("marketplace"))

# ─────────────────────────────────────────
#  MODERATION
# ─────────────────────────────────────────
@app.route("/moderation")
def moderation():
    if not logged_in(): return redirect(url_for("login"))

    warnings_raw = list(db["warnings"].find().sort("timestamp", -1).limit(50))
    warns = []
    for w in warnings_raw:
        warns.append({
            "id":       str(w["_id"]),
            "username": get_username(w.get("user_id")),
            "user_id":  w.get("user_id"),
            "by":       get_username(w.get("by")),
            "reason":   w.get("reason", "No reason"),
            "time":     fmt_time(w.get("timestamp")),
        })

    stats = {
        "total":   db["warnings"].count_documents({}),
    }

    return render_template("moderation.html", warns=warns, stats=stats)

@app.route("/delete_warning/<warning_id>", methods=["POST"])
def delete_warning(warning_id):
    if not logged_in(): return redirect(url_for("login"))
    try:
        db["warnings"].delete_one({"_id": ObjectId(warning_id)})
    except Exception:
        pass
    return redirect(url_for("moderation"))

@app.route("/clear_user_warnings/<int:user_id>", methods=["POST"])
def clear_user_warnings(user_id):
    if not logged_in(): return redirect(url_for("login"))
    db["warnings"].delete_many({"user_id": user_id})
    return redirect(url_for("moderation"))

# ─────────────────────────────────────────
#  LOGS
# ─────────────────────────────────────────
@app.route("/logs")
def logs():
    if not logged_in(): return redirect(url_for("login"))

    log_type = request.args.get("type", "all")
    query = {} if log_type == "all" else {"type": log_type}

    logs_raw = list(db["logs"].find(query).sort("timestamp", -1).limit(100))
    logs_list = []
    for l in logs_raw:
        logs_list.append({
            "title":       l.get("title", ""),
            "description": l.get("description", ""),
            "type":        l.get("type", "general"),
            "time":        fmt_time(l.get("timestamp")),
        })

    log_types = ["all", "moderation", "ticket", "member", "message", "order", "automod", "general"]

    return render_template("logs.html", logs=logs_list, log_types=log_types, current_type=log_type)

@app.route("/clear_logs", methods=["POST"])
def clear_logs():
    if not logged_in(): return redirect(url_for("login"))
    db["logs"].delete_many({})
    return redirect(url_for("logs"))

# ─────────────────────────────────────────
#  ROLES
# ─────────────────────────────────────────
@app.route("/roles")
def roles():
    if not logged_in(): return redirect(url_for("login"))

    config = db["config"].find_one({"key": "roles_config"}) or {}
    language_roles = config.get("language_roles", {
        "English": 1506219132037763092,
        "Arabic":  1506219366939885669,
    })
    game_roles = config.get("game_roles", {
        "ARC Raiders": 1506219518567911566,
        "PUBG Mobile": 1506219627246649455,
        "PUBG Steam":  1506219763171463209,
    })

    return render_template("roles.html", language_roles=language_roles, game_roles=game_roles)

# ─────────────────────────────────────────
#  WELCOME
# ─────────────────────────────────────────
@app.route("/welcome")
def welcome():
    if not logged_in(): return redirect(url_for("login"))

    config = db["config"].find_one({"key": "welcome_config"}) or {}
    welcome_msg = config.get("message", "We hope you have a great time.")

    return render_template("welcome.html", welcome_msg=welcome_msg)

@app.route("/save_welcome", methods=["POST"])
def save_welcome():
    if not logged_in(): return redirect(url_for("login"))
    msg = request.form.get("message", "")
    db["config"].update_one(
        {"key": "welcome_config"},
        {"$set": {"message": msg}},
        upsert=True
    )
    return redirect(url_for("welcome"))

# ─────────────────────────────────────────
#  SETTINGS
# ─────────────────────────────────────────
@app.route("/settings")
def settings():
    if not logged_in(): return redirect(url_for("login"))
    config = db["config"].find_one({"key": "bot_settings"}) or {}
    return render_template("settings.html", config=config)

@app.route("/save_settings", methods=["POST"])
def save_settings():
    if not logged_in(): return redirect(url_for("login"))
    footer = request.form.get("footer", "Powered by MEM Development | Deaplo")
    db["config"].update_one(
        {"key": "bot_settings"},
        {"$set": {"footer": footer}},
        upsert=True
    )
    return redirect(url_for("settings"))

# ─────────────────────────────────────────
#  API
# ─────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    if not logged_in():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "tickets":  db["tickets"].count_documents({}),
        "orders":   db["leaderboard"].count_documents({}),
        "warnings": db["warnings"].count_documents({}),
        "logs":     db["logs"].count_documents({}),
    })

# ─────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
