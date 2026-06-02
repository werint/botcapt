import discord
from discord import app_commands
import asyncio
import os
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────
#  НАСТРОЙКИ
# ─────────────────────────────────────────
BOT_TOKEN       = os.environ["DISCORD_TOKEN"]
CAPTAIN_ROLE_ID = int(os.environ.get("CAPTAIN_ROLE_ID", "1478205318591938671"))
UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", "20"))   # секунд
MAX_UPDATES     = int(os.environ.get("MAX_UPDATES",     "180"))  # 180 × 20с = 60 мин
CHUNK_SIZE      = 40  # человек в одном поле embed
# ─────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members   = True

bot  = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

sessions: dict[int, dict] = {}


# ── helpers ───────────────────────────────

def has_captain_role(member: discord.Member) -> bool:
    return any(r.id == CAPTAIN_ROLE_ID for r in member.roles)


def make_embed(picked: list[int], update_num: int, started_at: datetime) -> discord.Embed:
    ends_at = started_at + timedelta(seconds=UPDATE_INTERVAL * MAX_UPDATES)
    embed = discord.Embed(
        title=f"⚔️  Список  [{len(picked)} чел.]",
        color=0xE8B84B,
        timestamp=utcnow(),
    )
    if not picked:
        embed.description = "*Никого ещё не выбрали...*"
    else:
        chunks = [picked[i:i + CHUNK_SIZE] for i in range(0, len(picked), CHUNK_SIZE)]
        for idx, chunk in enumerate(chunks):
            start_num = idx * CHUNK_SIZE + 1
            embed.add_field(
                name=f"#{start_num}–{start_num + len(chunk) - 1}",
                value="\n".join(f"{start_num + j}. <@{uid}>" for j, uid in enumerate(chunk)),
                inline=True,
            )
    embed.set_footer(
        text=f"Обновление {update_num}/{MAX_UPDATES}  •  Завершится в {ends_at.strftime('%H:%M')} UTC"
    )
    return embed


# ── реакции через события (мгновенно, без polling) ───

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    """Капитан поставил реакцию — добавляем автора сообщения в список."""
    channel_id = payload.channel_id
    if channel_id not in sessions or not sessions[channel_id]["active"]:
        return

    # Проверяем роль реагирующего
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member or not has_captain_role(member):
        return

    # Получаем автора сообщения
    channel = bot.get_channel(channel_id)
    try:
        msg = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    author = msg.author
    if author.bot:
        return

    session = sessions[channel_id]
    if author.id not in session["picked_set"]:
        session["picked_set"].add(author.id)
        session["picked"].append(author.id)
        print(f"[+] Добавлен <@{author.id}> ({author.display_name})")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
    """Капитан убрал реакцию — проверяем, остались ли другие реакции капитанов под этим сообщением."""
    channel_id = payload.channel_id
    if channel_id not in sessions or not sessions[channel_id]["active"]:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member or not has_captain_role(member):
        return

    channel = bot.get_channel(channel_id)
    try:
        msg = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    author = msg.author
    if author.bot:
        return

    session = sessions[channel_id]
    if author.id not in session["picked_set"]:
        return

    # Проверяем: есть ли ещё хоть одна реакция капитана под этим сообщением?
    still_picked = False
    for reaction in msg.reactions:
        async for user in reaction.users():
            if user.bot:
                continue
            m = guild.get_member(user.id)
            if m and has_captain_role(m):
                still_picked = True
                break
        if still_picked:
            break

    if not still_picked:
        session["picked_set"].discard(author.id)
        session["picked"] = [uid for uid in session["picked"] if uid != author.id]
        print(f"[-] Убран <@{author.id}> ({author.display_name})")


# ── первоначальный сбор истории (один раз при старте) ─

async def initial_scan(channel: discord.TextChannel) -> tuple[list[int], set[int]]:
    """Сканирует историю канала один раз при запуске команды."""
    picked: list[int] = []
    picked_set: set[int] = set()

    async for msg in channel.history(limit=500):
        if not msg.reactions or msg.author.bot or msg.author.id in picked_set:
            continue
        for reaction in msg.reactions:
            found = False
            async for user in reaction.users():
                if user.bot:
                    continue
                m = channel.guild.get_member(user.id)
                if m and has_captain_role(m):
                    found = True
                    break
            if found:
                picked_set.add(msg.author.id)
                picked.append(msg.author.id)
                break

    return picked, picked_set


# ── update loop (только обновляет embed по таймеру) ───

async def update_loop(channel_id: int) -> None:
    session = sessions[channel_id]

    for i in range(1, MAX_UPDATES + 1):
        await asyncio.sleep(UPDATE_INTERVAL)

        if not session["active"]:
            break

        session["update_count"] = i

        try:
            embed_msg = await session["channel"].fetch_message(session["message"].id)
        except discord.NotFound:
            print(f"[-] Embed удалён — останавливаем сессию {channel_id}")
            session["active"] = False
            break

        try:
            await embed_msg.edit(embed=make_embed(session["picked"], i, session["started_at"]))
        except discord.HTTPException as exc:
            print(f"[!] Ошибка редактирования embed: {exc}")

        print(f"[~] {channel_id}: обновление {i}/{MAX_UPDATES}, в списке {len(session['picked'])} чел.")

    # ── финал ──
    session["active"] = False
    try:
        embed_msg = await session["channel"].fetch_message(session["message"].id)
        final = make_embed(session["picked"], MAX_UPDATES, session["started_at"])
        final.title = "✅  Список на капт  —  Завершён"
        final.color = 0x57F287
        final.set_footer(text="Сбор завершён")
        await embed_msg.edit(embed=final)
        await session["channel"].send("🏁 **Список на капт завершён!**")
    except Exception:
        pass

    sessions.pop(channel_id, None)
    print(f"[✓] Сессия {channel_id} завершена")


# ── slash commands ────────────────────────

@tree.command(name="капт", description="Запустить список на капт (обновляется 60 минут)")
async def capt_command(interaction: discord.Interaction) -> None:
    member = interaction.user
    if not isinstance(member, discord.Member) or not has_captain_role(member):
        await interaction.response.send_message(
            "⛔ У тебя нет прав для запуска этой команды.", ephemeral=True
        )
        return

    channel_id = interaction.channel_id
    if channel_id in sessions and sessions[channel_id]["active"]:
        await interaction.response.send_message(
            "⚠️ Список на капт уже активен в этом канале!", ephemeral=True
        )
        return

    await interaction.response.defer()

    started_at = utcnow()
    message = await interaction.followup.send(embed=make_embed([], 0, started_at))

    # Сканируем историю один раз
    picked, picked_set = await initial_scan(interaction.channel)

    sessions[channel_id] = {
        "active":       True,
        "message":      message,
        "channel":      interaction.channel,
        "picked":       picked,        # список (порядок важен)
        "picked_set":   picked_set,    # множество для быстрой проверки дублей
        "update_count": 0,
        "started_at":   started_at,
        "initiator_id": interaction.user.id,
    }

    # Обновляем embed с результатами начального скана
    try:
        await message.edit(embed=make_embed(picked, 0, started_at))
    except discord.HTTPException:
        pass

    asyncio.create_task(update_loop(channel_id))
    print(f"[+] Сессия запущена: {interaction.channel.name} (id={channel_id}), начальный скан: {len(picked)} чел.")


@tree.command(name="стоп_капт", description="Досрочно завершить список на капт")
async def stop_capt(interaction: discord.Interaction) -> None:
    member = interaction.user
    if not isinstance(member, discord.Member) or not has_captain_role(member):
        await interaction.response.send_message(
            "⛔ У тебя нет прав для этой команды.", ephemeral=True
        )
        return

    channel_id = interaction.channel_id
    if channel_id not in sessions or not sessions[channel_id]["active"]:
        await interaction.response.send_message(
            "❌ Нет активного списка в этом канале.", ephemeral=True
        )
        return

    sessions[channel_id]["active"] = False
    await interaction.response.send_message("🛑 Список на капт остановлен досрочно.")


# ── bot events ────────────────────────────

@bot.event
async def on_ready() -> None:
    await tree.sync()
    print(f"[✓] Бот запущен: {bot.user}  (id={bot.user.id})")
    print(f"    CAPTAIN_ROLE_ID : {CAPTAIN_ROLE_ID}")
    print(f"    Интервал        : {UPDATE_INTERVAL}с × {MAX_UPDATES} = {UPDATE_INTERVAL * MAX_UPDATES // 60} мин")


bot.run(BOT_TOKEN)