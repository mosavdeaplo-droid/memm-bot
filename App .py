from flask import Flask, render_template, jsonify
from pymongo import MongoClient
import os

app = Flask(__name__)

mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client["mem_store"]

@app.route("/")
def index():
    # Stats
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
        leaderboard.append({
            "seller_id": s.get("seller_id"),
            "total":     total,
            "positive":  positive,
            "ratio":     ratio,
        })

    # Warnings
    warnings = list(db["warnings"].find().sort("timestamp", -1).limit(20))
    warns = []
    for w in warnings:
        warns.append({
            "user_id": w.get("user_id"),
            "reason":  w.get("reason"),
            "by":      w.get("by"),
            "time":    w.get("timestamp").strftime("%Y-%m-%d %H:%M") if w.get("timestamp") else "N/A",
        })

    return render_template("index.html",
        total_tickets=total_tickets,
        total_orders=total_orders,
        total_warnings=total_warnings,
        leaderboard=leaderboard,
        warnings=warns,
    )

@app.route("/api/stats")
def api_stats():
    return jsonify({
        "tickets":  db["tickets"].count_documents({}),
        "orders":   db["leaderboard"].count_documents({}),
        "warnings": db["warnings"].count_documents({}),
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)