import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import os
import traceback

# Настройки бота
TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_ROLE_ID = 1478205318591938671  # Роль для регистрации и создания капта
ALLOWED_CREATOR_ROLE = 1478205318591938671  # Только эта роль может создавать /capt
LOG_CHANNEL_ID = 1448991378750046209  # Канал для логов
SCREENSHOT_WAIT_TIME = 300  # 5 минут ожидания скриншота

# Хранилище активных каптов
active_capts = {}

class CaptManager:
    def __init__(self, message_id, channel_id, creator_id, text, need_screenshot):
        self.message_id = message_id
        self.channel_id = channel_id
        self.creator_id = creator_id
        self.created_at = datetime.now()
        self.is_active = True
        self.text = text
        self.need_screenshot = need_screenshot
        self.screenshot_provided = False
        self.screenshot_user = None
        self.screenshot_wait_task = None
        self.registered_users = []  # Список зарегистрированных пользователей (кто в левой колонке)
        self.plus_users = []  # Список пользователей, кто поставил плюс
        self.update_count = 0

# Правильная настройка интентов
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
    """Получает канал для логов"""
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except:
            print(f"⚠️ Канал логов {LOG_CHANNEL_ID} не найден")
            return None
    return channel

async def send_log(message: str, color: int = 0x0099ff, title: str = "📋 Лог"):
    """Отправляет сообщение в канал логов"""
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
    """Проверяет, есть ли у пользователя роль для создания капта"""
    return any(role.id == ALLOWED_CREATOR_ROLE for role in interaction.user.roles)

def check_register_role(interaction: discord.Interaction) -> bool:
    """Проверяет, есть ли у пользователя роль для регистрации"""
    return any(role.id == ALLOWED_CREATOR_ROLE for role in interaction.user.roles)

async def update_capt_embed(message_id):
    """Обновляет embed с текущими списками"""
    if message_id not in active_capts:
        return False
    
    capt = active_capts[message_id]
    if not capt.is_active:
        return False
    
    channel = bot.get_channel(capt.channel_id)
    if not channel:
        return False
    
    try:
        message = await channel.fetch_message(message_id)
        
        # Формируем левую колонку (зарегистрированные)
        registered_text = ""
        if capt.registered_users:
            for i, user in enumerate(capt.registered_users, 1):
                registered_text += f"{i}. {user.mention}\n"
        else:
            registered_text = "Нет зарегистрированных"
        
        # Формируем правую колонку (плюсы)
        plus_text = ""
        if capt.plus_users:
            for i, user in enumerate(capt.plus_users, 1):
                plus_text += f"{i}. {user.mention}\n"
        else:
            plus_text = "Нет плюсов"
        
        embed = discord.Embed(
            color=0x0099ff,
            title=f"📋 Капт",
            timestamp=datetime.now()
        )
        
        embed.add_field(name="📝 Регнутые игроки", value=registered_text, inline=True)
        embed.add_field(name="👍 Плюсы", value=plus_text, inline=True)
        
        # Информация о времени
        time_left = timedelta(hours=1) - (datetime.now() - capt.created_at)
        minutes_left = int(time_left.total_seconds() / 60)
        seconds_left = int(time_left.total_seconds() % 60)
        
        if minutes_left > 0:
            time_str = f"Осталось {minutes_left} мин {seconds_left} сек"
        else:
            time_str = f"Осталось {seconds_left} сек"
        
        embed.set_footer(text=f"🔄 Обновлено • {time_str}")
        
        # Создаем кнопки
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
        
        # Если у пользователя есть роль регистратора, добавляем кнопку регистрации
        # Она будет отображаться, но проверка прав будет при нажатии
        
        await message.edit(embed=embed, view=view)
        
        return True
        
    except Exception as e:
        print(f"Ошибка при обновлении капта {message_id}: {e}")
        return False

async def start_screenshot_wait(message_id):
    """Запускает ожидание скриншота"""
    if message_id not in active_capts:
        return
    
    capt = active_capts[message_id]
    
    async def wait_for_screenshot():
        await asyncio.sleep(SCREENSHOT_WAIT_TIME)
        if capt.is_active and not capt.screenshot_provided:
            # Время вышло, отправляем без скриншота
            capt.screenshot_provided = True  # Помечаем как обработанное
            
            # Отправляем сообщение с текстом
            channel = bot.get_channel(capt.channel_id)
            if channel:
                await channel.send(f"{capt.text}")
                await update_capt_embed(message_id)
                
                await send_log(
                    f"⏰ **Скриншот не получен**\n"
                    f"• Капт ID: {message_id}\n"
                    f"• Создатель: <@{capt.creator_id}>\n"
                    f"• Текст: {capt.text[:100]}",
                    color=0xffaa00,
                    title="⏰ Таймаут скриншота"
                )
    
    capt.screenshot_wait_task = asyncio.create_task(wait_for_screenshot())

async def disable_capt(message_id):
    """Деактивирует капт через час"""
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
            
            # Деактивируем кнопки
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
            
            # Логируем итоги
            await send_log(
                f"⏰ **Капт завершен**\n"
                f"• Канал: {channel.mention}\n"
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

@bot.tree.command(name="capt", description="Создать капт с текстом")
@app_commands.describe(text="Текст для отправки (например: @everyone ПРАК, ВСЕ В РЕГУ // КОД ГРУППЫ - D2YXN)")
async def capt_command(interaction: discord.Interaction, text: str):
    # Проверка прав
    if not check_creator_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав на использование этой команды.\n"
            f"Требуется роль: <@&{ALLOWED_CREATOR_ROLE}>", 
            ephemeral=True
        )
        return
    
    # Спрашиваем про скриншот
    embed = discord.Embed(
        color=0x0099ff,
        title="📸 Нужен скриншот?",
        description="Требуется ли скриншот для этого капта?\n\n"
                    f"**Текст:** {text}",
        timestamp=datetime.now()
    )
    
    view = discord.ui.View(timeout=60)
    
    async def yes_callback(interaction_btn: discord.Interaction):
        await interaction_btn.response.defer()
        await interaction_btn.followup.send("✅ Скриншот будет ожидаться 5 минут", ephemeral=True)
        
        # Создаем капт с ожиданием скриншота
        await create_capt(interaction_btn, text, need_screenshot=True)
    
    async def no_callback(interaction_btn: discord.Interaction):
        await interaction_btn.response.defer()
        await interaction_btn.followup.send("✅ Капт создан без скриншота", ephemeral=True)
        
        # Создаем капт без скриншота
        await create_capt(interaction_btn, text, need_screenshot=False)
    
    yes_button = discord.ui.Button(label="✅ Да", style=discord.ButtonStyle.success)
    yes_button.callback = yes_callback
    
    no_button = discord.ui.Button(label="❌ Нет", style=discord.ButtonStyle.danger)
    no_button.callback = no_callback
    
    view.add_item(yes_button)
    view.add_item(no_button)
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def create_capt(interaction: discord.Interaction, text: str, need_screenshot: bool):
    """Создает капт после ответа о скриншоте"""
    channel = interaction.channel
    
    # Создаем embed
    embed = discord.Embed(
        color=0x0099ff,
        title=f"📋 Капт",
        description="Загрузка...",
        timestamp=datetime.now()
    )
    
    embed.add_field(name="📝 Регнутые игроки", value="Загрузка...", inline=True)
    embed.add_field(name="👍 Плюсы", value="Загрузка...", inline=True)
    embed.set_footer(text="Создание капта...")
    
    # Создаем временные кнопки
    view = discord.ui.View(timeout=None)
    plus_button = discord.ui.Button(
        label="➕ Кинуть плюс",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        custom_id="plus_temp"
    )
    remove_plus_button = discord.ui.Button(
        label="➖ Убрать плюс",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        custom_id="remove_plus_temp"
    )
    view.add_item(plus_button)
    view.add_item(remove_plus_button)
    
    message = await channel.send(embed=embed, view=view)
    
    # Создаем менеджер капта
    capt = CaptManager(
        message.id, 
        channel.id, 
        interaction.user.id, 
        text, 
        need_screenshot
    )
    active_capts[message.id] = capt
    
    # Если нужен скриншот, запускаем ожидание
    if need_screenshot:
        await start_screenshot_wait(message.id)
        
        # Отправляем сообщение о необходимости скриншота
        await channel.send(
            f"<@&{ALLOWED_CREATOR_ROLE}> Ожидается скриншот в течение 5 минут!\n"
            f"Отправьте скриншот в этот канал или используйте кнопку ниже.",
            view=ScreenshotWaitView(message.id)
        )
    else:
        # Сразу отправляем текст
        await channel.send(f"{text}")
        await update_capt_embed(message.id)
    
    # Запускаем задачу истечения через час
    async def expire_loop():
        await asyncio.sleep(3600)
        await disable_capt(message.id)
    
    capt.expire_task = asyncio.create_task(expire_loop())
    
    # Логируем создание
    await send_log(
        f"✅ **Новый капт создан**\n"
        f"• Канал: {channel.mention}\n"
        f"• Сообщение: [ссылка]({message.jump_url})\n"
        f"• Создатель: {interaction.user.mention}\n"
        f"• Текст: {text}\n"
        f"• Скриншот: {'Да' if need_screenshot else 'Нет'}",
        color=0x00ff00,
        title="📋 Новый капт"
    )

class ScreenshotWaitView(discord.ui.View):
    def __init__(self, capt_id):
        super().__init__(timeout=300)  # 5 минут таймаут
        self.capt_id = capt_id
    
    @discord.ui.button(label="📸 Скриншот отправлен", style=discord.ButtonStyle.success, custom_id="screenshot_done")
    async def screenshot_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_creator_role(interaction):
            await interaction.response.send_message("❌ У вас нет прав для подтверждения скриншота", ephemeral=True)
            return
        
        if self.capt_id not in active_capts:
            await interaction.response.send_message("❌ Капт не найден", ephemeral=True)
            return
        
        capt = active_capts[self.capt_id]
        if capt.screenshot_provided:
            await interaction.response.send_message("❌ Скриншот уже был подтвержден", ephemeral=True)
            return
        
        capt.screenshot_provided = True
        if capt.screenshot_wait_task:
            capt.screenshot_wait_task.cancel()
        
        # Отправляем текст
        channel = interaction.channel
        await channel.send(f"{capt.text}")
        await update_capt_embed(self.capt_id)
        
        # Удаляем это сообщение с кнопкой
        await interaction.message.delete()
        
        await interaction.response.send_message("✅ Скриншот подтвержден! Капт активирован.", ephemeral=True)
        
        await send_log(
            f"📸 **Скриншот получен**\n"
            f"• Капт ID: {self.capt_id}\n"
            f"• Подтвердил: {interaction.user.mention}",
            color=0x00ff00,
            title="📸 Скриншот"
        )

@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Обработка нажатий на кнопки"""
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]
        
        # Обработка плюсов
        if custom_id.startswith("plus_"):
            message_id = int(custom_id.split("_")[1])
            
            if message_id not in active_capts:
                await interaction.response.send_message("❌ Капт не найден", ephemeral=True)
                return
            
            capt = active_capts[message_id]
            if not capt.is_active:
                await interaction.response.send_message("❌ Срок действия капта истек", ephemeral=True)
                return
            
            user = interaction.user
            
            if user.id in [u.id for u in capt.plus_users]:
                await interaction.response.send_message("❌ Вы уже поставили плюс!", ephemeral=True)
                return
            
            capt.plus_users.append(user)
            await update_capt_embed(message_id)
            await interaction.response.send_message("✅ Вы поставили плюс!", ephemeral=True)
            
            await send_log(
                f"➕ **Плюс поставлен**\n"
                f"• Капт ID: {message_id}\n"
                f"• Пользователь: {user.mention}",
                color=0x00ff00,
                title="➕ Плюс"
            )
        
        # Обработка удаления плюсов
        elif custom_id.startswith("remove_plus_"):
            message_id = int(custom_id.split("_")[2])
            
            if message_id not in active_capts:
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
                f"• Капт ID: {message_id}\n"
                f"• Пользователь: {user.mention}",
                color=0xffaa00,
                title="➖ Плюс убран"
            )
        
        # Обработка регистрации пользователей (только для роли 1478205318591938671)
        elif custom_id.startswith("register_"):
            message_id = int(custom_id.split("_")[1])
            target_user_id = int(custom_id.split("_")[2])
            
            if not check_register_role(interaction):
                await interaction.response.send_message("❌ У вас нет прав для регистрации пользователей", ephemeral=True)
                return
            
            if message_id not in active_capts:
                await interaction.response.send_message("❌ Капт не найден", ephemeral=True)
                return
            
            capt = active_capts[message_id]
            if not capt.is_active:
                await interaction.response.send_message("❌ Срок действия капта истек", ephemeral=True)
                return
            
            target_user = interaction.guild.get_member(target_user_id)
            if not target_user:
                await interaction.response.send_message("❌ Пользователь не найден", ephemeral=True)
                return
            
            if target_user.id in [u.id for u in capt.registered_users]:
                await interaction.response.send_message("❌ Пользователь уже зарегистрирован!", ephemeral=True)
                return
            
            capt.registered_users.append(target_user)
            await update_capt_embed(message_id)
            await interaction.response.send_message(f"✅ Пользователь {target_user.mention} зарегистрирован!", ephemeral=True)
            
            await send_log(
                f"📝 **Пользователь зарегистрирован**\n"
                f"• Капт ID: {message_id}\n"
                f"• Зарегистрировал: {interaction.user.mention}\n"
                f"• Пользователь: {target_user.mention}",
                color=0x00ff00,
                title="📝 Регистрация"
            )

@bot.tree.command(name="регистрация", description="Зарегистрировать пользователя в капте")
@app_commands.describe(
    сообщение="ID сообщения с каптом",
    пользователь="Пользователь для регистрации"
)
async def register_user_command(interaction: discord.Interaction, сообщение: str, пользователь: discord.User):
    """Команда для регистрации пользователя (только для роли 1478205318591938671)"""
    if not check_register_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для использования этой команды.\n"
            f"Требуется роль: <@&{ALLOWED_CREATOR_ROLE}>", 
            ephemeral=True
        )
        return
    
    try:
        message_id = int(сообщение)
        
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
        await update_capt_embed(message_id)
        
        await interaction.response.send_message(f"✅ Пользователь {пользователь.mention} зарегистрирован в капте!", ephemeral=True)
        
        await send_log(
            f"📝 **Пользователь зарегистрирован**\n"
            f"• Капт ID: {message_id}\n"
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
    """Показывает список активных каптов"""
    if not active_capts:
        await interaction.response.send_message("❌ Нет активных каптов", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 Активные капты",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    for message_id, capt in active_capts.items():
        time_left = timedelta(hours=1) - (datetime.now() - capt.created_at)
        minutes_left = int(time_left.total_seconds() / 60)
        
        embed.add_field(
            name=f"Капт #{message_id}",
            value=f"• Канал: <#{capt.channel_id}>\n"
                  f"• Создатель: <@{capt.creator_id}>\n"
                  f"• Зарегистрировано: {len(capt.registered_users)}\n"
                  f"• Плюсов: {len(capt.plus_users)}\n"
                  f"• Осталось: {minutes_left} мин",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Запуск бота
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