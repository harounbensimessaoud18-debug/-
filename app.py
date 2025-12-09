[file name]: app.py
[file content begin]
import os
import sys
import telebot
from telebot import types
import requests
import time
import threading
import subprocess
import psutil
import re
import logging
import sqlite3
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from flask import Flask


app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 البوت شغال 😇🚀"

@app.route('/health')
def health_check():
    return "✅ Bot is healthy and running", 200

@app.route('/ping')
def ping():
    return "pong", 200

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

bot_scripts = defaultdict(lambda: {
    'process': None,
    'log_file': None,
    'script_name': None,
    'log_path': None,
    'uploader': '',
    'paused': False,  # حالة جديدة لتتبع إذا كان البوت متوقف
    'script_path': None,  # مسار الملف للتشغيل مرة أخرى
    'file_type': None  # نوع الملف: python أو php
})
user_files = {}
lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=20)

BOT_TOKEN = "8516967656:AAGK-pyJr4vd6hbkci3pHbMp0k-OrvNxdTQ"
ADMIN_IDS = [7090080089, 8267319664]
YOUR_USERNAME = "@harounben13 "
bot = telebot.TeleBot(BOT_TOKEN)
banned_users = set()
user_chats = {}
active_chats = {}


REFERRAL_LIMIT_INCREASE = 1
DEFAULT_UPLOAD_LIMIT = 1


conn = sqlite3.connect('referral.db', check_same_thread=False)
c = conn.cursor()


c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT, upload_limit INTEGER DEFAULT 1, referrals_count INTEGER DEFAULT 0)''')

c.execute('''CREATE TABLE IF NOT EXISTS referrals
             (referral_id TEXT, referrer_id INTEGER, referee_id INTEGER, used INTEGER DEFAULT 0,
             UNIQUE(referee_id))''')

c.execute('''CREATE TABLE IF NOT EXISTS uploaded_files
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              file_name TEXT,
              upload_date TEXT,
              status TEXT DEFAULT 'active',
              original_file_name TEXT,
              file_type TEXT DEFAULT 'python')''')  # إضافة نوع الملف

c.execute('''CREATE TABLE IF NOT EXISTS subscription_channels
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              channel_username TEXT,
              channel_id TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS admins
             (user_id INTEGER PRIMARY KEY,
              username TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS banned_users
             (user_id INTEGER PRIMARY KEY, username TEXT)''')

conn.commit()


def is_admin(user_id):
    with lock:
        c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return user_id in ADMIN_IDS or c.fetchone() is not None

def add_admin(user_id, username):
    with lock:
        c.execute("INSERT OR REPLACE INTO admins (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()

def remove_admin(user_id):
    with lock:
        c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()

def get_admins():
    with lock:
        c.execute("SELECT user_id, username FROM admins")
        return c.fetchall()

def get_upload_limit(user_id):
    with lock:
        c.execute("SELECT upload_limit FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        return result[0] if result else DEFAULT_UPLOAD_LIMIT

def generate_referral_link(user_id):
    return f"https://t.me/{bot.get_me().username}?start=ref_{user_id}"

def process_referral(start_param, referee_id):
    try:
        if not start_param.startswith('ref_'):
            return False

        try:
            referrer_id = int(start_param.split('_')[1])
        except (IndexError, ValueError):
            return False

        if referee_id == referrer_id:
            bot.send_message(referee_id, "❌ لا يمكنك استخدام رابط الإحالة الخاص بك!")
            return False

        with lock:
            c.execute("SELECT 1 FROM referrals WHERE referee_id = ?", (referee_id,))
            if c.fetchone():
                bot.send_message(referee_id, "⚠️ لقد استخدمت رابط إحالة سابقاً!")
                return False

            c.execute("SELECT 1 FROM users WHERE user_id = ?", (referrer_id,))
            if not c.fetchone():
                bot.send_message(referee_id, "❌ المستخدم المحيل غير موجود!")
                return False

            c.execute("INSERT INTO referrals (referral_id, referrer_id, referee_id, used) VALUES (?, ?, ?, 1)",
                     (start_param, referrer_id, referee_id))

            c.execute("UPDATE users SET referrals_count = referrals_count + 1, upload_limit = upload_limit + ? WHERE user_id = ?",
                     (REFERRAL_LIMIT_INCREASE, referrer_id))

            c.execute("SELECT upload_limit FROM users WHERE user_id = ?", (referrer_id,))
            result = c.fetchone()
            new_limit = result[0] if result else DEFAULT_UPLOAD_LIMIT

            conn.commit()

            try:
                bot.send_message(
                    referrer_id,
                    f"🎉 تمت إحالة مستخدم جديد!\n📈 تم زيادة حد الرفع الخاص بك إلى {new_limit}"
                )
            except:
                pass

            return True

    except sqlite3.IntegrityError:
        bot.send_message(referee_id, "⚠️ لقد استخدمت رابط إحالة سابقاً!")
        return False
    except Exception as e:
        logging.error(f"Error in referral processing: {e}")
        return False

def get_code_preview(file_path, lines=200):
    try:
        preview_lines = []
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f):
                if i >= lines:
                    break
                preview_lines.append(line)
        return ''.join(preview_lines)
    except Exception as e:
        logging.error(f"Error getting code preview: {e}")
        return "❌ تعذر قراءة الملف"


def get_subscription_channels():
    with lock:
        c.execute("SELECT channel_username, channel_id FROM subscription_channels")
        return c.fetchall()

def add_subscription_channel(channel_username, channel_id):
    with lock:
        c.execute("INSERT INTO subscription_channels (channel_username, channel_id) VALUES (?, ?)",
                 (channel_username, channel_id))
        conn.commit()

def remove_subscription_channel(channel_id):
    with lock:
        c.execute("DELETE FROM subscription_channels WHERE channel_id = ?", (channel_id,))
        conn.commit()

def check_subscription(user_id):
    try:
        channels = get_subscription_channels()

        if not channels:
            return True

        for channel_username, channel_id in channels:
            if channel_id:
                member_status = bot.get_chat_member(channel_id, user_id).status
                if member_status not in ['member', 'administrator', 'creator']:
                    return False
            elif channel_username:
                try:
                    chat = bot.get_chat(f"@{channel_username}")
                    member_status = bot.get_chat_member(chat.id, user_id).status
                    if member_status not in ['member', 'administrator', 'creator']:
                        return False
                except:
                    return False
        return True
    except Exception as e:
        logging.error(f"Error checking subscription: {e}")
        return False

def subscription_required(func):
    def wrapper(message):
        user_id = message.from_user.id

        if not check_subscription(user_id):
            channels = get_subscription_channels()
            if channels:
                markup = types.InlineKeyboardMarkup()
                for channel_username, channel_id in channels:
                    if channel_username:
                        channel_url = f"https://t.me/{channel_username}"
                    else:
                        try:
                            chat = bot.get_chat(channel_id)
                            if chat.username:
                                channel_url = f"https://t.me/{chat.username}"
                            else:
                                channel_url = f"https://t.me/c/{str(channel_id)[4:]}"
                        except:
                            channel_url = f"https://t.me/c/{str(channel_id)[4:]}"

                    channel_button = types.InlineKeyboardButton(f"الاشتراك في القناة 📢", url=channel_url)
                    markup.add(channel_button)

                check_button = types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data='check_subscription')
                markup.add(check_button)

                bot.send_message(
                    message.chat.id,
                    "طلب بسيط لاستخدام البوت: يجب الاشتراك في القنوات التالية 👇😄😉:\n\n"
                    "بعد الاشتراك، اضغط على زر التحقق أو اضغط /start",
                    reply_markup=markup
                )
            else:
                bot.send_message(message.chat.id, "❌ لم يتم تعيين قنوات اشتراك إجبارية. يرجى التواصل مع الأدمن.")
            return
        return func(message)
    return wrapper


def admin_control_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)

    broadcast_text = types.InlineKeyboardButton("📢 إذاعة نصية", callback_data='broadcast_text')
    broadcast_media = types.InlineKeyboardButton("🖼 إذاعة بالوسائط", callback_data='broadcast_media')
    user_stats = types.InlineKeyboardButton("📊 إحصائيات المستخدمين", callback_data='user_stats')
    ban_user = types.InlineKeyboardButton("⛔ حظر مستخدم", callback_data='ban_user')
    unban_user = types.InlineKeyboardButton("✅ فك حظر", callback_data='unban_user')
    set_limit = types.InlineKeyboardButton("🔄 تعديل الحدود", callback_data='set_limit')
    reset_limits = types.InlineKeyboardButton("🔄 تصفير الحدود", callback_data='reset_limits')
    add_channel = types.InlineKeyboardButton("📢 إضافة قناة اشتراك", callback_data='add_channel')
    remove_channel = types.InlineKeyboardButton("❌ إزالة قناة اشتراك", callback_data='remove_channel')
    list_channels = types.InlineKeyboardButton("📡 عرض القنوات الحالية", callback_data='list_channels')
    view_scripts = types.InlineKeyboardButton("📂 عرض البوتات النشطة", callback_data='view_scripts')
    add_admin_btn = types.InlineKeyboardButton("➕ إضافة أدمن", callback_data='add_admin')
    remove_admin_btn = types.InlineKeyboardButton("➖ إزالة أدمن", callback_data='remove_admin')
    list_admins_btn = types.InlineKeyboardButton("👥 عرض الأدمن", callback_data='list_admins')

    markup.add(broadcast_text, broadcast_media)
    markup.add(user_stats, ban_user, unban_user)
    markup.add(set_limit, reset_limits)
    markup.add(add_channel, remove_channel, list_channels)
    markup.add(view_scripts)
    markup.add(add_admin_btn, remove_admin_btn, list_admins_btn)

    return markup


bot.remove_webhook()

uploaded_files_dir = "uploaded_files"
if not os.path.exists(uploaded_files_dir):
    os.makedirs(uploaded_files_dir)

def save_chat_id(chat_id):
    if chat_id not in user_chats:
        user_chats[chat_id] = True

@bot.message_handler(commands=['start'])
def start_handler(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or ""

        if not check_subscription(user_id):
            channels = get_subscription_channels()
            if channels:
                markup = types.InlineKeyboardMarkup()
                for channel_username, channel_id in channels:
                    if channel_username:
                        channel_url = f"https://t.me/{channel_username}"
                    else:
                        try:
                            chat = bot.get_chat(channel_id)
                            if chat.username:
                                channel_url = f"https://t.me/{chat.username}"
                            else:
                                channel_url = f"https://t.me/c/{str(channel_id)[4:]}"
                        except:
                            channel_url = f"https://t.me/c/{str(channel_id)[4:]}"

                    channel_button = types.InlineKeyboardButton(f"الاشتراك في القناة 📢", url=channel_url)
                    markup.add(channel_button)

                check_button = types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data='check_subscription')
                markup.add(check_button)

                bot.send_message(
                    message.chat.id,
                    "طلب بسيط لاستخدام البوت: يجب الاشتراك في القنوات التالية 👇😄😉:\n\n"
                    "بعد الاشتراك، اضغط على زر التحقق أو اضغط /start",
                    reply_markup=markup
                )
            else:
                bot.send_message(message.chat.id, "❌ لم يتم تعيين قنوات اشتراك إجبارية. يرجى التواصل مع الأدمن.")
            return

        referral_processed = False
        if len(message.text.split()) > 1:
            start_param = message.text.split()[1]
            if start_param.startswith('ref_'):
                referral_processed = process_referral(start_param, user_id)

        with lock:
            c.execute("INSERT OR IGNORE INTO users (user_id, username, join_date) VALUES (?, ?, ?)",
                     (user_id, username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()

        start(message, referral_processed)
    except Exception as e:
        logging.error(f"Error in start handler: {e}")
        bot.send_message(message.chat.id, "❌ حدث خطأ أثناء معالجة طلبك. يرجى المحاولة لاحقاً.")

def start(message, referral_processed=False):
    save_chat_id(message.chat.id)

    with lock:
        c.execute("SELECT username FROM banned_users WHERE user_id = ?", (message.from_user.id,))
        if c.fetchone() or message.from_user.username in banned_users:
            bot.send_message(message.chat.id, "⁉️ تم حظرك من البوت. تواصل مع المطور @TT_1_TT")
            return

    user_id = message.from_user.id
    username = message.from_user.username or ""

    with lock:
        c.execute("SELECT upload_limit FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        upload_limit = result[0] if result else DEFAULT_UPLOAD_LIMIT

    if user_id not in bot_scripts:
        bot_scripts[user_id] = {
            'process': None,
            'log_file': None,
            'script_name': None,
            'log_path': None,
            'uploader': username,
            'paused': False,
            'script_path': None,
            'file_type': None
        }

    markup = types.InlineKeyboardMarkup()
    upload_button = types.InlineKeyboardButton("📁 - رفع ملف", callback_data='upload')
    stop_all_button = types.InlineKeyboardButton("🛑 - ايقاف جميع بوتاتي النشطة", callback_data='stop_all_bots')
    
    # زر الإيقاف/التشغيل الجديد
    stop_resume_button = types.InlineKeyboardButton("⏸️/▶️ - إيقاف/تشغيل البوت", callback_data='stop_resume_bot')
    
    developer_button = types.InlineKeyboardButton("📡 - قناة المطور", url='https://t.me/harouninternet')
    speed_button = types.InlineKeyboardButton("⚡ - سرعة البوت", callback_data='speed')
    commands_button = types.InlineKeyboardButton("📘 - حول البوت", callback_data='commands')
    contact_button = types.InlineKeyboardButton('💬 - الدعم الفني', url=f'https://t.me/harounben13')
    download_button = types.InlineKeyboardButton("🛠 - تثبيت مكتبة", callback_data='download_lib')
    referral_button = types.InlineKeyboardButton("🎯 - زيادة حد الرفع", callback_data='get_referral')

    if is_admin(message.from_user.id):
        control_button = types.InlineKeyboardButton("⚙️ - لوحة التحكم", callback_data='admin_control')
        markup.add(control_button)

    markup.add(upload_button)
    markup.add(stop_all_button)
    markup.add(stop_resume_button)  # إضافة الزر الجديد
    markup.add(speed_button, developer_button)
    markup.add(contact_button, commands_button)
    markup.add(download_button)
    markup.add(referral_button)

    referral_message = ""
    if referral_processed:
        referral_message = "\n\n🎉 تمت معالجة رابط الإحالة بنجاح! تم زيادة حد الرفع للمستخدم الذي أحالك."

    bot.send_message(
        message.chat.id,
        f"⚙️ مرحباً بك {message.from_user.first_name} في بوت رفع وتشغيل ملفات بايثون و PHP!\n\n"
        f"📊 الحد الحالي للرفع: {upload_limit} ملف\n"
        f"{referral_message}\n\n"
        "✨ الميزات المتاحة:\n"
        "• تشغيل ملفات Python و PHP على سيرفر خاص وآمن\n"
        "• عرض النتائج مباشرة بعد التنفيذ\n"
        "• سهولة في رفع وتشغيل الملفات\n"
        "• تواصل مباشر مع المطور لأي استفسار\n\n"
        "👇 اختر من الأزرار أدناه للبدء:",
        reply_markup=markup
    )


def send_script_log(user_id, script_name, log_file_path):
    try:
        if not os.path.exists(log_file_path):
            bot.send_message(user_id, f"❌ لا يوجد ملف سجل لـ {script_name}.")
            return

        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as log_file:
            full_content = log_file.read()

            if not full_content:
                bot.send_message(user_id, f"📄 سجلات {script_name} فارغة حالياً.")
                return

            if len(full_content) > 3000:
                parts = [full_content[i:i+3000] for i in range(0, len(full_content), 3000)]
                for i, part in enumerate(parts):
                    bot.send_message(
                        user_id,
                        f"📄 **سجلات {script_name} (الجزء {i+1}/{len(parts)})**\n\n"
                        f"```\n{part}\n```",
                        parse_mode='Markdown'
                    )
            else:
                bot.send_message(
                    user_id,
                    f"📄 **سجلات {script_name}**\n\n"
                    f"```\n{full_content}\n```",
                    parse_mode='Markdown'
                )
    except Exception as e:
        logging.error(f"Error sending script log to user {user_id}: {e}")
        bot.send_message(user_id, f"❌ حدث خطأ أثناء قراءة سجلات {script_name}: {e}")


def install_and_run_uploaded_file(script_path, user_id, original_file_name):
    try:
        # تحديد نوع الملف
        if original_file_name.endswith('.py'):
            file_type = 'python'
        elif original_file_name.endswith('.php'):
            file_type = 'php'
        else:
            file_type = 'unknown'
        
        current_script_info = bot_scripts.get(user_id)
        if current_script_info and current_script_info.get('process') and \
           psutil.pid_exists(current_script_info['process'].pid):
            stop_bot(user_id)
            bot.send_message(user_id, f"⚠️ تم إيقاف الملف السابق قبل تشغيل الملف الجديد.")

        user_script_dir = os.path.dirname(script_path)
        if not os.path.exists(user_script_dir):
            os.makedirs(user_script_dir)

        log_file_path = os.path.join(user_script_dir, f"{original_file_name}.log")

        # تثبيت المكتبات لملفات Python فقط
        if file_type == 'python':
            requirements_path = os.path.join(user_script_dir, "requirements.txt")
            if os.path.exists(requirements_path):
                bot.send_message(user_id, f"🛠 جاري تثبيت المكتبات من requirements.txt لـ {original_file_name}...")
                req_log_path = os.path.join(user_script_dir, f"{original_file_name}_requirements.log")
                try:
                    with open(req_log_path, "w") as req_log:
                        process = subprocess.run(
                            [sys.executable, '-m', 'pip', 'install', '-r', requirements_path],
                            stdout=req_log,
                            stderr=req_log,
                            timeout=300
                        )
                    if process.returncode == 0:
                        bot.send_message(user_id, f"✅ تم تثبيت المكتبات لـ {original_file_name}.")
                    else:
                        bot.send_message(user_id, f"⚠️ حدثت مشاكل أثناء تثبيت بعض المكتبات لـ {original_file_name}. قد يعمل البوت بشكل جزئي.")
                except subprocess.TimeoutExpired:
                    bot.send_message(user_id, f"⏰ انتهت المهلة أثناء تثبيت مكتبات {original_file_name}. قد لا تعمل بعض الوظائف.")
                except Exception as e:
                    bot.send_message(user_id, f"⚠️ فشل في تثبيت مكتبات {original_file_name}: {str(e)}")

        log_file = open(log_file_path, "w")
        
        # تشغيل الملف بناءً على نوعه
        if file_type == 'python':
            p = subprocess.Popen(
                [sys.executable, script_path],
                stdout=log_file,
                stderr=log_file
            )
        elif file_type == 'php':
            # تشغيل ملف PHP
            p = subprocess.Popen(
                ['php', script_path],
                stdout=log_file,
                stderr=log_file
            )
        else:
            bot.send_message(user_id, f"❌ نوع الملف غير مدعوم: {original_file_name}")
            return

        with lock:
            bot_scripts[user_id] = {
                'process': p,
                'log_file': log_file,
                'script_name': original_file_name,
                'log_path': log_file_path,
                'uploader': bot_scripts[user_id].get('uploader', ''),
                'paused': False,
                'script_path': script_path,
                'file_type': file_type
            }

        bot.send_message(user_id, f"✅ تم تشغيل {original_file_name} بنجاح. يمكنك عرض السجلات باستخدام الزر.")
    except Exception as e:
        logging.error(f"Error running script for user {user_id}: {e}")
        bot.send_message(user_id, f"❌ حدث خطأ أثناء تشغيل الملف: {e}")

def stop_bot(user_id, delete=False):
    try:
        script_info = bot_scripts.get(user_id)
        if not script_info or not script_info.get('script_name'):
            return "❌ لا يوجد ملف نشط لإيقافه"

        script_name = script_info['script_name']
        user_script_dir = os.path.join(uploaded_files_dir, str(user_id))
        script_path = os.path.join(user_script_dir, script_name)
        log_file_path = script_info.get('log_path')

        if script_info.get('process') and psutil.pid_exists(script_info['process'].pid):
            parent = psutil.Process(script_info['process'].pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()

            if script_info.get('log_file'):
                script_info['log_file'].close()

            with lock:
                bot_scripts[user_id] = {
                    'process': None,
                    'log_file': None,
                    'script_name': None if delete else script_name,
                    'log_path': None if delete else log_file_path,
                    'uploader': script_info.get('uploader', ''),
                    'paused': False,
                    'script_path': None if delete else script_path,
                    'file_type': script_info.get('file_type')
                }

            if delete:
                if os.path.exists(script_path):
                    os.remove(script_path)
                if log_file_path and os.path.exists(log_file_path):
                    os.remove(log_file_path)

                # حذف ملفات السجلات الإضافية لملفات Python فقط
                if script_info.get('file_type') == 'python':
                    req_log_path = os.path.join(user_script_dir, f"{script_name}_requirements.log")
                    if os.path.exists(req_log_path):
                        os.remove(req_log_path)

                if os.path.exists(user_script_dir) and not os.listdir(user_script_dir):
                    os.rmdir(user_script_dir)

                with lock:
                    c.execute("UPDATE uploaded_files SET status = 'deleted' WHERE user_id = ? AND original_file_name = ?", (user_id, script_name))
                    conn.commit()
                return f"✅ تم حذف {script_name} من الاستضافة"
            else:
                return f"✅ تم إيقاف {script_name} بنجاح"
        else:
            return f"⚠️ عملية {script_name} غير موجودة أو أنها قد توقفت بالفعل"
    except psutil.NoSuchProcess:
        return f"⚠️ عملية {script_name} غير موجودة."
    except Exception as e:
        logging.error(f"Error stopping bot for user {user_id}: {e}")
        return f"❌ حدث خطأ أثناء إيقاف {script_name}: {e}"

# دالة جديدة: إيقاف/تشغيل البوت
def stop_resume_bot(user_id):
    try:
        script_info = bot_scripts.get(user_id)
        if not script_info or not script_info.get('script_name'):
            return "❌ لا يوجد بوت نشط لإيقافه أو تشغيله", None

        script_name = script_info['script_name']
        script_path = script_info.get('script_path')
        file_type = script_info.get('file_type', 'python')
        
        if script_info.get('paused', False):
            # إعادة تشغيل البوت
            if not script_path or not os.path.exists(script_path):
                return "❌ لا يمكن إعادة تشغيل البوت: الملف غير موجود", None
            
            log_file_path = script_info.get('log_path')
            user_script_dir = os.path.dirname(script_path)
            
            # فتح ملف السجل للإلحاق
            if log_file_path:
                try:
                    log_file = open(log_file_path, "a")
                except:
                    log_file = open(log_file_path, "w")
            else:
                log_file_path = os.path.join(user_script_dir, f"{script_name}.log")
                log_file = open(log_file_path, "w")
            
            # تشغيل العملية من جديد بناءً على نوع الملف
            if file_type == 'python':
                p = subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=log_file,
                    stderr=log_file
                )
            elif file_type == 'php':
                p = subprocess.Popen(
                    ['php', script_path],
                    stdout=log_file,
                    stderr=log_file
                )
            else:
                return f"❌ نوع الملف غير مدعوم: {file_type}", None
            
            with lock:
                bot_scripts[user_id] = {
                    'process': p,
                    'log_file': log_file,
                    'script_name': script_name,
                    'log_path': log_file_path,
                    'uploader': script_info.get('uploader', ''),
                    'paused': False,
                    'script_path': script_path,
                    'file_type': file_type
                }
            
            return f"✅ تم تشغيل {script_name} بنجاح", False
            
        else:
            # إيقاف البوت مؤقتًا
            if script_info.get('process') and psutil.pid_exists(script_info['process'].pid):
                parent = psutil.Process(script_info['process'].pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()

                if script_info.get('log_file'):
                    script_info['log_file'].close()

                with lock:
                    bot_scripts[user_id] = {
                        'process': None,
                        'log_file': None,
                        'script_name': script_name,
                        'log_path': script_info.get('log_path'),
                        'uploader': script_info.get('uploader', ''),
                        'paused': True,
                        'script_path': script_path,
                        'file_type': file_type
                    }
                
                return f"✅ تم إيقاف {script_name} مؤقتاً", True
            else:
                return f"⚠️ البوت {script_name} غير نشط حالياً", None
                
    except Exception as e:
        logging.error(f"Error in stop_resume_bot for user {user_id}: {e}")
        return f"❌ حدث خطأ: {e}", None


def get_bot_username(script_path, file_type='python'):
    try:
        if file_type == 'python':
            token_value = ""
            username_value = ""
            with open(script_path, 'r', encoding='utf-8', errors='ignore') as file:
                for line in file:
                    if "TOKEN" in line and not token_value:
                        token_match = re.search(r'[\'"]([^\'"]*)[\'"]', line)
                        if token_match:
                            token_value = token_match.group(1)
                    if "BOT_USERNAME" in line and not username_value:
                        username_match = re.search(r'[\'"]([^\'"]*)[\'"]', line)
                        if username_match:
                            username_value = username_match.group(1)
                    if token_value and username_value:
                        break

            if username_value:
                return f"@{username_value}"
            elif token_value:
                return "معرف البوت (تم العثور على توكن)"
            return "تعذر الحصول على معرف البوت"
        elif file_type == 'php':
            # محاولة استخراج معلومات من ملف PHP
            bot_token = ""
            bot_username = ""
            with open(script_path, 'r', encoding='utf-8', errors='ignore') as file:
                content = file.read()
                
                # البحث عن التوكن في ملف PHP
                token_patterns = [
                    r'\$botToken\s*=\s*["\']([^"\']+)["\']',
                    r'define\s*\(\s*["\']BOT_TOKEN["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
                    r'["\']token["\']\s*=>\s*["\']([^"\']+)["\']'
                ]
                
                for pattern in token_patterns:
                    match = re.search(pattern, content)
                    if match:
                        bot_token = match.group(1)
                        break
                
                # البحث عن اسم المستخدم في ملف PHP
                username_patterns = [
                    r'\$botUsername\s*=\s*["\']([^"\']+)["\']',
                    r'define\s*\(\s*["\']BOT_USERNAME["\']\s*,\s*["\']([^"\']+)["\']\s*\)'
                ]
                
                for pattern in username_patterns:
                    match = re.search(pattern, content)
                    if match:
                        bot_username = match.group(1)
                        break
            
            if bot_username:
                return f"@{bot_username}"
            elif bot_token:
                return "معرف البوت (تم العثور على توكن)"
            return "ملف PHP - تعذر الحصول على معرف البوت"
        else:
            return "نوع ملف غير معروف"
    except Exception as e:
        logging.error(f"Error getting bot username from script file {script_path}: {e}")
        return "تعذر الحصول على معرف البوت"

@bot.message_handler(content_types=['document'])
def handle_file(message):
    try:
        user_id = message.from_user.id

        if not check_subscription(user_id):
            channels = get_subscription_channels()
            if channels:
                markup = types.InlineKeyboardMarkup()
                for channel_username, channel_id in channels:
                    if channel_username:
                        channel_url = f"https://t.me/{channel_username}"
                    else:
                        try:
                            chat = bot.get_chat(channel_id)
                            if chat.username:
                                channel_url = f"https://t.me/{chat.username}"
                            else:
                                channel_url = f"https://t.me/c/{str(channel_id)[4:]}"
                        except:
                            channel_url = f"https://t.me/c/{str(channel_id)[4:]}")

                    channel_button = types.InlineKeyboardButton(f"الاشتراك في القناة 📢", url=channel_url)
                    markup.add(channel_button)

                check_button = types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data='check_subscription')
                markup.add(check_button)

                bot.send_message(
                    message.chat.id,
                    "طلب بسيط إشترك في القنوات لاستخدام البوت 👇😄😉 :\n\n"
                    "بعد الاشتراك، اضغط على زر التحقق أو /start ",
                    reply_markup=markup
                )
            else:
                bot.send_message(message.chat.id, "❌ لم يتم تعيين قنوات اشتراك إجبارية. يرجى التواصل مع الأدمن.")
            return

        handle_file_upload(message)
    except Exception as e:
        logging.error(f"Error in file handler for user {message.from_user.id}: {e}")
        bot.reply_to(message, f"❌ حدث خطأ أثناء معالجة الملف: {str(e)}")

def handle_file_upload(message):
    user_id = message.from_user.id

    with lock:
        c.execute("SELECT username FROM banned_users WHERE user_id = ?", (user_id,))
        if c.fetchone() or message.from_user.username in banned_users:
            bot.send_message(message.chat.id, "⁉️ تم حظرك من البوت. تواصل مع المطور @TT_1_TT")
            return

    if message.document.file_size > 20 * 1024 * 1024:
        bot.reply_to(message, "❌ حجم الملف كبير جداً! الحد الأقصى المسموح به هو 20MB")
        return

    current_limit = get_upload_limit(user_id)
    with lock:
        c.execute("SELECT COUNT(*) FROM uploaded_files WHERE user_id = ? AND status = 'active'", (user_id,))
        result = c.fetchone()
        active_files = result[0] if result else 0

    if active_files >= current_limit:
        bot.reply_to(message, f"❌ لقد وصلت إلى حد الرفع الحالي ({current_limit})\n"
                             f"يمكنك زيادة الحد عن طريق دعوة مستخدمين جدد")
        return

    file_id = message.document.file_id
    file_info = bot.get_file(file_id)
    original_file_name = message.document.file_name

    # قبول ملفات Python و PHP
    if not (original_file_name.endswith('.py') or original_file_name.endswith('.php')):
        bot.reply_to(message, " ❌ هذا بوت خاص برفع ملفات بايثون و PHP فقط.")
        return

    # تحديد نوع الملف
    file_type = 'python' if original_file_name.endswith('.py') else 'php'

    user_uploaded_dir = os.path.join(uploaded_files_dir, str(user_id))
    if not os.path.exists(user_uploaded_dir):
        os.makedirs(user_uploaded_dir)

    script_path = os.path.join(user_uploaded_dir, original_file_name)
    download_message = bot.send_message(message.chat.id, f"⏬ جاري تنزيل الملف: 0%")

    with open(script_path, 'wb') as new_file:
        response = requests.get(f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}', stream=True)
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        chunk_size = 1024 * 1024

        for data in response.iter_content(chunk_size=chunk_size):
            downloaded += len(data)
            new_file.write(data)
            progress = int(100 * downloaded / total_size)
            if progress % 10 == 0 or downloaded == total_size:
                try:
                    bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=download_message.message_id,
                        text=f"⏬ جاري تنزيل الملف: {progress}%"
                    )
                except Exception as e:
                    logging.warning(f"Failed to edit download message for user {user_id}: {e}")
                    pass

    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=download_message.message_id,
        text=f"✅ تم تنزيل الملف بنجاح: {original_file_name}"
    )

    send_for_approval(user_id, script_path, original_file_name, message, file_type)

    with lock:
        c.execute("INSERT INTO uploaded_files (user_id, file_name, upload_date, original_file_name, file_type) VALUES (?, ?, ?, ?, ?)",
                 (user_id, script_path, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), original_file_name, file_type))
        conn.commit()

def send_for_approval(user_id, file_path, original_file_name, message, file_type):
    try:
        admins = get_admins()
        admin_ids_from_db = [admin[0] for admin in admins]
        all_admin_ids = list(set(ADMIN_IDS + admin_ids_from_db))

        for admin_id in all_admin_ids:
            try:
                with open(file_path, 'rb') as file:
                    bot.send_document(
                        admin_id,
                        file,
                        caption=f"📤 ملف جديد من @{message.from_user.username or 'بدون يوزر'} (ID: {user_id})\n"
                                f"📝 اسم الملف: {original_file_name}\n"
                                f"📁 نوع الملف: {file_type.upper()}"
                    )

                try:
                    code_preview = get_code_preview(file_path)
                    if len(code_preview) > 4000:
                        code_preview = code_preview[:4000] + "\n... (تم اقتطاع الجزء الزائد)"

                    bot.send_message(
                        admin_id,
                        f"📄 معاينة الكود (200 سطر):\n```{file_type}\n{code_preview}\n```",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logging.error(f"Error sending preview to admin {admin_id}: {e}")
                    bot.send_message(admin_id, "❌ تعذر إرسال معاينة الكود")

                markup = types.InlineKeyboardMarkup()
                approve_button = types.InlineKeyboardButton(
                    "✅ موافقة",
                    callback_data=f'approve_{user_id}_{original_file_name}_{file_type}'
                )
                reject_button = types.InlineKeyboardButton(
                    "❌ رفض",
                    callback_data=f'reject_{user_id}_{original_file_name}_{file_type}'
                )
                markup.add(approve_button, reject_button)

                bot.send_message(
                    admin_id,
                    "اختر الإجراء:",
                    reply_markup=markup
                )
            except Exception as e:
                logging.error(f"Error sending to admin {admin_id}: {e}")

        bot.reply_to(
            message,
            f"📤 تم إرسال ملفك ({file_type.upper()}) إلى الأدمن للمراجعة والموافقة. سيتم إعلامك بالنتيجة قريباً."
        )

    except Exception as e:
        logging.error(f"Error in approval process for user {user_id}: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء معالجة الملف")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_')))
def handle_approval(call):
    try:
        data_parts = call.data.split('_')
        action = data_parts[0]
        user_id = int(data_parts[1])
        original_file_name = '_'.join(data_parts[2:-1])  # استخراج اسم الملف
        file_type = data_parts[-1]  # استخراج نوع الملف

        user_script_dir = os.path.join(uploaded_files_dir, str(user_id))
        file_path = os.path.join(user_script_dir, original_file_name)

        if action == 'approve':
            install_and_run_uploaded_file(file_path, user_id, original_file_name)
            bot_username = get_bot_username(file_path, file_type)

            markup = types.InlineKeyboardMarkup()
            stop_button = types.InlineKeyboardButton(f"🔴 إيقاف", callback_data=f'stop_{user_id}_{original_file_name}_{file_type}')
            delete_button = types.InlineKeyboardButton(f"🗑 حذف", callback_data=f'delete_{user_id}_{original_file_name}_{file_type}')
            view_logs_button = types.InlineKeyboardButton(f"📄 عرض السجلات", callback_data=f'viewlog_{user_id}_{original_file_name}_{file_type}')
            markup.row(stop_button, delete_button)
            markup.row(view_logs_button)

            bot.send_message(
                user_id,
                f"✅ تمت الموافقة على ملفك!\n\n"
                f"تم رفع ملف بوتك بنجاح ✅\n\n"
                f"📄 إسم الملف: {original_file_name}\n"
                f"📁 نوع الملف: {file_type.upper()}\n"
                f"🤖 معرف البوت: {bot_username}\n"
                f"📊 يمكنك عرض سجلات التشغيل بالضغط على زر 'عرض السجلات'\n\n"
                f"يمكنك إيقاف أو حذف البوت باستخدام الأزرار أدناه:",
                reply_markup=markup
            )
            bot.answer_callback_query(call.id, "✅ تمت الموافقة على الملف!")

            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✅ تم الموافقة على ملف {original_file_name} ({file_type.upper()}) للمستخدم {user_id}",
                reply_markup=None
            )

        elif action == 'reject':
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)

                user_script_dir = os.path.dirname(file_path)
                if os.path.exists(user_script_dir) and not os.listdir(user_script_dir):
                    os.rmdir(user_script_dir)

                with lock:
                    c.execute("UPDATE uploaded_files SET status = 'rejected' WHERE user_id = ? AND original_file_name = ?", (user_id, original_file_name))
                    conn.commit()

            except Exception as e:
                logging.error(f"Error deleting rejected file {file_path}: {e}")
                pass

            bot.send_message(user_id, "❌ تم رفض ملفك من قبل الأدمن.")
            bot.answer_callback_query(call.id, "❌ تم رفض الملف!")
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"❌ تم رفض ملف {original_file_name} ({file_type.upper()}) للمستخدم {user_id}",
                reply_markup=None
            )

    except Exception as e:
        logging.error(f"Error handling approval callback {call.data}: {e}")
        bot.answer_callback_query(call.id, "❌ حدث خطأ في المعالجة")


@bot.callback_query_handler(func=lambda call: call.data == 'admin_control')
def show_admin_control(call):
    if is_admin(call.from_user.id):
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🛠 لوحة تحكم الأدمن",
            reply_markup=admin_control_panel()
        )
    else:
        bot.answer_callback_query(call.id, "❌ ليس لديك صلاحية الوصول!")

@bot.callback_query_handler(func=lambda call: call.data in [
    'broadcast_text', 'broadcast_media', 'user_stats',
    'ban_user', 'unban_user', 'set_limit', 'reset_limits',
    'add_channel', 'remove_channel', 'list_channels', 'view_scripts',
    'add_admin', 'remove_admin', 'list_admins'
])
def handle_admin_actions(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ ليس لديك صلاحية الوصول!")
        return

    if call.data == 'broadcast_text':
        bot.send_message(call.message.chat.id, "أرسل النص الذي تريد إذاعته:")
        bot.register_next_step_handler(call.message, process_broadcast_text)

    elif call.data == 'broadcast_media':
        bot.send_message(call.message.chat.id, "أرسل الصورة/الملف الذي تريد إذاعته:")
        bot.register_next_step_handler(call.message, process_broadcast_media)

    elif call.data == 'user_stats':
        with lock:
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM referrals WHERE used = 1")
            total_referrals = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM uploaded_files WHERE status = 'active'")
            active_bots = c.fetchone()[0]
            # إحصائيات حسب نوع الملف
            c.execute("SELECT COUNT(*), file_type FROM uploaded_files WHERE status = 'active' GROUP BY file_type")
            file_type_stats = c.fetchall()

        stats_message = f"📊 إحصائيات المستخدمين:\n" \
                       f"- إجمالي المستخدمين: {total_users}\n" \
                       f"- إجمالي الإحالات: {total_referrals}\n" \
                       f"- عدد البوتات النشطة: {active_bots}\n\n" \
                       f"📁 إحصائيات حسب نوع الملف:\n"
        
        for count, ftype in file_type_stats:
            stats_message += f"- {ftype.upper()}: {count}\n"

        bot.send_message(call.message.chat.id, stats_message)

    elif call.data == 'ban_user':
        bot.send_message(call.message.chat.id, "أرسل معرف المستخدم الذي تريد حظره (مثال: @username أو user_id):")
        bot.register_next_step_handler(call.message, process_ban_user)

    elif call.data == 'unban_user':
        bot.send_message(call.message.chat.id, "أرسل معرف المستخدم الذي تريد فك حظره (مثال: @username أو user_id):")
        bot.register_next_step_handler(call.message, process_unban_user)

    elif call.data == 'set_limit':
        bot.send_message(call.message.chat.id, "أرسل معرف المستخدم والحد الجديد (مثال: @username 5 أو user_id 5):")
        bot.register_next_step_handler(call.message, process_set_limit)

    elif call.data == 'reset_limits':
        with lock:
            c.execute("UPDATE users SET upload_limit = ?", (DEFAULT_UPLOAD_LIMIT,))
            conn.commit()
        bot.send_message(call.message.chat.id, f"✅ تم تصفير حدود جميع المستخدمين إلى {DEFAULT_UPLOAD_LIMIT}")

    elif call.data == 'add_channel':
        bot.send_message(
            call.message.chat.id,
            "أرسل معرف القناة (يوزرنيم أو ID) لإضافتها كقناة اشتراك إجبارية:\n"
            "مثال: @channel_username\n"
            "أو  -1001234567890"
        )
        bot.register_next_step_handler(call.message, process_add_channel)

    elif call.data == 'remove_channel':
        channels = get_subscription_channels()
        if not channels:
            bot.answer_callback_query(call.id, "❌ لا توجد قنوات مضافة")
            return

        markup = types.InlineKeyboardMarkup()
        for channel_username, channel_id in channels:
            if channel_username:
                display_name = f"@{channel_username}"
            else:
                display_name = f"ID: {channel_id}"
            btn = types.InlineKeyboardButton(display_name, callback_data=f'remove_ch_{channel_id}')
            markup.add(btn)

        bot.send_message(call.message.chat.id, "اختر القناة التي تريد إزالتها:", reply_markup=markup)

    elif call.data == 'list_channels':
        channels = get_subscription_channels()
        if not channels:
            bot.answer_callback_query(call.id, "❌ لا توجد قنوات مضافة")
            return

        channels_list = []
        for i, (channel_username, channel_id) in enumerate(channels, 1):
            if channel_username:
                display_name = f"@{channel_username}"
            else:
                display_name = f"ID: {channel_id}"
            channels_list.append(f"{i}. {display_name}")

        bot.send_message(call.message.chat.id, "📡 القنوات الإجبارية الحالية:\n" + "\n".join(channels_list))

    elif call.data == 'view_scripts':
        active_scripts = []
        with lock:
            for user_id, script_info in bot_scripts.items():
                if script_info.get('script_name') and script_info.get('process') and psutil.pid_exists(script_info['process'].pid):
                    file_type = script_info.get('file_type', 'python')
                    active_scripts.append(
                        f"- {script_info['script_name']} ({file_type.upper()}) بواسطة @{script_info.get('uploader', 'N/A')} (ID: {user_id})"
                    )

        if active_scripts:
            bot.send_message(call.message.chat.id, "📂 البوتات النشطة:\n" + "\n".join(active_scripts))
        else:
            bot.send_message(call.message.chat.id, "⚠️ لا يوجد بوتات نشطة حالياً")

    elif call.data == 'add_admin':
        bot.send_message(call.message.chat.id, "أرسل معرف المستخدم (user_id) لإضافته كأدمن:")
        bot.register_next_step_handler(call.message, process_add_admin)

    elif call.data == 'remove_admin':
        admins = get_admins()
        all_admins_for_removal = list(set(ADMIN_IDS + [admin[0] for admin in admins]))

        if ADMIN_IDS and ADMIN_IDS[0] in all_admins_for_removal:
             all_admins_for_removal.remove(ADMIN_IDS[0])

        if not all_admins_for_removal:
            bot.answer_callback_query(call.id, "❌ لا يوجد أدمن لإزالته (عدا الأدمن الافتراضي).")
            return

        markup = types.InlineKeyboardMarkup()
        for admin_id in all_admins_for_removal:
            try:
                user_info = bot.get_chat(admin_id)
                display_name = f"@{user_info.username}" if user_info.username else f"ID: {admin_id}"
            except Exception:
                display_name = f"ID: {admin_id} (غير معروف)"
            btn = types.InlineKeyboardButton(display_name, callback_data=f'remove_ad_{admin_id}')
            markup.add(btn)

        bot.send_message(call.message.chat.id, "اختر الأدمن الذي تريد إزالته:", reply_markup=markup)

    elif call.data == 'list_admins':
        admins = get_admins()
        hardcoded_admins = list(ADMIN_IDS)
        all_admins = list(set(hardcoded_admins + [admin[0] for admin in admins]))

        if not all_admins:
            bot.answer_callback_query(call.id, "❌ لا يوجد أدمن")
            return

        admins_list = []
        for i, admin_id in enumerate(all_admins, 1):
            try:
                user_info = bot.get_chat(admin_id)
                display_name = f"@{user_info.username}" if user_info.username else f"ID: {admin_id}"
            except Exception:
                display_name = f"ID: {admin_id} (غير معروف)"
            admins_list.append(f"{i}. {display_name}")

        bot.send_message(call.message.chat.id, "👥 قائمة الأدمن الحالية:\n" + "\n".join(admins_list))


def process_broadcast_text(message):
    if not is_admin(message.from_user.id):
        return

    sent = 0
    failed = 0
    current_user_chats = list(user_chats.keys())
    for chat_id in current_user_chats:
        try:
            bot.send_message(chat_id, message.text)
            sent += 1
        except Exception as e:
            logging.error(f"Failed to send broadcast to {chat_id}: {e}")
            failed += 1

    bot.reply_to(message, f"✅ تم إرسال الرسالة إلى {sent} مستخدم\n❌ فشل الإرسال لـ {failed} مستخدم")

def process_broadcast_media(message):
    if not is_admin(message.from_user.id):
        return

    file_id = None
    send_func = None
    caption = message.caption

    if message.content_type == 'photo':
        file_id = message.photo[-1].file_id
        send_func = bot.send_photo
    elif message.content_type == 'document':
        file_id = message.document.file_id
        send_func = bot.send_document
    elif message.content_type == 'video':
        file_id = message.video.file_id
        send_func = bot.send_video
    elif message.content_type == 'audio':
        file_id = message.audio.file_id
        send_func = bot.send_audio
    else:
        bot.reply_to(message, "نوع الوسائط غير مدعوم للإذاعة.")
        return

    sent = 0
    failed = 0
    current_user_chats = list(user_chats.keys())
    for chat_id in current_user_chats:
        try:
            send_func(chat_id, file_id, caption=caption)
            sent += 1
        except Exception as e:
            logging.error(f"Failed to send media broadcast to {chat_id}: {e}")
            failed += 1

    bot.reply_to(message, f"✅ تم إرسال الوسائط إلى {sent} مستخدم\n❌ فشل الإرسال لـ {failed} مستخدم")

def process_ban_user(message):
    if not is_admin(message.from_user.id):
        return

    target_id_or_username = message.text.strip()
    user_id_to_ban = None
    username_to_ban = None

    if target_id_or_username.startswith('@'):
        username_to_ban = target_id_or_username.lstrip('@')
        with lock:
            c.execute("SELECT user_id FROM users WHERE username = ?", (username_to_ban,))
            result = c.fetchone()
            if result:
                user_id_to_ban = result[0]
    else:
        try:
            user_id_to_ban = int(target_id_or_username)
            with lock:
                c.execute("SELECT username FROM users WHERE user_id = ?", (user_id_to_ban,))
                result = c.fetchone()
                if result:
                    username_to_ban = result[0]
        except ValueError:
            bot.reply_to(message, "❌ صيغة غير صحيحة. يرجى إرسال معرف المستخدم (ID) أو اليوزرنيم (@username).")
            return

    if user_id_to_ban:
        if user_id_to_ban in ADMIN_IDS:
            bot.reply_to(message, "⚠️ لا يمكن حظر الأدمن الافتراضي.")
            return

        with lock:
            c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id_to_ban,))
            if c.fetchone():
                bot.reply_to(message, "⚠️ لا يمكن حظر الأدمن.")
                return

        with lock:
            c.execute("INSERT OR REPLACE INTO banned_users (user_id, username) VALUES (?, ?)", (user_id_to_ban, username_to_ban))
            conn.commit()
        if username_to_ban:
            banned_users.add(username_to_ban)
        bot.reply_to(message, f"✅ تم حظر المستخدم {target_id_or_username}.")
        try:
            bot.send_message(user_id_to_ban, "⁉️ تم حظرك من البوت. تواصل مع المطور @TT_1_TT")
        except Exception as e:
            logging.warning(f"Could not notify banned user {user_id_to_ban}: {e}")
    else:
        bot.reply_to(message, f"❌ لم يتم العثور على المستخدم {target_id_or_username}.")

def process_unban_user(message):
    if not is_admin(message.from_user.id):
        return

    target_id_or_username = message.text.strip()
    user_id_to_unban = None
    username_to_unban = None

    if target_id_or_username.startswith('@'):
        username_to_unban = target_id_or_username.lstrip('@')
        with lock:
            c.execute("SELECT user_id FROM users WHERE username = ?", (username_to_unban,))
            result = c.fetchone()
            if result:
                user_id_to_unban = result[0]
    else:
        try:
            user_id_to_unban = int(target_id_or_username)
            with lock:
                c.execute("SELECT username FROM users WHERE user_id = ?", (user_id_to_unban,))
                result = c.fetchone()
                if result:
                    username_to_unban = result[0]
        except ValueError:
            bot.reply_to(message, "❌ صيغة غير صحيحة. يرجى إرسال معرف المستخدم (ID) أو اليوزرنيم (@username).")
            return

    if user_id_to_unban:
        with lock:
            c.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id_to_unban,))
            conn.commit()
        if username_to_unban in banned_users:
            banned_users.remove(username_to_unban)
        bot.reply_to(message, f"✅ تم فك حظر المستخدم {target_id_or_username}.")
    else:
        bot.reply_to(message, f"❌ المستخدم {target_id_or_username} غير محظور أو لم يتم العثور عليه.")


def process_set_limit(message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ صيغة غير صحيحة. استخدم: @username 5 أو user_id 5")
        return

    target_identifier = parts[0]
    try:
        new_limit = int(parts[1])
    except ValueError:
        bot.reply_to(message, "❌ الرجاء إدخال رقم صحيح للحد الجديد.")
        return

    user_id_target = None
    username_target = None

    if target_identifier.startswith('@'):
        username_target = target_identifier.lstrip('@')
        with lock:
            c.execute("SELECT user_id FROM users WHERE username = ?", (username_target,))
            result = c.fetchone()
            if result:
                user_id_target = result[0]
    else:
        try:
            user_id_target = int(target_identifier)
            with lock:
                c.execute("SELECT username FROM users WHERE user_id = ?", (user_id_target,))
                result = c.fetchone()
                if result:
                    username_target = result[0]
        except ValueError:
            bot.reply_to(message, "❌ معرف المستخدم غير صحيح (يجب أن يكون رقمًا أو يوزرنيم).")
            return

    if user_id_target:
        with lock:
            c.execute("UPDATE users SET upload_limit = ? WHERE user_id = ?", (new_limit, user_id_target))
            conn.commit()

            if c.rowcount > 0:
                bot.reply_to(message, f"✅ تم تحديث حد الرفع لـ {target_identifier} إلى {new_limit}.")
            else:
                bot.reply_to(message, f"❌ لم يتم العثور على المستخدم {target_identifier}.")
    else:
        bot.reply_to(message, f"❌ لم يتم العثور على المستخدم {target_identifier}.")


def process_add_channel(message):
    if not is_admin(message.from_user.id):
        return

    channel_info = message.text.strip()
    channel_id = None
    channel_username = None

    if channel_info.startswith('@'):
        channel_username = channel_info.lstrip('@')
        try:
            chat = bot.get_chat(f"@{channel_username}")
            channel_id = str(chat.id)
        except Exception as e:
            logging.error(f"Error getting channel ID for username: {e}")
            bot.reply_to(message, f"❌ تعذر العثور على القناة أو البوت ليس عضواً فيها: {channel_info}. تأكد أن البوت أدمن في القناة.")
            return
    elif channel_info.startswith('-100') or channel_info.isdigit():
        channel_id = channel_info
        try:
            chat = bot.get_chat(channel_id)
            channel_username = chat.username if chat.username else None
        except Exception as e:
            logging.error(f"Error getting channel info for ID: {e}")
            bot.reply_to(message, f"❌ تعذر العثور على القناة بالمعرف: {channel_info}. تأكد أن البوت عضواً في القناة.")
            return
    else:
        bot.reply_to(message, "❌ معرف القناة غير صحيح. استخدم يوزرنيم (@username) أو ID (-100...).")
        return

    try:
        if channel_id:
            bot_member = bot.get_chat_member(channel_id, bot.get_me().id)
            if bot_member.status not in ['administrator', 'creator']:
                bot.reply_to(message, f"⚠️ البوت ليس مشرفاً في القناة {channel_info}. يجب أن يكون مشرفاً للتحقق من الاشتراكات.")
                return
    except Exception as e:
        logging.error(f"Error checking bot's admin status in channel {channel_info}: {e}")
        bot.reply_to(message, f"❌ تعذر التحقق من صلاحيات البوت في القناة {channel_info}.")
        return

    add_subscription_channel(channel_username, channel_id)

    if channel_username:
        display_name = f"@{channel_username}"
    else:
        display_name = f"ID: {channel_id}"

    bot.reply_to(message, f"✅ تم إضافة قناة الاشتراك الإجباري: {display_name}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_ch_'))
def remove_channel_callback(call):
    channel_id = call.data.split('_')[2]
    remove_subscription_channel(channel_id)
    bot.answer_callback_query(call.id, "✅ تمت إزالة القناة")
    try:
        bot.edit_message_text("✅ تمت إزالة القناة", call.message.chat.id, call.message.message_id)
    except Exception as e:
        logging.warning(f"Could not edit message after removing channel: {e}")
        bot.send_message(call.message.chat.id, "✅ تمت إزالة القناة")

def process_add_admin(message):
    if not is_admin(message.from_user.id):
        return

    try:
        new_admin_id = int(message.text.strip())
        try:
            user_chat = bot.get_chat(new_admin_id)
            username = user_chat.username
        except:
            username = None

        add_admin(new_admin_id, username)
        bot.reply_to(message, f"✅ تمت إضافة الأدمن: {new_admin_id}")
    except ValueError:
        bot.reply_to(message, "❌ الرجاء إدخال رقم صحيح لمعرف المستخدم")

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_ad_'))
def remove_admin_callback(call):
    admin_id_to_remove = int(call.data.split('_')[2])

    if admin_id_to_remove in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ لا يمكن إزالة الأدمن الافتراضي (المبرمج).")
        return

    remove_admin(admin_id_to_remove)
    bot.answer_callback_query(call.id, "✅ تمت إزالة الأدمن")
    try:
        bot.edit_message_text("✅ تمت إزالة الأدمن", call.message.chat.id, call.message.message_id)
    except Exception as e:
        logging.warning(f"Could not edit message after removing admin: {e}")
        bot.send_message(call.message.chat.id, "✅ تمت إزالة الأدمن")


@bot.callback_query_handler(func=lambda call: call.data == 'get_referral')
def get_referral_link(call):
    user_id = call.from_user.id
    referral_link = generate_referral_link(user_id)

    with lock:
        c.execute("SELECT referrals_count, upload_limit FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        referrals_count = result[0] if result else 0
        upload_limit = result[1] if result else DEFAULT_UPLOAD_LIMIT

    bot.send_message(
        call.message.chat.id,
        f"🔗 رابط الإحالة الخاص بك:\n\n{referral_link}\n\n"
        "عندما ينضم شخص جديد عبر هذا الرابط:\n"
        f"- ستحصل على +{REFERRAL_LIMIT_INCREASE} لحد الرفع\n\n"
        f"📊 إحصائياتك الحالية:\n"
        f"- عدد الإحالات: {referrals_count}\n"
        f"- حد الرفع الحالي: {upload_limit}"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'stop_all_bots')
def stop_all_user_bots(call):
    user_id = call.from_user.id
    
    with lock:
        c.execute("SELECT original_file_name FROM uploaded_files WHERE user_id = ? AND status = 'active'", (user_id,))
        active_files = c.fetchall()
    
    if not active_files:
        bot.answer_callback_query(call.id, "لا توجد لديك بوتات نشطة لإيقافها")
        bot.send_message(call.message.chat.id, "لا توجد لديك بوتات نشطة لإيقافها")
        return
    
    stopped_count = 0
    for file_row in active_files:
        file_name = file_row[0]
        try:
            stop_bot(user_id, delete=True)
            stopped_count += 1
        except Exception as e:
            logging.error(f"Error stopping bot {file_name} for user {user_id}: {e}")
    
    bot.answer_callback_query(call.id, "تم ايقاف جميع بوتاتك")
    bot.send_message(call.message.chat.id, "تم ايقاف جميع بوتاتك")

# معالج جديد: إيقاف/تشغيل البوت
@bot.callback_query_handler(func=lambda call: call.data == 'stop_resume_bot')
def handle_stop_resume_bot(call):
    user_id = call.from_user.id
    
    # التحقق من حالة البوت الحالية
    script_info = bot_scripts.get(user_id)
    
    if not script_info or not script_info.get('script_name'):
        bot.answer_callback_query(call.id, "❌ لا يوجد بوت نشط حالياً")
        bot.send_message(call.message.chat.id, "❌ لا يوجد بوت نشط حالياً لإيقافه أو تشغيله.")
        return
    
    script_name = script_info['script_name']
    
    # التحقق مما إذا كان البوت متوقف مؤقتاً أم نشط
    if script_info.get('paused', False):
        # البوت متوقف - تشغيله
        result, new_paused_state = stop_resume_bot(user_id)
        if new_paused_state is False:
            bot.answer_callback_query(call.id, "✅ تم تشغيل البوت")
            bot.send_message(call.message.chat.id, f"✅ تم تشغيل {script_name} بنجاح.")
        else:
            bot.answer_callback_query(call.id, "❌ فشل في تشغيل البوت")
            bot.send_message(call.message.chat.id, result)
    else:
        # البوت نشط - إيقافه مؤقتاً
        result, new_paused_state = stop_resume_bot(user_id)
        if new_paused_state is True:
            bot.answer_callback_query(call.id, "⏸️ تم إيقاف البوت مؤقتاً")
            bot.send_message(call.message.chat.id, f"⏸️ تم إيقاف {script_name} مؤقتاً.\n\nيمكنك تشغيله مرة أخرى بالضغط على زر 'إيقاف/تشغيل البوت'.")
        else:
            bot.answer_callback_query(call.id, "❌ فشل في إيقاف البوت")
            bot.send_message(call.message.chat.id, result)

@bot.message_handler(commands=['help'])
@subscription_required
def instructions(message):
    with lock:
        c.execute("SELECT username FROM banned_users WHERE user_id = ?", (message.from_user.id,))
        if c.fetchone() or message.from_user.username in banned_users:
            bot.send_message(message.chat.id, "⁉️ تم حظرك من البوت. تواصل مع المطور @TT_1_TT")
            return

    markup = types.InlineKeyboardMarkup()
    support_button = types.InlineKeyboardButton("التواصل مع الدعم أونلاين 💬", callback_data='online_support')
    markup.add(support_button)

    bot.send_message(
        message.chat.id,
        "🤗 الأوامر المتاحة:\n"
        "يمكنك استخدام الأزرار أدناه للوصول السريع للأوامر 👇",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == 'online_support')
def online_support(call):
    user_id = call.from_user.id
    user_name = call.from_user.first_name
    user_username = call.from_user.username or "بدون يوزر"

    all_admin_ids = list(set(ADMIN_IDS + [admin[0] for admin in get_admins()]))
    for admin_id in all_admin_ids:
        try:
            bot.send_message(
                admin_id,
                f"📞 طلب دعم أونلاين من المستخدم:\n"
                f"👤 الاسم: {user_name}\n"
                f"📌 اليوزر: @{user_username}\n"
                f"🆔 ID: {user_id}\n\n"
                f"يرجى التواصل معه في أقرب وقت."
            )
        except Exception as e:
            logging.error(f"Failed to send online support request to admin {admin_id}: {e}")

    bot.send_message(
        call.message.chat.id,
        "✅ تم إرسال طلبك بنجاح! سيتواصل معك الدعم قريباً."
    )

@bot.message_handler(commands=['ban'])
@subscription_required
def ban_user_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, " ❌ ليس لديك صلاحية استخدام هذا الأمر.")
        return

    try:
        username_or_id = message.text.split(' ', 1)[1].strip()
        class MockMessage:
            def __init__(self, text, from_user):
                self.text = text
                self.from_user = from_user
        mock_msg = MockMessage(username_or_id, message.from_user)
        process_ban_user(mock_msg)

    except IndexError:
        bot.reply_to(message, "يرجى كتابة معرف المستخدم (ID) أو اليوزرنيم (@username) بعد الأمر.")

@bot.message_handler(commands=['uban'])
@subscription_required
def unban_user_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, " ❌ ليس لديك صلاحية استخدام هذا الأمر.")
        return

    try:
        username_or_id = message.text.split(' ', 1)[1].strip()
        class MockMessage:
            def __init__(self, text, from_user):
                self.text = text
                self.from_user = from_user
        mock_msg = MockMessage(username_or_id, message.from_user)
        process_unban_user(mock_msg)
    except IndexError:
        bot.reply_to(message, "يرجى كتابة معرف المستخدم (ID) أو اليوزرنيم (@username) بعد الأمر.")

@bot.callback_query_handler(func=lambda call: call.data == 'speed')
@subscription_required
def check_speed(call):
    bot.send_message(call.message.chat.id, "⏳ انتظر، يتم قياس سرعة البوت...")
    start_time = time.time()
    temp_msg = bot.send_message(call.message.chat.id, "🔄 جار قياس السرعة")
    response_time = time.time() - start_time
    response_time_ms = response_time * 1000

    bot.delete_message(call.message.chat.id, temp_msg.message_id)

    if response_time_ms < 100:
        speed_feedback = f"سرعة البوت الحالية: {response_time_ms:.2f} ms - ممتازه ! 🔥"
    elif response_time_ms < 300:
        speed_feedback = f"سرعة البوت الحالية: {response_time_ms:.2f} ms - جيد جدا ✨"
    else:
        speed_feedback = f"سرعة البوت الحالية: {response_time_ms:.2f} ms - يجب تحسين الإنترنت ❌"

    bot.send_message(call.message.chat.id, speed_feedback)

@bot.callback_query_handler(func=lambda call: call.data == 'download_lib')
@subscription_required
def ask_library_name(call):
    bot.send_message(call.message.chat.id, "🛠 أرسل إسم المكتبة المطلوب تثبيتها.")
    bot.register_next_step_handler(call.message, install_library)

def install_library(message):
    library_name = message.text.strip()
    bot.send_message(message.chat.id, f"🔄 جاري تنزيل المكتبة: {library_name}...")
    try:
        process = subprocess.run(
            [sys.executable, "-m", "pip", "install", library_name],
            capture_output=True,
            text=True,
            check=True,
            timeout=120
        )
        bot.send_message(message.chat.id, f"✅ تم تثبيت المكتبة {library_name} بنجاح.")
        if process.stdout:
            logging.info(f"Pip install stdout for {library_name}: {process.stdout}")
    except subprocess.CalledProcessError as e:
        error_output = e.stderr or e.stdout
        error_preview = error_output[:1500] if error_output else "لا يوجد تفاصيل عن الخطأ"
        bot.send_message(message.chat.id, f"❌ فشل في تثبيت المكتبة {library_name}.\nالخطأ:\n```\n{error_preview}\n```", parse_mode='Markdown')
        logging.error(f"Pip install error for {library_name}: {error_output}")
    except subprocess.TimeoutExpired:
        bot.send_message(message.chat.id, f"⏰ انتهت المهلة أثناء تثبيت المكتبة {library_name}. قد تكون المكتبة كبيرة جداً.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ حدث خطأ غير متوقع أثناء تثبيت المكتبة {library_name}.\nالخطأ: {str(e)}")
        logging.error(f"Unexpected error during pip install for {library_name}: {e}")


@bot.message_handler(commands=['rck'])
@subscription_required
def broadcast_message_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, " ❌ ليس لديك صلاحية استخدام هذا الأمر.")
        return

    try:
        msg = message.text.split(' ', 1)[1]
        sent_count = 0
        failed_count = 0

        current_user_chats = list(user_chats.keys())
        for chat_id in current_user_chats:
            try:
                bot.send_message(chat_id, msg)
                sent_count += 1
            except Exception as e:
                logging.error(f"Error sending message to {chat_id}: {e}")
                failed_count += 1

        bot.reply_to(message, f"✅ تم إرسال الرسالة بنجاح إلى {sent_count} مستخدم\n"
                           f"❌ فشلت الرسالة في إرسالها إلى {failed_count} مستخدم")
    except IndexError:
        bot.reply_to(message, "يرجى كتابة الرسالة بعد الأمر.")

@bot.message_handler(commands=['del'])
@subscription_required
def delete_file_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message," ❌ ليس لديك صلاحية استخدام هذا الأمر.")
        return

    try:
        if len(message.text.split()) > 1:
            parts = message.text.split(' ', 2)
            if len(parts) < 3:
                bot.reply_to(message, "يرجى تحديد معرف المستخدم واسم الملف المراد حذفه بعد الأمر. مثال: /del <user_id> <filename.py>")
                return

            target_user_id = int(parts[1])
            file_name_to_delete = parts[2].strip()

            target_chat_id = None
            with lock:
                script_info = bot_scripts.get(target_user_id)
                if script_info and script_info.get('script_name') == file_name_to_delete:
                    target_chat_id = target_user_id

            if target_chat_id:
                result = stop_bot(target_chat_id, delete=True)
                bot.reply_to(message, result)
            else:
                user_script_dir = os.path.join(uploaded_files_dir, str(target_user_id))
                script_path = os.path.join(user_script_dir, file_name_to_delete)
                log_file_path = os.path.join(user_script_dir, f"{file_name_to_delete}.log")
                req_log_path = os.path.join(user_script_dir, f"{file_name_to_delete}_requirements.log")

                if os.path.exists(script_path):
                    os.remove(script_path)
                    if os.path.exists(log_file_path):
                        os.remove(log_file_path)
                    if os.path.exists(req_log_path):
                        os.remove(req_log_path)

                    if os.path.exists(user_script_dir) and not os.listdir(user_script_dir):
                        os.rmdir(user_script_dir)

                    with lock:
                        c.execute("UPDATE uploaded_files SET status = 'deleted' WHERE user_id = ? AND original_file_name = ?", (target_user_id, file_name_to_delete))
                        conn.commit()
                    bot.reply_to(message, f"✅ تم حذف {file_name_to_delete} للمستخدم {target_user_id} من الاستضافة.")
                else:
                    bot.reply_to(message, f"❌ الملف {file_name_to_delete} للمستخدم {target_user_id} غير موجود أو غير نشط.")
        else:
            bot.reply_to(message, "يرجى تحديد معرف المستخدم واسم الملف المراد حذفه بعد الأمر.")

    except ValueError:
        bot.reply_to(message, "❌ معرف المستخدم يجب أن يكون رقماً صحيحاً.")
    except Exception as e:
        bot.reply_to(message,f"حدث خطأ: {e}")

@bot.message_handler(commands=['stp'])
@subscription_required
def stop_file_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, " ❌ ليس لديك صلاحية استخدام هذا الأمر.")
        return

    try:
        if len(message.text.split()) > 1:
            parts = message.text.split(' ', 2)
            if len(parts) < 3:
                bot.reply_to(message, "يرجى تحديد معرف المستخدم واسم الملف المراد إيقافه بعد الأمر. مثال: /stp <user_id> <filename.py>")
                return

            target_user_id = int(parts[1])
            file_name_to_stop = parts[2].strip()

            target_chat_id = None
            with lock:
                script_info = bot_scripts.get(target_user_id)
                if script_info and script_info.get('script_name') == file_name_to_stop:
                    target_chat_id = target_user_id

            if target_chat_id:
                result = stop_bot(target_chat_id)
                bot.reply_to(message, result)
            else:
                bot.reply_to(message, f"❌ الملف {file_name_to_stop} للمستخدم {target_user_id} غير نشط حالياً.")
        else:
            bot.reply_to(message, "يرجى تحديد معرف المستخدم واسم الملف المراد إيقافه بعد الأمر.")

    except ValueError:
        bot.reply_to(message, "❌ معرف المستخدم يجب أن يكون رقماً صحيحاً.")
    except Exception as e:
        bot.reply_to(message, f"حدث خطأ: {e}")

@bot.message_handler(commands=['str'])
@subscription_required
def start_file_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, " ❌ ليس لديك صلاحية استخدام هذا الأمر.")
        return

    try:
        parts = message.text.split(' ', 2)
        if len(parts) < 3:
            bot.reply_to(message, "يرجى تحديد معرف المستخدم واسم الملف المراد تشغيله بعد الأمر. مثال: /str <user_id> <filename.py>")
            return

        target_user_id = int(parts[1])
        original_file_name = parts[2].strip()

        user_script_dir = os.path.join(uploaded_files_dir, str(target_user_id))
        script_path = os.path.join(user_script_dir, original_file_name)

        if not os.path.exists(script_path):
            bot.reply_to(message, f"❌ الملف {original_file_name} للمستخدم {target_user_id} غير موجود في الاستضافة.")
            return

        with lock:
            if bot_scripts.get(target_user_id, {}).get('script_name') == original_file_name and \
               bot_scripts[target_user_id].get('process') and \
               psutil.pid_exists(bot_scripts[target_user_id]['process'].pid):
                bot.reply_to(message, f"⚠️ الملف {original_file_name} يعمل بالفعل للمستخدم {target_user_id}.")
                return

        install_and_run_uploaded_file(script_path, target_user_id, original_file_name)
        bot.reply_to(message, f"✅ تم بدء تشغيل {original_file_name} للمستخدم {target_user_id}.")

    except ValueError:
        bot.reply_to(message, "❌ معرف المستخدم يجب أن يكون رقماً صحيحاً.")
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {e}")

@bot.message_handler(commands=['rr'])
@subscription_required
def send_private_message_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, " ❌ ليس لديك صلاحية استخدام هذا الأمر.")
        return

    try:
        parts = message.text.split(' ', 2)
        if len(parts) < 3:
            bot.reply_to(message, "يرجى كتابة معرف المستخدم (ID) أو اليوزرنيم (@username) والرسالة بعد الأمر.")
            return

        target_identifier = parts[1].strip()
        msg = parts[2]

        user_id_target = None

        if target_identifier.startswith('@'):
            username = target_identifier.lstrip('@')
            with lock:
                c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
                result = c.fetchone()
                if result:
                    user_id_target = result[0]
        else:
            try:
                user_id_target = int(target_identifier)
            except ValueError:
                bot.reply_to(message, "❌ معرف المستخدم غير صحيح (يجب أن يكون رقمًا أو يوزرنيم).")
                return

        if user_id_target:
            try:
                bot.send_message(user_id_target, msg)
                bot.reply_to(message, "تم إرسال الرسالة بنجاح ✅.")
            except Exception as e:
                bot.reply_to(message, f"❌ فشل إرسال الرسالة إلى {target_identifier}. قد يكون المستخدم قد حظر البوت أو الدردشة غير موجودة. الخطأ: {e}")
                logging.error(f"Error sending direct message to {user_id_target}: {e}")
        else:
            bot.reply_to(message, f"تعذر العثور على المستخدم {target_identifier}. تأكد من إدخال الاسم أو المعرف بشكل صحيح ⁉️.")
    except Exception as e:
        logging.error(f"Error in /rr command: {e}")
        bot.reply_to(message, " ❌ حدث خطأ أثناء معالجة الأمر. يرجى المحاولة مرة أخرى.")

@bot.message_handler(commands=['cmd'])
@subscription_required
def display_commands(message):
    with lock:
        c.execute("SELECT username FROM banned_users WHERE user_id = ?", (message.from_user.id,))
        if c.fetchone() or message.from_user.username in banned_users:
            bot.send_message(message.chat.id, "⁉️ تم حظرك من البوت. تواصل مع المطور @TT_1_TT")
            return

    markup = types.InlineKeyboardMarkup()
    report_button = types.InlineKeyboardButton( "إرسال رسالة الى المطور 👨‍💻", callback_data='report_issue')
    suggestion_button = types.InlineKeyboardButton("إقتراح تعديل 🔧", callback_data='suggest_modification')
    chat_button = types.InlineKeyboardButton("فتح محادثة مع المطور 💬", callback_data='open_chat')

    markup.row(report_button)
    markup.row(suggestion_button)
    markup.row(chat_button)

    bot.send_message(
        message.chat.id,
        "📜 الأوامر المتاحة:\nاختر أحد الخيارات أدناه 👇😄:",
        reply_markup=markup
    )

@bot.message_handler(commands=['developer'])
@subscription_required
def contact_developer(message):
    with lock:
        c.execute("SELECT username FROM banned_users WHERE user_id = ?", (message.from_user.id,))
        if c.fetchone() or message.from_user.username in banned_users:
            bot.send_message(message.chat.id, "⁉️ تم حظرك من البوت. تواصل مع المطور @TT_1_TT")
            return

    markup = types.InlineKeyboardMarkup()
    open_chat_button = types.InlineKeyboardButton("فتح محادثة مع المطور 👨‍💻", callback_data='open_chat')
    markup.add(open_chat_button)
    bot.send_message(message.chat.id, "لتواصل مع المطور إختر أحد الخيارات أدناه 👇😊:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'open_chat')
@subscription_required
def initiate_chat(call):
    user_id = call.from_user.id

    if user_id in active_chats:
        bot.send_message(user_id, "❌ لديك محادثة نشطة بالفعل مع المطور")
        return

    bot.send_message(user_id, "✅ تم إرسال طلب فتح محادثة، الرجاء إنتظار المطور.")
    markup = types.InlineKeyboardMarkup()
    accept_button = types.InlineKeyboardButton("قبول المحادثة ✅", callback_data=f'accept_chat_{user_id}')
    reject_button = types.InlineKeyboardButton("رفض المحادثة ❎", callback_data=f'reject_chat_{user_id}')
    markup.add(accept_button, reject_button)

    all_admin_ids = list(set(ADMIN_IDS + [admin[0] for admin in get_admins()]))
    for admin_id in all_admin_ids:
        try:
            bot.send_message(
                admin_id,
                f"📞 طلب محادثة جديد من المستخدم:\n"
                f"👤 الاسم: {call.from_user.first_name}\n"
                f"📌 اليوزر: @{call.from_user.username or 'بدون يوزر'}\n"
                f"🆔 ID: {user_id}",
                reply_markup=markup
            )
        except Exception as e:
            logging.error(f"Failed to send chat request to admin {admin_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_chat_'))
def accept_chat_request(call):
    user_id = int(call.data.split('_')[2])
    admin_id = call.from_user.id

    if user_id not in active_chats and admin_id not in active_chats:
        active_chats[user_id] = admin_id
        active_chats[admin_id] = user_id

        bot.send_message(
            user_id,
            f"✅ تم قبول محادثتك من المطور @{call.from_user.username or 'بدون يوزر'}."
        )

        markup = types.InlineKeyboardMarkup()
        close_button = types.InlineKeyboardButton("إنهاء المحادثة", callback_data=f'close_chat_{user_id}')
        markup.add(close_button)

        bot.send_message(user_id, "يمكنك البدء بالدردشة الآن. لإنهاء المحادثة، اضغط هنا 👇:", reply_markup=markup)
        bot.send_message(admin_id, "يمكنك البدء بالدردشة الآن. لإنهاء المحادثة، اضغط هنا 👇:", reply_markup=markup)
        bot.answer_callback_query(call.id, "✅ تم قبول المحادثة وبدء الدردشة.")
    else:
        bot.answer_callback_query(call.id, "⚠️ هذه المحادثة نشطة بالفعل أو تمت معالجتها.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_chat_'))
def reject_chat_request(call):
    user_id = int(call.data.split('_')[2])
    if user_id in active_chats:
        if active_chats.get(active_chats[user_id]) == user_id:
            del active_chats[active_chats[user_id]]
        del active_chats[user_id]

    bot.send_message(user_id, "❌ تم رفض محادثتك من قبل المطور")
    bot.answer_callback_query(call.id, "✅ تم رفض المحادثة")
    try:
        bot.edit_message_text(f"❌ تم رفض طلب المحادثة للمستخدم {user_id}", call.message.chat.id, call.message.message_id)
    except Exception as e:
        logging.warning(f"Could not edit message after rejecting chat: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('close_chat_'))
def close_chat_session(call):
    user_id_initiator = int(call.data.split('_')[2])
    caller_id = call.from_user.id

    if caller_id == user_id_initiator:
        user_id = caller_id
        admin_id = active_chats.get(user_id)
    elif active_chats.get(caller_id) == user_id_initiator:
        admin_id = caller_id
        user_id = user_id_initiator
    else:
        bot.answer_callback_query(call.id, "لا تملك صلاحية إغلاق هذه المحادثة.")
        return

    if admin_id and active_chats.get(user_id) == admin_id and active_chats.get(admin_id) == user_id:
        try:
            bot.send_message(user_id, "❌ تم إغلاق المحادثة.")
            bot.send_message(admin_id, "✅ تم إغلاق المحادثة.")
        except Exception as e:
            logging.error(f"Error sending close chat message: {e}")

        if user_id in active_chats: del active_chats[user_id]
        if admin_id in active_chats: del active_chats[admin_id]

        bot.answer_callback_query(call.id, "تم إغلاق المحادثة")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception as e:
            logging.warning(f"Could not remove reply markup after closing chat: {e}")
    else:
        bot.answer_callback_query(call.id, "لا توجد محادثة نشطة أو تم إغلاقها بالفعل.")


@bot.message_handler(func=lambda message: message.from_user.id in active_chats and message.text)
def handle_user_messages_in_chat(message):
    user_id = message.from_user.id

    if user_id in active_chats:
        recipient_id = active_chats[user_id]
        try:
            sender_name = f"👤 {message.from_user.first_name} (@{message.from_user.username or 'بدون يوزر'}):\n"
            bot.send_message(recipient_id, sender_name + message.text)
        except Exception as e:
            logging.error(f"Error forwarding message from {user_id} to {recipient_id}: {e}")
            bot.send_message(user_id, "❌ فشل في إرسال الرسالة. قد يكون الطرف الآخر قد أنهى المحادثة أو حظر البوت.")
    elif is_admin(user_id) and user_id in active_chats:
        recipient_id = active_chats[user_id]
        try:
            admin_name = f"👨‍💻 المطور (@{message.from_user.username or 'بدون يوزر'}):\n"
            bot.send_message(recipient_id, admin_name + message.text)
        except Exception as e:
            logging.error(f"Error forwarding message from admin {user_id} to {recipient_id}: {e}")
            bot.send_message(user_id, "❌ فشل في إرسال الرسالة. قد يكون المستخدم قد أنهى المحادثة أو حظر البوت.")


@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    pass


@bot.callback_query_handler(func=lambda call: call.data == 'report_issue')
@subscription_required
def report_issue(call):
    bot.send_message(call.message.chat.id, "🛠️ ارسل مشكلتك الآن، وسيحلها المطور في أقرب وقت.")
    bot.register_next_step_handler(call.message, handle_report)

def handle_report(message):
    if message.text:
        all_admin_ids = list(set(ADMIN_IDS + [admin[0] for admin in get_admins()]))
        for admin_id in all_admin_ids:
            try:
                bot.send_message(admin_id, f"🛠️ تم الإبلاغ عن مشكلة من @{message.from_user.username or 'بدون يوزر'} (ID: {message.from_user.id}):\n\n{message.text}")
            except Exception as e:
                logging.error(f"Failed to send report to admin {admin_id}: {e}")
        bot.send_message(message.chat.id, "✅ تم إرسال مشكلتك بنجاح! سيتواصل معك المطور قريبًا.")
    else:
        bot.send_message(message.chat.id, "❌ لم يتم تلقي أي نص. يرجى إرسال المشكلة مرة أخرى.")

@bot.callback_query_handler(func=lambda call: call.data == 'suggest_modification')
@subscription_required
def suggest_modification(call):
    bot.send_message(call.message.chat.id, "💡 اكتب اقتراحك الآن، أو أرسل صورة أو ملف وسأرسله للمطور.")
    bot.register_next_step_handler(call.message, handle_suggestion)

def handle_suggestion(message):
    all_admin_ids = list(set(ADMIN_IDS + [admin[0] for admin in get_admins()]))
    if message.text:
        for admin_id in all_admin_ids:
            try:
                bot.send_message(admin_id, f"💡 اقتراح من @{message.from_user.username or 'بدون يوزر'} (ID: {message.from_user.id}):\n\n{message.text}")
            except Exception as e:
                logging.error(f"Failed to send suggestion to admin {admin_id}: {e}")
        bot.send_message(message.chat.id, "✅ تم إرسال اقتراحك بنجاح للمطور!")
    elif message.photo:
        photo_id = message.photo[-1].file_id
        for admin_id in all_admin_ids:
            try:
                bot.send_photo(admin_id, photo_id, caption=f"💡 اقتراح من @{message.from_user.username or 'بدون يوزر'} (ID: {message.from_user.id}) (صورة)")
            except Exception as e:
                logging.error(f"Failed to send photo suggestion to admin {admin_id}: {e}")
        bot.send_message(message.chat.id, "✅ تم إرسال اقتراحك كصورة للمطور!")
    elif message.document:
        file_id = message.document.file_id
        for admin_id in all_admin_ids:
            try:
                bot.send_document(admin_id, file_id, caption=f"💡 اقتراح من @{message.from_user.username or 'بدون يوزر'} (ID: {message.from_user.id}) (ملف)")
            except Exception as e:
                logging.error(f"Failed to send document suggestion to admin {admin_id}: {e}")
        bot.send_message(message.chat.id, "✅ تم إرسال اقتراحك كملف للمطور!")
    else:
        bot.send_message(message.chat.id, "❌ لم يتم تلقي أي محتوى. يرجى إرسال الاقتراح مرة أخرى.")

@bot.callback_query_handler(func=lambda call: call.data == 'commands')
@subscription_required
def process_commands_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "اهلا بك\n\n"
        "• 『 إرشادات الاستخدام والقيود الخاصة بالبوت 』\n\n"
        "✦ التعليمات ✦\n"
        "• 1︙ يُرجى رفع ملفك عبر زر \"رفع ملف\"\n"
        "• 2︙ يمكن رفع ملفات Python (.py) و PHP (.php)\n"
        "• 3︙ لملفات Python: تأكد من تثبيت كافة المكتبات البرمجية المطلوبة قبل الرفع\n"
        "• 4︙ يُرجى مراجعة كود البوت والتأكد من خلوه من الأخطاء البرمجية\n"
        "• 5︙ تأكد من إدخال رمز التوكن بشكل صحيح داخل الكود\n"
        "• 6︙ في حال وجود أي استفسار أو مشكلة، يمكنك التواصل مع المطور عبر زر \"الدعم الفني\"\n\n"
        "✦ القيود والممنوعات ✦\n"
        "• 1︙ يُمنع رفع أي ملفات تحتوي محتوى مشبوه أو ضار حفاظاً على سلامة النظام\n"
        "• 2︙ يُمنع رفع ملفات تخص بوتات الاستضافة أو التخزين أو السكربتات بجميع أنواعها\n"
        "• 3︙ يُمنع تمامًا القيام بأي محاولات اختراق مثل:\n"
        "    - استغلال الثغرات\n"
        "    - تنفيذ الهجمات\n"
        "    - أي نشاط ضار آخر\n\n"
        "⚠️ 『 تنويه هام 』\n"
        "• أي مخالفة لأي من الشروط السابقة ستؤدي إلى:\n"
        "    - حظر دائم من استخدام البوت\n"
        "    - ولا توجد أي إمكانية لفك الحظر مستقبلاً\n\n"
        "• نقدر التزامك ونهدف لتوفير بيئة آمنة للجميع. شكراً لتفهمك!"
    )


@bot.callback_query_handler(func=lambda call: True)
@subscription_required
def callback_handler(call):
    if call.data == 'upload':
        bot.send_message(call.message.chat.id, "📄 يرجى إرسال ملف بايثون (.py) أو PHP (.php) الآن:")
    elif call.data.startswith(('delete_', 'stop_', 'start_', 'viewlog_')):
        try:
            data_parts = call.data.split('_')
            action = data_parts[0]
            user_id = int(data_parts[1])
            # استخراج اسم الملف ونوعه
            if len(data_parts) >= 4:
                original_file_name = '_'.join(data_parts[2:-1])
                file_type = data_parts[-1]
            else:
                original_file_name = '_'.join(data_parts[2:])
                file_type = 'python'  # افتراضي

            user_script_dir = os.path.join(uploaded_files_dir, str(user_id))
            script_path = os.path.join(user_script_dir, original_file_name)

            if action == 'delete':
                result = stop_bot(user_id, delete=True)
                bot.send_message(call.message.chat.id, result)
                if is_admin(call.from_user.id) and call.from_user.id != user_id:
                     bot.send_message(call.from_user.id, f"👤 قام الأدمن بحذف ملف {original_file_name} ({file_type.upper()}) للمستخدم {user_id}.")
                elif call.from_user.id == user_id:
                    all_admin_ids = list(set(ADMIN_IDS + [admin[0] for admin in get_admins()]))
                    for admin_id in all_admin_ids:
                        try:
                            if admin_id != call.from_user.id:
                                bot.send_message(admin_id, f"👤 قام المستخدم @{call.from_user.username or 'بدون يوزر'} بحذف ملفه {original_file_name} ({file_type.upper()}).")
                        except Exception as e:
                            logging.warning(f"Could not notify admin {admin_id} about user delete: {e}")

                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=result,
                    reply_markup=None
                )

            elif action == 'stop':
                result = stop_bot(user_id)
                if is_admin(call.from_user.id) and call.from_user.id != user_id:
                    bot.send_message(call.from_user.id, f"👤 قام الأدمن بإيقاف ملف {original_file_name} ({file_type.upper()}) للمستخدم {user_id}.")
                elif call.from_user.id == user_id:
                    all_admin_ids = list(set(ADMIN_IDS + [admin[0] for admin in get_admins()]))
                    for admin_id in all_admin_ids:
                        try:
                            if admin_id != call.from_user.id:
                                bot.send_message(admin_id, f"👤 قام المستخدم @{call.from_user.username or 'بدون يوزر'} بإيقاف ملفه {original_file_name} ({file_type.upper()}).")
                        except Exception as e:
                            logging.warning(f"Could not notify admin {admin_id} about user stop: {e}")

                markup = types.InlineKeyboardMarkup()
                start_button = types.InlineKeyboardButton(f"▶️ تشغيل", callback_data=f'start_{user_id}_{original_file_name}_{file_type}')
                delete_button = types.InlineKeyboardButton(f"🗑 حذف", callback_data=f'delete_{user_id}_{original_file_name}_{file_type}')
                view_logs_button = types.InlineKeyboardButton(f"📄 عرض السجلات", callback_data=f'viewlog_{user_id}_{original_file_name}_{file_type}')
                markup.row(start_button, delete_button)
                markup.row(view_logs_button)

                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"{result}\n\nيمكنك تشغيله مرة أخرى أو حذفه نهائيًا",
                    reply_markup=markup
                )

            elif action == 'start':
                install_and_run_uploaded_file(script_path, user_id, original_file_name)
                if is_admin(call.from_user.id) and call.from_user.id != user_id:
                    bot.send_message(call.from_user.id, f"👤 قام الأدمن بتشغيل ملف {original_file_name} ({file_type.upper()}) للمستخدم {user_id}.")
                elif call.from_user.id == user_id:
                    all_admin_ids = list(set(ADMIN_IDS + [admin[0] for admin in get_admins()]))
                    for admin_id in all_admin_ids:
                        try:
                            if admin_id != call.from_user.id:
                                bot.send_message(admin_id, f"👤 قام المستخدم @{call.from_user.username or 'بدون يوزر'} بتشغيل ملفه {original_file_name} ({file_type.upper()}).")
                        except Exception as e:
                            logging.warning(f"Could not notify admin {admin_id} about user start: {e}")

                markup = types.InlineKeyboardMarkup()
                stop_button = types.InlineKeyboardButton(f"🔴 إيقاف", callback_data=f'stop_{user_id}_{original_file_name}_{file_type}')
                delete_button = types.InlineKeyboardButton(f"🗑 حذف", callback_data=f'delete_{user_id}_{original_file_name}_{file_type}')
                view_logs_button = types.InlineKeyboardButton(f"📄 عرض السجلات", callback_data=f'viewlog_{user_id}_{original_file_name}_{file_type}')
                markup.row(stop_button, delete_button)
                markup.row(view_logs_button)

                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"✅ تم تشغيل ملف {original_file_name} ({file_type.upper()}) بنجاح",
                    reply_markup=markup
                )

            elif action == 'viewlog':
                script_info = bot_scripts.get(user_id)
                if script_info and script_info.get('log_path'):
                    send_script_log(call.message.chat.id, script_info['script_name'], script_info['log_path'])
                    bot.answer_callback_query(call.id, "✅ تم إرسال السجلات.")
                else:
                    bot.answer_callback_query(call.id, "❌ لا توجد سجلات متاحة حالياً لهذا البوت.")


        except Exception as e:
            logging.error(f"Error in callback_handler for {call.data}: {e}")
            bot.answer_callback_query(call.id, f"حدث خطأ: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'check_subscription')
def check_subscription_callback(call):
    user_id = call.from_user.id
    if check_subscription(user_id):
        bot.answer_callback_query(call.id, "✅ تم التحقق من الاشتراك بنجاح!")
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ لم يتم الاشتراك بعد. يرجى الاشتراك أولاً.")


def run_bot():
    while True:
        try:
            logging.info("🚀 Starting Telegram Bot...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except telebot.apihelper.ApiTelegramException as e:
            if "Conflict: terminated by other getUpdates request" in str(e):
                logging.error("⚠️ Telegram API Conflict error! Another instance might be running. Retrying in 30 seconds...")
            else:
                logging.error(f"⚠️ Telegram API Error: {str(e)}. Retrying in 30 seconds...")
            time.sleep(30)
        except requests.exceptions.ConnectionError:
            logging.warning("🌐 Connection error, retrying in 30 seconds...")
            time.sleep(30)
        except Exception as e:
            logging.error(f"❌ Unexpected error: {str(e)}. Retrying in 15 seconds...")
            time.sleep(15)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("bot_runtime.log"),
            logging.StreamHandler()
        ]
    )

    logger = telebot.logger
    telebot.logger.setLevel(logging.INFO)

    if not os.path.exists(uploaded_files_dir):
        os.makedirs(uploaded_files_dir)

    try:
        c.execute("SELECT username FROM banned_users")
        for row in c.fetchall():
            if row[0]:
                banned_users.add(row[0])
    except Exception as e:
        logging.error(f"Error initializing banned_users from DB: {e}")

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    logging.info("✅ Flask server started on port 5000")
    logging.info("🚀 Starting Telegram Bot with PHP support...")

    run_bot()
[file content end]