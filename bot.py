import asyncio
import logging
import os
import json
import os

ADMIN_MESSAGES_FILE = "admin_messages.json"

def load_admin_messages():
    if os.path.exists(ADMIN_MESSAGES_FILE):
        with open(ADMIN_MESSAGES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_admin_messages():
    with open(ADMIN_MESSAGES_FILE, "w") as f:
        json.dump(admin_messages, f)

# Загружаем при старте
admin_messages = load_admin_messages()
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web  # для health check (Railway)

# Токен и ID админа из переменных окружения (или вставь вручную для теста)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8772167663:AAHBNvA2GTT08sqDyeXgUcPOz_g5fD7q2rg")
ADMIN_ID = int(os.getenv("ADMIN_ID", 998894037))  # замени 123456789 на свой ID

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Машина состояний ---
class Form(StatesGroup):
    waiting_for_message = State()  # ждём любое сообщение (текст, фото, стикер...)

# Хранилище: сообщение админа -> ID пользователя
admin_messages = {}

# --- Команда /start ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer(
        "привет! напиши сообщение для меня с любой темой.\n"
        "есть возможность выбора -- остаться анонимным или отправить публично."
    )
    await state.set_state(Form.waiting_for_message)

# --- УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК: ловим ВСЁ, когда ждём сообщение ---
@dp.message(Form.waiting_for_message)
async def process_user_media(message: types.Message, state: FSMContext):
    # Сохраняем ID пользователя
    data = {"user_id": message.from_user.id}
    
    # Определяем тип контента и сохраняем нужную информацию
    if message.text:
        data["type"] = "text"
        data["content"] = message.text
    elif message.photo:
        data["type"] = "photo"
        # Берём самое большое фото (последнее в массиве)
        data["file_id"] = message.photo[-1].file_id
        data["caption"] = message.caption or ""  # подпись к фото, если есть
    elif message.sticker:
        data["type"] = "sticker"
        data["file_id"] = message.sticker.file_id
    elif message.animation:
        data["type"] = "animation"  # GIF
        data["file_id"] = message.animation.file_id
        data["caption"] = message.caption or ""
    else:
        # Если тип не поддерживается
        await message.answer("можно отправить лишь текст, фото, стикер или гиф =[")
        return
    
    # Сохраняем данные в состояние
    await state.update_data(**data)
    
    # Кнопки выбора
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="анонимно", callback_data="send_anon"),
            InlineKeyboardButton(text="публично", callback_data="send_public")
        ]
    ])
    
    await message.answer(
        "как вы хотите оставить сообщение?",
        reply_markup=keyboard
    )

# --- Обработка нажатий кнопок ---
@dp.callback_query(F.data.startswith("send_"))
async def process_send_choice(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id")
    content_type = data.get("type")
    
    if not user_id or not content_type:
        await callback.answer("данные утеряны =[ начните снова со /start")
        await state.clear()
        return
    
    # Формируем информацию об отправителе
    user = callback.from_user
    if callback.data == "send_public":
        if user.username:
            sender = f"@{user.username}"
        else:
            sender = f"{user.first_name or ''} {user.last_name or ''}".strip()
        header = f"сообщение {sender}:"
    else:
        header = "анонимное сообщение:"
    
    # Отправляем админу в зависимости от типа
    try:
        if content_type == "text":
            sent = await bot.send_message(
                ADMIN_ID,
                f"{header}\n\n{data['content']}"
            )
        elif content_type == "photo":
            sent = await bot.send_photo(
                ADMIN_ID,
                photo=data["file_id"],
                caption=f"{header}\n\n{data['caption']}".strip()
            )
        elif content_type == "sticker":
            sent = await bot.send_sticker(
                ADMIN_ID,
                sticker=data["file_id"]
            )
            # Для стикеров отдельно отправим заголовок (нельзя прикрепить к стикеру)
            await bot.send_message(ADMIN_ID, header)
        elif content_type == "animation":  # GIF
            sent = await bot.send_animation(
                ADMIN_ID,
                animation=data["file_id"],
                caption=f"{header}\n\n{data['caption']}".strip()
            )
        else:
            await callback.answer("неизвестный тип сообщения")
            return
        
        # Сохраняем связь: сообщение админа -> пользователь
        admin_messages[sent.message_id] = user_id
        save_admin_messages()
        
        # Уведомляем пользователя
        await callback.message.edit_text("отправлено! ожидайте ответа =]")
        
    except Exception as e:
        logging.error(f"Ошибка отправки админу: {e}")
        await callback.message.edit_text("ошибка при отправке. попробуйте позже.")
    
    await state.clear()
    await callback.answer()

# --- УНИВЕРСАЛЬНЫЙ обработчик ответов админа (текст, фото, стикер, GIF) ---
@dp.message(F.reply_to_message & (F.from_user.id == ADMIN_ID))
async def reply_to_user(message: types.Message):
    replied = message.reply_to_message
    replied_id = replied.message_id
    
    print(f"🔵 Админ ответил на сообщение ID: {replied_id}")
    print(f"📚 Словарь admin_messages: {admin_messages}")
    
    user_id = admin_messages.get(str(replied_id))  # JSON хранит ключи как строки
    
    if not user_id:
        await message.reply("пользователь не найден (возможно, бот перезапущен).")
        return
    
    try:
        # Отправляем ответ в зависимости от типа
        if message.text:
            await bot.send_message(
                int(user_id),
                f"ответ от хуфф:\n{message.text}"
            )
        elif message.photo:
            await bot.send_photo(
                int(user_id),
                photo=message.photo[-1].file_id,
                caption=f"ответ от хуфф:\n{message.caption or ''}"
            )
        elif message.sticker:
            await bot.send_sticker(
                int(user_id),
                sticker=message.sticker.file_id
            )
        elif message.animation:
            await bot.send_animation(
                int(user_id),
                animation=message.animation.file_id,
                caption=f"ответ от хуфф:\n{message.caption or ''}"
            )
        else:
            await message.reply("этот тип пока не поддерживается")
            return
        
        # Удаляем использованную связь и сохраняем
        del admin_messages[str(replied_id)]
        save_admin_messages()
        
        await message.reply("ответ отправлен!")
        
    except Exception as e:
        logging.error(f"Ошибка отправки ответа: {e}")
        await message.reply(f"не удалось отправить: {e}")

# --- Обработка всего остального (если не в состоянии) ---
@dp.message()
async def fallback(message: types.Message):
    await message.answer("начните с команды /start")

# --- Health check для Railway (веб-сервер) ---
async def handle_health(request):
    return web.Response(text="Bot is running!")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("✅ Health check server started on port 8080")

# --- Запуск ---
async def main():
    await run_web_server()
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())