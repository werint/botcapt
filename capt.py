import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import os
import traceback

# Настройки бота
TOKEN = os.getenv('DISCORD_TOKEN')
ALLOWED_CREATOR_ROLE = 1478205318591938671
LOG_CHANNEL_ID = 1448991378750046209
SCREENSHOT_WAIT_TIME = 300
SCREENSHOT_DELETE_DELAY = 6  # Задержка перед удалением скриншота

# ID ролей для отображения
ROLE_IDS = {
    'primary_roles': [
        1400274896365420674,
        1421509117591293972,
        1400274302686986271,
        1421509201498476726,
        1400276595226185870,
        1421734059259727923
    ],
    'secondary_roles': [
        1317882573342507069,
        1383426539886084267,
        1352527374515699712
    ]
}

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

def get_user_roles_info(member):
    """Получает информацию о ролях пользователя"""
    primary_role = None
    secondary_role = None
    
    for role_id in ROLE_IDS['primary_roles']:
        role = member.get_role(role_id)
        if role:
            primary_role = role.name
            break
    
    for role_id in ROLE_IDS['secondary_roles']:
        role = member.get_role(role_id)
        if role:
            secondary_role = role.name
            break
    
    return primary_role, secondary_role

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

async def update_capt_embed(message_id):
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
    
    message = await channel.send(embed=embed)
    
    capt.message_id = message.id
    
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
        
        # Сначала отправляем финальное сообщение
        await send_capt_message(interaction.channel, capt)
        
        # Затем удаляем сообщение со скриншотом с задержкой
        await asyncio.sleep(SCREENSHOT_DELETE_DELAY)
        await screenshot_msg.delete()
        
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

# Класс для выбора пользователей на регистрацию (только те, кто кинул плюс)
class RegisterSelect(discord.ui.Select):
    def __init__(self, capt, plus_users_page, page_num, total_pages):
        self.capt = capt
        self.page_num = page_num
        self.total_pages = total_pages
        options = []
        
        for member in plus_users_page:
            # Определяем, зарегистрирован ли пользователь
            is_registered = member.id in [u.id for u in capt.registered_users]
            
            # Получаем роли пользователя
            primary_role, secondary_role = get_user_roles_info(member)
            
            # Формируем описание с ролями
            role_text = f"{primary_role if primary_role else 'Нет роли'}"
            if secondary_role:
                role_text += f" | {secondary_role}"
            
            # Добавляем отметку о регистрации
            label = f"{'✅' if is_registered else '❌'} {member.display_name}"
            
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    description=role_text[:100],
                    value=str(member.id)
                )
            )
        
        super().__init__(
            placeholder=f"Страница {page_num}/{total_pages} - Выберите пользователей",
            min_values=1,
            max_values=min(25, len(options)),
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        if not check_creator_role(interaction):
            await interaction.response.send_message("❌ У вас нет прав", ephemeral=True)
            return
        
        selected_users = []
        for user_id_str in self.values:
            user_id = int(user_id_str)
            member = interaction.guild.get_member(user_id)
            if member:
                selected_users.append(member)
        
        # Регистрируем выбранных пользователей
        for user in selected_users:
            if user.id not in [u.id for u in self.capt.registered_users]:
                self.capt.registered_users.append(user)
                # Удаляем из плюсов если был
                if user.id in [u.id for u in self.capt.plus_users]:
                    self.capt.plus_users = [u for u in self.capt.plus_users if u.id != user.id]
        
        await update_capt_embed(self.capt.message_id)
        
        # Формируем сообщение о зарегистрированных
        users_list = "\n".join([f"• {u.mention}" for u in selected_users])
        await interaction.response.send_message(
            f"✅ Зарегистрированы:\n{users_list}",
            ephemeral=True
        )
        
        await send_log(
            f"📝 **Массовая регистрация**\n"
            f"• Капт: {self.capt.title_text}\n"
            f"• Зарегистрировал: {interaction.user.mention}\n"
            f"• Пользователи: {len(selected_users)} чел.",
            color=0x00ff00,
            title="📝 Массовая регистрация"
        )

# Класс для пагинации
class PaginationView(discord.ui.View):
    def __init__(self, capt, plus_users, current_page=0):
        super().__init__(timeout=120)
        self.capt = capt
        self.plus_users = plus_users
        self.current_page = current_page
        self.items_per_page = 25
        
        if not plus_users:
            # Если нет пользователей с плюсами
            self.total_pages = 1
            members_page = []
        else:
            self.total_pages = (len(plus_users) + self.items_per_page - 1) // self.items_per_page
            start = self.current_page * self.items_per_page
            end = start + self.items_per_page
            members_page = plus_users[start:end]
        
        if members_page:
            self.add_item(RegisterSelect(capt, members_page, self.current_page + 1, self.total_pages))
    
    @discord.ui.button(label="◀️ Назад", style=discord.ButtonStyle.secondary, row=1)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            new_view = PaginationView(self.capt, self.plus_users, self.current_page - 1)
            await interaction.response.edit_message(view=new_view)
        else:
            await interaction.response.send_message("Это первая страница", ephemeral=True)
    
    @discord.ui.button(label="Вперед ▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            new_view = PaginationView(self.capt, self.plus_users, self.current_page + 1)
            await interaction.response.edit_message(view=new_view)
        else:
            await interaction.response.send_message("Это последняя страница", ephemeral=True)

@bot.tree.command(name="рег", description="Зарегистрировать пользователей в капте")
@app_commands.describe(сообщение_id="ID сообщения с каптом")
async def register_command(interaction: discord.Interaction, сообщение_id: str):
    if not check_creator_role(interaction):
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
        
        # Получаем только тех, кто кинул плюс, и сортируем по имени
        plus_users = sorted(capt.plus_users, key=lambda x: x.display_name)
        
        if not plus_users:
            await interaction.response.send_message(
                "❌ Нет пользователей, которые поставили плюс в этом капте.\n"
                "Регистрировать можно только тех, кто поставил плюс.",
                ephemeral=True
            )
            return
        
        # Рассчитываем количество страниц
        items_per_page = 25
        total_pages = (len(plus_users) + items_per_page - 1) // items_per_page
        
        embed = discord.Embed(
            title="📝 Регистрация пользователей",
            description=f"**Капт:** {capt.title_text}\n\n"
                        f"Выберите пользователей для регистрации.\n"
                        f"✅ - уже зарегистрирован\n"
                        f"❌ - не зарегистрирован\n\n"
                        f"📄 Всего пользователей с плюсами: {len(plus_users)}\n"
                        f"📄 Страниц: {total_pages}",
            color=0x0099ff,
            timestamp=datetime.now()
        )
        
        view = PaginationView(capt, plus_users)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    except ValueError:
        await interaction.response.send_message("❌ Неверный ID сообщения", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

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
        
        capt = CaptManager(
            message_id=0,
            channel_id=interaction_btn.channel_id,
            creator_id=interaction_btn.user.id,
            title_text=text,
            need_screenshot=True
        )
        
        await start_screenshot_wait(capt, interaction_btn)
    
    async def no_callback(interaction_btn: discord.Interaction):
        await interaction_btn.response.defer(ephemeral=True)
        
        capt = CaptManager(
            message_id=0,
            channel_id=interaction_btn.channel_id,
            creator_id=interaction_btn.user.id,
            title_text=text,
            need_screenshot=False
        )
        
        await send_capt_message(interaction_btn.channel, capt)
        
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
        
        if custom_id.startswith("plus_"):
            try:
                message_id = int(custom_id.split("_")[1])
                
                if message_id not in active_capts:
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
                await interaction.response.send_message("❌ Произошла ошибка", ephemeral=True)
        
        elif custom_id.startswith("remove_plus_"):
            try:
                parts = custom_id.split("_")
                if len(parts) >= 3:
                    message_id = int(parts[2])
                else:
                    await interaction.response.send_message("❌ Ошибка формата кнопки", ephemeral=True)
                    return
                
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
                    f"• Капт: {capt.title_text}\n"
                    f"• Пользователь: {user.mention}",
                    color=0xffaa00,
                    title="➖ Плюс убран"
                )
            except Exception as e:
                print(f"Ошибка при обработке удаления плюса: {e}")
                await interaction.response.send_message("❌ Произошла ошибка", ephemeral=True)

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