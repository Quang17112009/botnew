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



# --- Biến toàn cục và Lock để đảm bảo an toàn Thread ---
bot = telebot.TeleBot(BOT_TOKEN)
# user_states: Lưu trạng thái tạm thời của người dùng (ví dụ: đang chờ nhập key)
user_states = {}  # {chat_id: {"awaiting_key": True/False, "selected_game": None}}

# active_keys: Lưu trữ thông tin chi tiết về các key đã tạo và trạng thái kích hoạt
# {key_string: {"user_id": int, "username": str, "expiry": datetime, "limit_seconds": int}}
active_keys = {}

# user_preferences: Lưu trữ cài đặt và trạng thái liên quan đến từng người dùng
# {str(user_id): {"game": "Sunwin", "notify": True/False, "last_session_id": None, "key_active": True/False}}
user_preferences = {}

# admin_users: Tập hợp các ID của admin (để kiểm tra nhanh)
admin_users = set(ADMIN_IDS)

# Threading control
prediction_thread = None
stop_event = Event() # Sự kiện để ra hiệu dừng thread dự đoán
data_lock = Lock()   # Khóa để bảo vệ dữ liệu dùng chung khi nhiều thread truy cập

# --- Utility Functions ---
def is_admin(user_id):
    """Kiểm tra xem user_id có phải là admin hay không."""
    return user_id in admin_users

def generate_key(length=8):
    """Tạo một key ngẫu nhiên."""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def parse_time_duration(value, unit):
    """Phân tích thời lượng từ số và đơn vị (ví dụ: 1 ngày, 24 giờ)."""
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
            return timedelta(days=value * 30) # Approximate month
        elif 'năm' in unit:
            return timedelta(days=value * 365) # Approximate year
    except ValueError:
        return None
    return None

def save_data():
    """Lưu tất cả dữ liệu bot vào file JSON."""
    with data_lock:
        data = {
            "user_states": user_states,
            "active_keys": {k: {**v, 'expiry': v['expiry'].isoformat() if v.get('expiry') and v['expiry'] != datetime.max else None} for k, v in active_keys.items()},
            "user_preferences": user_preferences,
            "admin_users": list(admin_users)
        }
        try:
            with open("bot_data.json", "w") as f:
                json.dump(data, f, indent=4)
            # print("Dữ liệu bot đã được lưu.") # Gỡ comment để debug nếu cần
        except IOError as e:
            print(f"❌ Lỗi khi lưu dữ liệu vào file: {e}")

def load_data():
    """Tải dữ liệu bot từ file JSON."""
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
                    except (ValueError, TypeError):
                        v['expiry'] = None # Set to None if parsing fails
                active_keys[k] = v
            
            user_preferences = data.get("user_preferences", {})
            
            # Đảm bảo các admin mặc định (từ code) luôn có trong danh sách
            admin_users_loaded = set(data.get("admin_users", []))
            admin_users = admin_users_loaded.union(set(ADMIN_IDS)) 
            
            # Kiểm tra và làm sạch key hết hạn khi khởi động
            keys_to_delete = []
            for key_name, key_info in list(active_keys.items()):
                if key_info.get("user_id") and key_info.get("expiry") and key_info["expiry"] < datetime.now():
                    user_id_associated = str(key_info["user_id"])
                    if user_id_associated in user_preferences:
                        user_preferences[user_id_associated]["key_active"] = False
                        user_preferences[user_id_associated]["notify"] = False
                        # Không gửi tin nhắn tại đây để tránh spam khi khởi động lại
                    keys_to_delete.append(key_name)
            
            for key_name in keys_to_delete:
                print(f"Đã xóa key hết hạn khi khởi động: {key_name}")
                del active_keys[key_name]

            # Đồng bộ trạng thái key_active trong user_preferences
            for user_id_str, prefs in user_preferences.items():
                user_id = int(user_id_str)
                if prefs.get("key_active"): # Nếu user được đánh dấu là active
                    # Kiểm tra xem có key nào trong active_keys liên kết với user này và còn hạn không
                    is_user_actually_active = False
                    for key_name, key_info in active_keys.items():
                        if key_info.get("user_id") == user_id:
                            if not key_info.get("expiry") or key_info["expiry"] >= datetime.now():
                                is_user_actually_active = True
                                break
                    if not is_user_actually_active:
                        print(f"Người dùng {user_id} bị đánh dấu active nhưng không có key hợp lệ. Đang tắt.")
                        user_preferences[user_id_str]["key_active"] = False
                        user_preferences[user_id_str]["notify"] = False

    except (FileNotFoundError, json.JSONDecodeError):
        print("Không tìm thấy dữ liệu cũ hoặc dữ liệu bị hỏng. Khởi động lại từ đầu.")
        # Khởi tạo lại admin_users nếu không có file data
        admin_users = set(ADMIN_IDS)
    finally:
        save_data() # Lưu lại trạng thái sau khi tải/làm sạch

# ======================= HÀM XỬ LÝ DỰ ĐOÁN =======================
def du_doan_theo_xi_ngau(dice):
    """Tính toán dự đoán dựa trên kết quả xúc xắc."""
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
        prediction = "Xỉu" if prediction == "Tài" else "Tài" # Đảo ngược dự đoán cho cầu xấu
    else:
        loai_cau = "Không xác định" # Nên thêm các mẫu khác nếu cần

    return {
        "xuc_xac": dice,
        "tong": total,
        "cau": loai_cau,
        "du_doan": prediction,
        "chi_tiet": result_list
    }

def lay_du_lieu_api():
    """Lấy dữ liệu tài xỉu từ API."""
    try:
        response = requests.get(API_URL, timeout=10) # Tăng timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.Timeout:
        print("❌ Lỗi API: Yêu cầu hết thời gian.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi kết nối API: {e}")
        return None
    except json.JSONDecodeError:
        print("❌ Lỗi API: Phản hồi không phải JSON hợp lệ.")
        return None

def prediction_worker():
    """Thread chạy nền để lấy dữ liệu và gửi dự đoán."""
    last_processed_session = None
    while not stop_event.is_set():
        data = lay_du_lieu_api()
        if not data:
            time.sleep(5) # Đợi lâu hơn nếu không lấy được data
            continue

        current_session = data.get("Phien")
        dice = (
            data.get("Xuc_xac_1"),
            data.get("Xuc_xac_2"),
            data.get("Xuc_xac_3")
        )

        if not (isinstance(current_session, int) and all(isinstance(x, int) for x in dice) and len(dice) == 3):
            print(f"Dữ liệu API không hợp lệ hoặc thiếu: Phiên={current_session}, Xúc xắc={dice}")
            time.sleep(5)
            continue

        if current_session == last_processed_session:
            time.sleep(2) # Đợi 2 giây nếu phiên không đổi
            continue

        # Xử lý phiên mới
        last_processed_session = current_session
        ket_qua = du_doan_theo_xi_ngau(dice)
        prediction_for_next_session = ket_qua['du_doan']
        
        with data_lock:
            # Kiểm tra và xóa key hết hạn
            keys_to_delete = []
            for key_name, key_info in list(active_keys.items()): # Iterate over a copy
                if key_info.get("user_id") and key_info.get("expiry") and key_info["expiry"] < datetime.now():
                    user_id_associated = key_info["user_id"]
                    if str(user_id_associated) in user_preferences:
                        user_preferences[str(user_id_associated)]["key_active"] = False
                        user_preferences[str(user_id_associated)]["notify"] = False
                        try:
                            bot.send_message(user_id_associated, f"🔑 Key của bạn (`{key_name}`) đã hết hạn. Vui lòng liên hệ admin để gia hạn hoặc mua key mới.", parse_mode='Markdown')
                        except telebot.apihelper.ApiException as e:
                            print(f"Không thể gửi tin nhắn hết hạn cho {user_id_associated}: {e}")
                    keys_to_delete.append(key_name)
            
            for key_name in keys_to_delete:
                print(f"Đang xóa key hết hạn: {key_name}")
                del active_keys[key_name]
            
            # Gửi thông báo đến người dùng đang active
            for user_id_str, prefs in list(user_preferences.items()): # Iterate over a copy
                user_id = int(user_id_str)
                if prefs.get("notify") and prefs.get("game") == GAME_SUNWIN and prefs.get("key_active"):
                    # Chỉ gửi nếu phiên mới khác với phiên cuối cùng đã gửi cho user này
                    if prefs.get("last_session_id") != current_session:
                        message = (
                            f"🎮 **KẾT QUẢ PHIÊN HIỆN TẠI Sunwin** 🎮\n"
                            f"Phiên: `{current_session}` | Xúc xắc: `{dice}` | Kết quả: `{'Tài' if ket_qua['tong'] > 10 else 'Xỉu'}` (Tổng: `{ket_qua['tong']}`)\n\n" 
                            f"**Dự đoán cho phiên tiếp theo:**\n"
                            f"🔢 Phiên: `{current_session + 1}`\n"
                            f"🤖 Dự đoán: `{prediction_for_next_session}`\n"
                            f"⚠️ **Chúc Bạn May Mắn!**"
                        )
                        try:
                            bot.send_message(user_id, message, parse_mode='Markdown')
                            prefs["last_session_id"] = current_session # Cập nhật phiên cuối cùng đã gửi
                            user_preferences[user_id_str] = prefs # Lưu lại prefs đã cập nhật
                        except telebot.apihelper.ApiException as e:
                            print(f"Lỗi gửi tin nhắn đến {user_id}: {e}")
                            if "bot was blocked by the user" in str(e) or "chat not found" in str(e):
                                print(f"Người dùng {user_id} đã chặn bot. Đang tắt thông báo và key.")
                                prefs["notify"] = False
                                prefs["key_active"] = False
                                user_preferences[user_id_str] = prefs
                                # Xóa key liên quan nếu tìm thấy
                                for key_name, key_info in list(active_keys.items()):
                                    if key_info.get("user_id") == user_id:
                                        del active_keys[key_name]
                                        print(f"Đã xóa key {key_name} cho người dùng bị chặn {user_id}")
                                        break
                            elif "Too Many Requests" in str(e):
                                retry_after = e.result_json.get("parameters", {}).get("retry_after", 5)
                                print(f"Bị giới hạn tốc độ cho người dùng {user_id}. Đang thử lại sau {retry_after} giây.")
                                # Không cập nhật last_session_id để tin nhắn được gửi lại ở lần sau
                                time.sleep(retry_after) 
                            else:
                                print(f"Lỗi Telegram API không xác định cho người dùng {user_id}: {e}")
                        except Exception as e:
                            print(f"Lỗi không mong muốn cho người dùng {user_id}: {e}")
            save_data() # Lưu tất cả thay đổi sau khi xử lý các users
        time.sleep(2) # Đợi trước khi gọi API lần nữa

# --- Bot Handlers ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    # Đảm bảo các entry ban đầu tồn tại
    user_preferences.setdefault(str(user_id), {"key_active": False, "game": None, "notify": False, "last_session_id": None})
    user_states.setdefault(user_id, {"awaiting_key": False})

    is_active = user_preferences[str(user_id)].get("key_active", False)
    
    # Kiểm tra lại trạng thái key khi khởi động/start
    if is_active:
        found_valid_key = False
        with data_lock:
            for key_name, key_info in list(active_keys.items()):
                if key_info.get("user_id") == user_id:
                    if key_info.get("expiry") and key_info["expiry"] < datetime.now():
                        print(f"Key {key_name} cho người dùng {user_id} đã hết hạn trong khi /start.")
                        user_preferences[str(user_id)]["key_active"] = False
                        user_preferences[str(user_id)]["notify"] = False
                        del active_keys[key_name]
                        is_active = False # Cập nhật trạng thái
                        break
                    else:
                        found_valid_key = True
                        break
            if not found_valid_key and is_active: # Nếu không tìm thấy key hợp lệ nhưng lại active
                user_preferences[str(user_id)]["key_active"] = False
                user_preferences[str(user_id)]["notify"] = False
                is_active = False
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
            
            # Kiểm tra key hết hạn
            if key_info.get("expiry") and key_info["expiry"] < datetime.now():
                bot.reply_to(message, "❌ Key này đã hết hạn. Vui lòng liên hệ admin.")
                del active_keys[key] # Xóa key hết hạn
                save_data()
                return

            if key_info.get("user_id") is None: # Key chưa được gán
                # Hủy kích hoạt key cũ của user nếu có
                for old_key_name, old_key_info in list(active_keys.items()):
                    if old_key_info.get("user_id") == chat_id:
                        old_key_info["user_id"] = None
                        old_key_info["username"] = None
                        old_key_info["expiry"] = None # Reset expiry for unassigned keys
                        print(f"Đã hủy kích hoạt key cũ {old_key_name} của người dùng {chat_id}")
                        break

                key_info["user_id"] = chat_id
                key_info["username"] = message.from_user.username or message.from_user.first_name

                if key_info.get("limit_seconds") is not None:
                    key_info["expiry"] = datetime.now() + timedelta(seconds=key_info["limit_seconds"])
                else:
                    key_info["expiry"] = datetime.max # Vĩnh viễn

                # Đảm bảo entry user_preferences tồn tại và cập nhật trạng thái
                user_preferences.setdefault(str(chat_id), {"key_active": False, "game": None, "notify": False, "last_session_id": None})
                user_preferences[str(chat_id)]["key_active"] = True
                user_states[chat_id]["awaiting_key"] = False
                
                bot.reply_to(message, f"🥳 Key `{key}` đã được kích hoạt thành công! Bạn có thể bắt đầu sử dụng bot.", parse_mode='Markdown')
                save_data()
            elif key_info.get("user_id") == chat_id:
                bot.reply_to(message, f"Bạn đã kích hoạt key `{key}` rồi. Key này đang hoạt động.", parse_mode='Markdown')
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

    bot.reply_to(message, f"Đang lấy dữ liệu phiên gần nhất cho game `{selected_game}`...", parse_mode='Markdown')

    try:
        response = requests.get(API_URL, timeout=10) 
        response.raise_for_status()
        current_data = response.json()

        history_messages = []
        if current_data:
            session = current_data.get("Phien")
            dice = (current_data.get("Xuc_xac_1"), current_data.get("Xuc_xac_2"), current_data.get("Xuc_xac_3"))
            
            if isinstance(session, int) and all(isinstance(d, int) for d in dice) and len(dice) == 3:
                total = sum(dice)
                result_type = "Tài" if total > 10 else "Xỉu"
                
                ket_qua_phien_hien_tai = du_doan_theo_xi_ngau(dice)
                
                history_messages.append(
                    f"Phiên: `{session}` | Xúc xắc: `{dice}` | Tổng: `{total}` | Kết quả: `{result_type}`\n"
                    f"🤖 Dự đoán cho phiên tiếp theo: `{ket_qua_phien_hien_tai['du_doan']}` (Cầu: {ket_qua_phien_hien_tai['cau']})"
                )
            else:
                history_messages.append(f"Phiên: `{session}` | Dữ liệu không đầy đủ hoặc không hợp lệ từ API.")
        
        if history_messages:
            bot.send_message(chat_id, "**KẾT QUẢ PHIÊN GẦN NHẤT:**\n" + "\n".join(history_messages), parse_mode='Markdown')
            bot.send_message(chat_id, "⚠️ **Lưu ý:** API hiện tại chỉ cung cấp dữ liệu phiên gần nhất, không phải lịch sử nhiều phiên.")
        else:
            bot.send_message(chat_id, "Không có dữ liệu phiên gần nhất từ API.")

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
    limit_seconds = None 
    expiry_message = "không giới hạn"

    if len(args) == 4:
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
            "expiry": None, # Sẽ được thiết lập khi key được kích hoạt
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
        
        keys_to_clean_up = []
        for key, info in list(active_keys.items()): 
            status = "Chưa kích hoạt"
            expiry_info = ""
            
            if info.get("user_id"):
                status = f"Đã kích hoạt bởi user ID: `{info['user_id']}`"
                if info.get("username"):
                    status += f" (username: `{info['username']}`)"
                
                if info.get("expiry"):
                    if info['expiry'] == datetime.max:
                        expiry_info = " (Vĩnh viễn)"
                    elif info['expiry'] < current_time:
                        expiry_info = " (Đã hết hạn)"
                        # Đánh dấu để xóa key hết hạn
                        keys_to_clean_up.append(key)
                        # Đồng thời hủy kích hoạt người dùng liên quan
                        user_id_associated = info.get("user_id")
                        if user_id_associated and str(user_id_associated) in user_preferences:
                            user_preferences[str(user_id_associated)]["key_active"] = False
                            user_preferences[str(user_id_associated)]["notify"] = False
                            try:
                                bot.send_message(user_id_associated, f"🔑 Key của bạn (`{key}`) đã hết hạn. Vui lòng liên hệ admin để gia hạn hoặc mua key mới.", parse_mode='Markdown')
                            except telebot.apihelper.ApiException as e:
                                print(f"Không thể gửi tin nhắn hết hạn trong list_keys cho {user_id_associated}: {e}")
                    else:
                        expiry_info = f" (Hết hạn: `{info['expiry'].strftime('%Y-%m-%d %H:%M:%S')}`)"
                status += expiry_info
            
            key_list_messages.append(f"- `{key}`: {status}")
        
        # Thực hiện xóa các key đã đánh dấu
        for key_to_del in keys_to_clean_up:
            if key_to_del in active_keys:
                del active_keys[key_to_del]
                print(f"Đã dọn dẹp key hết hạn: {key_to_del}")
        
        save_data() # Lưu lại sau khi làm sạch
        
        if not key_list_messages:
            bot.reply_to(message, "Hiện không có key nào còn hiệu lực hoặc đã được kích hoạt.")
        else:
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
                user_preferences[str(user_id_associated)]["key_active"] = False
                user_preferences[str(user_id_associated)]["notify"] = False
                try:
                    bot.send_message(user_id_associated, f"⚠️ Key của bạn (`{key_to_delete}`) đã bị admin xóa. Bot sẽ ngừng hoạt động. Vui lòng liên hệ admin để biết thêm chi tiết.", parse_mode='Markdown')
                except telebot.apihelper.ApiException as e:
                    print(f"Không thể gửi tin nhắn xóa key cho {user_id_associated}: {e}")
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
        for uid_str, prefs in list(user_preferences.items()): # Iterate over a copy to avoid issues during modification
            if prefs.get("key_active", False): # Chỉ gửi đến user có key active
                try:
                    bot.send_message(int(uid_str), broadcast_text, parse_mode='Markdown')
                    sent_count += 1
                    time.sleep(0.05) # Delay nhỏ để tránh bị Telegram rate limit
                except telebot.apihelper.ApiException as e:
                    print(f"Lỗi gửi broadcast đến {uid_str}: {e}")
                    failed_count += 1
                    if "bot was blocked by the user" in str(e) or "chat not found" in str(e):
                        print(f"Người dùng {uid_str} đã chặn bot. Đang hủy kích hoạt key và thông báo.")
                        prefs["key_active"] = False
                        prefs["notify"] = False
                        user_preferences[uid_str] = prefs 
                        # Xóa key liên quan
                        for key_name, key_info in list(active_keys.items()):
                            if key_info.get("user_id") == int(uid_str):
                                del active_keys[key_name]
                                break
                except Exception as e:
                    print(f"Lỗi không mong muốn trong khi broadcast đến {uid_str}: {e}")
                    failed_count += 1
        save_data() 
        bot.reply_to(message, f"Đã gửi broadcast tới {sent_count} người dùng thành công, {failed_count} thất bại.")

# --- Callback Query Handler ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('select_game_'))
def callback_game_selection(call):
    chat_id = call.message.chat.id

    try:
        bot.answer_callback_query(call.id, text=f"Đã chọn game {call.data.split('_')[2]}")
    except telebot.apihelper.ApiException as e:
        if "query is too old and response timeout" in str(e) or "message is not modified" in str(e):
            print(f"Callback query đã được xử lý hoặc quá cũ cho chat {chat_id}: {e}")
            return 
        else:
            raise

    game = call.data.split('_')[2]

    with data_lock:
        if str(chat_id) in user_preferences and user_preferences[str(chat_id)].get("key_active"):
            user_preferences[str(chat_id)]["game"] = game
            user_preferences[str(chat_id)]["notify"] = True
            
            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"Tuyệt vời! Bạn đã chọn game **{game}**. Bot sẽ bắt đầu gửi thông báo dự đoán cho game này.",
                    parse_mode='Markdown'
                )
            except telebot.apihelper.ApiException as e:
                print(f"Lỗi chỉnh sửa tin nhắn cho chat {chat_id}: {e}")
                # Nếu không thể chỉnh sửa, gửi tin nhắn mới
                bot.send_message(chat_id, f"Tuyệt vời! Bạn đã chọn game **{game}**. Bot sẽ bắt đầu gửi thông báo dự đoán cho game này.", parse_mode='Markdown')

            save_data()
        else:
            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="Có lỗi xảy ra hoặc key của bạn không còn hoạt động. Vui lòng thử lại lệnh `/chaybot` hoặc kích hoạt key.",
                    parse_mode='Markdown'
                )
            except telebot.apihelper.ApiException as e:
                print(f"Lỗi chỉnh sửa tin nhắn cho người dùng key không hợp lệ {chat_id}: {e}")
                bot.send_message(chat_id, "Có lỗi xảy ra hoặc key của bạn không còn hoạt động. Vui lòng thử lại lệnh `/chaybot` hoặc kích hoạt key.", parse_mode='Markdown')


# --- Main execution ---
if __name__ == "__main__":
    load_data() # Tải dữ liệu khi bot khởi động

    print("Khởi động máy chủ Flask để giữ bot hoạt động...")
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True # Cho phép chương trình chính thoát ngay cả khi thread này đang chạy
    flask_thread.start()

    print("Khởi động thread dự đoán...")
    prediction_thread = Thread(target=prediction_worker)
    prediction_thread.daemon = True
    prediction_thread.start()

    print("Bắt đầu polling Telegram bot...")
    while True: # Vòng lặp vô hạn để tự động khởi động lại polling khi có lỗi
        try:
            bot.polling(none_stop=True, interval=1, timeout=30) # Tăng timeout
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Mất kết nối với Telegram API: {e}. Đang thử lại sau 5 giây...")
            time.sleep(5)
        except telebot.apihelper.ApiException as e:
            if "Forbidden: bot was blocked by the user" in str(e):
                print(f"Bot bị người dùng chặn: {e}. Sẽ tiếp tục polling cho các user khác.")
                # Lỗi này không cần dừng polling
            elif "Bad Gateway" in str(e) or "Gateway Timeout" in str(e) or "Conflict" in str(e): # Bắt thêm lỗi Conflict ở đây
                print(f"Telegram API lỗi Gateway hoặc Conflict: {e}. Đang thử lại sau 5 giây...")
                time.sleep(5)
            else:
                print(f"❌ Lỗi Telegram API không xác định: {e}. Đang thử lại sau 5 giây...")
                time.sleep(5)
        except Exception as e:
            print(f"❌ Lỗi không mong muốn trong polling: {e}. Đang thử lại sau 10 giây...")
            time.sleep(10)
        
        time.sleep(1) # Thêm một chút delay giữa các lần polling lại để tránh spam
