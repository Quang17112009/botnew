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

# --- Cấu hình Bot ---
BOT_TOKEN = "7630248769:AAG36CSLxWWovAfa-Byjh_DohcpN3pA94Iw"
ADMIN_IDS = [6915752059, 6285177749] # Make sure these are integers

API_URL = "https://wanglinapiws.up.railway.app/api/taixiu"

# --- Constants ---
GAME_SUNWIN = "Sunwin"
GAME_88VIN = "88vin" # Placeholder for future game, not implemented in API logic provided

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
active_keys = {}  # {key: {"user_id": int, "username": str, "expiry": datetime, "limit": int}}
user_preferences = {} # {user_id: {"game": "Sunwin", "notify": True/False, "last_session_id": None}}
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

def parse_time_duration(duration_str):
    if not duration_str:
        return None
    try:
        value = int(duration_str.split(' ')[0])
        unit = duration_str.split(' ')[1].lower()
        if 'giờ' in unit or 'gio' in unit:
            return timedelta(hours=value)
        elif 'ngày' in unit:
            return timedelta(days=value)
        elif 'tuần' in unit:
            return timedelta(weeks=value)
        elif 'tháng' in unit:
            return timedelta(days=value * 30) # Approximate
        elif 'năm' in unit:
            return timedelta(days=value * 365) # Approximate
    except (ValueError, IndexError):
        return None
    return None

def save_data():
    with data_lock:
        data = {
            "user_states": user_states,
            "active_keys": {k: {**v, 'expiry': v['expiry'].isoformat()} for k, v in active_keys.items()},
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
            active_keys = {k: {**v, 'expiry': datetime.fromisoformat(v['expiry'])} for k, v in data.get("active_keys", {}).items()}
            user_preferences = data.get("user_preferences", {})
            admin_users = set(data.get("admin_users", ADMIN_IDS)) # Load and ensure initial ADMIN_IDS are present
    except (FileNotFoundError, json.JSONDecodeError):
        print("No existing data found or data corrupted. Starting fresh.")
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
    last_session_info = {} # {chat_id: last_session_id}
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
            # print("⚠️ Dữ liệu API không đầy đủ hoặc không hợp lệ.")
            time.sleep(2)
            continue

        with data_lock:
            for user_id_str, prefs in list(user_preferences.items()): # Use list() to iterate over a copy
                user_id = int(user_id_str)
                if prefs.get("notify") and prefs.get("game") == GAME_SUNWIN:
                    last_notified_session = prefs.get("last_session_id")
                    if current_session != last_notified_session:
                        ket_qua = du_doan_theo_xi_ngau(dice)
                        prediction_for_next_session = ket_qua['du_doan']
                        
                        message = (
                            f"🎮 **KẾT QUẢ PHIÊN HIỆN TẠI Sunwin** 🎮\n"
                            f"Phiên: `{current_session}` | Kết quả: `{ 'Tài' if ket_qua['tong'] > 10 else 'Xỉu' }` (Tổng: `{ket_qua['tong']}`)\n\n"
                            f"**Dự đoán cho phiên tiếp theo:**\n"
                            f"🔢 Phiên: `{current_session + 1}`\n"
                            f"🤖 Dự đoán: `{prediction_for_next_session}`\n"
                            f"⚠️ **Chúc Bạn May Mắn!**"
                        )
                        try:
                            bot.send_message(user_id, message, parse_mode='Markdown')
                            prefs["last_session_id"] = current_session # Update last notified session
                            user_preferences[user_id_str] = prefs # Save updated preference
                            save_data() # Save data after updating user preference
                        except telebot.apihelper.ApiException as e:
                            print(f"Error sending message to {user_id}: {e}")
                            if "bot was blocked by the user" in str(e) or "chat not found" in str(e):
                                # User blocked the bot, remove them from notifications
                                print(f"Removing {user_id} from notifications as bot was blocked.")
                                prefs["notify"] = False
                                user_preferences[user_id_str] = prefs
                                save_data() # Persist the change
                        except Exception as e:
                            print(f"An unexpected error occurred for user {user_id}: {e}")

        time.sleep(2)

# --- Bot Handlers ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    if str(user_id) in user_preferences and user_preferences[str(user_id)].get("key_active"):
        welcome_message = (
            "Chào mừng bạn trở lại! Bot đã sẵn sàng.\n\n"
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
                "- `/taokey <tên_key> [giới_hạn] [thời_gian]`: Tạo key mới. Ví dụ: `/taokey MYKEY123 1 ngày`, `/taokey VIPKEY 24 giờ`\n"
                "- `/lietkekey`: Liệt kê tất cả key và trạng thái sử dụng\n"
                "- `/xoakey <key>`: Xóa key khỏi hệ thống\n"
                "- `/themadmin <id>`: Thêm ID người dùng làm admin\n"
                "- `/xoaadmin <id>`: Xóa ID người dùng khỏi admin\n"
                "- `/danhsachadmin`: Xem danh sách các ID admin\n"
                "- `/broadcast [tin nhắn]`: Gửi thông báo đến tất cả người dùng\n\n"
            )
        welcome_message += "══════════════════════════\n👥 Liên hệ admin để được hỗ trợ thêm."
        bot.reply_to(message, welcome_message, parse_mode='Markdown')
    else:
        bot.reply_to(message, "Chào mừng bạn! Vui lòng nhập key để sử dụng bot. Sử dụng lệnh `/key <key_của_bạn>`")
        user_states[user_id] = {"awaiting_key": True}
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
            if key_info.get("user_id") is None: # Key is not yet assigned
                key_info["user_id"] = chat_id
                key_info["username"] = message.from_user.username or message.from_user.first_name
                key_info["expiry"] = datetime.now() + timedelta(days=key_info.get("limit", 0)) if key_info.get("limit") else datetime.max # Set expiry or effectively never expire
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
        response = requests.get(f"{API_URL}/history?limit=10", timeout=5) # Assuming API has a history endpoint
        response.raise_for_status()
        history_data = response.json()

        if not history_data:
            bot.send_message(chat_id, "Không có dữ liệu lịch sử.")
            return

        history_messages = []
        for entry in history_data:
            session = entry.get("Phien")
            dice = (entry.get("Xuc_xac_1"), entry.get("Xuc_xac_2"), entry.get("Xuc_xac_3"))
            if all(isinstance(d, int) for d in dice):
                total = sum(dice)
                result_type = "Tài" if total > 10 else "Xỉu"
                history_messages.append(f"Phiên: `{session}` | Xúc xắc: `{dice}` | Tổng: `{total}` | Kết quả: `{result_type}`")
            else:
                history_messages.append(f"Phiên: `{session}` | Dữ liệu không đầy đủ.")

        bot.send_message(chat_id, "**Lịch sử 10 phiên gần nhất:**\n" + "\n".join(history_messages), parse_mode='Markdown')

    except requests.exceptions.RequestException as e:
        bot.send_message(chat_id, f"❌ Lỗi khi lấy lịch sử từ API: {e}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Đã xảy ra lỗi: {e}")

# --- Admin Commands ---
@bot.message_handler(commands=['taokey'])
def create_key(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = message.text.split(maxsplit=3) # /taokey <tên_key> [giới_hạn] [thời_gian]
    if len(args) < 2:
        bot.reply_to(message, "Vui lòng cung cấp tên key. Cú pháp: `/taokey <tên_key> [giới_hạn_sử_dụng] [thời_gian]`.\nVí dụ: `/taokey MYKEY123 1 ngày`, `/taokey VIPKEY 24 giờ`", parse_mode='Markdown')
        return

    key_name = args[1].strip()
    limit = 0 # Default to no time limit (manual deletion)
    expiry_message = "không giới hạn"

    if len(args) >= 4:
        duration_str = f"{args[2]} {args[3]}"
        duration_td = parse_time_duration(duration_str)
        if duration_td:
            limit = duration_td.total_seconds() / (24 * 3600) # Convert to days for storage
            expiry_message = f"hết hạn sau {args[2]} {args[3]}"
        else:
            bot.reply_to(message, "Thời gian không hợp lệ. Vui lòng sử dụng định dạng như '1 ngày', '24 giờ'.")
            return
    elif len(args) == 3: # Handle case like "/taokey MYKEY 1" (assuming 1 day)
        try:
            value = int(args[2])
            limit = value # Assume days if only a number
            expiry_message = f"hết hạn sau {value} ngày"
        except ValueError:
            bot.reply_to(message, "Thời gian không hợp lệ. Vui lòng sử dụng định dạng như '1 ngày', '24 giờ' hoặc chỉ số ngày.")
            return

    with data_lock:
        if key_name in active_keys:
            bot.reply_to(message, f"Key `{key_name}` đã tồn tại.", parse_mode='Markdown')
            return

        active_keys[key_name] = {
            "user_id": None,
            "username": None,
            "expiry": None, # Will be set upon activation
            "limit": limit # Store limit in days or 0 for no limit
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
                    elif info['expiry'] > datetime.now():
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
                del user_preferences[str(user_id_associated)] # Remove user preferences associated with this key
            del active_keys[key_to_delete]
            save_data()
            bot.reply_to(message, f"Key `{key_to_delete}` đã được xóa thành công và người dùng liên kết đã bị hủy kích hoạt.", parse_mode='Markdown')
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
            admin_users.add(new_admin_id)
            save_data()
            bot.reply_to(message, f"Người dùng có ID `{new_admin_id}` đã được thêm vào danh sách admin.", parse_mode='Markdown')
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
        for user_id_str in user_preferences.keys():
            try:
                bot.send_message(int(user_id_str), broadcast_text, parse_mode='Markdown')
                sent_count += 1
                time.sleep(0.05) # Delay to avoid hitting Telegram API limits
            except telebot.apihelper.ApiException as e:
                print(f"Failed to send broadcast to {user_id_str}: {e}")
                failed_count += 1
            except Exception as e:
                print(f"An unexpected error occurred during broadcast to {user_id_str}: {e}")
                failed_count += 1
        bot.reply_to(message, f"Đã gửi broadcast tới {sent_count} người dùng thành công, {failed_count} thất bại.")

# --- Callback Query Handler ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('select_game_'))
def callback_game_selection(call):
    chat_id = call.message.chat.id
    game = call.data.split('_')[2]

    with data_lock:
        if str(chat_id) in user_preferences:
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
                text="Có lỗi xảy ra. Vui lòng thử lại lệnh `/chaybot`."
            )
            bot.answer_callback_query(call.id, text="Lỗi kích hoạt.")

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
        bot.polling(none_stop=True, interval=0)
    except Exception as e:
        print(f"Bot polling stopped due to an error: {e}")
    finally:
        stop_event.set() # Signal prediction thread to stop
        print("Bot stopped. Waiting for threads to finish...")
        if prediction_thread.is_alive():
            prediction_thread.join(timeout=5) # Give it some time to finish
        print("Threads terminated.")

