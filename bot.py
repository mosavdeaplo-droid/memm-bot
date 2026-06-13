import discord
from discord.ext import commands
from discord.ui import View, Button
from discord import Option, PermissionOverwrite
from pymongo import MongoClient
from datetime import datetime, timezone
from collections import defaultdict
import asyncio
import os
import io
import re
import aiohttp
import queue
import json
import websockets
import websockets.exceptions

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
GIF_URL  = "https://cdn.discordapp.com/attachments/1504271389656486049/1506983848229998644/mem.gif?ex=6a103f93&is=6a0eee13&hm=e317fb999d07c38c7f833503be07946596fab23962f8ad1a640b5c58&"
LOGO_URL = "https://cdn.discordapp.com/attachments/1504256416569884788/1505797502622896198/Geometric_Monogram_Logo_for_MEM.png?ex=6a0beeb4&is=6a0a9d34&hm=24492cc4843e4969bea21c79aff736ec0c1a36dc26778ffff54087fd2291a3e0&"

EMBED_COLOR  = 0x1a2332
FOOTER_TEXT  = "Powered by MEM Development | Deaplo"
SERVER_NAME  = "MEM Store"
GUILD_ID     = 1504256091872301116

# ── Channels ──
TICKET_CHANNEL_ID      = 1505921799978881105
ORDER_CHANNEL_ID       = 1504265744719020122
WELCOME_CHANNEL_ID     = 1505922477753368740
LOG_CHANNEL_ID         = 1505308788780040222
LEADERBOARD_CHANNEL_ID = 1505922561903562812
LINKS_ALLOWED_CHANNEL  = 1504271389656486049
SELF_ROLES_CHANNEL_ID  = 1506220242626543697
FEEDBACK_CHANNEL_ID    = 1506926493798764635

# ── Categories ──
TICKET_CATEGORY_ID = 1505922835359596644

# ── Roles ──
STAFF_ROLE_ID    = 1504374917360128040
MEMBER_ROLE_ID   = 1504383155921092808
SECURITY_ROLE_ID = 1505133078111191142
ARC_ROLE_ID      = 1506219518567911566

LANGUAGE_ROLES = {
    "English": 1506219132037763092,
    "Arabic":  1506219366939885669,
}
GAME_ROLES = {
    "ARC Raiders": 1506219518567911566,
    "PUBG Mobile": 1506219627246649455,
    "PUBG Steam":  1506219763171463209,
}

# ── Bad Words Filter ──
BAD_WORDS = [
    "fuck", "shit", "bitch", "asshole", "bastard", "cunt", "damn", "dick",
    "pussy", "nigga", "nigger", "faggot", "retard", "whore", "slut",
    "كس", "زب", "طيز", "منيوك", "شرموط", "عرص", "خول", "متناك",
    "كلب", "حمار", "زنيك", "نيك", "ابن الشرموطة", "ابن الكلب",
    "يلعن", "العن", "لعنة", "قحبة", "وسخ",
]

# ── Anti Spam ──
spam_tracker = defaultdict(list)
SPAM_LIMIT   = 5
SPAM_WINDOW  = 5

# ─────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────
mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client["mem_store"]

# ─────────────────────────────────────────
#  VOICE RELAY
# ─────────────────────────────────────────
audio_queue: queue.Queue = queue.Queue(maxsize=500)
ws_clients: set = set()
voice_session: dict = {}   # {guild_id: {"channel": name, "start": iso_str}}


class MicAudioSource(discord.AudioSource):
    FRAME_SIZE = 3840  # 20ms @ 48kHz stereo 16-bit

    def __init__(self):
        self.buffer = b''
        self.silence = b'\x00' * self.FRAME_SIZE

    def read(self) -> bytes:
        while len(self.buffer) < self.FRAME_SIZE:
            try:
                self.buffer += audio_queue.get_nowait()
            except queue.Empty:
                return self.silence
        frame = self.buffer[:self.FRAME_SIZE]
        self.buffer = self.buffer[self.FRAME_SIZE:]
        return frame

    def is_opus(self) -> bool:
        return False


async def _ws_broadcast(data: dict):
    if ws_clients:
        msg = json.dumps(data)
        await asyncio.gather(*[c.send(msg) for c in list(ws_clients)],
                             return_exceptions=True)


async def ws_handler(websocket):
    ws_clients.add(websocket)
    # أرسل الحالة الحالية للـ client الجديد فور اتصاله
    if bot.is_ready():
        await websocket.send(json.dumps({"type": "bot_ready", "user": str(bot.user)}))
    for guild in bot.guilds:
        if guild.voice_client and guild.voice_client.is_connected():
            sess = voice_session.get(guild.id, {})
            await websocket.send(json.dumps({
                "type": "joined",
                "channel": guild.voice_client.channel.name,
                "start": sess.get("start", "")
            }))
            break
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                try:
                    audio_queue.put_nowait(message)
                except queue.Full:
                    try:
                        audio_queue.get_nowait()
                        audio_queue.put_nowait(message)
                    except queue.Empty:
                        pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        ws_clients.discard(websocket)

# ─────────────────────────────────────────
#  BOT SETUP
# ─────────────────────────────────────────
intents = discord.Intents.all()
bot = discord.Bot(intents=intents)

# ─────────────────────────────────────────
#  HELPER: SEND LOG
# ─────────────────────────────────────────
async def send_log(guild, title: str, description: str, color: int = EMBED_COLOR, fields: list = None):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    embed.set_footer(text=FOOTER_TEXT)
    await channel.send(embed=embed)

    try:
        log_entry = {
            "guild_id":    guild.id,
            "title":       title,
            "description": description,
            "fields":      [{"name": f[0], "value": f[1]} for f in (fields or [])],
            "timestamp":   datetime.now(timezone.utc),
            "color":       color,
        }
        if any(x in title for x in ["Ban", "Kick", "Warn", "Timeout"]):
            log_entry["type"] = "moderation"
        elif "Ticket" in title:
            log_entry["type"] = "ticket"
        elif any(x in title for x in ["Member", "Join", "Left"]):
            log_entry["type"] = "member"
        elif any(x in title for x in ["Message", "Edit", "Delete"]):
            log_entry["type"] = "message"
        elif "Order" in title:
            log_entry["type"] = "order"
        elif any(x in title for x in ["Spam", "Link", "Bad Word"]):
            log_entry["type"] = "automod"
        else:
            log_entry["type"] = "general"
        db["logs"].insert_one(log_entry)
    except Exception:
        pass

# ─────────────────────────────────────────
#  HELPER: SECURITY CHECK
# ─────────────────────────────────────────
def has_security_role():
    async def predicate(ctx):
        role = ctx.guild.get_role(SECURITY_ROLE_ID)
        if role not in ctx.author.roles:
            await ctx.respond("❌ You don't have permission to use this command.", ephemeral=True)
            return False
        return True
    return commands.check(predicate)

# ─────────────────────────────────────────
#  HELPER: DISCORD API CALL
# ─────────────────────────────────────────
async def discord_api(method: str, endpoint: str, data: dict = None):
    url     = f"https://discord.com/api/v10{endpoint}"
    headers = {
        "Authorization": f"Bot {os.getenv('MTUwNDM1MDk4ODA0MTk4MjAwMw.GEenXb._DSxvdJaqGVMAPmmdnDbt5LKDRhR0ypiA13Ee4')}",
        "Content-Type":  "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, json=data, headers=headers) as r:
            if r.status in (200, 201, 204):
                try:
                    return await r.json()
                except Exception:
                    return {}
            return None

# ═══════════════════════════════════════════════════════════════
#  ██  TICKETS SYSTEM
# ═══════════════════════════════════════════════════════════════

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Sell", emoji="💰", style=discord.ButtonStyle.secondary, custom_id="ticket_sell")
    async def sell_button(self, button: Button, interaction: discord.Interaction):
        await open_ticket(interaction, ticket_type="Sell")

    @discord.ui.button(label="Buy", emoji="🛒", style=discord.ButtonStyle.success, custom_id="ticket_buy")
    async def buy_button(self, button: Button, interaction: discord.Interaction):
        await open_ticket(interaction, ticket_type="Buy")

    @discord.ui.button(label="Partner", emoji="🤝", style=discord.ButtonStyle.danger, custom_id="ticket_partner")
    async def partner_button(self, button: Button, interaction: discord.Interaction):
        await open_ticket(interaction, ticket_type="Partner")


class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_button(self, button: Button, interaction: discord.Interaction):
        await close_ticket(interaction)

    @discord.ui.button(label="Claim", emoji="✋", style=discord.ButtonStyle.primary, custom_id="ticket_claim")
    async def claim_button(self, button: Button, interaction: discord.Interaction):
        await claim_ticket(interaction)


class TicketRatingView(View):
    def __init__(self, seller_id: int):
        super().__init__(timeout=120)
        self.seller_id = seller_id

    @discord.ui.button(label="👍 Like", style=discord.ButtonStyle.success, custom_id="rating_like")
    async def like_button(self, button: Button, interaction: discord.Interaction):
        await submit_rating(interaction, self.seller_id, is_positive=True)
        self.stop()

    @discord.ui.button(label="👎 Dislike", style=discord.ButtonStyle.danger, custom_id="rating_dislike")
    async def dislike_button(self, button: Button, interaction: discord.Interaction):
        await submit_rating(interaction, self.seller_id, is_positive=False)
        self.stop()


async def open_ticket(interaction: discord.Interaction, ticket_type: str):
    guild  = interaction.guild
    member = interaction.user

    existing = discord.utils.get(
        guild.text_channels,
        name=f"ticket-{member.name.lower().replace(' ', '-')}"
    )
    if existing:
        await interaction.response.send_message(
            f"❌ You already have an open ticket: {existing.mention}", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    category   = discord.utils.get(guild.categories, id=TICKET_CATEGORY_ID)
    staff_role = guild.get_role(STAFF_ROLE_ID)

    overwrites = {
        guild.default_role: PermissionOverwrite(view_channel=False, send_messages=False),
        member: PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: PermissionOverwrite(view_channel=True, manage_channels=True),
    }
    if staff_role:
        overwrites[staff_role] = PermissionOverwrite(view_channel=True, send_messages=True)

    channel = await guild.create_text_channel(
        name=f"ticket-{member.name.lower().replace(' ', '-')}",
        category=category,
        overwrites=overwrites
    )

    db["tickets"].insert_one({
        "channel_id": channel.id,
        "user_id":    member.id,
        "type":       ticket_type,
        "opened_at":  datetime.now(timezone.utc),
        "seller_id":  None,
        "status":     "open",
    })

    embed = discord.Embed(
        title=f"🎫 {ticket_type} Ticket",
        description=f"Welcome {member.mention}!\nOur team will assist you as soon as possible.",
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_image(url=GIF_URL)
    embed.set_footer(text=FOOTER_TEXT)

    await channel.send(
        content=f"{member.mention} | <@&{STAFF_ROLE_ID}>",
        embed=embed,
        view=TicketControlView()
    )

    await send_log(guild, "🎫 Ticket Opened",
        f"**User:** {member.mention}\n**Type:** {ticket_type}\n**Channel:** {channel.mention}",
        color=0x57F287)

    await interaction.followup.send(f"✅ Your ticket has been created: {channel.mention}", ephemeral=True)


async def close_ticket(interaction: discord.Interaction):
    channel = interaction.channel
    guild   = interaction.guild

    await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")
    await asyncio.sleep(5)

    transcript = []
    async for msg in channel.history(limit=500, oldest_first=True):
        transcript.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author}: {msg.content}")

    transcript_file = discord.File(
        fp=io.BytesIO("\n".join(transcript).encode()),
        filename=f"transcript-{channel.name}.txt"
    )

    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        log_embed = discord.Embed(
            title="📋 Ticket Closed",
            description=f"**Channel:** {channel.name}\n**Closed by:** {interaction.user.mention}",
            color=0xED4245,
            timestamp=datetime.now(timezone.utc)
        )
        log_embed.set_footer(text=FOOTER_TEXT)
        await log_channel.send(embed=log_embed, file=transcript_file)

    ticket_data = db["tickets"].find_one({"channel_id": channel.id})
    buyer_id  = ticket_data["user_id"]   if ticket_data else None
    seller_id = ticket_data["seller_id"] if ticket_data else None

    db["tickets"].update_one({"channel_id": channel.id}, {"$set": {"status": "closed"}})

    if buyer_id and seller_id:
        buyer  = guild.get_member(buyer_id)
        seller = guild.get_member(seller_id)
        if buyer and seller:
            try:
                rating_embed = discord.Embed(
                    title="⭐ Rate Your Experience",
                    description=f"How was your experience with **{seller.display_name}**?\nPlease rate the seller:",
                    color=EMBED_COLOR
                )
                rating_embed.set_thumbnail(url=seller.display_avatar.url)
                rating_embed.set_footer(text=FOOTER_TEXT)
                await buyer.send(embed=rating_embed, view=TicketRatingView(seller_id=seller_id))
            except discord.Forbidden:
                pass

    await channel.delete()


async def claim_ticket(interaction: discord.Interaction):
    staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in interaction.user.roles:
        await interaction.response.send_message("❌ Only staff can claim tickets.", ephemeral=True)
        return

    db["tickets"].update_one(
        {"channel_id": interaction.channel.id},
        {"$set": {"seller_id": interaction.user.id}}
    )

    embed = discord.Embed(
        description=f"✋ This ticket has been claimed by {interaction.user.mention}",
        color=0x57F287,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)


async def submit_rating(interaction: discord.Interaction, seller_id: int, is_positive: bool):
    db["leaderboard"].update_one(
        {"seller_id": seller_id},
        {"$inc": {"total": 1, "positive": 1 if is_positive else 0}},
        upsert=True
    )
    embed = discord.Embed(
        description="✅ Thanks for your feedback!",
        color=0x57F287 if is_positive else 0xED4245
    )
    await interaction.response.edit_message(embed=embed, view=None)
    await update_leaderboard()

# ═══════════════════════════════════════════════════════════════
#  ██  ORDERS SYSTEM
# ═══════════════════════════════════════════════════════════════

class OrderView(View):
    def __init__(self, poster_id: int = 0):
        super().__init__(timeout=None)
        self.poster_id = poster_id

    @discord.ui.button(label="تواصل مع صاحب الرسالة", emoji="💬", style=discord.ButtonStyle.primary, custom_id="order_contact")
    async def contact_button(self, button: Button, interaction: discord.Interaction):
        await contact_seller(interaction, self.poster_id)

    @discord.ui.button(label="تم الاستلام", emoji="✅", style=discord.ButtonStyle.success, custom_id="order_done")
    async def done_button(self, button: Button, interaction: discord.Interaction):
        await mark_done(interaction)


async def contact_seller(interaction: discord.Interaction, poster_id: int):
    guild  = interaction.guild
    buyer  = interaction.user
    seller = guild.get_member(poster_id)

    if not seller:
        await interaction.response.send_message("❌ Could not find the seller.", ephemeral=True)
        return

    dm_link   = f"https://discord.com/users/{buyer.id}"
    timestamp = int(datetime.now(timezone.utc).timestamp())

    try:
        dm_embed = discord.Embed(
            title="📩 طلب تواصل جديد",
            description=f"مرحبا {seller.mention}، هناك عضو مهتم بالطلب الخاص بك ويرغب في التواصل معك لمناقشة التفاصيل.",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )
        dm_embed.set_thumbnail(url=buyer.display_avatar.url)
        dm_embed.add_field(name="User",                value=f"({buyer.mention})",               inline=False)
        dm_embed.add_field(name="Direct Message Link", value=f"[Click here to view]({dm_link})", inline=False)
        dm_embed.add_field(name="⏰ Time",             value=f"<t:{timestamp}:R>",               inline=False)
        dm_embed.set_footer(text=FOOTER_TEXT)
        await seller.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    await interaction.response.send_message("✅ The seller has been notified!", ephemeral=True)


async def mark_done(interaction: discord.Interaction):
    message = interaction.message
    if not message.embeds:
        await interaction.response.send_message("❌ No embed found.", ephemeral=True)
        return

    embed       = message.embeds[0]
    embed.title = "🔴 Order Completed"
    embed.color = 0xED4245

    await message.edit(embed=embed, view=None)

    await send_log(interaction.guild, "📦 Order Completed",
        f"**Order marked as done by:** {interaction.user.mention}",
        color=0x57F287)

    await interaction.response.send_message("✅ Order marked as completed!", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  ██  LEADERBOARD
# ═══════════════════════════════════════════════════════════════

async def update_leaderboard():
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if not channel:
        return

    sellers = list(db["leaderboard"].find().sort("positive", -1))
    medals  = ["🥇", "🥈", "🥉"]
    lines   = []

    for i, seller in enumerate(sellers[:10]):
        seller_id = seller.get("seller_id")
        total     = seller.get("total", 0)
        positive  = seller.get("positive", 0)
        ratio     = round((positive / total) * 100) if total > 0 else 0
        medal     = medals[i] if i < 3 else f"`#{i+1}`"
        member    = channel.guild.get_member(seller_id)
        name      = member.display_name if member else f"Unknown#{seller_id}"
        lines.append(f"{medal} **{name}** — 👍 {positive}/{total} deals ({ratio}%)")

    embed = discord.Embed(
        title="📊 MEM Store | Leaderboard",
        description="\n".join(lines) if lines else "No ratings yet.",
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_image(url=GIF_URL)
    embed.set_footer(text=FOOTER_TEXT)

    lb_data = db["config"].find_one({"key": "leaderboard_message"})
    if lb_data:
        try:
            msg = await channel.fetch_message(lb_data["message_id"])
            await msg.edit(embed=embed)
            return
        except (discord.NotFound, discord.HTTPException):
            pass

    msg = await channel.send(embed=embed)
    db["config"].update_one(
        {"key": "leaderboard_message"},
        {"$set": {"message_id": msg.id}},
        upsert=True
    )

# ═══════════════════════════════════════════════════════════════
#  ██  WELCOME SYSTEM
# ═══════════════════════════════════════════════════════════════

@bot.event
async def on_member_join(member: discord.Member):
    guild   = member.guild
    channel = guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        return

    config = db["config"].find_one({"key": "welcome_config"}) or {}
    custom_msg = config.get("message", "We hope you have a great time.")

    ticket_channel = guild.get_channel(TICKET_CHANNEL_ID)
    order_channel  = guild.get_channel(ORDER_CHANNEL_ID)
    timestamp      = int(member.joined_at.timestamp()) if member.joined_at else int(datetime.now(timezone.utc).timestamp())

    embed = discord.Embed(
        title=f"👋 Welcome to {SERVER_NAME}",
        description=(
            f"{member.mention} <> | <t:{timestamp}:F>\n\n"
            f"• Welcome {member.mention}\n"
            f"• Our family now consists of **{guild.member_count} Members**\n"
            f"• For Make Ticket: {ticket_channel.mention if ticket_channel else '#ticket'}\n"
            f"• Check our orders: {order_channel.mention if order_channel else '#orders'}\n"
            f"• {custom_msg}"
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_image(url=GIF_URL)
    embed.set_footer(text=FOOTER_TEXT)

    if MEMBER_ROLE_ID:
        role = guild.get_role(MEMBER_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

    msg = await channel.send(embed=embed)
    for emoji in ["🔷", "⭐", "🌟"]:
        await msg.add_reaction(emoji)

    await send_log(guild, "👋 Member Joined",
        f"**User:** {member.mention}\n**Account Created:** <t:{int(member.created_at.timestamp())}:R>",
        color=0x57F287)

    db["members"].update_one(
        {"user_id": member.id},
        {"$set": {"username": str(member), "joined_at": datetime.now(timezone.utc)}},
        upsert=True
    )


@bot.event
async def on_member_remove(member: discord.Member):
    await send_log(member.guild, "👋 Member Left",
        f"**User:** {member.mention} ({member.name})",
        color=0xED4245)

# ═══════════════════════════════════════════════════════════════
#  ██  MODERATION
# ═══════════════════════════════════════════════════════════════

mod = bot.create_group("mod", "Moderation commands")

@mod.command(name="ban", description="Ban a member")
@has_security_role()
async def ban(ctx, member: Option(discord.Member, "Member to ban"), reason: Option(str, "Reason", default="No reason provided")):
    try:
        await member.ban(reason=reason)
        embed = discord.Embed(description=f"✅ **{member}** has been banned.\n**Reason:** {reason}", color=0xED4245)
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, "🔨 Member Banned",
            f"**User:** {member.mention}\n**By:** {ctx.author.mention}\n**Reason:** {reason}", color=0xED4245)
    except discord.Forbidden:
        await ctx.respond("❌ I don't have permission to ban this member.", ephemeral=True)


@mod.command(name="unban", description="Unban a member by ID")
@has_security_role()
async def unban(ctx, user_id: Option(str, "User ID to unban")):
    try:
        user = await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user)
        embed = discord.Embed(description=f"✅ **{user}** has been unbanned.", color=0x57F287)
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, "✅ Member Unbanned",
            f"**User:** {user.mention}\n**By:** {ctx.author.mention}", color=0x57F287)
    except Exception:
        await ctx.respond("❌ Could not find or unban this user.", ephemeral=True)


@mod.command(name="kick", description="Kick a member")
@has_security_role()
async def kick(ctx, member: Option(discord.Member, "Member to kick"), reason: Option(str, "Reason", default="No reason provided")):
    try:
        await member.kick(reason=reason)
        embed = discord.Embed(description=f"✅ **{member}** has been kicked.\n**Reason:** {reason}", color=0xED4245)
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, "👢 Member Kicked",
            f"**User:** {member.mention}\n**By:** {ctx.author.mention}\n**Reason:** {reason}", color=0xED4245)
    except discord.Forbidden:
        await ctx.respond("❌ I don't have permission to kick this member.", ephemeral=True)


@mod.command(name="timeout", description="Timeout a member")
@has_security_role()
async def timeout(ctx,
    member: Option(discord.Member, "Member to timeout"),
    minutes: Option(int, "Duration in minutes", min_value=1, max_value=10080),
    reason: Option(str, "Reason", default="No reason provided")):
    try:
        import datetime as dt
        await member.timeout_for(dt.timedelta(minutes=minutes), reason=reason)
        embed = discord.Embed(
            description=f"✅ **{member}** timed out for **{minutes} minutes**.\n**Reason:** {reason}",
            color=0xFEE75C)
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, "⏰ Member Timed Out",
            f"**User:** {member.mention}\n**By:** {ctx.author.mention}\n**Duration:** {minutes} min\n**Reason:** {reason}",
            color=0xFEE75C)
    except discord.Forbidden:
        await ctx.respond("❌ I don't have permission.", ephemeral=True)


@mod.command(name="untimeout", description="Remove timeout from a member")
@has_security_role()
async def untimeout(ctx, member: Option(discord.Member, "Member to untimeout")):
    try:
        await member.remove_timeout()
        embed = discord.Embed(description=f"✅ Timeout removed from **{member}**.", color=0x57F287)
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, "✅ Timeout Removed",
            f"**User:** {member.mention}\n**By:** {ctx.author.mention}", color=0x57F287)
    except discord.Forbidden:
        await ctx.respond("❌ I don't have permission.", ephemeral=True)


@mod.command(name="warn", description="Warn a member")
@has_security_role()
async def warn(ctx, member: Option(discord.Member, "Member to warn"), reason: Option(str, "Reason")):
    import datetime as dt
    db["warnings"].insert_one({
        "guild_id":  ctx.guild.id,
        "user_id":   member.id,
        "reason":    reason,
        "by":        ctx.author.id,
        "timestamp": datetime.now(timezone.utc)
    })
    warn_count = db["warnings"].count_documents({"guild_id": ctx.guild.id, "user_id": member.id})
    embed = discord.Embed(
        description=f"⚠️ **{member}** warned.\n**Reason:** {reason}\n**Total:** {warn_count}",
        color=0xFEE75C)
    await ctx.respond(embed=embed)
    await send_log(ctx.guild, "⚠️ Member Warned",
        f"**User:** {member.mention}\n**By:** {ctx.author.mention}\n**Reason:** {reason}\n**Total:** {warn_count}",
        color=0xFEE75C)
    if warn_count >= 5:
        try:
            await member.ban(reason="Auto-ban: 5 warnings")
            await send_log(ctx.guild, "🔨 Auto Ban", f"**User:** {member.mention} — 5 warnings.", color=0xED4245)
        except discord.Forbidden:
            pass
    elif warn_count >= 3:
        try:
            await member.timeout_for(dt.timedelta(hours=1), reason="Auto-timeout: 3 warnings")
            await send_log(ctx.guild, "⏰ Auto Timeout", f"**User:** {member.mention} — 3 warnings.", color=0xFEE75C)
        except discord.Forbidden:
            pass


@mod.command(name="warnings", description="View warnings of a member")
@has_security_role()
async def warnings(ctx, member: Option(discord.Member, "Member to check")):
    warns = list(db["warnings"].find({"guild_id": ctx.guild.id, "user_id": member.id}))
    if not warns:
        await ctx.respond(f"✅ **{member}** has no warnings.", ephemeral=True)
        return
    lines = [f"`{i}.` {w['reason']} — <t:{int(w['timestamp'].timestamp())}:R>" for i, w in enumerate(warns, 1)]
    embed = discord.Embed(title=f"⚠️ Warnings for {member}", description="\n".join(lines), color=0xFEE75C)
    await ctx.respond(embed=embed, ephemeral=True)


@mod.command(name="clearwarnings", description="Clear all warnings for a member")
@has_security_role()
async def clearwarnings(ctx, member: Option(discord.Member, "Member to clear warnings")):
    db["warnings"].delete_many({"guild_id": ctx.guild.id, "user_id": member.id})
    await ctx.respond(f"✅ All warnings cleared for **{member}**.", ephemeral=True)
    await send_log(ctx.guild, "🗑️ Warnings Cleared",
        f"**User:** {member.mention}\n**By:** {ctx.author.mention}", color=0x57F287)


@mod.command(name="clear", description="Delete messages")
@has_security_role()
async def clear(ctx, amount: Option(int, "Number of messages to delete", min_value=1, max_value=100)):
    await ctx.channel.purge(limit=amount)
    await ctx.respond(f"✅ Deleted **{amount}** messages.", ephemeral=True)
    await send_log(ctx.guild, "🗑️ Messages Cleared",
        f"**Channel:** {ctx.channel.mention}\n**Amount:** {amount}\n**By:** {ctx.author.mention}", color=0xFEE75C)


@mod.command(name="lock", description="Lock a channel")
@has_security_role()
async def lock(ctx, channel: Option(discord.TextChannel, "Channel to lock", default=None)):
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.respond(f"🔒 {ch.mention} locked.", ephemeral=True)
    await send_log(ctx.guild, "🔒 Channel Locked", f"**Channel:** {ch.mention}\n**By:** {ctx.author.mention}", color=0xED4245)


@mod.command(name="unlock", description="Unlock a channel")
@has_security_role()
async def unlock(ctx, channel: Option(discord.TextChannel, "Channel to unlock", default=None)):
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.respond(f"🔓 {ch.mention} unlocked.", ephemeral=True)
    await send_log(ctx.guild, "🔓 Channel Unlocked", f"**Channel:** {ch.mention}\n**By:** {ctx.author.mention}", color=0x57F287)


@mod.command(name="slowmode", description="Set slowmode for a channel")
@has_security_role()
async def slowmode(ctx,
    seconds: Option(int, "Slowmode in seconds (0 to disable)", min_value=0, max_value=21600),
    channel: Option(discord.TextChannel, "Channel", default=None)):
    ch = channel or ctx.channel
    await ch.edit(slowmode_delay=seconds)
    status = f"set to **{seconds}s**" if seconds > 0 else "**disabled**"
    await ctx.respond(f"✅ Slowmode {status} in {ch.mention}.", ephemeral=True)
    await send_log(ctx.guild, "🐢 Slowmode Updated",
        f"**Channel:** {ch.mention}\n**Slowmode:** {seconds}s\n**By:** {ctx.author.mention}", color=0xFEE75C)

# ═══════════════════════════════════════════════════════════════
#  ██  SELF ROLES
# ═══════════════════════════════════════════════════════════════

class LanguageRoleView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="🌍 Choose your language! | إختر لغتك!",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="English", emoji="🇬🇧", value="English"),
            discord.SelectOption(label="Arabic",  emoji="🇸🇦", value="Arabic"),
        ],
        custom_id="select_language"
    )
    async def language_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        await toggle_role(interaction, LANGUAGE_ROLES[select.values[0]], select.values[0])


class GameRoleView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="🎮 Choose your game! | إختر لعبتك!",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="ARC Raiders", emoji="🎯", value="ARC Raiders"),
            discord.SelectOption(label="PUBG Mobile",  emoji="📱", value="PUBG Mobile"),
            discord.SelectOption(label="PUBG Steam",   emoji="💻", value="PUBG Steam"),
        ],
        custom_id="select_game"
    )
    async def game_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        await toggle_role(interaction, GAME_ROLES[select.values[0]], select.values[0])


async def toggle_role(interaction: discord.Interaction, role_id: int, role_name: str):
    guild  = interaction.guild
    member = interaction.user
    role   = guild.get_role(role_id)
    if not role:
        await interaction.response.send_message("❌ Role not found.", ephemeral=True)
        return
    if role in member.roles:
        await member.remove_roles(role)
        await interaction.response.send_message(f"✅ Removed **{role_name}** role.", ephemeral=True)
    else:
        await member.add_roles(role)
        await interaction.response.send_message(f"✅ Added **{role_name}** role.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════
#  ██  AUTO MOD
# ═══════════════════════════════════════════════════════════════

URL_REGEX = re.compile(r"(https?://\S+|www\.\S+|discord\.gg/\S+)")

async def check_spam(message: discord.Message):
    user_id = message.author.id
    now     = datetime.now(timezone.utc).timestamp()
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if now - t < SPAM_WINDOW]
    spam_tracker[user_id].append(now)
    if len(spam_tracker[user_id]) >= SPAM_LIMIT:
        spam_tracker[user_id] = []
        try:
            import datetime as dt
            await message.author.timeout_for(dt.timedelta(minutes=5), reason="Auto-mod: Spam")
            embed = discord.Embed(description=f"⚠️ {message.author.mention} timed out for **5 minutes** (spam).", color=0xED4245)
            await message.channel.send(embed=embed, delete_after=5)
            await send_log(message.guild, "🚨 Anti-Spam", f"**User:** {message.author.mention}", color=0xED4245)
        except discord.Forbidden:
            pass
        return True
    return False


async def check_bad_words(message: discord.Message):
    content_lower = message.content.lower()
    config = db["config"].find_one({"key": "bad_words"})
    words  = config.get("words", BAD_WORDS) if config else BAD_WORDS
    for word in words:
        if word in content_lower:
            try:
                await message.delete()
                embed = discord.Embed(
                    description=f"⚠️ {message.author.mention} your message was removed for inappropriate language.",
                    color=0xED4245)
                await message.channel.send(embed=embed, delete_after=5)
                await send_log(message.guild, "🤬 Bad Word Detected",
                    f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}", color=0xED4245)
            except discord.Forbidden:
                pass
            return True
    return False


async def check_links(message: discord.Message):
    if message.channel.id == LINKS_ALLOWED_CHANNEL:
        return False
    if URL_REGEX.search(message.content):
        staff_role = message.guild.get_role(STAFF_ROLE_ID)
        if staff_role and staff_role in message.author.roles:
            return False
        if message.author.guild_permissions.administrator:
            return False
        try:
            await message.delete()
            embed = discord.Embed(
                description=f"⚠️ {message.author.mention} links are not allowed in this channel.",
                color=0xED4245)
            await message.channel.send(embed=embed, delete_after=5)
            await send_log(message.guild, "🔗 Link Blocked",
                f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}", color=0xED4245)
        except discord.Forbidden:
            pass
        return True
    return False

# ═══════════════════════════════════════════════════════════════
#  ██  EVENTS
# ═══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    bot.add_view(TicketView())
    bot.add_view(TicketControlView())
    bot.add_view(OrderView())
    bot.add_view(LanguageRoleView())
    bot.add_view(GameRoleView())
    await bot.sync_commands()
    print(f"✅ {bot.user} is online | MEM Store Bot | Guild: {GUILD_ID}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id == ORDER_CHANNEL_ID:
        content   = message.content
        author    = message.author
        timestamp = int(message.created_at.timestamp())
        await message.delete()
        embed = discord.Embed(title="🛒 MEM Store | ORDER", description=content, color=EMBED_COLOR)
        embed.set_thumbnail(url=author.display_avatar.url)
        embed.set_image(url=GIF_URL)
        embed.add_field(name="• Posted By :", value=f"{author.mention} | <@&{ARC_ROLE_ID}>", inline=False)
        embed.add_field(name="⏰ Time:",       value=f"<t:{timestamp}:F>",                    inline=False)
        embed.set_footer(text=FOOTER_TEXT)
        await message.channel.send(embed=embed, view=OrderView(poster_id=author.id))
        await send_log(message.guild, "📦 New Order Posted", f"**By:** {author.mention}", color=0x5865F2)
        return

    if message.channel.id == FEEDBACK_CHANNEL_ID:
        content   = message.content
        author    = message.author
        timestamp = int(message.created_at.timestamp())
        await message.delete()
        embed = discord.Embed(title="💬 MEM Store | FEEDBACK", description=content, color=EMBED_COLOR)
        embed.set_thumbnail(url=author.display_avatar.url)
        embed.set_image(url=GIF_URL)
        embed.add_field(name="• Posted By :", value=f"{author.mention} | <@&{ARC_ROLE_ID}>", inline=False)
        embed.add_field(name="⏰ Time:",       value=f"<t:{timestamp}:F>",                    inline=False)
        embed.set_footer(text=FOOTER_TEXT)
        await message.channel.send(embed=embed)
        await send_log(message.guild, "💬 New Feedback Posted", f"**By:** {author.mention}", color=0x5865F2)
        return

    if await check_bad_words(message): return
    if await check_links(message):     return
    if await check_spam(message):      return


@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild: return
    await send_log(message.guild, "🗑️ Message Deleted",
        f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Content:** {message.content or 'No content'}",
        color=0xED4245)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild: return
    if before.content == after.content: return
    await send_log(before.guild, "✏️ Message Edited",
        f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}",
        color=0xFEE75C,
        fields=[("Before", before.content or "Empty", False), ("After", after.content or "Empty", False)])


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.display_name != after.display_name:
        await send_log(before.guild, "✏️ Nickname Changed",
            f"**User:** {after.mention}\n**Before:** {before.display_name}\n**After:** {after.display_name}",
            color=0x5865F2)

# ═══════════════════════════════════════════════════════════════
#  ██  SLASH COMMANDS
# ═══════════════════════════════════════════════════════════════

@bot.slash_command(name="ticket_panel", description="Send the MEM Store ticket panel")
@commands.has_permissions(administrator=True)
async def ticket_panel(ctx):
    embed = discord.Embed(
        title="🎫 MEM Store | Ticket Center", **...**

_This response is too long to display in full._
