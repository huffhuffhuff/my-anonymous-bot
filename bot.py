import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8772167663:AAHBNvA2GTT08sqDyeXgUcPOz_g5fD7q2rg")
ADMIN_ID = int(os.getenv("ADMIN_ID", 998894037))
ADMIN_MESSAGES_FILE = "admin_messages.json"

logging.basicConfig(level=logging.INFO)

# ========== РАБОТА С ФАЙЛОМ ==========
def load_admin_messages():
    """Загружает словарь сообщений из JSON файла"""
    if os.path.exists(ADMIN_MESSAGES_FILE):
        with open(ADMIN_MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_admin_messages(messages_dict):
    """Сохраняет словарь сообщений в JSON файл"""
    with open(ADMIN_MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(messages_dict, f, ensure_ascii=False, indent=2)

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Загружаем сохранённые связи (бот -> пользователь)
admin_messages = load_admin_messages()
print(f"загружено {len(admin_messages)} связей из файла")

# ========== МАШИНА СОСТОЯНИЙ ==========
class Form(StatesGroup):
    waiting_for_message = State()

# ========== КОМАНДА START ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer(
        "привет! напиши сообщение для меня с любой темой.\n"
        "есть возможность выбора — остаться анонимным или отправить публично."
    )
    await state.set_state(Form.waiting_for_message)

# ========== ПОЛУЧЕНИЕ СООБЩЕНИЯ ОТ ПОЛЬЗОВАТЕЛЯ ==========
@dp.message(Form.waiting_for_message)
async def process_user_media(message: types.Message, state: FSMContext):
    data = {"user_id": message.from_user.id}
    
    if message.text:
        data["type"] = "text"
        data["content"] = message.text
    elif message.photo:
        data["type"] = "photo"
        data["file_id"] = message.photo[-1].file_id
        data["caption"] = message.caption or ""
    elif message.sticker:
        data["type"] = "sticker"
        data["file_id"] = message.sticker.file_id
    elif message.animation:
        data["type"] = "animation"
        data["file_id"] = message.animation.file_id
        data["caption"] = message.caption or ""
    else:
        await message.answer("можно отправить только текст, фото, стикер или гиф =[")
        return
    
    await state.update_data(**data)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="анонимно", callback_data="send_anon"),
            InlineKeyboardButton(text="публично", callback_data="send_public")
        ]
    ])
    
    await message.answer(
        "как хотите отправить сообщение?",
        reply_markup=keyboard
    )

# ========== ВЫБОР СПОСОБА ОТПРАВКИ ==========
@dp.callback_query(F.data.startswith("send_"))
async def process_send_choice(callback: types.CallbackQuery, state: FSMContext):
    global admin_messages
    
    data = await state.get_data()
    user_id = data.get("user_id")
    content_type = data.get("type")
    
    if not user_id or not content_type:
        await callback.answer("данные утеряны. начните с /start")
        await state.clear()
        return
    
    # Формируем подпись
    user = callback.from_user
    if callback.data == "send_public":
        if user.username:
            sender = f"@{user.username}"
        else:
            sender = f"{user.first_name or ''} {user.last_name or ''}".strip()
        header = f"сообщение от {sender}:"
    else:
        header = "анонимное сообщение:"
    
    try:
        sent_messages = []  # список отправленных сообщений
        
        if content_type == "text":
            msg = await bot.send_message(ADMIN_ID, f"{header}\n\n{data['content']}")
            sent_messages.append(msg)
            
        elif content_type == "photo":
            msg = await bot.send_photo(
                ADMIN_ID,
                photo=data["file_id"],
                caption=f"{header}\n\n{data['caption']}".strip()
            )
            sent_messages.append(msg)
            
        elif content_type == "sticker":
            # Отправляем стикер
            sticker_msg = await bot.send_sticker(ADMIN_ID, sticker=data["file_id"])
            sent_messages.append(sticker_msg)
            # Отправляем заголовок отдельно
            header_msg = await bot.send_message(ADMIN_ID, header)
            sent_messages.append(header_msg)
            
        elif content_type == "animation":
            msg = await bot.send_animation(
                ADMIN_ID,
                animation=data["file_id"],
                caption=f"{header}\n\n{data['caption']}".strip()
            )
            sent_messages.append(msg)
        
        # Сохраняем ВСЕ отправленные сообщения в словарь
        for msg in sent_messages:
            admin_messages[str(msg.message_id)] = user_id
            print(f"сохранено: сообщение {msg.message_id} -> пользователь {user_id}")
        
        save_admin_messages(admin_messages)
        
        await callback.message.edit_text("отправлено! ожидайте ответа =]")
        
    except Exception as e:
        logging.error(f"Ошибка отправки админу: {e}")
        await callback.message.edit_text("ошибка при отправке. попробуйте позже.")
    
    await state.clear()
    await callback.answer()

# ========== ОТВЕТЫ АДМИНА ==========
@dp.message(F.reply_to_message & (F.from_user.id == ADMIN_ID))
async def reply_to_user(message: types.Message):
    global admin_messages
    
    replied = message.reply_to_message
    replied_id = str(replied.message_id)
    
    print(f"админ ответил на сообщение ID: {replied_id}")
    print(f"словарь admin_messages: {admin_messages}")
    
    # Ищем пользователя по ID сообщения
    user_id = admin_messages.get(replied_id)
    
    if not user_id:
        await message.reply("пользователь не найден (возможно, бот перезапущен).")
        return
    
    try:
        # Отправляем ответ пользователю
        if message.text:
            await bot.send_message(
                int(user_id),
                f"ответ:\n{message.text}"
            )
        elif message.photo:
            await bot.send_photo(
                int(user_id),
                photo=message.photo[-1].file_id,
                caption=f"ответ:\n{message.caption or ''}"
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
                caption=f"ответ:\n{message.caption or ''}"
            )
        elif message.video:
            await bot.send_video(
                int(user_id),
                video=message.video.file_id,
                caption=f"ответ:\n{message.caption or ''}"
            )
        elif message.voice:
            await bot.send_voice(
                int(user_id),
                voice=message.voice.file_id
            )
        elif message.document:
            await bot.send_document(
                int(user_id),
                document=message.document.file_id,
                caption=f"ответ:\n{message.caption or ''}"
            )
        else:
            await message.reply("этот тип сообщений пока не поддерживается")
            return
        
        # Удаляем использованную связь
        if replied_id in admin_messages:
            del admin_messages[replied_id]
            save_admin_messages(admin_messages)
            print(f"удалена связь для сообщения {replied_id}")
        
        await message.reply("✅ Ответ отправлен!")
        
    except Exception as e:
        logging.error(f"Ошибка отправки ответа: {e}")
        await message.reply(f"не удалось отправить: {e}")

# ========== ВСЁ ОСТАЛЬНОЕ ==========
@dp.message()
async def fallback(message: types.Message):
    await message.answer("Начните с команды /start")

# ========== HEALTH CHECK ДЛЯ RAILWAY ==========
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

# ========== ЗАПУСК ==========
async def main():
    await run_web_server()
    print("бот запущен и готов к работе!")
    print(f"ADMIN_ID: {ADMIN_ID}")
    print(f"Файл с сообщениями: {ADMIN_MESSAGES_FILE}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())