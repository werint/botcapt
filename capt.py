import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import os
import traceback

# Настройки бота
TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_ROLE_ID = 1478205318591938671  # Роль, которая ставит реакции
CHECKMARK_EMOJI = '✅'
ALLOWED_ROLES = [
    1310673963000528949,
    1223589384452833290, 
    1381682246678741022,
    1478205318591938671
]
LOG_CHANNEL_ID = 1448991378750046209  # Канал для логов
AUTO_UPDATE_INTERVAL = 5  # секунд - теперь реально будет обновляться каждые 5 секунд

# Хранилище активных каптов
active_capts = {}

class CaptManager:
    def __init__(self, message_id, channel_id, creator_id):
        self.message_id = message_id
        self.channel_id = channel_id
        self.creator_id = creator_id
        self.created_at = datetime.now()
        self.is_active = True
        self.expire_task = None
        self.auto_update_task = None
        self.update_count = 0
        self.last_users = []  # Кэш последних пользователей

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
        f"• Автообновление: каждые {AUTO_UPDATE_INTERVAL} сек\n"
        f"• Канал логов: <#{LOG_CHANNEL_ID}>",
        color=0x00ff00,
        title="🚀 Бот запущен"
    )
    
    cleanup_expired_capts.start()

async def get_users_with_checkmark_from_target_role(channel):
    """
    Получает ВСЕХ пользователей, на чьих сообщениях есть реакция ✅,
    которую поставил пользователь с ролью TARGET_ROLE_ID.
    Возвращает список кортежей (пользователь, время_первой_реакции)
    """
    target_role = channel.guild.get_role(TARGET_ROLE_ID)
    if not target_role:
        print(f"⚠️ Роль {TARGET_ROLE_ID} не найдена на сервере {channel.guild.name}")
        return []
    
    # Словарь для хранения {user_id: (user, first_reaction_time)}
    user_data = {}
    
    try:
        # Перебираем все сообщения в канале (увеличил лимит для точности)
        async for message in channel.history(limit=2000):
            # Проверяем все реакции на сообщении
            for reaction in message.reactions:
                # Проверяем, что это нужная реакция ✅
                if str(reaction.emoji) == CHECKMARK_EMOJI or reaction.emoji == '✅':
                    
                    # Проверяем всех, кто поставил эту реакцию
                    async for user in reaction.users():
                        if isinstance(user, discord.Member):
                            # Если пользователь, поставивший реакцию, имеет целевую роль
                            if target_role in user.roles:
                                # Добавляем АВТОРА сообщения в словарь с временем сообщения
                                if message.author and not message.author.bot:
                                    user_id = message.author.id
                                    reaction_time = message.created_at
                                    
                                    # Сохраняем самое раннее время реакции для каждого пользователя
                                    if user_id not in user_data:
                                        user_data[user_id] = (message.author, reaction_time)
                                    else:
                                        # Если нашли более раннюю реакцию, обновляем время
                                        if reaction_time < user_data[user_id][1]:
                                            user_data[user_id] = (message.author, reaction_time)
        
        # Преобразуем в список и сортируем по времени (от самого раннего к позднему)
        users_list = [(user, reaction_time) for user, reaction_time in user_data.values()]
        users_list.sort(key=lambda x: x[1])  # Сортировка по времени реакции
        
        print(f"📊 Найдено {len(users_list)} пользователей, отсортировано по времени")
        
        # Возвращаем только список пользователей (без времени)
        return [user for user, _ in users_list]
        
    except discord.Forbidden:
        print(f"❌ Нет доступа к каналу {channel.name}")
        return []
    except Exception as e:
        print(f"❌ Ошибка при обработке канала {channel.name}: {e}")
        return []

async def update_capt_list(message_id, auto_update=False):
    """Обновляет список пользователей в embed с оптимизацией"""
    if message_id not in active_capts:
        return False
    
    capt = active_capts[message_id]
    if not capt.is_active:
        return False
    
    channel = bot.get_channel(capt.channel_id)
    if not channel:
        return False
    
    try:
        start_time = datetime.now()
        message = await channel.fetch_message(message_id)
        
        # Получаем отсортированных пользователей
        users = await get_users_with_checkmark_from_target_role(channel)
        
        # Проверяем, изменился ли список
        current_user_ids = [user.id for user in users]
        old_user_ids = [user.id for user in capt.last_users] if capt.last_users else []
        
        has_changed = current_user_ids != old_user_ids
        
        if users:
            # Создаем описание со списком пользователей
            description_parts = [f"**Найдено пользователей: {len(users)}**\n"]
            
            # Добавляем пользователей с нумерацией по порядку (кто раньше поставил реакцию - тот выше в списке)
            for i, user in enumerate(users, 1):
                description_parts.append(f"{i}. {user.mention}")
            
            description = '\n'.join(description_parts)
            color = 0x00ff00
        else:
            description = '❌ Пользователи с реакцией ✅ от целевой роли не найдены'
            color = 0xff0000
        
        embed = discord.Embed(
            color=color,
            title='📋 Список на капт',
            description=description,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="📌 Канал",
            value=f"{channel.mention}",
            inline=True
        )
        
        embed.add_field(
            name="✅ Условие",
            value=f"Реакция `{CHECKMARK_EMOJI}` от <@&{TARGET_ROLE_ID}>",
            inline=False
        )
        
        # Информация о времени
        time_left = timedelta(hours=1) - (datetime.now() - capt.created_at)
        minutes_left = int(time_left.total_seconds() / 60)
        seconds_left = int(time_left.total_seconds() % 60)
        
        if minutes_left > 0:
            time_str = f"Осталось {minutes_left} мин {seconds_left} сек"
        else:
            time_str = f"Осталось {seconds_left} сек"
        
        # Время последнего обновления
        update_time_str = datetime.now().strftime("%H:%M:%S")
        auto_update_status = f"🔄 Автообновление ({capt.update_count}) • Последнее: {update_time_str}"
            
        embed.set_footer(text=f"{auto_update_status} • {time_str}")
        
        await message.edit(embed=embed)
        
        # Сохраняем текущий список для сравнения
        capt.last_users = users.copy()
        capt.update_count += 1
        
        elapsed = (datetime.now() - start_time).total_seconds()
        if auto_update:
            print(f"🤖 Автообновление #{capt.update_count} выполнено за {elapsed:.2f} сек, пользователей: {len(users)}")
        
        return True
        
    except discord.NotFound:
        error_msg = f"❌ Сообщение {message_id} не найдено"
        print(error_msg)
        await send_log(error_msg, color=0xff0000, title="❌ Ошибка")
        if message_id in active_capts:
            del active_capts[message_id]
        return False
    except Exception as e:
        error_msg = f"❌ Ошибка при обновлении капта {message_id}: {e}"
        print(error_msg)
        traceback.print_exc()
        return False

async def start_auto_update(message_id):
    """Запускает автоматическое обновление капта"""
    if message_id not in active_capts:
        return
    
    capt = active_capts[message_id]
    
    async def auto_update_loop():
        try:
            while capt.is_active:
                # Используем asyncio.sleep, который не блокирует
                await asyncio.sleep(AUTO_UPDATE_INTERVAL)
                if capt.is_active:
                    # Запускаем обновление, но не ждем его завершения, если оно долгое
                    # Это предотвращает накопление задержек
                    asyncio.create_task(update_capt_list(message_id, auto_update=True))
        except asyncio.CancelledError:
            print(f"🛑 Автообновление капта {message_id} остановлено")
    
    capt.auto_update_task = asyncio.create_task(auto_update_loop())
    print(f"🤖 Автообновление запущено для капта {message_id} (каждые {AUTO_UPDATE_INTERVAL} сек)")

async def disable_capt(message_id):
    """Деактивирует капт через час"""
    if message_id not in active_capts:
        return
    
    capt = active_capts[message_id]
    capt.is_active = False
    
    if capt.auto_update_task:
        capt.auto_update_task.cancel()
    
    channel = bot.get_channel(capt.channel_id)
    if channel:
        try:
            message = await channel.fetch_message(message_id)
            
            embed = message.embeds[0]
            embed.color = 0x808080
            embed.set_footer(text="⏰ Срок действия истек")
            
            view = discord.ui.View(timeout=None)
            button = discord.ui.Button(
                label="🔄 Обновить",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id="refresh_capt_disabled"
            )
            view.add_item(button)
            
            await message.edit(embed=embed, view=view)
            print(f"✅ Капт {message_id} деактивирован")
            
            await send_log(
                f"⏰ **Капт завершен**\n"
                f"• Канал: {channel.mention}\n"
                f"• Сообщение: [ссылка]({message.jump_url})\n"
                f"• Создатель: <@{capt.creator_id}>\n"
                f"• Всего обновлений: {capt.update_count}",
                color=0x808080,
                title="⏰ Капт завершен"
            )
            
        except Exception as e:
            print(f"Ошибка при деактивации капта: {e}")
    
    if message_id in active_capts:
        del active_capts[message_id]

def check_allowed_roles(interaction: discord.Interaction) -> bool:
    """Проверяет наличие разрешенных ролей у пользователя"""
    user_roles = [role.id for role in interaction.user.roles]
    return any(role_id in user_roles for role_id in ALLOWED_ROLES)

@bot.tree.command(name="capt", description="Создать список пользователей с реакцией ✅ от целевой роли")
async def capt_command(interaction: discord.Interaction):
    if not check_allowed_roles(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав на использование этой команды.\n"
            f"Требуются роли: <@&{ALLOWED_ROLES[0]}>, <@&{ALLOWED_ROLES[1]}>, <@&{ALLOWED_ROLES[2]}>, <@&{ALLOWED_ROLES[3]}>", 
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        color=0x0099ff,
        title='📋 Список на капт',
        description='🔍 Нажмите кнопку "Обновить" для поиска пользователей',
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="📌 Канал",
        value=f"{interaction.channel.mention}",
        inline=True
    )
    embed.add_field(
        name="✅ Условие",
        value=f"Реакция `{CHECKMARK_EMOJI}` от <@&{TARGET_ROLE_ID}>",
        inline=False
    )
    embed.add_field(
        name="📋 Результат",
        value="Все пользователи, на чьи сообщения поставили ✅\n**Сортировка:** по времени первой реакции",
        inline=False
    )
    
    embed.set_footer(text=f"🔄 Автообновление каждые {AUTO_UPDATE_INTERVAL} сек • Активен 1 час")
    
    view = discord.ui.View(timeout=None)
    button = discord.ui.Button(
        label="🔄 Обновить",
        style=discord.ButtonStyle.primary,
        custom_id="refresh_capt"
    )
    view.add_item(button)
    
    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()
    
    capt = CaptManager(message.id, interaction.channel_id, interaction.user.id)
    active_capts[message.id] = capt
    
    await start_auto_update(message.id)
    
    async def expire_loop():
        await asyncio.sleep(3600)
        await disable_capt(message.id)
    
    capt.expire_task = asyncio.create_task(expire_loop())
    
    await send_log(
        f"✅ **Новый капт создан**\n"
        f"• Канал: {interaction.channel.mention}\n"
        f"• Сообщение: [ссылка]({message.jump_url})\n"
        f"• Создатель: {interaction.user.mention}\n"
        f"• Условие: реакция {CHECKMARK_EMOJI} от <@&{TARGET_ROLE_ID}>\n"
        f"• Автообновление: каждые {AUTO_UPDATE_INTERVAL} сек\n"
        f"• Сортировка: по времени реакции",
        color=0x00ff00,
        title="📋 Новый капт"
    )

class CaptButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="🔄 Обновить",
            style=discord.ButtonStyle.primary,
            custom_id="refresh_capt"
        )
    
    async def callback(self, interaction: discord.Interaction):
        if not check_allowed_roles(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав на использование этой кнопки.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        message_id = interaction.message.id
        
        if message_id in active_capts:
            capt = active_capts[message_id]
            if capt.is_active:
                await interaction.followup.send(
                    f"🔍 Поиск пользователей с реакцией {CHECKMARK_EMOJI} от <@&{TARGET_ROLE_ID}>...", 
                    ephemeral=True
                )
                
                success = await update_capt_list(message_id)
                
                if success:
                    await interaction.followup.send("✅ Список обновлен!", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Ошибка при обновлении списка.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Срок действия этого капта истек.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Капт не найден.", ephemeral=True)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Обработка нажатий на кнопки"""
    if interaction.type == discord.InteractionType.component:
        if interaction.data["custom_id"] == "refresh_capt":
            button = CaptButton()
            await button.callback(interaction)

@tasks.loop(minutes=5)
async def cleanup_expired_capts():
    """Очистка истекших каптов из памяти"""
    current_time = datetime.now()
    expired = []
    
    for message_id, capt in active_capts.items():
        if current_time - capt.created_at > timedelta(hours=1, minutes=10):
            expired.append(message_id)
    
    for message_id in expired:
        if message_id in active_capts:
            if active_capts[message_id].auto_update_task:
                active_capts[message_id].auto_update_task.cancel()
            del active_capts[message_id]
            print(f"🧹 Очищен истекший капт {message_id} из памяти")
    
    if expired:
        await send_log(
            f"🧹 **Очистка памяти**\n"
            f"• Удалено истекших каптов: {len(expired)}",
            color=0x808080,
            title="🧹 Очистка"
        )

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