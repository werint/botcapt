import discord
from discord import app_commands
import asyncio
import os
from datetime import datetime, timedelta

# ─────────────────────────────────────────
#  НАСТРОЙКИ  (через переменные окружения Railway)
# ─────────────────────────────────────────
BOT_TOKEN        = os.environ["DISCORD_TOKEN"]          # обязательно
CAPTAIN_ROLE_ID  = int(os.environ.get("CAPTAIN_ROLE_ID", "1478205318591938671"))
UPDATE_INTERVAL  = int(os.environ.get("UPDATE_INTERVAL", "60"))   # секунд
MAX_UPDATES      = int(os.environ.get("MAX_UPDATES",     "60"))    # итераций
# ─────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# channel_id -> сессия
sessions: dict[int, dict] = {}


# ── helpers ──────────────────────────────

def has_captain_role(member: discord.Member) -> bool:
    return any(r.id == CAPTAIN_ROLE_ID for r in member.roles)


def make_embed(reactions: dict[str, list[str]], update_num: int, started_at: datetime) -> discord.Embed:
    ends_at = started_at + timedelta(seconds=UPDATE_INTERVAL * MAX_UPDATES)

    embed = discord.Embed(
        title="⚔️  Список на капт",
        color=0xE8B84B,
        timestamp=datetime.utcnow(),
    )

    if reactions:
        for emoji, users in reactions.items():
            embed.add_field(
                name=emoji,
                value="\n".join(f"• {u}" for u in users),
                inline=True,
            )
    else:
        embed.description = "*Реакций пока нет...*"

    embed.set_footer(
        text=(
            f"Обновление {update_num}/{MAX_UPDATES}  •  "
            f"Завершится в {ends_at.strftime('%H:%M')}"
        )
    )
    return embed


# ── update loop ───────────────────────────

async def update_loop(channel_id: int) -> None:
    session = sessions[channel_id]

    for i in range(1, MAX_UPDATES + 1):
        await asyncio.sleep(UPDATE_INTERVAL)

        if not session["active"]:
            break

        session["update_count"] = i

        try:
            msg: discord.Message = await session["channel"].fetch_message(
                session["message"].id
            )
        except discord.NotFound:
            print(f"[-] Сообщение удалено — останавливаем сессию {channel_id}")
            session["active"] = False
            break

        reactions_data: dict[str, list[str]] = {}
        for reaction in msg.reactions:
            emoji_str = str(reaction.emoji)
            names: list[str] = []
            async for user in reaction.users():
                if user.bot:
                    continue
                member = msg.guild.get_member(user.id)
                if member and has_captain_role(member):
                    names.append(member.display_name)
            if names:
                reactions_data[emoji_str] = names

        session["reactions"] = reactions_data

        try:
            await msg.edit(embed=make_embed(reactions_data, i, session["started_at"]))
        except discord.HTTPException as exc:
            print(f"[!] Ошибка редактирования embed: {exc}")

        print(f"[~] Канал {channel_id}: обновление {i}/{MAX_UPDATES}")

    # ── завершение ──
    session["active"] = False
    try:
        msg = await session["channel"].fetch_message(session["message"].id)
        final = make_embed(session["reactions"], MAX_UPDATES, session["started_at"])
        final.title  = "✅  Список на капт  —  Завершён"
        final.color  = 0x57F287
        final.set_footer(text="Сбор завершён")
        await msg.edit(embed=final)
        await session["channel"].send("🏁 **Список на капт завершён!**")
    except Exception:
        pass

    sessions.pop(channel_id, None)
    print(f"[✓] Сессия {channel_id} завершена")


# ── slash commands ────────────────────────

@tree.command(name="капт", description="Запустить список на капт (обновляется 60 минут)")
async def capt_command(interaction: discord.Interaction) -> None:
    # Проверка роли
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

    started_at = datetime.utcnow()
    embed = make_embed({}, 0, started_at)
    message = await interaction.followup.send(embed=embed)

    sessions[channel_id] = {
        "active":       True,
        "message":      message,
        "channel":      interaction.channel,
        "reactions":    {},
        "update_count": 0,
        "started_at":   started_at,
        "initiator_id": interaction.user.id,
    }

    asyncio.create_task(update_loop(channel_id))
    print(f"[+] Сессия запущена: канал {interaction.channel.name} (id={channel_id})")


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
