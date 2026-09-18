import asyncio
import os
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from dotenv import load_dotenv

from aiogram.client.session.aiohttp import AiohttpSession

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Наш прокси через Cloudflare Worker
PROXY_URL = "https://tg-proxy.aripovadiliara0.workers.dev"

from aiogram.client.telegram import TelegramAPIServer

session = AiohttpSession(api=TelegramAPIServer.from_base(PROXY_URL))
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher(storage=MemoryStorage())

SERVICES = {
    "Маникюр": "Маникюр с покрытием — 2500 ₽, 1.5 часа",
    "Стрижка": "Женская стрижка — 3000 ₽, 1 час",
    "Окрашивание": "Окрашивание в один тон — 6000 ₽, 2.5 часа",
    "Укладка": "Укладка волос — 2000 ₽, 45 минут",
}

MASTERS = ["Анна", "Мария", "Ольга", "Екатерина"]
WORK_SLOTS = ["10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00"]

DB_PATH = "bookings.db"


# --- База данных ---

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            service TEXT,
            master TEXT,
            date TEXT,
            time TEXT,
            name TEXT,
            phone TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_booking(user_id, username, service, master, date, time, name, phone):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bookings
        (user_id, username, service, master, date, time, name, phone, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, username, service, master, date, time, name, phone,
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


# --- FSM ---

class Booking(StatesGroup):
    name = State()
    phone = State()


# --- Клавиатуры ---

def services_keyboard() -> ReplyKeyboardMarkup:
    buttons = [KeyboardButton(text=name) for name in SERVICES]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def masters_keyboard() -> ReplyKeyboardMarkup:
    buttons = [KeyboardButton(text=name) for name in MASTERS]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def dates_keyboard() -> ReplyKeyboardMarkup:
    today = datetime.now().date()
    buttons = []
    for i in range(7):
        day = today + timedelta(days=i)
        buttons.append(KeyboardButton(text=day.strftime("%d.%m (%a)")))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def times_keyboard() -> ReplyKeyboardMarkup:
    buttons = [KeyboardButton(text=t) for t in WORK_SLOTS]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# --- Хэндлеры ---

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n"
        "Я бот салона красоты. Выбери услугу:",
        reply_markup=services_keyboard(),
    )


@dp.message(F.text.in_(SERVICES.keys()))
async def show_service(message: Message, state: FSMContext):
    await state.update_data(service=message.text)
    await message.answer(
        f"Услуга: {message.text}\n{SERVICES[message.text]}\n\n"
        "Теперь выбери мастера:",
        reply_markup=masters_keyboard(),
    )


@dp.message(F.text.in_(MASTERS))
async def show_master(message: Message, state: FSMContext):
    await state.update_data(master=message.text)
    await message.answer(
        f"Отлично! Мастер: {message.text}\n\nВыбери дату:",
        reply_markup=dates_keyboard(),
    )


@dp.message(F.text.regexp(r"^\d{2}\.\d{2} \(\w+\)$"))
async def show_date(message: Message, state: FSMContext):
    await state.update_data(date=message.text)
    await message.answer(
        f"Дата: {message.text}\n\nВыбери удобное время:",
        reply_markup=times_keyboard(),
    )


@dp.message(F.text.regexp(r"^\d{2}:\d{2}$"))
async def show_time(message: Message, state: FSMContext):
    await state.update_data(time=message.text)
    await message.answer(
        "Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Booking.name)


@dp.message(Booking.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(
        f"Приятно познакомиться, {message.text}!\n"
        "Оставь, пожалуйста, номер телефона для связи:"
    )
    await state.set_state(Booking.phone)


@dp.message(Booking.phone)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    data = await state.get_data()

    # Сохраняем в БД
    user = message.from_user
    save_booking(
        user_id=user.id,
        username=user.username or "",
        service=data["service"],
        master=data["master"],
        date=data["date"],
        time=data["time"],
        name=data["name"],
        phone=data["phone"],
    )

    # Клиенту — подтверждение
    await message.answer(
        "Запись оформлена!\n\n"
        f"Услуга: {data['service']}\n"
        f"Мастер: {data['master']}\n"
        f"Дата: {data['date']}\n"
        f"Время: {data['time']}\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n\n"
        "Мы свяжемся с тобой для подтверждения.",
        reply_markup=services_keyboard(),
    )

    # Админу — уведомление
    admin_text = (
        "🔔 Новая запись!\n\n"
        f"Услуга: {data['service']}\n"
        f"Мастер: {data['master']}\n"
        f"Дата: {data['date']}\n"
        f"Время: {data['time']}\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Telegram: @{user.username or '—'}"
    )
    try:
        await bot.send_message(ADMIN_ID, admin_text)
    except Exception as e:
        print(f"Не удалось отправить уведомление админу: {e}")

    await state.clear()


async def main():
    init_db()
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
