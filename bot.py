import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Токен бота (обязательно замените на свой!)
BOT_TOKEN = "8772167663:AAHBNvA2GTT08sqDyeXgUcPOz_g5fD7q2rg"

# ID администратора, которому будут приходить сообщения (ваш ID)
ADMIN_ID = 998894037  # например, 123456789

# Включаем логирование, чтобы видеть ошибки
logging.basicConfig(level=logging.INFO)

# Создаем объекты бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Машина состояний ---
# Будем использовать одно состояние: ожидание текста сообщения от пользователя
class Form(StatesGroup):
    waiting_for_message = State()  # пользователь должен прислать текст

# Словарь для хранения связи "сообщение админа" -> "пользователь"
# Когда админ отвечает на сообщение, мы будем искать, кому оно предназначалось
# Ключ: ID сообщения от админа (то, которое бот отправил админу)
# Значение: ID пользователя, который написал исходное сообщение
admin_messages = {}

# --- Команда /start ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Приветственное сообщение
    await message.answer(
        "привет! напиши сообщение для меня на любую тему.\n"
        "есть возможность выбора -- остаться анонимным или отправить публично."
    )
    # Устанавливаем состояние "ожидание сообщения"
    await state.set_state(Form.waiting_for_message)

# --- Обработка текстовых сообщений, когда бот ждет сообщение от пользователя ---
@dp.message(Form.waiting_for_message)
async def process_user_message(message: types.Message, state: FSMContext):
    # Сохраняем текст сообщения в данных состояния
    await state.update_data(user_text=message.text, user_id=message.from_user.id)
    
    # Создаем inline-кнопки для выбора способа отправки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="анонимно", callback_data="send_anon"),
            InlineKeyboardButton(text="публично", callback_data="send_public")
        ]
    ])
    
    await message.answer(
        "как вы хотите прислать сообщение?",
        reply_markup=keyboard
    )
    # Состояние не меняем, пока не получим ответ на кнопку

# --- Обработка нажатий на кнопки ---
@dp.callback_query(F.data.startswith("send_"))
async def process_send_choice(callback: types.CallbackQuery, state: FSMContext):
    # Получаем сохраненные данные (текст и id пользователя)
    data = await state.get_data()
    user_text = data.get("user_text")
    user_id = data.get("user_id")
    
    if not user_text:
        await callback.answer("ошибка :( сообщение не найдено. попробуйте снова.")
        await state.clear()
        return
    
    # Определяем, анонимно или публично
    if callback.data == "send_anon":
        # Анонимно: только текст
        admin_text = f"анонимное сообщение:\n{user_text}"
    else:
        # Публично: пытаемся получить юзернейм, если нет — имя и фамилию
        user = callback.from_user
        if user.username:
            sender_info = f"@{user.username}"
        else:
            sender_info = f"{user.first_name or ''} {user.last_name or ''}".strip()
        admin_text = f"сообщение от {sender_info}:\n{user_text}"
    
    # Отправляем сообщение админу
    sent_message = await bot.send_message(ADMIN_ID, admin_text)
    
    # Запоминаем, что это сообщение админа связано с пользователем
    admin_messages[sent_message.message_id] = user_id
    
    # Уведомляем пользователя об успехе
    await callback.message.edit_text("отправлено! ожидайте ответа =]")
    
    # Очищаем состояние, т.к. диалог завершен (но пользователь может снова написать)
    await state.clear()
    
    # Обязательно отвечаем на callback, чтобы убрать "часики" на кнопке
    await callback.answer()

# --- Обработка ответов от администратора ---
@dp.message(F.reply_to_message & F.from_user.id == ADMIN_ID)
async def reply_to_user(message: types.Message):
    # Проверяем, что админ ответил на какое-то сообщение
    replied_msg = message.reply_to_message
    
    # Ищем, не связано ли это сообщение с каким-либо пользователем
    user_id = admin_messages.get(replied_msg.message_id)
    
    if user_id:
        # Пересылаем ответ пользователю
        try:
            await bot.send_message(
                user_id,
                f"ответ хуфф:\n{message.text}"
            )
            await message.reply("отправлено!")
        except Exception as e:
            await message.reply(f"не удалось отправить ответ: пользователь заблокировал бота или удалил чат.")
    else:
        await message.reply("это сообщение не связано с пользователем (возможно, бот перезапущен или сообщение устарело).")

# --- Обработка всех остальных сообщений (например, если пользователь отправил что-то, пока не в состоянии) ---
@dp.message()
async def handle_other_messages(message: types.Message):
    # Если пользователь пишет что-то не по сценарию, напоминаем о /start
    await message.answer("пожалуйста, начните с команды /start !")

# --- Запуск бота ---
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())