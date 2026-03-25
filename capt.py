import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import os
import traceback

# Настройки бота
TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_ROLE_ID = 1478205318591938671
ALLOWED_CREATOR_ROLE = 1478205318591938671
LOG_CHANNEL_ID = 1448991378750046209
SCREENSHOT_WAIT_TIME = 300

# Хранилище активных каптов
active_capts = {}

class CaptManager:
    def __init__(self, message_id, channel_id, creator_id, title_text, need_screenshot):
        self.message_id = message_id
        self.channel_id = channel_id
        self.creator_id = creator_id
        self.created_at = datetime.now()
        self.is_active = True
        self.title_text = title_text
        self.need_screenshot = need_screenshot
        self.screenshot_url = None
        self.screenshot_user = None
        self.screenshot_wait_task = None
        self.registered_users = []
        self.plus_users = []
        self.update_count = 0
        self.message_sent = False

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True

class CaptBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        await self.tree.sync()
        print(f"✅ Команды синхронизированы")

bot = CaptBot()

async def get_log_channel():
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except:
            print(f"⚠️ Канал логов {LOG_CHANNEL_ID} не найден")
            return None
    return channel

async def send_log(message: str, color: int = 0x0099ff, title: str = "📋 Лог"):
    channel = await get_log_channel()
    if not channel:
        return
    
    embed = discord.Embed(
        color=color,
        title=title,
        description=message,
        timestamp=datetime.now()
    )
    
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"❌ Ошибка при отправке лога: {e}")

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'Подключен к серверам: {len(bot.guilds)}')
    
    await send_log(
        f"✅ **Бот запущен**\n"
        f"• Пользователь: {bot.user} (ID: {bot.user.id})\n"
        f"• Серверов: {len(bot.guilds)}\n"
        f"• Канал логов: <#{LOG_CHANNEL_ID}>",
        color=0x00ff00,
        title="🚀 Бот запущен"
    )

def check_creator_role(interaction: discord.Interaction) -> bool:
    return any(role.id == ALLOWED_CREATOR_ROLE for role in interaction.user.roles)

def check_register_role(interaction: discord.Interaction) -> bool:
    return any(role.id == ALLOWED_CREATOR_ROLE for role in interaction.user.roles)

async def update_capt_embed(message_id):
    if message_id not in active_capts:
        print(f"❌ Капт {message_id} не найден в active_capts")
        return False
    
    capt = active_capts[message_id]
    if not capt.is_active:
        return False
    
    channel = bot.get_channel(capt.channel_id)
    if not channel:
        return False
    
    try:
        message = await channel.fetch_message(message_id)
        
        registered_text = ""
        if capt.registered_users:
            for i, user in enumerate(capt.registered_users, 1):
                registered_text += f"{i}. {user.mention}\n"
        else:
            registered_text = "Нет зарегистрированных"
        
        plus_text = ""
        if capt.plus_users:
            for i, user in enumerate(capt.plus_users, 1):
                plus_text += f"{i}. {user.mention}\n"
        else:
            plus_text = "Нет плюсов"
        
        embed = discord.Embed(
            color=0x0099ff,
            title=f"📋 {capt.title_text}",
            timestamp=datetime.now()
        )
        
        embed.add_field(name="📝 Регнутые игроки", value=registered_text, inline=True)
        embed.add_field(name="👍 Плюсы", value=plus_text, inline=True)
        
        if capt.screenshot_url:
            embed.set_image(url=capt.screenshot_url)
        
        time_left = timedelta(hours=1) - (datetime.now() - capt.created_at)
        minutes_left = int(time_left.total_seconds() / 60)
        seconds_left = int(time_left.total_seconds() % 60)
        
        if minutes_left > 0:
            time_str = f"Осталось {minutes_left} мин {seconds_left} сек"
        else:
            time_str = f"Осталось {seconds_left} сек"
        
        embed.set_footer(text=f"🔄 Обновлено • {time_str}")
        
        view = discord.ui.View(timeout=None)
        
        plus_button = discord.ui.Button(
            label="➕ Кинуть плюс",
            style=discord.ButtonStyle.success,
            custom_id=f"plus_{message_id}"
        )
        remove_plus_button = discord.ui.Button(
            label="➖ Убрать плюс",
            style=discord.ButtonStyle.danger,
            custom_id=f"remove_plus_{message_id}"
        )
        
        view.add_item(plus_button)
        view.add_item(remove_plus_button)
        
        await message.edit(embed=embed, view=view)
        
        return True
        
    except Exception as e:
        print(f"Ошибка при обновлении капта {message_id}: {e}")
        traceback.print_exc()
        return False

async def send_capt_message(channel, capt):
    """Отправляет финальное сообщение с @everyone и embed"""
    await channel.send("@everyone")
    
    registered_text = ""
    if capt.registered_users:
        for i, user in enumerate(capt.registered_users, 1):
            registered_text += f"{i}. {user.mention}\n"
    else:
        registered_text = "Нет зарегистрированных"
    
    plus_text = ""
    if capt.plus_users:
        for i, user in enumerate(capt.plus_users, 1):
            plus_text += f"{i}. {user.mention}\n"
    else:
        plus_text = "Нет плюсов"
    
    embed = discord.Embed(
        color=0x0099ff,
        title=f"📋 {capt.title_text}",
        timestamp=datetime.now()
    )
    
    embed.add_field(name="📝 Регнутые игроки", value=registered_text, inline=True)
    embed.add_field(name="👍 Плюсы", value=plus_text, inline=True)
    
    if capt.screenshot_url:
        embed.set_image(url=capt.screenshot_url)
    
    embed.set_footer(text=f"🔄 Обновляется по кнопкам • Активен 1 час")
    
    view = discord.ui.View(timeout=None)
    
    # Кнопки создаются с правильным ID, который будет присвоен после отправки
    # Но мы не можем использовать capt.message_id, потому что он еще не присвоен
    # Поэтому создаем временный view, который будем обновлять после отправки
    
    message = await channel.send(embed=embed)
    
    # Теперь у нас есть реальный ID сообщения
    capt.message_id = message.id
    
    # Обновляем кнопки с правильным ID
    view = discord.ui.View(timeout=None)
    plus_button = discord.ui.Button(
        label="➕ Кинуть плюс",
        style=discord.ButtonStyle.success,
        custom_id=f"plus_{capt.message_id}"
    )
    remove_plus_button = discord.ui.Button(
        label="➖ Убрать плюс",
        style=discord.ButtonStyle.danger,
        custom_id=f"remove_plus_{capt.message_id}"
    )
    view.add_item(plus_button)
    view.add_item(remove_plus_button)
    
    await message.edit(view=view)
    
    capt.message_sent = True
    
    return message

async def start_screenshot_wait(capt, interaction):
    """Запускает ожидание скриншота"""
    embed = discord.Embed(
        color=0xffaa00,
        title="📸 Ожидание скриншота",
        description=f"Пожалуйста, отправьте скриншот в этот канал.\n\n"
                    f"**Текст капта:** {capt.title_text}\n"
                    f"⏰ Время ожидания: 5 минут",
        timestamp=datetime.now()
    )
    
    await interaction.followup.send(embed=embed, ephemeral=True)
    
    def check(msg):
        return (msg.author.id == interaction.user.id and 
                msg.channel.id == interaction.channel_id and
                msg.attachments and 
                any(att.content_type and att.content_type.startswith('image/') for att in msg.attachments))
    
    try:
        screenshot_msg = await bot.wait_for('message', timeout=SCREENSHOT_WAIT_TIME, check=check)
        
        capt.screenshot_url = screenshot_msg.attachments[0].url
        capt.screenshot_user = screenshot_msg.author
        
        await screenshot_msg.delete()
        
        await send_capt_message(interaction.channel, capt)
        
        # Сохраняем в активные капты с правильным ID
        active_capts[capt.message_id] = capt
        
        await send_log(
            f"📸 **Скриншот получен**\n"
            f"• Капт: {capt.title_text}\n"
            f"• Отправил: {screenshot_msg.author.mention}\n"
            f"• Скриншот: [ссылка]({capt.screenshot_url})",
            color=0x00ff00,
            title="📸 Скриншот получен"
        )
        
        async def expire_loop():
            await asyncio.sleep(3600)
            await disable_capt(capt.message_id)
        
        capt.expire_task = asyncio.create_task(expire_loop())
        
    except asyncio.TimeoutError:
        await send_capt_message(interaction.channel, capt)
        
        active_capts[capt.message_id] = capt
        
        await send_log(
            f"⏰ **Время ожидания скриншота истекло**\n"
            f"• Капт: {capt.title_text}\n"
            f"• Создатель: <@{capt.creator_id}>",
            color=0xffaa00,
            title="⏰ Таймаут скриншота"
        )
        
        async def expire_loop():
            await asyncio.sleep(3600)
            await disable_capt(capt.message_id)
        
        capt.expire_task = asyncio.create_task(expire_loop())

async def disable_capt(message_id):
    if message_id not in active_capts:
        return
    
    capt = active_capts[message_id]
    capt.is_active = False
    
    if capt.screenshot_wait_task:
        capt.screenshot_wait_task.cancel()
    
    channel = bot.get_channel(capt.channel_id)
    if channel:
        try:
            message = await channel.fetch_message(message_id)
            
            embed = message.embeds[0]
            embed.color = 0x808080
            embed.set_footer(text="⏰ Срок действия истек")
            
            view = discord.ui.View(timeout=None)
            plus_button = discord.ui.Button(
                label="➕ Кинуть плюс",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id="plus_disabled"
            )
            remove_plus_button = discord.ui.Button(
                label="➖ Убрать плюс",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id="remove_plus_disabled"
            )
            view.add_item(plus_button)
            view.add_item(remove_plus_button)
            
            await message.edit(embed=embed, view=view)
            print(f"✅ Капт {message_id} деактивирован")
            
            await send_log(
                f"⏰ **Капт завершен**\n"
                f"• Канал: {channel.mention}\n"
                f"• Название: {capt.title_text}\n"
                f"• Создатель: <@{capt.creator_id}>\n"
                f"• Зарегистрировано: {len(capt.registered_users)}\n"
                f"• Плюсов: {len(capt.plus_users)}",
                color=0x808080,
                title="⏰ Капт завершен"
            )
            
        except Exception as e:
            print(f"Ошибка при деактивации капта: {e}")
    
    if message_id in active_capts:
        del active_capts[message_id]

@bot.tree.command(name="capt", description="Создать капт")
@app_commands.describe(text="Текст для заголовка капта")
async def capt_command(interaction: discord.Interaction, text: str):
    if not check_creator_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав на использование этой команды.\n"
            f"Требуется роль: <@&{ALLOWED_CREATOR_ROLE}>", 
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        color=0x0099ff,
        title="📸 Нужен скриншот?",
        description=f"**Текст капта:** {text}\n\nТребуется ли скриншот для этого капта?",
        timestamp=datetime.now()
    )
    
    view = discord.ui.View(timeout=60)
    
    async def yes_callback(interaction_btn: discord.Interaction):
        await interaction_btn.response.defer(ephemeral=True)
        
        # Создаем капт с временным ID (0)
        capt = CaptManager(
            message_id=0,
            channel_id=interaction_btn.channel_id,
            creator_id=interaction_btn.user.id,
            title_text=text,
            need_screenshot=True
        )
        
        # Запускаем ожидание скриншота (внутри будет создан капт с реальным ID)
        await start_screenshot_wait(capt, interaction_btn)
    
    async def no_callback(interaction_btn: discord.Interaction):
        await interaction_btn.response.defer(ephemeral=True)
        
        # Создаем капт
        capt = CaptManager(
            message_id=0,
            channel_id=interaction_btn.channel_id,
            creator_id=interaction_btn.user.id,
            title_text=text,
            need_screenshot=False
        )
        
        # Отправляем сообщение
        await send_capt_message(interaction_btn.channel, capt)
        
        # Сохраняем в активные капты с правильным ID
        active_capts[capt.message_id] = capt
        
        async def expire_loop():
            await asyncio.sleep(3600)
            await disable_capt(capt.message_id)
        
        capt.expire_task = asyncio.create_task(expire_loop())
        
        await interaction_btn.followup.send("✅ Капт создан без скриншота!", ephemeral=True)
        
        await send_log(
            f"✅ **Новый капт создан (без скриншота)**\n"
            f"• Канал: {interaction_btn.channel.mention}\n"
            f"• Сообщение: [ссылка](https://discord.com/channels/{interaction_btn.guild.id}/{interaction_btn.channel.id}/{capt.message_id})\n"
            f"• Создатель: {interaction_btn.user.mention}\n"
            f"• Текст: {text}",
            color=0x00ff00,
            title="📋 Новый капт"
        )
    
    yes_button = discord.ui.Button(label="✅ Да", style=discord.ButtonStyle.success)
    yes_button.callback = yes_callback
    
    no_button = discord.ui.Button(label="❌ Нет", style=discord.ButtonStyle.danger)
    no_button.callback = no_callback
    
    view.add_item(yes_button)
    view.add_item(no_button)
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]
        
        print(f"🔍 Получен interaction: {custom_id}")
        
        # Обработка плюсов
        if custom_id.startswith("plus_"):
            try:
                message_id = int(custom_id.split("_")[1])
                print(f"➕ Обработка плюса для сообщения {message_id}")
                
                if message_id not in active_capts:
                    print(f"❌ Капт {message_id} не найден в active_capts")
                    print(f"Доступные ключи: {list(active_capts.keys())}")
                    await interaction.response.send_message("❌ Капт не найден", ephemeral=True)
                    return
                
                capt = active_capts[message_id]
                if not capt.is_active:
                    await interaction.response.send_message("❌ Срок действия капта истек", ephemeral=True)
                    return
                
                user = interaction.user
                
                if user.id in [u.id for u in capt.registered_users]:
                    await interaction.response.send_message("❌ Зарегистрированные игроки не могут ставить плюсы!", ephemeral=True)
                    return
                
                if user.id in [u.id for u in capt.plus_users]:
                    await interaction.response.send_message("❌ Вы уже поставили плюс!", ephemeral=True)
                    return
                
                capt.plus_users.append(user)
                await update_capt_embed(message_id)
                await interaction.response.send_message("✅ Вы поставили плюс!", ephemeral=True)
                
                await send_log(
                    f"➕ **Плюс поставлен**\n"
                    f"• Капт: {capt.title_text}\n"
                    f"• Пользователь: {user.mention}",
                    color=0x00ff00,
                    title="➕ Плюс"
                )
            except Exception as e:
                print(f"Ошибка при обработке плюса: {e}")
                traceback.print_exc()
                await interaction.response.send_message("❌ Произошла ошибка", ephemeral=True)
        
        # Обработка удаления плюсов
        elif custom_id.startswith("remove_plus_"):
            try:
                parts = custom_id.split("_")
                if len(parts) >= 3:
                    message_id = int(parts[2])
                else:
                    await interaction.response.send_message("❌ Ошибка формата кнопки", ephemeral=True)
                    return
                
                print(f"➖ Обработка удаления плюса для сообщения {message_id}")
                
                if message_id not in active_capts:
                    print(f"❌ Капт {message_id} не найден в active_capts")
                    print(f"Доступные ключи: {list(active_capts.keys())}")
                    await interaction.response.send_message("❌ Капт не найден", ephemeral=True)
                    return
                
                capt = active_capts[message_id]
                if not capt.is_active:
                    await interaction.response.send_message("❌ Срок действия капта истек", ephemeral=True)
                    return
                
                user = interaction.user
                
                if user.id not in [u.id for u in capt.plus_users]:
                    await interaction.response.send_message("❌ Вы не ставили плюс!", ephemeral=True)
                    return
                
                capt.plus_users = [u for u in capt.plus_users if u.id != user.id]
                await update_capt_embed(message_id)
                await interaction.response.send_message("✅ Плюс убран!", ephemeral=True)
                
                await send_log(
                    f"➖ **Плюс убран**\n"
                    f"• Капт: {capt.title_text}\n"
                    f"• Пользователь: {user.mention}",
                    color=0xffaa00,
                    title="➖ Плюс убран"
                )
            except Exception as e:
                print(f"Ошибка при обработке удаления плюса: {e}")
                traceback.print_exc()
                await interaction.response.send_message("❌ Произошла ошибка", ephemeral=True)

@bot.tree.command(name="регистрация", description="Зарегистрировать пользователя в капте")
@app_commands.describe(
    сообщение_id="ID сообщения с каптом",
    пользователь="Пользователь для регистрации"
)
async def register_user_command(interaction: discord.Interaction, сообщение_id: str, пользователь: discord.User):
    if not check_register_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для использования этой команды.\n"
            f"Требуется роль: <@&{ALLOWED_CREATOR_ROLE}>", 
            ephemeral=True
        )
        return
    
    try:
        message_id = int(сообщение_id)
        
        if message_id not in active_capts:
            await interaction.response.send_message("❌ Капт не найден или уже неактивен", ephemeral=True)
            return
        
        capt = active_capts[message_id]
        if not capt.is_active:
            await interaction.response.send_message("❌ Срок действия капта истек", ephemeral=True)
            return
        
        if пользователь.id in [u.id for u in capt.registered_users]:
            await interaction.response.send_message("❌ Пользователь уже зарегистрирован!", ephemeral=True)
            return
        
        capt.registered_users.append(пользователь)
        
        if пользователь.id in [u.id for u in capt.plus_users]:
            capt.plus_users = [u for u in capt.plus_users if u.id != пользователь.id]
        
        await update_capt_embed(message_id)
        
        await interaction.response.send_message(f"✅ Пользователь {пользователь.mention} зарегистрирован в капте!", ephemeral=True)
        
        await send_log(
            f"📝 **Пользователь зарегистрирован**\n"
            f"• Капт: {capt.title_text}\n"
            f"• Зарегистрировал: {interaction.user.mention}\n"
            f"• Пользователь: {пользователь.mention}",
            color=0x00ff00,
            title="📝 Регистрация"
        )
        
    except ValueError:
        await interaction.response.send_message("❌ Неверный ID сообщения", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

@bot.tree.command(name="капты", description="Показать активные капты")
async def list_capts(interaction: discord.Interaction):
    if not active_capts:
        await interaction.response.send_message("❌ Нет активных каптов", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 Активные капты",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    for message_id, capt in active_capts.items():
        if capt.message_id == 0:
            continue
            
        time_left = timedelta(hours=1) - (datetime.now() - capt.created_at)
        minutes_left = int(time_left.total_seconds() / 60)
        
        embed.add_field(
            name=f"Капт: {capt.title_text[:50]}",
            value=f"• ID: {message_id}\n"
                  f"• Канал: <#{capt.channel_id}>\n"
                  f"• Создатель: <@{capt.creator_id}>\n"
                  f"• Зарегистрировано: {len(capt.registered_users)}\n"
                  f"• Плюсов: {len(capt.plus_users)}\n"
                  f"• Осталось: {minutes_left} мин",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Ошибка: Не найден DISCORD_TOKEN в переменных окружения")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Ошибка: Неверный токен Discord")
        exit(1)
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
        exit(1)