import logging
import sqlite3
import random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from datetime import datetime, timedelta
import asyncio

# ------------ Config ------------
# تم تحديث التوكن ومعرف الأدمن الخاص بك
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 7549947471 

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ------------ Database Setup (SQLite) ------------
DB_NAME = 'store.db'

def init_db():
    """تهيئة قاعدة البيانات وإنشاء جميع الجداول."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. جدول الأقسام
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    
    # 2. جدول المنتجات (يحتوي على category_id)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            category_id INTEGER,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        )
    """)
    
    # 3. جدول المستخدمين
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.00,
            last_activity DATETIME DEFAULT CURRENT_TIMESTAMP 
        )
    """)
    
    # 4. جدول الإعدادات الديناميكية
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # 5. جدول الطلبات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_name TEXT,
            price REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'Completed',
            delivery_status TEXT DEFAULT 'Pending' 
        )
    """)
    
    # 6. جدول الطلبات القابلة للإلغاء
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cancellable_orders (
            order_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            expiry_time DATETIME
        )
    """)

    # 7. جدول الأزرار المخصصة
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_buttons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            url TEXT NOT NULL
        )
    """)

    # --- الإعدادات الافتراضية ---
    settings_data = {
        'btc_wallet_link': 'bc1qxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
        'support_contact': '@YourSupportUsername',
        'currency_symbol': 'USD',
        'welcome_message': 'أهلاً بك في متجر MR.DARK 🔥',
        'admin_welcome_message': 'مرحباً أيها الأدمن 👑',
        'cancellation_time_minutes': '30', 
        'faq_text': 'الأسئلة الشائعة: الإيداع يدوي ويستغرق 10-30 دقيقة.', 
        'suggestion_thanks': 'شكراً لاقتراحك! سيتم مراجعته قريباً.'
    }
    
    for key, value in settings_data.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    # إضافة أقسام افتراضية
    default_categories = ["بطاقات Mastercard", "بطاقات Visa", "حسابات"]
    for cat_name in default_categories:
        cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat_name,))

    conn.commit()
    conn.close()

# الدوال المساعدة لقاعدة البيانات
def get_setting(key):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_user_balance(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
    cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return balance

def get_all_user_ids():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users")
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids

def update_user_balance(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_product_by_id(product_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price FROM products WHERE id = ?", (product_id,))
    data = cursor.fetchone()
    conn.close()
    if data:
        pid, name, price = data
        return {"id": pid, "name": name, "price": f"{price:.2f}", "raw_price": price}
    return None

def record_order(user_id, product_name, price, is_cancellable=False):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO orders (user_id, product_name, price, delivery_status) VALUES (?, ?, ?, ?)", (user_id, product_name, price, 'Pending'))
    order_id = cursor.lastrowid
    
    if is_cancellable:
        minutes = int(get_setting('cancellation_time_minutes'))
        expiry_time = (datetime.now() + timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("INSERT INTO cancellable_orders (order_id, user_id, expiry_time) VALUES (?, ?, ?)", 
                       (order_id, user_id, expiry_time))
    
    conn.commit()
    conn.close()
    return order_id

def get_cancellable_order(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("""
        SELECT co.order_id, o.product_name, o.price, co.expiry_time 
        FROM cancellable_orders co
        JOIN orders o ON co.order_id = o.id
        WHERE co.user_id = ? AND co.expiry_time > ?
        ORDER BY co.order_id DESC LIMIT 1
    """, (user_id, now))
    
    result = cursor.fetchone()
    conn.close()
    return result

def cancel_pending_order(order_id, user_id, price):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM cancellable_orders WHERE order_id = ? AND user_id = ?", (order_id, user_id))
    cursor.execute("UPDATE orders SET status = 'Cancelled', delivery_status = 'N/A' WHERE id = ?", (order_id,))
    update_user_balance(user_id, price)
    
    conn.commit()
    conn.close()
    return True 

def get_user_orders(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT product_name, price, timestamp, status, delivery_status FROM orders WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (user_id,))
    orders = cursor.fetchall()
    conn.close()
    return orders

def get_all_products(category_id=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if category_id:
        cursor.execute("SELECT id, name, price FROM products WHERE category_id = ? ORDER BY id DESC", (category_id,))
    else:
        cursor.execute("SELECT id, name, price FROM products ORDER BY id DESC")
    products_data = cursor.fetchall()
    conn.close()
    return {pid: {"name": name, "price": f"{price:.2f}"} for pid, name, price in products_data}

def add_product_to_db(name, price, category_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO products (name, price, category_id) VALUES (?, ?, ?)", (name, price, category_id))
    conn.commit()
    conn.close()

def delete_product_from_db(product_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    return cursor.rowcount > 0

# دوال الأقسام
def get_all_categories():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories ORDER BY id ASC")
    data = cursor.fetchall()
    conn.close()
    return data

def add_category_to_db(name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_category_from_db(category_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET category_id = NULL WHERE category_id = ?", (category_id,))
    cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
    return cursor.rowcount > 0

def get_category_name(category_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM categories WHERE id = ?", (category_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "قسم غير معروف"

# دوال الأزرار المخصصة
def get_custom_buttons():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, text, url FROM custom_buttons ORDER BY id ASC")
    data = cursor.fetchall()
    conn.close()
    return data

def add_custom_button_to_db(text, url):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO custom_buttons (text, url) VALUES (?, ?)", (text, url))
    conn.commit()
    conn.close()

def delete_custom_button_from_db(button_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_buttons WHERE id = ?", (button_id,))
    conn.commit()
    return cursor.rowcount > 0

# دوال الإحصائيات
def get_statistics():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    total_users = cursor.execute("SELECT COUNT(id) FROM users").fetchone()[0]
    total_products = cursor.execute("SELECT COUNT(id) FROM products").fetchone()[0]
    total_orders = cursor.execute("SELECT COUNT(id) FROM orders WHERE status = 'Completed'").fetchone()[0]
    total_revenue = cursor.execute("SELECT SUM(price) FROM orders WHERE status = 'Completed'").fetchone()[0]
    
    conn.close()
    
    return {
        'users': total_users,
        'products': total_products,
        'orders': total_orders,
        'revenue': total_revenue if total_revenue else 0.00
    }

def update_order_delivery_status(order_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET delivery_status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()

def get_order_details(order_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, product_name, price FROM orders WHERE id = ?", (order_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {'user_id': result[0], 'product_name': result[1], 'price': result[2]}
    return None

# ------------ States ------------
class AddProduct(StatesGroup):
    waiting_for_category = State() 
    waiting_for_name = State()
    waiting_for_price = State()

class DeleteProduct(StatesGroup):
    waiting_for_id = State()

class AdminAddBalance(StatesGroup):
    waiting_for_target_id = State()
    waiting_for_amount = State()

class DepositFlow(StatesGroup):
    waiting_for_amount_to_send = State() 
    waiting_for_confirmation = State()

class EditSettings(StatesGroup):
    waiting_for_key_selection = State()
    waiting_for_new_value = State()

class SuggestionFlow(StatesGroup):
    waiting_for_suggestion = State()

class BroadcastFlow(StatesGroup):
    waiting_for_message = State()

class SendToUserFlow(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_message = State()
    
class DeliveryFlow(StatesGroup):
    waiting_for_delivery_data = State()

class AddCategory(StatesGroup): 
    waiting_for_name = State()

class DeleteCategory(StatesGroup): 
    waiting_for_id = State()

class AddCustomButton(StatesGroup): 
    waiting_for_text = State()
    waiting_for_url = State()

class DeleteCustomButton(StatesGroup): 
    waiting_for_id = State()

# ------------ Keyboards and Handlers ------------

def user_menu(user_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("الملف الشخصي 👤", callback_data="my_profile"),
        InlineKeyboardButton("إيداع 💸", callback_data="start_deposit"),
        InlineKeyboardButton("عرض المنتجات 🛍️", callback_data="show_categories"), 
        InlineKeyboardButton("سجل الطلبات 📜", callback_data="order_history"),
        InlineKeyboardButton("إرسال اقتراح 💡", callback_data="send_suggestion"),
        InlineKeyboardButton("الأسئلة الشائعة ❓", callback_data="show_faq")
    )
    
    custom_buttons = get_custom_buttons()
    for _, text, url in custom_buttons:
        kb.add(InlineKeyboardButton(text, url=url))

    pending_order = get_cancellable_order(user_id)
    if pending_order:
         kb.add(InlineKeyboardButton("إلغاء آخر طلب ❌", callback_data=f"cancel_{pending_order[0]}"))

    return kb

def admin_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 الإحصائيات", callback_data="show_statistics"), 
        InlineKeyboardButton("➕ إدارة المنتجات ➖", callback_data="manage_products"),
        InlineKeyboardButton("📁 إدارة الأقسام", callback_data="manage_categories"), 
        InlineKeyboardButton("🔗 إدارة الأزرار المخصصة", callback_data="manage_custom_buttons"), 
        InlineKeyboardButton("💰 إدارة الرصيد", callback_data="manage_balance"),
        InlineKeyboardButton("⚙️ إعدادات البوت", callback_data="edit_settings"),
        InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="start_broadcast"),
        InlineKeyboardButton("✉️ إرسال رسالة لفرد", callback_data="start_send_to_user")
    )
    kb.add(InlineKeyboardButton("📦 عرض المنتجات", callback_data="show_categories"))
    kb.add(InlineKeyboardButton("رجوع إلى القائمة الرئيسية (المستخدم) 🏠", callback_data="user_main_menu"))
    return kb

def manage_products_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ إضافة منتج", callback_data="add_product"),
        InlineKeyboardButton("➖ حذف منتج", callback_data="delete_product"),
        InlineKeyboardButton("رجوع إلى قائمة الأدمن ⬅️", callback_data="admin_main_menu")
    )
    return kb

def manage_categories_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ إضافة قسم", callback_data="add_category"),
        InlineKeyboardButton("➖ حذف قسم", callback_data="delete_category"),
        InlineKeyboardButton("رجوع إلى قائمة الأدمن ⬅️", callback_data="admin_main_menu")
    )
    return kb

def manage_custom_buttons_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ إضافة زر مخصص", callback_data="add_custom_button"),
        InlineKeyboardButton("➖ حذف زر مخصص", callback_data="delete_custom_button"),
        InlineKeyboardButton("رجوع إلى قائمة الأدمن ⬅️", callback_data="admin_main_menu")
    )
    return kb

def deposit_options():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("بيتكوين (BTC) ₿", callback_data="deposit_btc"),
        InlineKeyboardButton("رجوع ⬅️", callback_data="user_main_menu")
    )
    return kb

def settings_list_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    settings_keys = {
        'btc_wallet_link': "عنوان محفظة BTC",
        'support_contact': "رابط الدعم",
        'currency_symbol': "رمز العملة",
        'welcome_message': "رسالة الترحيب للمستخدم",
        'admin_welcome_message': "رسالة ترحيب الأدمن",
        'cancellation_time_minutes': "مهلة الإلغاء (دقيقة)",
        'faq_text': "نص الأسئلة الشائعة",
        'suggestion_thanks': "رسالة شكر الاقتراحات"
    }
    for key, name in settings_keys.items():
        kb.add(InlineKeyboardButton(f"⚙️ {name}", callback_data=f"edit_key_{key}"))
    kb.add(InlineKeyboardButton("رجوع إلى قائمة الأدمن ⬅️", callback_data="admin_main_menu"))
    return kb

def back_button_user():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("رجوع إلى القائمة الرئيسية 🏠", callback_data="user_main_menu"))

# ------------ Shared Handlers ------------
@dp.message_handler(commands=['start', 'menu'], state="*")
async def start_handler(msg: types.Message, state: FSMContext):
    await state.finish()
    get_user_balance(msg.from_user.id) 

    if msg.from_user.id == ADMIN_ID:
        welcome_msg = get_setting('admin_welcome_message')
        await msg.answer(welcome_msg, reply_markup=admin_menu())
    else:
        welcome_msg = get_setting('welcome_message')
        await msg.answer(welcome_msg, reply_markup=user_menu(msg.from_user.id))

@dp.callback_query_handler(lambda c: c.data == "user_main_menu", state="*")
async def return_to_user_menu(cb: types.CallbackQuery, state: FSMContext):
    await state.finish()
    
    if cb.from_user.id == ADMIN_ID:
        welcome_msg = get_setting('admin_welcome_message')
        await cb.message.edit_text(welcome_msg, reply_markup=admin_menu())
    else:
        welcome_msg = get_setting('welcome_message')
        await cb.message.edit_text(welcome_msg, reply_markup=user_menu(cb.from_user.id))
    await cb.answer()
    
@dp.callback_query_handler(lambda c: c.data == "admin_main_menu", state="*")
async def return_to_admin_menu(cb: types.CallbackQuery, state: FSMContext):
    await state.finish()
    welcome_msg = get_setting('admin_welcome_message')
    await cb.message.edit_text(welcome_msg, reply_markup=admin_menu())
    await cb.answer()

# ------------ User Features: Profile, FAQ, Suggestion, History ------------
@dp.callback_query_handler(lambda c: c.data == "my_profile")
async def show_profile(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    balance = get_user_balance(user_id)
    currency = get_setting('currency_symbol')
    
    text = (
        "👤 *ملفك الشخصي:*\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"💰 الرصيد الحالي: *{balance:.2f} {currency}*"
    )
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button_user())
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data == "show_faq")
async def show_faq(cb: types.CallbackQuery):
    faq_text = get_setting('faq_text')
    await cb.message.edit_text(f"❓ *الأسئلة الشائعة:*\n\n{faq_text}", parse_mode="Markdown", reply_markup=back_button_user())
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data == "send_suggestion")
async def start_suggestion(cb: types.CallbackQuery):
    await cb.message.edit_text("💡 *إرسال اقتراح:*\n\nالرجاء كتابة اقتراحك الآن:", parse_mode="Markdown", reply_markup=back_button_user())
    await SuggestionFlow.waiting_for_suggestion.set()
    await cb.answer()

@dp.message_handler(state=SuggestionFlow.waiting_for_suggestion)
async def process_suggestion(msg: types.Message, state: FSMContext):
    user_link = f"<a href='tg://user?id={msg.from_user.id}'>{msg.from_user.full_name}</a>"
    
    await bot.send_message(
        ADMIN_ID,
        f"💡 *اقتراح جديد من:*\n"
        f"👤 المستخدم: {user_link} (`{msg.from_user.id}`)\n"
        f"📩 الاقتراح:\n{msg.text}",
        parse_mode="HTML"
    )

    thanks_msg = get_setting('suggestion_thanks')
    await msg.answer(f"✅ {thanks_msg}", reply_markup=back_button_user())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "order_history")
async def show_order_history(cb: types.CallbackQuery):
    orders = get_user_orders(cb.from_user.id)
    currency = get_setting('currency_symbol')
    
    text = "📜 *سجل آخر 10 طلبات:*\n\n"
    if orders:
        for name, price, date, status, delivery in orders:
            text += f"• **{name}**\n   السعر: {price:.2f} {currency} | الحالة: {status}\n   التسليم: {delivery} | التاريخ: {date[:16]}\n"
    else:
        text += "لا يوجد لديك سجل طلبات حالياً."
        
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button_user())
    await cb.answer()

# ------------ User Features: Deposit (مع إخلاء المسؤولية) ------------
@dp.callback_query_handler(lambda c: c.data == "start_deposit")
async def start_deposit(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "يرجى اختيار العملة التي تريد الإيداع بها:",
        reply_markup=deposit_options()
    )
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data == "deposit_btc")
async def deposit_btc(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "💰 *الإيداع عبر البيتكوين (BTC):*\n\n"
        "الرجاء إرسال *المبلغ المحدد* (بالأرقام) الذي تنوي تحويله الآن. مثال: `100.00`",
        parse_mode="Markdown",
        reply_markup=back_button_user()
    )
    await DepositFlow.waiting_for_amount_to_send.set() 
    await cb.answer()

@dp.message_handler(state=DepositFlow.waiting_for_amount_to_send)
async def get_deposit_amount(msg: types.Message, state: FSMContext):
    try:
        amount = float(msg.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await msg.answer("❌ المبلغ غير صالح. الرجاء إرسال رقم موجب فقط (مثال: 50.75).", reply_markup=back_button_user())
        return

    wallet_address = get_setting('btc_wallet_link')
    currency = get_setting('currency_symbol')
    
    await state.update_data(expected_btc_amount=f"{amount:.2f}")

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("✔️ أكدت التحويل، يرجى المراجعة", callback_data="confirm_btc_transfer"),
        InlineKeyboardButton("رجوع ⬅️", callback_data="user_main_menu")
    )

    text = (
        "💰 *الإيداع عبر البيتكوين (BTC):*\n\n"
        f"✅ *المبلغ الذي أعلنته: {amount:.2f} {currency}*\n\n"
        "1. قم بتحويل المبلغ المحدد *بالضبط* إلى هذا العنوان:\n"
        f"   `{wallet_address}`\n\n"
        "🛑 *إخلاء مسؤولية هام:*\n"
        "إذا قمت بالإيداع وتحويل **مبلغ يختلف عن المبلغ الذي أعلنته هنا**، فإنك تتحمل **المسؤولية الكاملة** عن أي فرق أو تأخير في معالجة طلبك، وقد لا يتم إضافة الرصيد إلا بعد المراجعة اليدوية والتدقيق.\n"
        "_(يجب عليك تحويل المبلغ المعلن **بالكامل**)_\n\n"
        "2. بعد إتمام التحويل، *اضغط على الزر أدناه* لإشعار الأدمن."
    )
    
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb)
    await DepositFlow.waiting_for_confirmation.set()

@dp.callback_query_handler(lambda c: c.data == "confirm_btc_transfer", state=DepositFlow.waiting_for_confirmation)
async def confirm_btc_transfer(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    expected_amount = data.get('expected_btc_amount', 'غير محدد')
    user_link = f"<a href='tg://user?id={cb.from_user.id}'>{cb.from_user.full_name}</a>"

    await bot.send_message(
        ADMIN_ID,
        f"❗️ *تأكيد إيداع جديد (مراجعة يدوية):*\n\n"
        f"👤 المستخدم: {user_link}\n"
        f"🆔 ID: `{cb.from_user.id}`\n"
        f"💰 *المبلغ المتوقع (المعلن):* `{expected_amount}`\n"
        f"نوع الإيداع: بيتكوين (BTC)\n\n"
        f"⚠️ *ملاحظة للأدمن:* المستخدم أقر بتحويل المبلغ أعلاه. الرجاء التحقق من المحفظة والمطابقة مع التحويل الفعلي. إذا كان المبلغ المحول يختلف، **فالمستخدم يتحمل المسؤولية حسب الإشعار الذي ظهر له**. أمر الإضافة المقترح: `/add_balance {cb.from_user.id} {expected_amount}`",
        parse_mode="HTML"
    )

    await cb.message.edit_text(
        "✅ تم إرسال إشعار للأدمن بنجاح.\nسيتم مراجعة طلبك وإضافة الرصيد في أقرب وقت ممكن. شكراً لك.",
        reply_markup=back_button_user()
    )
    await state.finish()
    await cb.answer()

# ------------ Admin: Statistics (الإحصائيات) ------------
@dp.callback_query_handler(lambda c: c.data == "show_statistics")
async def show_statistics(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    stats = get_statistics()
    currency = get_setting('currency_symbol')
    
    text = (
        "📊 *إحصائيات المتجر:*\n\n"
        f"👥 إجمالي المستخدمين: *{stats['users']}*\n"
        f"📦 إجمالي المنتجات المعروضة: *{stats['products']}*\n"
        f"📜 إجمالي الطلبات المكتملة: *{stats['orders']}*\n"
        f"💰 إجمالي الإيرادات (المبيعات): *{stats['revenue']:.2f} {currency}*"
    )
    
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_menu())
    await cb.answer()

# ------------ Admin: Messaging Features (تم الإصلاح) ------------

@dp.callback_query_handler(lambda c: c.data == "start_broadcast")
async def start_broadcast(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.answer("📢 *البث الجماعي:*\n\nالرجاء إرسال الرسالة التي تريد إرسالها لجميع المستخدمين.", parse_mode="Markdown", reply_markup=admin_menu())
    await BroadcastFlow.waiting_for_message.set()
    await cb.answer()

@dp.message_handler(state=BroadcastFlow.waiting_for_message, content_types=types.ContentType.ANY)
async def send_broadcast(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.finish()

    user_ids = get_all_user_ids()
    sent_count = 0
    failed_count = 0
    
    await msg.answer("⏳ جارٍ إرسال الرسائل...", reply_markup=admin_menu())

    for user_id in user_ids:
        if user_id == ADMIN_ID: continue
        try:
            await bot.copy_message(user_id, msg.chat.id, msg.message_id)
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed_count += 1

    await bot.send_message(ADMIN_ID, 
                           f"✅ *اكتمل البث الجماعي:*\n"
                           f"تم الإرسال بنجاح إلى: {sent_count}\n"
                           f"فشل الإرسال إلى: {failed_count}",
                           parse_mode="Markdown")

@dp.callback_query_handler(lambda c: c.data == "start_send_to_user")
async def start_send_to_user(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.answer("✉️ *إرسال رسالة فردية:*\n\nالرجاء إرسال *ID المستخدم* المستهدف.", parse_mode="Markdown", reply_markup=admin_menu())
    await SendToUserFlow.waiting_for_user_id.set()
    await cb.answer()

@dp.message_handler(state=SendToUserFlow.waiting_for_user_id)
async def get_target_user_id(msg: types.Message, state: FSMContext):
    try:
        target_id = int(msg.text)
        await state.update_data(target_id=target_id)
        await msg.answer(f"تم اختيار المستخدم ID: `{target_id}`. الآن أرسل الرسالة التي تريد إرسالها.", parse_mode="Markdown")
        await SendToUserFlow.waiting_for_message.set()
    except ValueError:
        await msg.answer("❌ الرجاء إرسال ID مستخدم صحيح (رقم فقط).", reply_markup=admin_menu())
        await state.finish() 

@dp.message_handler(state=SendToUserFlow.waiting_for_message, content_types=types.ContentType.ANY)
async def send_message_to_user(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    target_id = data.get('target_id')
    await state.finish()

    try:
        await bot.copy_message(target_id, msg.chat.id, msg.message_id)
        await msg.answer(f"✅ تم إرسال الرسالة بنجاح إلى المستخدم ID: `{target_id}`.", parse_mode="Markdown", reply_markup=admin_menu())
    except Exception as e:
        await msg.answer(f"❌ فشل إرسال الرسالة إلى المستخدم ID: `{target_id}`.\nالخطأ: {e}", parse_mode="Markdown", reply_markup=admin_menu())


# ------------ Admin: Settings Management (تم الإصلاح) ------------

@dp.callback_query_handler(lambda c: c.data == "edit_settings")
async def start_edit_settings(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.edit_text("⚙️ *إدارة إعدادات البوت:*\n\nالرجاء اختيار الإعداد الذي تريد تعديله:", parse_mode="Markdown", reply_markup=settings_list_menu())
    await cb.answer()
    
@dp.callback_query_handler(lambda c: c.data.startswith("edit_key_"))
async def edit_setting_key(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID: return
    key = cb.data.split('_')[2]
    current_value = get_setting(key)
    
    await state.update_data(setting_key=key)
    
    await cb.message.edit_text(
        f"تعديل الإعداد: *{key}*\nالقيمة الحالية هي:\n`{current_value}`\n\nالرجاء إرسال القيمة الجديدة لهذا الإعداد:",
        parse_mode="Markdown",
        reply_markup=settings_list_menu()
    )
    await EditSettings.waiting_for_new_value.set()
    await cb.answer()

@dp.message_handler(state=EditSettings.waiting_for_new_value)
async def process_setting_value(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    key = data.get('setting_key')
    new_value = msg.text
    
    set_setting(key, new_value)
    
    await state.finish()
    await msg.answer(f"✅ تم تحديث الإعداد *{key}* إلى القيمة الجديدة بنجاح:\n`{new_value}`", 
                     parse_mode="Markdown",
                     reply_markup=settings_list_menu())


# ------------ Admin: Category Management ------------

@dp.callback_query_handler(lambda c: c.data == "manage_categories")
async def show_manage_categories_menu(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    categories = get_all_categories()
    text = "📁 *إدارة الأقسام:*\n\n"
    if categories:
        for cat_id, name in categories:
            text += f"• ID: `{cat_id}` - {name}\n"
    else:
        text += "لا توجد أقسام حالياً."
        
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=manage_categories_menu())
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data == "add_category")
async def start_add_category(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.answer("أرسل اسم القسم الجديد:", reply_markup=manage_categories_menu())
    await AddCategory.waiting_for_name.set()
    await cb.answer() 

@dp.message_handler(state=AddCategory.waiting_for_name)
async def process_add_category(msg: types.Message, state: FSMContext):
    if add_category_to_db(msg.text):
        await msg.answer("✔️ تم إضافة القسم بنجاح!", reply_markup=manage_categories_menu())
    else:
        await msg.answer("❌ هذا القسم موجود مسبقاً أو حدث خطأ.", reply_markup=manage_categories_menu())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "delete_category")
async def start_delete_category(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    categories = get_all_categories()
    if not categories:
        await cb.message.answer("لا توجد أقسام لحذفها.")
        await cb.answer()
        return
    
    text = "📦 *الأقسام المتوفرة:*\n\n"
    for cat_id, name in categories:
        text += f"• *ID:* `{cat_id}` | {name}\n"
    
    text += "\nالرجاء إرسال *رقم ID* القسم الذي تريد حذفه:"
    
    await cb.message.answer(text, parse_mode="Markdown", reply_markup=manage_categories_menu())
    await DeleteCategory.waiting_for_id.set()
    await cb.answer()

@dp.message_handler(state=DeleteCategory.waiting_for_id)
async def process_delete_category(msg: types.Message, state: FSMContext):
    try:
        cat_id = int(msg.text)
    except ValueError:
        await msg.answer("❌ الرجاء إرسال رقم ID صحيح.", reply_markup=manage_categories_menu())
        await state.finish()
        return

    if delete_category_from_db(cat_id):
        await msg.answer(f"✅ تم حذف القسم ذو ID `{cat_id}` بنجاح.\n*ملاحظة: تم نقل المنتجات المرتبطة به إلى حالة 'بدون قسم'*.", parse_mode="Markdown", reply_markup=manage_categories_menu())
    else:
        await msg.answer(f"❌ لم يتم العثور على قسم ذو ID `{cat_id}` للحذف.", reply_markup=manage_categories_menu())
    
    await state.finish()


# ------------ Admin: Custom Buttons Management ------------

@dp.callback_query_handler(lambda c: c.data == "manage_custom_buttons")
async def show_manage_buttons_menu(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    buttons = get_custom_buttons()
    text = "🔗 *إدارة الأزرار المخصصة:*\n\n"
    if buttons:
        for btn_id, text_btn, url_btn in buttons:
            text += f"• ID: `{btn_id}` | النص: {text_btn} | الرابط: {url_btn}\n"
    else:
        text += "لا توجد أزرار مخصصة حالياً."
        
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=manage_custom_buttons_menu())
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data == "add_custom_button")
async def start_add_button(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.answer("أرسل *نص* الزر الذي سيظهر للمستخدم:", parse_mode="Markdown", reply_markup=manage_custom_buttons_menu())
    await AddCustomButton.waiting_for_text.set()
    await cb.answer() 

@dp.message_handler(state=AddCustomButton.waiting_for_text)
async def button_text(msg: types.Message, state: FSMContext):
    await state.update_data(text=msg.text)
    await msg.answer("الآن أرسل *رابط (URL)* الذي سيؤدي إليه الزر (يجب أن يبدأ بـ http:// أو https://):", parse_mode="Markdown")
    await AddCustomButton.waiting_for_url.set()

@dp.message_handler(state=AddCustomButton.waiting_for_url)
async def button_url(msg: types.Message, state: FSMContext):
    url = msg.text
    if not (url.startswith('http://') or url.startswith('https://')):
        await msg.answer("❌ يجب أن يكون الرابط صحيحاً ويبدأ بـ `http://` أو `https://`.", reply_markup=manage_custom_buttons_menu())
        await state.finish()
        return

    data = await state.get_data()
    text = data["text"]

    add_custom_button_to_db(text, url) 

    await msg.answer("✔️ تم إضافة الزر المخصص بنجاح!", reply_markup=manage_custom_buttons_menu())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "delete_custom_button")
async def start_delete_button(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    buttons = get_custom_buttons()
    if not buttons:
        await cb.message.answer("لا توجد أزرار لحذفها.")
        await cb.answer()
        return
    
    text = "🔗 *الأزرار المتوفرة:*\n\n"
    for btn_id, text_btn, _ in buttons:
        text += f"• *ID:* `{btn_id}` | {text_btn}\n"
    
    text += "\nالرجاء إرسال *رقم ID* الزر الذي تريد حذفه:"
    
    await cb.message.answer(text, parse_mode="Markdown", reply_markup=manage_custom_buttons_menu())
    await DeleteCustomButton.waiting_for_id.set()
    await cb.answer()

@dp.message_handler(state=DeleteCustomButton.waiting_for_id)
async def process_delete_button(msg: types.Message, state: FSMContext):
    try:
        btn_id = int(msg.text)
    except ValueError:
        await msg.answer("❌ الرجاء إرسال رقم ID صحيح.", reply_markup=manage_custom_buttons_menu())
        await state.finish()
        return

    if delete_custom_button_from_db(btn_id):
        await msg.answer(f"✅ تم حذف الزر ذو ID `{btn_id}` بنجاح.", reply_markup=manage_custom_buttons_menu())
    else:
        await msg.answer(f"❌ لم يتم العثور على زر ذو ID `{btn_id}` للحذف.", reply_markup=manage_custom_buttons_menu())
    
    await state.finish()


# ------------ Admin: Product Management (CRUD) ------------
@dp.callback_query_handler(lambda c: c.data == "manage_products")
async def show_manage_products_menu(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.edit_text("➕ *إدارة المنتجات ➖*", parse_mode="Markdown", reply_markup=manage_products_menu())
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data == "add_product")
async def start_add_product(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    categories = get_all_categories()
    if not categories:
        await cb.message.answer("❌ يجب إضافة قسم واحد على الأقل قبل إضافة منتج. الرجاء إنشاء قسم أولاً.", reply_markup=manage_categories_menu())
        await cb.answer()
        return

    kb = InlineKeyboardMarkup(row_width=2)
    for cat_id, name in categories:
        kb.add(InlineKeyboardButton(name, callback_data=f"select_cat_{cat_id}"))
    
    kb.add(InlineKeyboardButton("رجوع ⬅️", callback_data="manage_products"))
    
    await cb.message.edit_text("الرجاء اختيار القسم الذي ينتمي إليه المنتج:", reply_markup=kb)
    await AddProduct.waiting_for_category.set()
    await cb.answer() 

@dp.callback_query_handler(lambda c: c.data.startswith("select_cat_"), state=AddProduct.waiting_for_category)
async def select_category(cb: types.CallbackQuery, state: FSMContext):
    cat_id = int(cb.data.split('_')[2])
    await state.update_data(category_id=cat_id)
    await cb.message.edit_text(f"✅ تم اختيار القسم. الآن أرسل اسم المنتج:", reply_markup=manage_products_menu())
    await AddProduct.waiting_for_name.set()
    await cb.answer()

@dp.message_handler(state=AddProduct.waiting_for_name)
async def product_name(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await msg.answer("الآن أرسل سعر المنتج (رقم):")
    await AddProduct.waiting_for_price.set()

@dp.message_handler(state=AddProduct.waiting_for_price)
async def product_price(msg: types.Message, state: FSMContext):
    try:
        price = float(msg.text)
    except ValueError:
        await msg.answer("❌ السعر غير صالح. الرجاء إرسال رقم (مثال: 50 أو 19.99):")
        return 

    data = await state.get_data()
    name = data["name"]
    category_id = data["category_id"]

    add_product_to_db(name, price, category_id) 

    await msg.answer("✔️ تم إضافة المنتج بنجاح!", reply_markup=manage_products_menu())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "delete_product")
async def start_delete_product(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    products = get_all_products()
    if not products:
        await cb.message.answer("لا توجد منتجات لحذفها.")
        await cb.answer()
        return
    
    text = "📦 *المنتجات المتوفرة:*\n\n"
    for pid, data in products.items():
        text += f"• *ID:* `{pid}` | {data['name']} | السعر: {data['price']}\n"
    
    text += "\nالرجاء إرسال *رقم ID* المنتج الذي تريد حذفه:"
    
    await cb.message.answer(text, parse_mode="Markdown", reply_markup=manage_products_menu())
    await DeleteProduct.waiting_for_id.set()
    await cb.answer()

@dp.message_handler(state=DeleteProduct.waiting_for_id)
async def process_delete_product(msg: types.Message, state: FSMContext):
    try:
        product_id = int(msg.text)
    except ValueError:
        await msg.answer("❌ الرجاء إرسال رقم ID صحيح.", reply_markup=manage_products_menu())
        await state.finish()
        return

    if delete_product_from_db(product_id):
        await msg.answer(f"✅ تم حذف المنتج ذو ID `{product_id}` بنجاح.", reply_markup=manage_products_menu())
    else:
        await msg.answer(f"❌ لم يتم العثور على منتج ذو ID `{product_id}` للحذف.", reply_markup=manage_products_menu())
    
    await state.finish()

# ------------ Admin: Balance Management ------------
@dp.callback_query_handler(lambda c: c.data == "manage_balance")
async def start_manage_balance(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.answer("💰 *إدارة الرصيد:*\n\nالرجاء إرسال ID المستخدم الذي تريد تعديل رصيده:", parse_mode="Markdown", reply_markup=admin_menu())
    await AdminAddBalance.waiting_for_target_id.set()
    await cb.answer()

@dp.message_handler(state=AdminAddBalance.waiting_for_target_id)
async def get_target_id_for_balance(msg: types.Message, state: FSMContext):
    try:
        target_id = int(msg.text)
        await state.update_data(target_id=target_id)
        current_balance = get_user_balance(target_id)
        currency = get_setting('currency_symbol')
        
        await msg.answer(f"تم اختيار المستخدم ID: `{target_id}`. رصيده الحالي: *{current_balance:.2f} {currency}*.\n\nالرجاء إرسال *قيمة التعديل* (موجب للإضافة، سالب للخصم). مثال: `+50` أو `-10`", parse_mode="Markdown")
        await AdminAddBalance.waiting_for_amount.set()
    except ValueError:
        await msg.answer("❌ الرجاء إرسال ID مستخدم صحيح (رقم فقط).", reply_markup=admin_menu())
        await state.finish()

@dp.message_handler(state=AdminAddBalance.waiting_for_amount)
async def process_balance_amount(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get('target_id')
    
    try:
        amount_str = msg.text.strip()
        if amount_str.startswith('+') or amount_str.startswith('-'):
            amount = float(amount_str)
        else:
            amount = float(amount_str) # التعامل مع الأرقام الموجبة الافتراضية كإضافة
    except ValueError:
        await msg.answer("❌ قيمة غير صالحة. الرجاء إرسال رقم مع إشارة (+ للإضافة، - للخصم).", reply_markup=admin_menu())
        await state.finish()
        return

    update_user_balance(target_id, amount)
    new_balance = get_user_balance(target_id)
    currency = get_setting('currency_symbol')

    await msg.answer(f"✅ تم تعديل رصيد المستخدم ID: `{target_id}` بنجاح.\nالرصيد الجديد: *{new_balance:.2f} {currency}*.", parse_mode="Markdown", reply_markup=admin_menu())
    
    try:
        # إرسال إشعار للمستخدم
        action = "إضافة" if amount >= 0 else "خصم"
        await bot.send_message(target_id, f"🔔 *تم تحديث رصيدك!* \nتم {action} مبلغ {abs(amount):.2f} {currency} من قبل الأدمن.\nرصيدك الجديد: {new_balance:.2f} {currency}", parse_mode="Markdown")
    except Exception:
        pass # تجاهل إذا كان المستخدم قد حظر البوت
    
    await state.finish()


# ------------ Buying System (with Cancellation Feature) ------------
# ... (تم نقل دالة الشراء إلى الأعلى في الكود السابق، ولكنها ستحفظ هنا لتسلسل الكود) ...
@dp.callback_query_handler(lambda c: c.data.startswith("buy_"))
async def buy_item(cb: types.CallbackQuery):
    pid = int(cb.data.split("_")[1])
    product = get_product_by_id(pid)
    user_id = cb.from_user.id
    current_balance = get_user_balance(user_id)
    currency = get_setting('currency_symbol')
    minutes = get_setting('cancellation_time_minutes')

    if not product:
        await cb.message.answer("❌ المنتج غير موجود!")
        await cb.answer()
        return

    price = product['raw_price']
    
    if current_balance < price:
        await cb.message.answer(
            f"❌ رصيدك الحالي ({current_balance:.2f} {currency}) لا يكفي لشراء {product['name']} ({product['price']} {currency}).\n"
            "الرجاء إيداع المزيد من الرصيد.",
            reply_markup=back_button_user()
        )
        await cb.answer()
        return

    update_user_balance(user_id, -price) 
    order_id = record_order(user_id, product['name'], price, is_cancellable=True) 

    new_balance = get_user_balance(user_id)
    
    kb_user = InlineKeyboardMarkup(row_width=1)
    kb_user.add(InlineKeyboardButton(f"❌ إلغاء الطلب (مهلة {minutes} دقيقة)", callback_data=f"cancel_{order_id}"))
    kb_user.add(InlineKeyboardButton("القائمة الرئيسية 🏠", callback_data="user_main_menu"))
    
    await cb.message.answer(
        f"✅ تم شراء المنتج *{product['name']}* بنجاح.\n"
        f"تم خصم: {product['price']} {currency}.\n"
        f"رصيدك الجديد هو: *{new_balance:.2f} {currency}*.\n\n"
        f"💬 سيتم إرسال تفاصيل المنتج إليك قريباً.\n"
        f"⚠️ لديك {minutes} دقيقة لإلغاء الطلب واسترداد الرصيد.",
        parse_mode="Markdown",
        reply_markup=kb_user
    )

    user_link = f"<a href='tg://user?id={cb.from_user.id}'>{cb.from_user.full_name}</a>"
    
    kb_admin = InlineKeyboardMarkup(row_width=1)
    kb_admin.add(
        InlineKeyboardButton("📦 تسليم المنتج الآن", callback_data=f"deliver_{order_id}")
    )
    
    await bot.send_message(
        ADMIN_ID,
        f"🎉 *عملية شراء جديدة (قيد التسليم):*\n\n"
        f"المنتج: {product['name']} (ID: {pid})\n"
        f"السعر: {product['price']} {currency}\n"
        f"المشتري: {user_link} (`{cb.from_user.id}`)\n"
        f"رقم الطلب المؤقت: `{order_id}`\n\n"
        f"⚠️ *الرجاء تسليم بيانات المنتج أو إلغاء الطلب إذا كان وهمياً.*",
        parse_mode="HTML",
        reply_markup=kb_admin
    )
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("cancel_"))
async def handle_cancel_order(cb: types.CallbackQuery):
    order_id = int(cb.data.split('_')[1])
    user_id = cb.from_user.id
    
    order_data = get_cancellable_order(user_id)
    
    if not order_data or order_data[0] != order_id:
        await cb.message.answer("❌ لا يمكن إلغاء هذا الطلب. قد تكون المهلة قد انتهت أو تم تسليمه بالفعل.")
        await cb.answer()
        return

    product_name = order_data[1]
    price = order_data[2]
    currency = get_setting('currency_symbol')
    
    if cancel_pending_order(order_id, user_id, price):
        await cb.message.edit_text(
            f"✅ تم إلغاء طلبك للمنتج *{product_name}* بنجاح.\n"
            f"تمت إعادة {price:.2f} {currency} إلى رصيدك.",
            parse_mode="Markdown",
            reply_markup=back_button_user()
        )
        
        user_link = f"<a href='tg://user?id={user_id}'>{cb.from_user.full_name}</a>"
        await bot.send_message(ADMIN_ID, 
                               f"🔔 *إشعار إلغاء:* \nقام المستخدم {user_link} (`{user_id}`) بإلغاء الطلب `{order_id}`.", 
                               parse_mode="HTML")
    else:
        await cb.message.answer("❌ فشل الإلغاء. الرجاء التواصل مع الدعم.")
        
    await cb.answer()
    
# ------------ Admin: Delivery Flow ------------
@dp.callback_query_handler(lambda c: c.data.startswith("deliver_"))
async def start_delivery(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID: return
    
    order_id = int(cb.data.split('_')[1])
    order_details = get_order_details(order_id)

    if not order_details:
        await cb.message.answer("❌ الطلب غير موجود أو تم إلغاؤه.")
        await cb.answer()
        return
        
    await state.update_data(current_order_id=order_id, target_user_id=order_details['user_id'])
    
    await cb.message.edit_text(
        f"📦 *تسليم الطلب رقم: {order_id}*\n\n"
        f"المنتج: {order_details['product_name']}\n"
        f"المشتري ID: `{order_details['user_id']}`\n\n"
        "الرجاء إرسال *البيانات/التفاصيل* الخاصة بهذا المنتج الآن (يمكن أن تكون رسالة أو ملف):",
        parse_mode="Markdown"
    )
    await DeliveryFlow.waiting_for_delivery_data.set()
    await cb.answer()

@dp.message_handler(state=DeliveryFlow.waiting_for_delivery_data, content_types=types.ContentType.ANY)
async def process_delivery_data(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    
    data = await state.get_data()
    order_id = data['current_order_id']
    target_user_id = data['target_user_id']
    
    try:
        # إرسال البيانات للمشتري (copy_message يعمل مع جميع أنواع الملفات)
        await bot.copy_message(target_user_id, msg.chat.id, msg.message_id)
        
        # إرسال إشعار للمشتري
        await bot.send_message(target_user_id, f"✅ *اكتمل التسليم!* \nتم إرسال تفاصيل طلبك رقم `{order_id}`. شكراً لك.", parse_mode="Markdown")
        
        # تحديث حالة الطلب
        update_order_delivery_status(order_id, 'Delivered')
        
        await msg.answer(f"✅ تم تسليم الطلب رقم `{order_id}` بنجاح إلى المستخدم ID `{target_user_id}`.", reply_markup=admin_menu())
        
    except Exception as e:
        await msg.answer(f"❌ فشل تسليم الطلب رقم `{order_id}` إلى ID `{target_user_id}`. قد يكون المستخدم حظر البوت.\nالخطأ: {e}", reply_markup=admin_menu())

    await state.finish()

# ------------ Show Products (Multi-level) ------------

@dp.callback_query_handler(lambda c: c.data == "show_categories")
async def show_categories_for_user(cb: types.CallbackQuery):
    categories = get_all_categories()
    
    if not categories:
        await cb.message.edit_text("لا توجد أقسام متاحة حالياً.", reply_markup=back_button_user())
        await cb.answer()
        return
        
    text = "📦 *الأقسام المتاحة:*\n\nالرجاء اختيار قسم لعرض المنتجات داخله:"
    kb = InlineKeyboardMarkup(row_width=1)
    
    for cat_id, name in categories:
        kb.add(InlineKeyboardButton(f"📁 {name}", callback_data=f"view_products_{cat_id}"))
        
    kb.add(InlineKeyboardButton("رجوع إلى القائمة الرئيسية 🏠", callback_data="user_main_menu"))
    
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("view_products_"))
async def show_products_in_category(cb: types.CallbackQuery):
    cat_id = int(cb.data.split('_')[2])
    products = get_all_products(cat_id)
    category_name = get_category_name(cat_id)
    currency = get_setting('currency_symbol')
    is_admin = cb.from_user.id == ADMIN_ID

    if not products:
        await cb.message.edit_text(f"📦 *قسم: {category_name}*\n\nلا توجد منتجات في هذا القسم حالياً.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ رجوع للأقسام", callback_data="show_categories")))
        await cb.answer()
        return

    text = f"📦 *قسم: {category_name}* ({len(products)} منتج)\n\n"
    kb = InlineKeyboardMarkup(row_width=1)

    for pid, data in products.items():
        admin_info = f"(ID: {pid}) " if is_admin else ""
        text += f"• **{admin_info}{data['name']}**\n   السعر: {data['price']} {currency}\n"
        kb.add(InlineKeyboardButton(f"شراء {data['name']} ({data['price']} {currency})", callback_data=f"buy_{pid}"))

    kb.add(InlineKeyboardButton("⬅️ رجوع للأقسام", callback_data="show_categories"))
    kb.add(InlineKeyboardButton("القائمة الرئيسية 🏠", callback_data="user_main_menu"))
    
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await cb.answer()

# ------------ Run Bot ------------
if __name__ == '__main__':
    init_db() 
    executor.start_polling(dp, skip_updates=True)

