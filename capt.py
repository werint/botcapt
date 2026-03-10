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
        self.update_task = None
        self.expire_task = None

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.message_reactions = True

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
    # Запускаем проверку истекших каптов
    check_expired_capts.start()

@tasks.loop(seconds=30)
async def check_expired_capts():
    """Проверяет истекшие капты каждые 30 секунд"""
    current_time = datetime.now()
    expired = []
    
    for message_id, capt in active_capts.items():
        if current_time - capt.created_at > timedelta(hours=1):
            expired.append(message_id)
            await disable_capt(capt.message_id)
    
    for message_id in expired:
        del active_capts[message_id]

async def get_users_with_reactions(guild):
    """Получает пользователей с ролью TARGET_ROLE_ID, которые ставили реакции"""
    target_role = guild.get_role(TARGET_ROLE_ID)
    if not target_role:
        return []
    
    users_with_reactions = set()
    
    for channel in guild.text_channels:
        try:
            async for message in channel.history(limit=100):
                for reaction in message.reactions:
                    async for user in reaction.users():
                        if isinstance(user, discord.Member) and target_role in user.roles:
                            users_with_reactions.add(user)
        except:
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
            mentions = '\n'.join([user.mention for user in users])
        else:
            mentions = 'Пользователи не найдены'
        
        embed = discord.Embed(
            color=0x0099ff,
            title='Список на капт И НИЧЕГО БОЛЬШЕ',
            description=mentions,
            timestamp=datetime.now()
        )
        
        # Добавляем информацию о времени
        time_left = timedelta(hours=1) - (datetime.now() - capt.created_at)
        minutes_left = int(time_left.total_seconds() / 60)
        embed.set_footer(text=f"Обновляется каждые 10 сек • Осталось {minutes_left} мин")
        
        await message.edit(embed=embed)
        
    except Exception as e:
        print(f"Ошибка при обновлении капта {message_id}: {e}")

async def disable_capt(message_id):
    """Деактивирует капт через час"""
    if message_id not in active_capts:
        return
    
    capt = active_capts[message_id]
    capt.is_active = False
    
    if capt.update_task:
        capt.update_task.cancel()
    
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
            
        except Exception as e:
            print(f"Ошибка при деактивации капта: {e}")

def check_allowed_roles(interaction: discord.Interaction) -> bool:
    """Проверяет наличие разрешенных ролей у пользователя"""
    return any(role.id in ALLOWED_ROLES for role in interaction.user.roles)

@bot.tree.command(name="capt", description="Создать список пользователей с реакциями")
async def capt_command(interaction: discord.Interaction):
    # Проверка прав
    if not check_allowed_roles(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав на использование этой команды.", 
            ephemeral=True
        )
        return
    
    # Создаем embed
    embed = discord.Embed(
        color=0x0099ff,
        title='Список на капт И НИЧЕГО БОЛЬШЕ',
        description='Загрузка участников...',
        timestamp=datetime.now()
    )
    
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
    
    # Запускаем задачи обновления
    async def update_loop():
        while True:
            if not capt.is_active:
                break
            await update_capt_list(message.id)
            await asyncio.sleep(10)
    
    capt.update_task = asyncio.create_task(update_loop())
    
    # Запускаем задачу истечения
    async def expire_loop():
        await asyncio.sleep(3600)  # 1 час
        await disable_capt(message.id)
        if message.id in active_capts:
            del active_capts[message.id]
    
    capt.expire_task = asyncio.create_task(expire_loop())

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
                    await interaction.response.defer()
                    await update_capt_list(message_id)
                    await interaction.followup.send("✅ Список обновлен!", ephemeral=True)
                else:
                    await interaction.response.send_message(
                        "❌ Срок действия этого капта истек.", 
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "❌ Капт не найден или уже неактивен.", 
                    ephemeral=True
                )

# Запуск бота
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Ошибка: Не найден DISCORD_TOKEN в переменных окружения")
        exit(1)
    
    bot.run(TOKEN)