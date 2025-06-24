import telebot
import requests
import time
import json
import os
import random
import string
from datetime import datetime, timedelta
from threading import Thread, Event, Lock

# --- Flask for Keep Alive ---
from flask import Flask, request
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# --- Cấu hình Bot (Lấy từ biến môi trường để bảo mật) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7630248769:AAG36CSLxWWovAfa-Byjh_DohcpN3pA94Iw") # THAY THẾ BẰNG TOKEN THẬT CỦA BẠN HOẶC ĐẶT BIẾN MÔI TRƯỜNG
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "6915752059,6285177749") # THAY THẾ BẰNG ID ADMIN THẬT CỦA BẠN
ADMIN_IDS = [int(id) for id in ADMIN_IDS_STR.split(',') if id.strip()]

API_URL = "https://wanglinapiws.up.railway.app/api/taixiu"

# --- Constants ---
GAME_SUNWIN = "Sunwin"
GAME_88VIN = "88vin" # Placeholder for future game

# ======================= DANH SÁCH CẦU ĐẸP & CẦU XẤU =======================
# Cầu đẹp: Tổng từ 9 đến 12 và không phải bộ 3 (không trùng)
cau_dep = {
    (1, 2, 6), (1, 4, 4), (1, 5, 3), (1, 6, 2),
    (2, 1, 6), (2, 2, 5), (2, 3, 4), (2, 4, 3), (2, 5, 2),
    (3, 1, 5), (3, 2, 4), (3, 3, 3), (3, 4, 2), (3, 5, 1),
    (4, 1, 4), (4, 2, 3), (4, 3, 2), (4, 4, 1),
    (5, 1, 4), (5, 3, 1),
    (6, 1, 2), (6, 2, 1),

    (1, 1, 7), (1, 2, 6), (1, 3, 5), (1, 4, 4), (1, 5, 3), (1, 6, 2),
    (2, 1, 6), (2, 2, 5), (2, 3, 4), (2, 4, 3), (2, 5, 2), (2, 6, 1),
    (3, 1, 5), (3, 2, 4), (3, 3, 3), (3, 4, 2), (3, 5, 1),
    (4, 1, 4), (4, 2, 3), (4, 3, 2), (4, 4, 1), (5, 2, 2), (5, 3, 1),
    (6, 1, 2), (6, 2, 1),(3,4,1),(6,4,5),(1,6,3),(2,6,4),(6,1,4),(1,3,2),(2,4,5),(1,3,4),(1,5,1),(3,6,6),(3,6,4),(5,4,6),(3,1,6),(1,3,6),(2,2,4),(1,5,3),(2,4,5),(2,1,2),(6,1,4),(4,6,6),(4,3,5),(3,2,5),(3,4,2),(1,6,4),(6,4,4),(2,3,1),(1,2,1),(6,2,5),(3,1,3),(5,5,1),(4,5,4),(4,6,1),(3,6,1)
}

# Các mẫu còn lại là cầu xấu (tổng <9 hoặc >12 hoặc là bộ 3)
# Đã lọc ra thủ công
cau_xau = {
    (1, 1, 1), (1, 1, 2), (1, 1, 3), (1, 1, 4), (1, 1, 5), (1, 1, 6),
    (1, 2, 2), (1, 2, 3), (1, 2, 4), (1, 2, 5),
    (1, 3, 1), (1, 3, 3),
    (1, 4, 1), (1, 4, 2), (1, 4, 3),
     (1, 5, 2),
    (1, 6, 1), (1, 6, 6),
    (2, 1, 1), (2, 1, 3), (2, 1, 4), (2, 1, 5),
    (2, 2, 1), (2, 2, 2), (2, 2, 3),
     (2, 3, 2), (2, 3, 3),
    (2, 4, 1), (2, 4, 2),
    (2, 5, 1), (2, 5, 6),
    (2, 6, 5), (2, 6, 6),
    (3, 1, 1), (3, 1, 2), (3, 1, 4),
    (3, 2, 1), (3, 2, 2), (3, 2, 3),
    (3, 3, 1), (3, 3, 2), (3, 3, 3), (3, 4, 6),
    (3, 5, 5), (3, 5, 6),
    (3, 6, 5),
    (4, 1, 2), (4, 1, 3),
    (4, 2, 1), (4, 2, 2),
    (4, 3, 1), (4, 3, 6),
    (4, 4, 4), (4, 4, 5), (4, 4, 6),
    (4, 5, 5), (4, 5, 6),
    (4, 6, 3), (4, 6, 4), (4, 6, 5),
    (5, 1, 1), (5, 1, 2),
    (5, 2, 1), (5, 2, 6),
    (5, 3, 6),
    (5, 4, 5),
    (5, 5, 5), (5, 5, 6),
    (5, 6, 4), (5, 6, 5), (5, 6, 6),
    (6, 1, 1),
    (6, 2, 6),
    (6, 3, 6),
    (6, 5, 6),
    (6, 6, 1), (6, 6, 2), (6, 6, 3), (6, 6, 4), (6, 6, 5), (6, 6, 6),(5,1,3),(2,6,1),(6,4,6),(5,2,2),(2,1,2),(4,4,1),(1,2,1),(1,3,5)
}

# --- Biến toàn cục và Lock để đảm bảo an toàn Thread ---
bot = telebot.TeleBot(BOT_TOKEN)
user_states = {}  # {chat_id: {"awaiting_key": True/False, "selected_game": None, "bot_running": True/False}}
active_keys = {}  # {key: {"user_id": int, "username": str, "expiry": datetime, "limit_seconds": int}}
user_preferences = {} # {user_id: {"game": "Sunwin", "notify": True/False, "last_session_id": None, "key_active": True/False}}
admin_users = set(ADMIN_IDS) # Use a set for faster lookups

# Threading control
prediction_thread = None
stop_event = Event()
data_lock = Lock() # To protect shared data like user_preferences and active_keys

# --- Utility Functions ---
def is_admin(user_id):
    return user_id in admin_users

def generate_key(length=8):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def parse_time_duration(value, unit):
    try:
        value = int(value)
        unit = unit.lower()
        if 'phút' in unit or 'phut' in unit:
            return timedelta(minutes=value)
        elif 'giờ' in unit or 'gio' in unit:
            return timedelta(hours=value)
        elif 'ngày' in unit:
            return timedelta(days=value)
        elif 'tuần' in unit:
            return timedelta(weeks=value)
        elif 'tháng' in unit:
            return timedelta(days=value * 30) # Approximate
        elif 'năm' in unit:
            return timedelta(days=value * 365) # Approximate
    except ValueError:
        return None
    return None

def save_data():
    with data_lock:
        data = {
            "user_states": user_states,
            "active_keys": {k: {**v, 'expiry': v['expiry'].isoformat() if v.get('expiry') else None} for k, v in active_keys.items()},
            "user_preferences": user_preferences,
            "admin_users": list(admin_users)
        }
        with open("bot_data.json", "w") as f:
            json.dump(data, f, indent=4)

def load_data():
    global user_states, active_keys, user_preferences, admin_users
    try:
        with open("bot_data.json", "r") as f:
            data = json.load(f)
            user_states = data.get("user_states", {})
            
            loaded_keys = data.get("active_keys", {})
            active_keys = {}
            for k, v in loaded_keys.items():
                if v.get('expiry'):
                    try:
                        v['expiry'] = datetime.fromisoformat(v['expiry'])
                    except ValueError: # Handle cases where expiry might be malformed
                        v['expiry'] = None # Set to None or a default if conversion fails
                active_keys[k] = v
            
            user_preferences = data.get("user_preferences", {})
            admin_users = set(data.get("admin_users", ADMIN_IDS))
            
            # Ensure existing users from preferences also have an entry in user_states if missing
            for user_id_str in user_preferences.keys():
                user_id = int(user_id_str)
                if user_id not in user_states:
                    user_states[user_id] = {"awaiting_key": False} # Assume they are past key entry stage
                # Clean up expired keys for active users
                if user_preferences[user_id_str].get("key_active"):
                    found_active_key = False
                    for key_name, key_info in active_keys.items():
                        if key_info.get("user_id") == user_id:
                            if key_info.get("expiry") and key_info["expiry"] < datetime.now():
                                print(f"Key {key_name} for user {user_id} expired. Deactivating user.")
                                user_preferences[user_id_str]["key_active"] = False
                                user_preferences[user_id_str]["notify"] = False
                                del active_keys[key_name] # Remove expired key
                                break
                            found_active_key = True
                            break
                    if not found_active_key: # User was active but no active key found
                        print(f"User {user_id} was active but no corresponding active key found. Deactivating.")
                        user_preferences[user_id_str]["key_active"] = False
                        user_preferences[user_id_str]["notify"] = False

    except (FileNotFoundError, json.JSONDecodeError):
        print("No existing data found or data corrupted. Starting fresh.")
        # Ensure default ADMIN_IDS are included if starting fresh
        admin_users.update(ADMIN_IDS)
        save_data() # Save initial state if no file or corrupted

# ======================= HÀM XỬ LÝ DỰ ĐOÁN =======================
def du_doan_theo_xi_ngau(dice):
    d1, d2, d3 = dice
    total = d1 + d2 + d3
    result_list = []

    for d in [d1, d2, d3]:
        tmp = d + total
        if tmp in [4, 5]:
            tmp -= 4
        elif tmp >= 6:
            tmp -= 6
        result_list.append("Tài" if tmp % 2 == 0 else "Xỉu")

    tai_count = result_list.count("Tài")
    prediction = "Tài" if tai_count >= 2 else "Xỉu"

    # Phân loại cầu theo danh sách đã liệt kê
    if dice in cau_dep:
        loai_cau = "Cầu đẹp"
    elif dice in cau_xau:
        loai_cau = "Cầu xấu"
        prediction = "Xỉu" if prediction == "Tài" else "Tài" # Invert prediction for bad patterns
    else:
        loai_cau = "Không xác định" # Should ideally not happen if lists are comprehensive

    return {
        "xuc_xac": dice,
        "tong": total,
        "cau": loai_cau,
        "du_doan": prediction,
        "chi_tiet": result_list
    }

def lay_du_lieu_api():
    try:
        response = requests.get(API_URL, timeout=5)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.Timeout:
        print("❌ Lỗi API: Yêu cầu hết thời gian.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi kết nối API: {e}")
        return None

def prediction_worker():
    last_processed_session = None # Global last processed session to prevent re-processing
    while not stop_event.is_set():
        data = lay_du_lieu_api()
        if not data:
            time.sleep(2)
            continue

        current_session = data.get("Phien")
        dice = (
            data.get("Xuc_xac_1"),
            data.get("Xuc_xac_2"),
            data.get("Xuc_xac_3")
        )

        if not (current_session and all(isinstance(x, int) for x in dice)):
            time.sleep(2)
            continue

        if current_session == last_processed_session:
            time.sleep(2)
            continue # Already processed this session

        # Process this new session
        last_processed_session = current_session
        ket_qua = du_doan_theo_xi_ngau(dice)
        prediction_for_next_session = ket_qua['du_doan']

        with data_lock:
            # Check and remove expired keys first
            keys_to_delete = []
            for key_name, key_info in active_keys.items():
                if key_info.get("expiry") and key_info["expiry"] < datetime.now():
                    user_id_associated = key_info.get("user_id")
                    if user_id_associated and str(user_id_associated) in user_preferences:
                        user_preferences[str(user_id_associated)]["key_active"] = False
                        user_preferences[str(user_id_associated)]["notify"] = False
                        try:
                            bot.send_message(user_id_associated, f"🔑 Key của bạn đã hết hạn. Vui lòng liên hệ admin để gia hạn hoặc mua key mới.", parse_mode='Markdown')
                        except telebot.apihelper.ApiException as e:
                            print(f"Could not send expiry message to {user_id_associated}: {e}")
                    keys_to_delete.append(key_name)
            
            for key_name in keys_to_delete:
                del active_keys[key_name]
            
            # Now send notifications to active users
            for user_id_str, prefs in list(user_preferences.items()):
                user_id = int(user_id_str)
                if prefs.get("notify") and prefs.get("game") == GAME_SUNWIN and prefs.get("key_active"):
                    # Only send if the session is new for this user, or if last_session_id is None
                    if prefs.get("last_session_id") != current_session:
                        message = (
                            f"🎮 **KẾT QUẢ PHIÊN HIỆN TẠI Sunwin** 🎮\n"
                            f"Phiên: `{current_session}` | Kết quả: `{'Tài' if ket_qua['tong'] > 10 else 'Xỉu'}` (Tổng: `{ket_qua['tong']}`)\n\n"
                            f"**Dự đoán cho phiên tiếp theo:**\n"
                            f"🔢 Phiên: `{current_session + 1}`\n"
                            f"🤖 Dự đoán: `{prediction_for_next_session}`\n"
                            f"⚠️ **Chúc Bạn May Mắn!**"
                        )
                        try:
                            bot.send_message(user_id, message, parse_mode='Markdown')
                            prefs["last_session_id"] = current_session # Update last notified session
                            user_preferences[user_id_str] = prefs # Save updated preference
                        except telebot.apihelper.ApiException as e:
                            print(f"Error sending message to {user_id}: {e}")
                            if "bot was blocked by the user" in str(e) or "chat not found" in str(e):
                                print(f"Removing {user_id} from notifications as bot was blocked.")
                                prefs["notify"] = False
                                user_preferences[user_id_str] = prefs # Persist the change
                            elif "Too Many Requests" in str(e):
                                print(f"Rate limited for user {user_id}. Will retry later.")
                                pass # Don't update last_session_id so it gets retried
                            else:
                                print(f"Unhandled Telegram API error for user {user_id}: {e}")
                        except Exception as e:
                            print(f"An unexpected error occurred for user {user_id}: {e}")
            save_data() # Save all changes after iterating through users
        time.sleep(2) # Wait before next API call

# --- Bot Handlers ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    user_preferences.setdefault(str(user_id), {"key_active": False, "game": None, "notify": False, "last_session_id": None})
    user_states.setdefault(user_id, {"awaiting_key": False})

    # Check if the user has an active key
    is_active = user_preferences[str(user_id)].get("key_active", False)
    
    # Also check if their assigned key has expired
    if is_active:
        key_expired = True
        with data_lock:
            for key_name, key_info in active_keys.items():
                if key_info.get("user_id") == user_id:
                    if key_info.get("expiry") and key_info["expiry"] < datetime.now():
                        print(f"Key {key_name} for user {user_id} expired during /start check.")
                        user_preferences[str(user_id)]["key_active"] = False
                        user_preferences[str(user_id)]["notify"] = False
                        del active_keys[key_name]
                        is_active = False # Mark as inactive
                        break
                    else:
                        key_expired = False
                        break
            if key_expired and user_preferences[str(user_id)]["key_active"]: # If key_active was true but no non-expired key found
                user_preferences[str(user_id)]["key_active"] = False
                user_preferences[str(user_id)]["notify"] = False
                is_active = False # Mark as inactive
        save_data()

    welcome_message = (
        "🔔 **HƯỚNG DẪN SỬ DỤNG BOT**\n"
        "══════════════════════════\n"
        "🔑 Lệnh cơ bản:\n"
        "- `/start`: Hiển thị thông tin chào mừng\n"
        "- `/key <key>`: Nhập key để kích hoạt bot\n"
        "- `/chaybot`: Bật nhận thông báo dự đoán tự động (sẽ hỏi chọn game)\n"
        "- `/tatbot`: Tắt nhận thông báo dự đoán tự động\n"
        "- `/lichsu`: Xem lịch sử 10 phiên gần nhất của game bạn đang chọn\n\n"
    )
    if is_admin(user_id):
        welcome_message += (
            "🛡️ Lệnh admin:\n"
            "- `/taokey <tên_key> [giới_hạn_số] [đơn_vị_thời_gian]`: Tạo key mới. Ví dụ: `/taokey MYKEY123 1 ngày`, `/taokey VIPKEY 24 giờ`, `/taokey TESTKEY 30 phút`\n"
            "- `/lietkekey`: Liệt kê tất cả key và trạng thái sử dụng\n"
            "- `/xoakey <key>`: Xóa key khỏi hệ thống\n"
            "- `/themadmin <id>`: Thêm ID người dùng làm admin\n"
            "- `/xoaadmin <id>`: Xóa ID người dùng khỏi admin\n"
            "- `/danhsachadmin`: Xem danh sách các ID admin\n"
            "- `/broadcast [tin nhắn]`: Gửi thông báo đến tất cả người dùng\n\n"
        )
    welcome_message += "══════════════════════════\n👥 Liên hệ admin để được hỗ trợ thêm."

    if not is_active:
        bot.reply_to(message, "Chào mừng bạn! Vui lòng nhập key để sử dụng bot. Sử dụng lệnh `/key <key_của_bạn>`\n\n" + welcome_message, parse_mode='Markdown')
        user_states[user_id]["awaiting_key"] = True
    else:
        bot.reply_to(message, "Chào mừng bạn trở lại! Bot đã sẵn sàng.\n\n" + welcome_message, parse_mode='Markdown')
        user_states[user_id]["awaiting_key"] = False
    save_data()


@bot.message_handler(commands=['key'])
def handle_key(message):
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Vui lòng nhập key sau lệnh /key. Ví dụ: `/key ABCXYZ`", parse_mode='Markdown')
        return

    key = args[1].strip()
    with data_lock:
        if key in active_keys:
            key_info = active_keys[key]
            
            # Check if key is expired before assigning
            if key_info.get("expiry") and key_info["expiry"] < datetime.now():
                bot.reply_to(message, "❌ Key này đã hết hạn. Vui lòng liên hệ admin.")
                del active_keys[key] # Clean up expired key immediately
                save_data()
                return

            if key_info.get("user_id") is None: # Key is not yet assigned
                key_info["user_id"] = chat_id
                key_info["username"] = message.from_user.username or message.from_user.first_name

                if key_info.get("limit_seconds") is not None:
                    key_info["expiry"] = datetime.now() + timedelta(seconds=key_info["limit_seconds"])
                else:
                    key_info["expiry"] = datetime.max # Effectively never expires if limit_seconds is not set

                user_preferences[str(chat_id)] = {"key_active": True, "game": None, "notify": False, "last_session_id": None}
                user_states[chat_id] = {"awaiting_key": False}
                bot.reply_to(message, f"🥳 Key `{key}` đã được kích hoạt thành công! Bạn có thể bắt đầu sử dụng bot.", parse_mode='Markdown')
                save_data()
            elif key_info.get("user_id") == chat_id:
                bot.reply_to(message, f"Bạn đã kích hoạt key `{key}` rồi.", parse_mode='Markdown')
            else:
                bot.reply_to(message, "❌ Key này đã được sử dụng bởi người khác.")
        else:
            bot.reply_to(message, "❌ Key không hợp lệ hoặc không tồn tại.")

@bot.message_handler(commands=['chaybot'])
def start_bot_notifications(message):
    chat_id = message.chat.id
    if str(chat_id) not in user_preferences or not user_preferences[str(chat_id)].get("key_active"):
        bot.reply_to(message, "Vui lòng kích hoạt bot bằng key trước khi sử dụng chức năng này. Dùng lệnh `/key <key>`.", parse_mode='Markdown')
        return

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("Sunwin", callback_data=f"select_game_{GAME_SUNWIN}"))
    # markup.add(telebot.types.InlineKeyboardButton("88vin", callback_data=f"select_game_{GAME_88VIN}")) # Example for another game
    bot.reply_to(message, "Chọn game bạn muốn nhận thông báo:", reply_markup=markup)

@bot.message_handler(commands=['tatbot'])
def stop_bot_notifications(message):
    chat_id = message.chat.id
    with data_lock:
        if str(chat_id) in user_preferences:
            user_preferences[str(chat_id)]["notify"] = False
            bot.reply_to(message, "Bot dự đoán đã được tắt. Bạn sẽ không nhận được thông báo tự động nữa.")
            save_data()
        else:
            bot.reply_to(message, "Bạn chưa bật bot dự đoán.")

@bot.message_handler(commands=['lichsu'])
def show_history(message):
    chat_id = message.chat.id
    if str(chat_id) not in user_preferences or not user_preferences[str(chat_id)].get("key_active"):
        bot.reply_to(message, "Vui lòng kích hoạt bot bằng key trước khi sử dụng chức năng này. Dùng lệnh `/key <key>`.", parse_mode='Markdown')
        return

    selected_game = user_preferences[str(chat_id)].get("game")
    if not selected_game:
        bot.reply_to(message, "Bạn chưa chọn game nào để xem lịch sử. Vui lòng chạy `/chaybot` để chọn game trước.", parse_mode='Markdown')
        return

    bot.reply_to(message, f"Đang lấy lịch sử 10 phiên gần nhất cho game `{selected_game}`...", parse_mode='Markdown')

    try:
        # Assuming API_URL can handle /history for general history or /taixiu/history for specific
        # Based on your prompt, the primary API is for taixiu, so we'll just show the latest from that.
        # If the API provided a separate /history endpoint for all games, it would be different.
        response = requests.get(API_URL, timeout=5) # Re-using the main API for latest data
        response.raise_for_status()
        current_data = response.json()

        # To get proper history, you'd ideally need an API endpoint like:
        # requests.get(f"{API_URL}/history?limit=10")
        # For now, we'll simulate by fetching the latest and assuming it's part of a historical sequence
        # THIS PART NEEDS A PROPER API HISTORY ENDPOINT TO WORK AS INTENDED
        
        history_messages = []
        if current_data:
            session = current_data.get("Phien")
            dice = (current_data.get("Xuc_xac_1"), current_data.get("Xuc_xac_2"), current_data.get("Xuc_xac_3"))
            if all(isinstance(d, int) for d in dice):
                total = sum(dice)
                result_type = "Tài" if total > 10 else "Xỉu"
                history_messages.append(f"Phiên: `{session}` | Xúc xắc: `{dice}` | Tổng: `{total}` | Kết quả: `{result_type}`")
            else:
                history_messages.append(f"Phiên: `{session}` | Dữ liệu không đầy đủ.")
        
        if history_messages:
            bot.send_message(chat_id, "**Lịch sử 1 phiên gần nhất (chỉ lấy được 1 phiên từ API hiện tại):**\n" + "\n".join(history_messages), parse_mode='Markdown')
            bot.send_message(chat_id, "⚠️ **Lưu ý:** Để có lịch sử đầy đủ 10 phiên, API cần hỗ trợ endpoint lịch sử chuyên biệt.")
        else:
            bot.send_message(chat_id, "Không có dữ liệu lịch sử.")

    except requests.exceptions.RequestException as e:
        bot.send_message(chat_id, f"❌ Lỗi khi lấy dữ liệu từ API: {e}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Đã xảy ra lỗi: {e}")

# --- Admin Commands ---
@bot.message_handler(commands=['taokey'])
def create_key(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = message.text.split(maxsplit=3) # /taokey <tên_key> [số] [đơn_vị]
    if len(args) < 2:
        bot.reply_to(message, "Vui lòng cung cấp tên key. Cú pháp: `/taokey <tên_key> [giới_hạn_số] [đơn_vị_thời_gian]`.\nVí dụ: `/taokey MYKEY123 1 ngày`, `/taokey VIPKEY 24 giờ`, `/taokey TESTKEY 30 phút`", parse_mode='Markdown')
        return

    key_name = args[1].strip()
    limit_seconds = None # Default to no time limit (manual deletion)
    expiry_message = "không giới hạn"

    if len(args) == 4: # e.g., /taokey MYKEY 1 ngay
        try:
            value = int(args[2])
            unit = args[3].lower()
            duration_td = parse_time_duration(value, unit)
            if duration_td:
                limit_seconds = duration_td.total_seconds()
                expiry_message = f"hết hạn sau {value} {unit}"
            else:
                bot.reply_to(message, "Đơn vị thời gian không hợp lệ. Vui lòng sử dụng 'phút', 'giờ', 'ngày', 'tuần', 'tháng', 'năm'.")
                return
        except ValueError:
            bot.reply_to(message, "Số lượng thời gian không hợp lệ. Vui lòng nhập một số nguyên.")
            return

    with data_lock:
        if key_name in active_keys:
            bot.reply_to(message, f"Key `{key_name}` đã tồn tại.", parse_mode='Markdown')
            return

        active_keys[key_name] = {
            "user_id": None,
            "username": None,
            "expiry": None, # Will be set upon activation
            "limit_seconds": limit_seconds 
        }
        save_data()
        bot.reply_to(message, f"🔑 Key `{key_name}` đã được tạo thành công, {expiry_message}. Vui lòng chia sẻ cho người dùng.", parse_mode='Markdown')

@bot.message_handler(commands=['lietkekey'])
def list_keys(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    with data_lock:
        if not active_keys:
            bot.reply_to(message, "Hiện không có key nào được tạo.")
            return

        key_list_messages = ["**DANH SÁCH KEY HIỆN CÓ:**"]
        current_time = datetime.now()
        
        for key, info in active_keys.items():
            status = "Chưa kích hoạt"
            expiry_info = ""
            
            if info.get("user_id"):
                status = f"Đã kích hoạt bởi user ID: `{info['user_id']}`"
                if info.get("username"):
                    status += f" (username: `{info['username']}`)"
                
                if info.get("expiry"):
                    if info['expiry'] == datetime.max:
                        expiry_info = " (Vĩnh viễn)"
                    elif info['expiry'] > current_time:
                        expiry_info = f" (Hết hạn: `{info['expiry'].strftime('%Y-%m-%d %H:%M:%S')}`)"
                    else:
                        expiry_info = " (Đã hết hạn)"
                status += expiry_info
            
            key_list_messages.append(f"- `{key}`: {status}")

        bot.reply_to(message, "\n".join(key_list_messages), parse_mode='Markdown')

@bot.message_handler(commands=['xoakey'])
def delete_key(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Vui lòng cung cấp tên key cần xóa. Ví dụ: `/xoakey MYKEY123`", parse_mode='Markdown')
        return

    key_to_delete = args[1].strip()
    with data_lock:
        if key_to_delete in active_keys:
            user_id_associated = active_keys[key_to_delete].get("user_id")
            if user_id_associated and str(user_id_associated) in user_preferences:
                # Invalidate user's key status and notification
                user_preferences[str(user_id_associated)]["key_active"] = False
                user_preferences[str(user_id_associated)]["notify"] = False
                try:
                    bot.send_message(user_id_associated, f"⚠️ Key của bạn (`{key_to_delete}`) đã bị admin xóa. Bot sẽ ngừng hoạt động. Vui lòng liên hệ admin để biết thêm chi tiết.", parse_mode='Markdown')
                except telebot.apihelper.ApiException as e:
                    print(f"Could not send key deletion message to {user_id_associated}: {e}")
            del active_keys[key_to_delete]
            save_data()
            bot.reply_to(message, f"Key `{key_to_delete}` đã được xóa thành công và người dùng liên kết (nếu có) đã bị hủy kích hoạt.", parse_mode='Markdown')
        else:
            bot.reply_to(message, "Key không tồn tại.")

@bot.message_handler(commands=['themadmin'])
def add_admin(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Vui lòng cung cấp ID người dùng cần thêm làm admin. Ví dụ: `/themadmin 123456789`", parse_mode='Markdown')
        return

    try:
        new_admin_id = int(args[1].strip())
        with data_lock:
            if new_admin_id not in admin_users:
                admin_users.add(new_admin_id)
                save_data()
                bot.reply_to(message, f"Người dùng có ID `{new_admin_id}` đã được thêm vào danh sách admin.", parse_mode='Markdown')
            else:
                bot.reply_to(message, f"Người dùng có ID `{new_admin_id}` đã là admin rồi.", parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "ID người dùng không hợp lệ. Vui lòng nhập một số nguyên.")

@bot.message_handler(commands=['xoaadmin'])
def remove_admin(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Vui lòng cung cấp ID người dùng cần xóa khỏi admin. Ví dụ: `/xoaadmin 123456789`", parse_mode='Markdown')
        return

    try:
        admin_to_remove_id = int(args[1].strip())
        with data_lock:
            if admin_to_remove_id in admin_users:
                if len(admin_users) == 1:
                    bot.reply_to(message, "Không thể xóa admin cuối cùng. Phải có ít nhất một admin.")
                    return
                admin_users.remove(admin_to_remove_id)
                save_data()
                bot.reply_to(message, f"Người dùng có ID `{admin_to_remove_id}` đã được xóa khỏi danh sách admin.", parse_mode='Markdown')
            else:
                bot.reply_to(message, "ID người dùng không có trong danh sách admin.")
    except ValueError:
        bot.reply_to(message, "ID người dùng không hợp lệ. Vui lòng nhập một số nguyên.")

@bot.message_handler(commands=['danhsachadmin'])
def list_admins(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    with data_lock:
        if not admin_users:
            bot.reply_to(message, "Hiện không có admin nào được thêm.")
            return

        admin_list_messages = ["**DANH SÁCH ADMIN HIỆN CÓ:**"]
        for admin_id in admin_users:
            admin_list_messages.append(f"- ID: `{admin_id}`")

        bot.reply_to(message, "\n".join(admin_list_messages), parse_mode='Markdown')


@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Vui lòng cung cấp nội dung tin nhắn broadcast. Ví dụ: `/broadcast Chào mọi người!`", parse_mode='Markdown')
        return

    broadcast_text = args[1].strip()
    with data_lock:
        sent_count = 0
        failed_count = 0
        for uid_str, prefs in list(user_preferences.items()): # Iterate over a copy
            # Only broadcast to users with an active key
            if prefs.get("key_active", False):
                try:
                    bot.send_message(int(uid_str), broadcast_text, parse_mode='Markdown')
                    sent_count += 1
                    time.sleep(0.05) # Delay to avoid hitting Telegram API limits
                except telebot.apihelper.ApiException as e:
                    print(f"Failed to send broadcast to {uid_str}: {e}")
                    failed_count += 1
                    if "bot was blocked by the user" in str(e) or "chat not found" in str(e):
                        # User blocked the bot, deactivate their key and notify
                        print(f"User {uid_str} blocked bot, deactivating key.")
                        prefs["key_active"] = False
                        prefs["notify"] = False
                        user_preferences[uid_str] = prefs # Update in original dict
                        # Also remove their key from active_keys if found
                        for key_name, key_info in active_keys.items():
                            if key_info.get("user_id") == int(uid_str):
                                del active_keys[key_name]
                                break
                except Exception as e:
                    print(f"An unexpected error occurred during broadcast to {uid_str}: {e}")
                    failed_count += 1
        save_data() # Save data after potential deactivations
        bot.reply_to(message, f"Đã gửi broadcast tới {sent_count} người dùng thành công, {failed_count} thất bại.")

# --- Callback Query Handler ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('select_game_'))
def callback_game_selection(call):
    chat_id = call.message.chat.id
    game = call.data.split('_')[2]

    with data_lock:
        if str(chat_id) in user_preferences and user_preferences[str(chat_id)].get("key_active"):
            user_preferences[str(chat_id)]["game"] = game
            user_preferences[str(chat_id)]["notify"] = True
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Tuyệt vời! Bạn đã chọn game **{game}**. Bot sẽ bắt đầu gửi thông báo dự đoán cho game này.",
                parse_mode='Markdown'
            )
            save_data()
            bot.answer_callback_query(call.id, text=f"Đã chọn game {game}")
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Có lỗi xảy ra hoặc key của bạn không còn hoạt động. Vui lòng thử lại lệnh `/chaybot` hoặc kích hoạt key.",
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id, text="Lỗi kích hoạt hoặc key không hợp lệ.")


# --- Main execution ---
if __name__ == "__main__":
    load_data()
    print("Starting Flask server for keep-alive...")
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True # Allow main program to exit even if this thread is running
    flask_thread.start()

    print("Starting prediction worker thread...")
    prediction_thread = Thread(target=prediction_worker)
    prediction_thread.daemon = True
    prediction_thread.start()

    print("Starting Telegram bot polling...")
    try:
        # Increase polling interval slightly to be less aggressive, could help with stability
        bot.polling(none_stop=True, interval=1) 
    except Exception as e:
        print(f"Bot polling stopped due to an error: {e}")
    finally:
        stop_event.set() # Signal prediction thread to stop
        print("Bot stopped. Waiting for threads to finish...")
        if prediction_thread.is_alive():
            prediction_thread.join(timeout=5) # Give it some time to finish
        print("Threads terminated.")

