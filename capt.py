import discord
from discord import app_commands
import asyncio
import os
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────
#  НАСТРОЙКИ  (через переменные окружения Railway)
# ─────────────────────────────────────────
BOT_TOKEN       = os.environ["DISCORD_TOKEN"]
CAPTAIN_ROLE_ID = int(os.environ.get("CAPTAIN_ROLE_ID", "1478205318591938671"))
UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", "60"))   # секунд
MAX_UPDATES     = int(os.environ.get("MAX_UPDATES",     "60"))    # итераций
# ─────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot  = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# channel_id -> сессия
sessions: dict[int, dict] = {}


# ── helpers ───────────────────────────────

def has_captain_role(member: discord.Member) -> bool:
    return any(r.id == CAPTAIN_ROLE_ID for r in member.roles)


def make_embed(
    reactions: dict[str, list[int]],   # emoji -> [user_id, ...]
    update_num: int,
    started_at: datetime,
) -> discord.Embed:
    ends_at = started_at + timedelta(seconds=UPDATE_INTERVAL * MAX_UPDATES)

    embed = discord.Embed(
        title="⚔️  Список на капт",
        color=0xE8B84B,
        timestamp=utcnow(),
    )

    if reactions:
        for emoji, user_ids in reactions.items():
            mentions = "\n".join(f"• <@{uid}>" for uid in user_ids)
            embed.add_field(name=emoji, value=mentions, inline=True)
    else:
        embed.description = "*Реакций пока нет...*"

    embed.set_footer(
        text=(
            f"Обновление {update_num}/{MAX_UPDATES}  •  "
            f"Завершится в {ends_at.strftime('%H:%M')} UTC"
        )
    )
    return embed


async def collect_reactions(channel: discord.TextChannel, embed_msg_id: int) -> dict[str, list[int]]:
    """
    Сканирует ВСЕ сообщения канала (историю + embed-сообщение).
    Возвращает словарь emoji -> [user_id, ...] только для капитанов.
    Один человек считается только один раз (первый встреченный эмодзи игнорируется — 
    берётся любой, но дублей нет).
    """
    reactions_data: dict[str, list[int]] = {}
    seen_users: set[int] = set()

    # Собираем все message_id канала (история, лимит 500 сообщений)
    message_ids: list[int] = []
    async for hist_msg in channel.history(limit=500):
        if hist_msg.reactions:
            message_ids.append(hist_msg.id)

    # Убеждаемся что embed-сообщение тоже в списке
    if embed_msg_id not in message_ids:
        message_ids.append(embed_msg_id)

    for mid in message_ids:
        try:
            msg = await channel.fetch_message(mid)
        except discord.NotFound:
            continue

        for reaction in msg.reactions:
            emoji_str = str(reaction.emoji)
            async for user in reaction.users():
                if user.bot or user.id in seen_users:
                    continue
                member = channel.guild.get_member(user.id)
                if member and has_captain_role(member):
                    seen_users.add(user.id)
                    reactions_data.setdefault(emoji_str, []).append(user.id)

    return reactions_data


# ── update loop ───────────────────────────

async def update_loop(channel_id: int) -> None:
    session = sessions[channel_id]

    for i in range(1, MAX_UPDATES + 1):
        await asyncio.sleep(UPDATE_INTERVAL)

        if not session["active"]:
            break

        session["update_count"] = i

        # Проверяем, что embed-сообщение ещё живо
        try:
            embed_msg: discord.Message = await session["channel"].fetch_message(
                session["message"].id
            )
        except discord.NotFound:
            print(f"[-] Embed удалён — останавливаем сессию {channel_id}")
            session["active"] = False
            break

        reactions_data = await collect_reactions(session["channel"], embed_msg.id)
        session["reactions"] = reactions_data

        try:
            await embed_msg.edit(embed=make_embed(reactions_data, i, session["started_at"]))
        except discord.HTTPException as exc:
            print(f"[!] Ошибка редактирования embed: {exc}")

        print(f"[~] Канал {channel_id}: обновление {i}/{MAX_UPDATES}, найдено {sum(len(v) for v in reactions_data.values())} реакций капитанов")

    # ── финальное обновление ──
    session["active"] = False
    try:
        embed_msg = await session["channel"].fetch_message(session["message"].id)
        final = make_embed(session["reactions"], MAX_UPDATES, session["started_at"])
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

    # Первый сбор — уже до команды (история канала)
    channel = interaction.channel
    initial_reactions = await collect_reactions(channel, 0)  # 0 — embed ещё не создан

    embed = make_embed(initial_reactions, 0, started_at)
    message = await interaction.followup.send(embed=embed)

    sessions[channel_id] = {
        "active":       True,
        "message":      message,
        "channel":      channel,
        "reactions":    initial_reactions,
        "update_count": 0,
        "started_at":   started_at,
        "initiator_id": interaction.user.id,
    }

    asyncio.create_task(update_loop(channel_id))
    print(f"[+] Сессия запущена: канал {channel.name} (id={channel_id}), начальных реакций: {sum(len(v) for v in initial_reactions.values())}")


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