import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import os

# Настройки бота
TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_ROLE_ID = 1478205318591938671
ALLOWED_ROLES = [
    1310673963000528949,
    1223589384452833290, 
    1381682246678741022,
    1478205318591938671
]

# Хранилище активных каптов
active_capts = {}

class CaptManager:
    def __init__(self, message_id, channel_id):
        self.message_id = message_id
        self.channel_id = channel_id
        self.created_at = datetime.now()
        self.is_active = True
        self.expire_task = None

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

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'Подключен к серверам: {len(bot.guilds)}')

async def get_users_with_reactions(guild):
    """Получает пользователей с ролью TARGET_ROLE_ID, которые ставили реакции"""
    target_role = guild.get_role(TARGET_ROLE_ID)
    if not target_role:
        print(f"⚠️ Роль {TARGET_ROLE_ID} не найдена на сервере {guild.name}")
        return []
    
    users_with_reactions = set()
    
    for channel in guild.text_channels:
        try:
            async for message in channel.history(limit=200):
                for reaction in message.reactions:
                    async for user in reaction.users():
                        if isinstance(user, discord.Member):
                            if target_role in user.roles:
                                users_with_reactions.add(user)
        except discord.Forbidden:
            continue
        except Exception as e:
            print(f"Ошибка при обработке канала {channel.name}: {e}")
            continue
    
    return list(users_with_reactions)

async def update_capt_list(message_id):
    """Обновляет список пользователей в embed"""
    if message_id not in active_capts:
        return
    
    capt = active_capts[message_id]
    if not capt.is_active:
        return
    
    channel = bot.get_channel(capt.channel_id)
    if not channel:
        return
    
    try:
        message = await channel.fetch_message(message_id)
        
        # Получаем пользователей с реакциями
        users = await get_users_with_reactions(message.guild)
        
        if users:
            # Сортируем пользователей по имени
            users.sort(key=lambda x: x.display_name.lower())
            mentions = '\n'.join([f"• {user.mention}" for user in users])
            
            # Добавляем счетчик
            description = f"**Найдено пользователей: {len(users)}**\n\n{mentions}"
        else:
            description = '❌ Пользователи с реакциями не найдены'
        
        embed = discord.Embed(
            color=0x0099ff,
            title='📋 Список на капт',
            description=description,
            timestamp=datetime.now()
        )
        
        # Добавляем информацию о времени
        time_left = timedelta(hours=1) - (datetime.now() - capt.created_at)
        minutes_left = int(time_left.total_seconds() / 60)
        seconds_left = int(time_left.total_seconds() % 60)
        
        if minutes_left > 0:
            time_str = f"Осталось {minutes_left} мин {seconds_left} сек"
        else:
            time_str = f"Осталось {seconds_left} сек"
            
        embed.set_footer(text=f"🔄 Обновляется по кнопке • {time_str}")
        
        await message.edit(embed=embed)
        
    except discord.NotFound:
        print(f"❌ Сообщение {message_id} не найдено")
        if message_id in active_capts:
            del active_capts[message_id]
    except Exception as e:
        print(f"Ошибка при обновлении капта {message_id}: {e}")

async def disable_capt(message_id):
    """Деактивирует капт через час"""
    if message_id not in active_capts:
        return
    
    capt = active_capts[message_id]
    capt.is_active = False
    
    channel = bot.get_channel(capt.channel_id)
    if channel:
        try:
            message = await channel.fetch_message(message_id)
            
            # Обновляем embed с пометкой об истечении
            embed = message.embeds[0]
            embed.color = 0x808080
            embed.set_footer(text="⏰ Срок действия истек")
            
            # Деактивируем кнопку
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
            
        except Exception as e:
            print(f"Ошибка при деактивации капта: {e}")
    
    if message_id in active_capts:
        del active_capts[message_id]

def check_allowed_roles(interaction: discord.Interaction) -> bool:
    """Проверяет наличие разрешенных ролей у пользователя"""
    user_roles = [role.id for role in interaction.user.roles]
    return any(role_id in user_roles for role_id in ALLOWED_ROLES)

@bot.tree.command(name="capt", description="Создать список пользователей с реакциями")
async def capt_command(interaction: discord.Interaction):
    # Проверка прав
    if not check_allowed_roles(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав на использование этой команды.\n"
            f"Требуются роли: <@&{ALLOWED_ROLES[0]}>, <@&{ALLOWED_ROLES[1]}>, <@&{ALLOWED_ROLES[2]}>, <@&{ALLOWED_ROLES[3]}>", 
            ephemeral=True
        )
        return
    
    # Создаем embed
    embed = discord.Embed(
        color=0x0099ff,
        title='📋 Список на капт',
        description='🔍 Нажмите кнопку "Обновить" для загрузки списка',
        timestamp=datetime.now()
    )
    embed.set_footer(text="🔄 Обновляется по кнопке • 1 час")
    
    # Создаем кнопку
    view = discord.ui.View(timeout=None)
    button = discord.ui.Button(
        label="🔄 Обновить",
        style=discord.ButtonStyle.primary,
        custom_id="refresh_capt"
    )
    view.add_item(button)
    
    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()
    
    # Создаем менеджер капта
    capt = CaptManager(message.id, interaction.channel_id)
    active_capts[message.id] = capt
    
    # Запускаем задачу истечения
    async def expire_loop():
        await asyncio.sleep(3600)  # 1 час
        await disable_capt(message.id)
    
    capt.expire_task = asyncio.create_task(expire_loop())
    
    await interaction.followup.send(
        f"✅ Капт создан! Будет активен 1 час.\n"
        f"ID: {message.id}",
        ephemeral=True
    )

@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Обработка нажатий на кнопки"""
    if interaction.type == discord.InteractionType.component:
        if interaction.data["custom_id"] == "refresh_capt":
            # Проверка прав
            if not check_allowed_roles(interaction):
                await interaction.response.send_message(
                    "❌ У вас нет прав на использование этой кнопки.", 
                    ephemeral=True
                )
                return
            
            message_id = interaction.message.id
            
            if message_id in active_capts:
                capt = active_capts[message_id]
                if capt.is_active:
                    await interaction.response.defer(ephemeral=True)
                    await update_capt_list(message_id)
                    await interaction.followup.send("✅ Список обновлен!", ephemeral=True)
                else:
                    await interaction.response.send_message(
                        "❌ Срок действия этого капта истек.", 
                        ephemeral=True
                    )
            else:
                # Проверяем, может быть капт уже истек, но сообщение осталось
                try:
                    message = await interaction.message.fetch()
                    if message.embeds:
                        embed = message.embeds[0]
                        if "Срок действия истек" in embed.footer.text:
                            await interaction.response.send_message(
                                "❌ Срок действия этого капта истек.", 
                                ephemeral=True
                            )
                        else:
                            await interaction.response.send_message(
                                "❌ Капт не найден в активных. Возможно, бот был перезапущен.", 
                                ephemeral=True
                            )
                    else:
                        await interaction.response.send_message(
                            "❌ Капт не найден.", 
                            ephemeral=True
                        )
                except:
                    await interaction.response.send_message(
                        "❌ Капт не найден.", 
                        ephemeral=True
                    )

@tasks.loop(minutes=5)
async def cleanup_expired_capts():
    """Очистка истекших каптов из памяти"""
    current_time = datetime.now()
    expired = []
    
    for message_id, capt in active_capts.items():
        if current_time - capt.created_at > timedelta(hours=1, minutes=10):  # +10 минут запас
            expired.append(message_id)
    
    for message_id in expired:
        if message_id in active_capts:
            del active_capts[message_id]
            print(f"🧹 Очищен истекший капт {message_id} из памяти")

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'Подключен к серверам: {len(bot.guilds)}')
    cleanup_expired_capts.start()

# Запуск бота
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Ошибка: Не найден DISCORD_TOKEN в переменных окружения")
        print("Добавьте переменную окружения DISCORD_TOKEN в Railway")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Ошибка: Неверный токен Discord")
        exit(1)
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
        exit(1)