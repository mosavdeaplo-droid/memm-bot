from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timezone
import os, requests

app = Flask(__name__)
app.secret_key = "mem-store-secret-2026-xX"

mongo_client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
db = mongo_client["mem_store"]

DASHBOARD_PASSWORD = "deaplo-_-100X#"
DISCORD_BOT_TOKEN  = os.getenv("DISCORD_TOKEN", "")

GUILD_ID = 1504256091872301116

def logged_in(): return session.get("auth") == True

def get_username(user_id):
    if not user_id: return "Unknown"
    try:
        r = requests.get(f"https://discord.com/api/v10/users/{user_id}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}, timeout=3)
        if r.status_code == 200:
            d = r.json()
            return d.get("global_name") or d.get("username", str(user_id))
    except: pass
    return str(user_id)

def fmt_time(ts):
    if not ts: return "N/A"
    if isinstance(ts, datetime): return ts.strftime("%Y-%m-%d %H:%M")
    return str(ts)

def discord_api(method, endpoint, data=None):
    url = f"https://discord.com/api/v10{endpoint}"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.request(method, url, json=data, headers=headers, timeout=5)
        if r.status_code in (200, 201, 204):
            try: return r.json()
            except: return {}
    except: pass
    return None

@app.route("/login", methods=["GET","POST"])
def login():
    if logged_in(): return redirect(url_for("home"))
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

@app.route("/")
def home():
    if not logged_in(): return redirect(url_for("login"))
    stats = {
        "tickets":  db["tickets"].count_documents({}),
        "orders":   db["leaderboard"].count_documents({}),
        "warnings": db["warnings"].count_documents({}),
        "logs":     db["logs"].count_documents({}),
        "members":  db["members"].count_documents({}) if "members" in db.list_collection_names() else 0,
    }
    top = list(db["leaderboard"].find().sort("positive",-1).limit(3))
    top_sellers = []
    for s in top:
        total=s.get("total",0); positive=s.get("positive",0)
        top_sellers.append({"username":get_username(s.get("seller_id")),"positive":positive,"total":total,
            "ratio":round((positive/total)*100) if total>0 else 0})
    recent_logs = list(db["logs"].find().sort("timestamp",-1).limit(5))
    for l in recent_logs:
        l["time"] = fmt_time(l.get("timestamp")); l.pop("_id",None)
    return render_template("home.html", stats=stats, top_sellers=top_sellers, recent_logs=recent_logs)

@app.route("/tickets")
def tickets():
    if not logged_in(): return redirect(url_for("login"))
    tickets_raw = list(db["tickets"].find().sort("opened_at",-1).limit(50))
    tickets_list = []
    for t in tickets_raw:
        tickets_list.append({"id":str(t["_id"]),"username":get_username(t.get("user_id")),
            "user_id":t.get("user_id"),"type":t.get("type","N/A"),
            "seller":get_username(t.get("seller_id")) if t.get("seller_id") else "Unclaimed",
            "status":t.get("status","open"),"time":fmt_time(t.get("opened_at"))})
    stats = {"total":db["tickets"].count_documents({}),"sell":db["tickets"].count_documents({"type":"Sell"}),
        "buy":db["tickets"].count_documents({"type":"Buy"}),"partner":db["tickets"].count_documents({"type":"Partner"})}
    config = db["config"].find_one({"key":"ticket_config"}) or {}
    return render_template("tickets.html", tickets=tickets_list, stats=stats, config=config)

@app.route("/save_ticket_config", methods=["POST"])
def save_ticket_config():
    if not logged_in(): return redirect(url_for("login"))
    data = {"key":"ticket_config","title":request.form.get("title","🎫 MEM Store | Ticket Center"),
        "description":request.form.get("description",""),"footer":request.form.get("footer",""),
        "category_id":request.form.get("category_id",""),"log_channel":request.form.get("log_channel","")}
    db["config"].update_one({"key":"ticket_config"},{"$set":data},upsert=True)
    return redirect(url_for("tickets"))

@app.route("/delete_ticket/<ticket_id>", methods=["POST"])
def delete_ticket(ticket_id):
    if not logged_in(): return redirect(url_for("login"))
    try: db["tickets"].delete_one({"_id":ObjectId(ticket_id)})
    except: pass
    return redirect(url_for("tickets"))

@app.route("/marketplace")
def marketplace():
    if not logged_in(): return redirect(url_for("login"))
    sellers = list(db["leaderboard"].find().sort("positive",-1).limit(20))
    leaderboard = []
    for i,s in enumerate(sellers):
        total=s.get("total",0); positive=s.get("positive",0)
        leaderboard.append({"rank":i+1,"id":str(s["_id"]),"seller_id":s.get("seller_id"),
            "username":get_username(s.get("seller_id")),"total":total,"positive":positive,
            "negative":total-positive,"ratio":round((positive/total)*100) if total>0 else 0})
    orders = list(db["logs"].find({"type":"order"}).sort("timestamp",-1).limit(10))
    for o in orders: o["time"]=fmt_time(o.get("timestamp")); o.pop("_id",None)
    feedback = list(db["logs"].find({"title":{"$regex":"Feedback","$options":"i"}}).sort("timestamp",-1).limit(10))
    for f in feedback: f["time"]=fmt_time(f.get("timestamp")); f.pop("_id",None)
    return render_template("marketplace.html", leaderboard=leaderboard, orders=orders, feedback=feedback)

@app.route("/reset_leaderboard", methods=["POST"])
def reset_leaderboard():
    if not logged_in(): return redirect(url_for("login"))
    db["leaderboard"].delete_many({}); db["config"].delete_one({"key":"leaderboard_message"})
    return redirect(url_for("marketplace"))

@app.route("/delete_seller/<seller_id>", methods=["POST"])
def delete_seller(seller_id):
    if not logged_in(): return redirect(url_for("login"))
    try: db["leaderboard"].delete_one({"_id":ObjectId(seller_id)})
    except: pass
    return redirect(url_for("marketplace"))

@app.route("/moderation")
def moderation():
    if not logged_in(): return redirect(url_for("login"))
    warnings_raw = list(db["warnings"].find().sort("timestamp",-1).limit(50))
    warns = []
    for w in warnings_raw:
        warns.append({"id":str(w["_id"]),"username":get_username(w.get("user_id")),
            "user_id":w.get("user_id"),"by":get_username(w.get("by")),
            "reason":w.get("reason","No reason"),"time":fmt_time(w.get("timestamp"))})
    stats = {"total":db["warnings"].count_documents({}),
        "bans":db["logs"].count_documents({"title":{"$regex":"Ban","$options":"i"}}),
        "kicks":db["logs"].count_documents({"title":{"$regex":"Kick","$options":"i"}}),
        "timeouts":db["logs"].count_documents({"title":{"$regex":"Timeout","$options":"i"}})}
    blacklist_raw = list(db["blacklist"].find()) if "blacklist" in db.list_collection_names() else []
    blacklist = []
    for b in blacklist_raw:
        blacklist.append({"id":str(b["_id"]),"user_id":b.get("user_id"),
            "username":get_username(b.get("user_id")),"reason":b.get("reason",""),"time":fmt_time(b.get("added_at"))})
    return render_template("moderation.html", warns=warns, stats=stats, blacklist=blacklist)

@app.route("/delete_warning/<warning_id>", methods=["POST"])
def delete_warning(warning_id):
    if not logged_in(): return redirect(url_for("login"))
    try: db["warnings"].delete_one({"_id":ObjectId(warning_id)})
    except: pass
    return redirect(url_for("moderation"))

@app.route("/clear_user_warnings/<int:user_id>", methods=["POST"])
def clear_user_warnings(user_id):
    if not logged_in(): return redirect(url_for("login"))
    db["warnings"].delete_many({"user_id":user_id})
    return redirect(url_for("moderation"))

@app.route("/add_blacklist", methods=["POST"])
def add_blacklist():
    if not logged_in(): return redirect(url_for("login"))
    user_id=request.form.get("user_id","").strip(); reason=request.form.get("reason","No reason")
    if user_id:
        try: db["blacklist"].update_one({"user_id":int(user_id)},
            {"$set":{"user_id":int(user_id),"reason":reason,"added_at":datetime.now(timezone.utc)}},upsert=True)
        except: pass
    return redirect(url_for("moderation"))

@app.route("/remove_blacklist/<entry_id>", methods=["POST"])
def remove_blacklist(entry_id):
    if not logged_in(): return redirect(url_for("login"))
    try: db["blacklist"].delete_one({"_id":ObjectId(entry_id)})
    except: pass
    return redirect(url_for("moderation"))

@app.route("/logs")
def logs():
    if not logged_in(): return redirect(url_for("login"))
    log_type = request.args.get("type","all")
    query = {} if log_type=="all" else {"type":log_type}
    logs_raw = list(db["logs"].find(query).sort("timestamp",-1).limit(100))
    logs_list = []
    for l in logs_raw:
        logs_list.append({"title":l.get("title",""),"description":l.get("description",""),
            "type":l.get("type","general"),"time":fmt_time(l.get("timestamp"))})
    log_types = ["all","moderation","ticket","member","message","order","automod","general"]
    return render_template("logs.html", logs=logs_list, log_types=log_types, current_type=log_type)

@app.route("/clear_logs", methods=["POST"])
def clear_logs():
    if not logged_in(): return redirect(url_for("login"))
    db["logs"].delete_many({})
    return redirect(url_for("logs"))

@app.route("/roles")
def roles():
    if not logged_in(): return redirect(url_for("login"))
    config = db["config"].find_one({"key":"roles_config"}) or {}
    language_roles = config.get("language_roles",{"English":1506219132037763092,"Arabic":1506219366939885669})
    game_roles = config.get("game_roles",{"ARC Raiders":1506219518567911566,"PUBG Mobile":1506219627246649455,"PUBG Steam":1506219763171463209})
    return render_template("roles.html", language_roles=language_roles, game_roles=game_roles)

@app.route("/save_roles", methods=["POST"])
def save_roles():
    if not logged_in(): return redirect(url_for("login"))
    lang_names=request.form.getlist("lang_name"); lang_ids=request.form.getlist("lang_id")
    game_names=request.form.getlist("game_name"); game_ids=request.form.getlist("game_id")
    language_roles={n:int(i) for n,i in zip(lang_names,lang_ids) if n and i}
    game_roles={n:int(i) for n,i in zip(game_names,game_ids) if n and i}
    db["config"].update_one({"key":"roles_config"},
        {"$set":{"language_roles":language_roles,"game_roles":game_roles}},upsert=True)
    return redirect(url_for("roles"))

@app.route("/welcome")
def welcome():
    if not logged_in(): return redirect(url_for("login"))
    config = db["config"].find_one({"key":"welcome_config"}) or {}
    return render_template("welcome.html", config=config)

@app.route("/save_welcome", methods=["POST"])
def save_welcome():
    if not logged_in(): return redirect(url_for("login"))
    data={"message":request.form.get("message","We hope you have a great time."),
        "welcome_channel":request.form.get("welcome_channel",""),
        "member_role":request.form.get("member_role",""),
        "leave_message":request.form.get("leave_message","")}
    db["config"].update_one({"key":"welcome_config"},{"$set":data},upsert=True)
    return redirect(url_for("welcome"))

@app.route("/security")
def security():
    if not logged_in(): return redirect(url_for("login"))
    config = db["config"].find_one({"key":"security_config"}) or {}
    bad_words_config = db["config"].find_one({"key":"bad_words"}) or {}
    bad_words_list = bad_words_config.get("words",[])
    return render_template("security.html", config=config, bad_words=bad_words_list)

@app.route("/save_security", methods=["POST"])
def save_security():
    if not logged_in(): return redirect(url_for("login"))
    data={"anti_raid":"anti_raid" in request.form,"anti_bot":"anti_bot" in request.form,
        "anti_scam":"anti_scam" in request.form,"anti_mention":"anti_mention" in request.form,
        "anti_spam":"anti_spam" in request.form,"anti_links":"anti_links" in request.form,
        "mention_limit":int(request.form.get("mention_limit",5)),
        "spam_limit":int(request.form.get("spam_limit",5)),
        "spam_window":int(request.form.get("spam_window",5))}
    db["config"].update_one({"key":"security_config"},{"$set":data},upsert=True)
    words_raw = request.form.get("bad_words_list","")
    words = [w.strip() for w in words_raw.split("\n") if w.strip()]
    db["config"].update_one({"key":"bad_words"},{"$set":{"words":words}},upsert=True)
    return redirect(url_for("security"))

@app.route("/embeds")
def embeds():
    if not logged_in(): return redirect(url_for("login"))
    saved_embeds = list(db["saved_embeds"].find().sort("created_at",-1).limit(20))
    for e in saved_embeds: e["id"]=str(e["_id"]); e.pop("_id",None)
    return render_template("embeds.html", saved_embeds=saved_embeds)

@app.route("/send_embed", methods=["POST"])
def send_embed():
    if not logged_in(): return redirect(url_for("login"))
    channel_id = request.form.get("channel_id","").strip()
    title      = request.form.get("title","")
    description= request.form.get("description","")
    color_hex  = request.form.get("color","#1a2332").lstrip("#")
    footer     = request.form.get("footer","Powered by MEM Development | Deaplo")
    image_url  = request.form.get("image_url","")
    thumbnail  = request.form.get("thumbnail","")
    save_it    = "save_embed" in request.form
    try: color_int = int(color_hex,16)
    except: color_int = 0x1a2332
    embed_data = {"title":title,"description":description,"color":color_int,"footer":{"text":footer}}
    if image_url: embed_data["image"] = {"url":image_url}
    if thumbnail: embed_data["thumbnail"] = {"url":thumbnail}
    result = discord_api("POST", f"/channels/{channel_id}/messages", {"embeds":[embed_data]})
    if save_it and title:
        db["saved_embeds"].insert_one({"title":title,"description":description,"color":color_hex,
            "footer":footer,"image_url":image_url,"thumbnail":thumbnail,
            "created_at":datetime.now(timezone.utc)})
    msg = "✅ Embed sent!" if result is not None else "❌ Failed to send. Check the channel ID."
    return render_template("embeds.html",
        saved_embeds=[{**e,"id":str(e["_id"])} for e in db["saved_embeds"].find().sort("created_at",-1).limit(20)],
        flash_msg=msg, form_data=request.form)

@app.route("/delete_embed/<embed_id>", methods=["POST"])
def delete_embed(embed_id):
    if not logged_in(): return redirect(url_for("login"))
    try: db["saved_embeds"].delete_one({"_id":ObjectId(embed_id)})
    except: pass
    return redirect(url_for("embeds"))

@app.route("/analytics")
def analytics():
    if not logged_in(): return redirect(url_for("login"))
    log_types=["moderation","ticket","member","message","order","automod","general"]
    type_counts={t:db["logs"].count_documents({"type":t}) for t in log_types}
    top_sellers=list(db["leaderboard"].find().sort("positive",-1).limit(10))
    for s in top_sellers:
        s["username"]=get_username(s.get("seller_id"))
        total=s.get("total",0); positive=s.get("positive",0)
        s["ratio"]=round((positive/total)*100) if total>0 else 0
        s.pop("_id",None)
    stats={"tickets":db["tickets"].count_documents({}),"orders":db["leaderboard"].count_documents({}),
        "warnings":db["warnings"].count_documents({}),"logs":db["logs"].count_documents({}),
        "sell":db["tickets"].count_documents({"type":"Sell"}),
        "buy":db["tickets"].count_documents({"type":"Buy"}),
        "partner":db["tickets"].count_documents({"type":"Partner"})}
    return render_template("analytics.html", stats=stats, type_counts=type_counts, top_sellers=top_sellers)

@app.route("/settings")
def settings():
    if not logged_in(): return redirect(url_for("login"))
    config = db["config"].find_one({"key":"bot_settings"}) or {}
    return render_template("settings.html", config=config)

@app.route("/save_settings", methods=["POST"])
def save_settings():
    if not logged_in(): return redirect(url_for("login"))
    data={"footer":request.form.get("footer","Powered by MEM Development | Deaplo"),
        "embed_color":request.form.get("embed_color","#1a2332"),
        "log_channel":request.form.get("log_channel",""),
        "ticket_channel":request.form.get("ticket_channel",""),
        "order_channel":request.form.get("order_channel",""),
        "welcome_channel":request.form.get("welcome_channel",""),
        "lb_channel":request.form.get("lb_channel",""),
        "feedback_channel":request.form.get("feedback_channel",""),
        "systems":{"tickets":"sys_tickets" in request.form,"orders":"sys_orders" in request.form,
            "welcome":"sys_welcome" in request.form,"automod":"sys_automod" in request.form,
            "leaderboard":"sys_leaderboard" in request.form,"logging":"sys_logging" in request.form}}
    db["config"].update_one({"key":"bot_settings"},{"$set":data},upsert=True)
    return redirect(url_for("settings"))

@app.route("/voice")
def voice():
    if not logged_in(): return redirect(url_for("login"))
    ws_url = os.getenv("WS_URL", "ws://localhost:8765")
    calls_raw = list(db["voice_calls"].find().sort("end", -1).limit(50))
    calls_list = []
    for c in calls_raw:
        dur = c.get("duration_secs", 0)
        calls_list.append({
            "channel":    c.get("channel", "N/A"),
            "started_by": get_username(c.get("started_by")),
            "start":      fmt_time(c.get("start")),
            "end":        fmt_time(c.get("end")),
            "duration":   f"{dur // 60}m {dur % 60}s",
        })
    total_calls = db["voice_calls"].count_documents({})
    all_calls   = list(db["voice_calls"].find({}, {"duration_secs": 1}))
    total_secs  = sum(c.get("duration_secs", 0) for c in all_calls)
    total_duration = f"{total_secs // 3600}h {(total_secs % 3600) // 60}m"
    return render_template("voice.html",
        ws_url=ws_url,
        calls=calls_list,
        total_calls=total_calls,
        total_duration=total_duration)

@app.route("/api/stats")
def api_stats():
    if not logged_in(): return jsonify({"error":"Unauthorized"}),401
    return jsonify({"tickets":db["tickets"].count_documents({}),"orders":db["leaderboard"].count_documents({}),
        "warnings":db["warnings"].count_documents({}),"logs":db["logs"].count_documents({})})

if __name__ == "__main__":
    port = int(os.getenv("PORT",5000))
    app.run(host="0.0.0.0", port=port)
