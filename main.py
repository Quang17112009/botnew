import telebot
from telebot import types
import requests
import time
import json
import os
import random
import string
from datetime import datetime, timedelta
from threading import Thread, Event, Lock

from flask import Flask, request

# --- Cấu hình Bot (ĐẶT TRỰC TIẾP TẠY ĐÂY) ---
BOT_TOKEN = "8167401761:AAGL9yN2YwzmmjgC7fbgkBYhTI7DhE3_V7w"
ADMIN_IDS = [6915752059, 6285177749] # Thêm ID admin mới vào đây

DATA_FILE = 'user_data.json'
CODES_FILE = 'codes.json' 

# Chỉ có một API cho Sunwin
API_SUNWIN = "https://wanglinapiws.up.railway.app/api/taixiu"

# --- Khởi tạo Flask App và Telegram Bot ---
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# Global flags và objects
bot_enabled = True # Cờ này sẽ kiểm soát việc bot có gửi thông báo dự đoán tự động hay không
bot_disable_reason = "Không có"
bot_disable_admin_id = None
prediction_stop_event = Event() # Để kiểm soát luồng dự đoán
bot_initialized = False # Cờ để đảm bảo bot chỉ được khởi tạo một lần
bot_init_lock = Lock() # Khóa để tránh race condition khi khởi tạo

# Global sets for patterns and codes
GENERATED_KEYS = {} # {key: {"value": 1, "type": "day", "used_by": null, "used_time": null}}
LAST_PREDICTION_ID = None # Lưu ID phiên cuối cùng cho Sunwin
GAME_HISTORY = [] # Lưu lịch sử 10 phiên gần nhất cho Sunwin

# ======================= DANH SÁCH CẦU ĐẸP & CẦU XẤU (Thuật toán của bạn) =======================
# Danh sách cầu đẹp và cầu xấu
cau_dep = {
    (1, 4, 4), (1, 6, 2), (2, 2, 5), (2, 4, 3), (2, 5, 2),
    (3, 1, 5), (3, 2, 4), (3, 4, 2), (3, 5, 1), (4, 1, 4), (4, 2, 3),
    (4, 3, 2), (4, 4, 1), (5, 1, 4), (5, 3, 1), (6, 2, 1),
    (1, 1, 7), (1, 2, 6), (1, 3, 5), (1, 4, 4), (1, 6, 2),
    (2, 1, 6), (2, 2, 5), (2, 3, 4), (2, 4, 3), (2, 5, 2), (2, 6, 1),
    (3, 2, 4), (3, 4, 2), (3, 5, 1), (4, 1, 4), (4, 2, 3), (4, 3, 2), (4, 4, 1),
    (5, 3, 1), (6, 1, 2), (6, 2, 1), (3, 4, 1), (6, 4, 5), (1, 6, 3), (2, 6, 4),
    (6, 1, 4), (1, 3, 2), (2, 4, 5), (1, 3, 4), (1, 5, 1), (3, 6, 6), (3, 6, 4), (5, 4, 6),
    (3, 1, 6), (1, 3, 6), (2, 2, 4), (2, 4, 5), (2, 1, 2), (6, 1, 4), (4, 6, 6),
    (4, 3, 5), (3, 2, 5), (3, 4, 2), (6, 4, 4), (2, 3, 1), (1, 2, 1), (6, 2, 5),
    (3, 1, 3), (5, 5, 1), (4, 5, 4), (4, 6, 1), (3, 6, 1), (5, 6, 6), (2, 4, 4),
    (1, 6, 5), (5, 5, 3), (1, 6, 6), (4, 1, 2), (3, 3, 2), (1, 4, 6), (4, 3, 4),
    (1, 4, 1), (5, 1, 5), (4, 4, 6), (5, 4, 5), (3, 6, 5), (5, 6, 3), (6, 5, 4), (4, 3, 6),
    (6, 1, 1), (5, 6, 1), (5, 6, 5), (2, 2, 1), (4, 5, 3), (3, 5, 6), (1, 5, 4), (1, 1, 4),
    (2, 1, 3), (2, 4, 1), (2, 6, 6), (5, 6, 1), (3, 4, 3),(3, 3, 4),
    (4, 6, 4), (5, 1, 6),(4, 2, 1),(1,2,4) # ✅ Thêm mẫu này vào cầu đẹp
}

cau_xau = {
    (1, 1, 1), (1, 1, 2), (1, 1, 3), (1, 1, 5), (1, 1, 6),
    (1, 2, 2), (1, 2, 3), (1, 2, 5), (1, 3, 1), (1, 3, 3),
    (1, 4, 2), (1, 4, 3), (1, 5, 2), (1, 6, 1),
    (2, 1, 1), (2, 1, 4), (2, 1, 5), (2, 2, 2), (2, 2, 3), (2, 3, 2),
    (2, 3, 3), (2, 4, 2), (2, 5, 1), (2, 5, 6), (2, 6, 5),
    (3, 1, 1), (3, 1, 2), (3, 1, 4), (3, 2, 1), (3, 2, 2), (3, 2, 3),
    (3, 3, 1), (3, 3, 3), (3, 4, 6), (3, 5, 5),
    (4, 1, 3), (4, 3, 1), (4, 4, 4), (4, 4, 5),
    (4, 5, 5), (4, 5, 6), (4, 6, 3), (4, 6, 4), (4, 6, 5),
    (5, 1, 1), (5, 1, 2), (5, 2, 1), (5, 2, 6), (5, 3, 6),
    (5, 5, 5), (5, 5, 6), (5, 6, 4), (5, 4, 1),
    (6, 2, 6), (6, 3, 6), (6, 5, 6), (6, 6, 1),(6, 6, 2),
    (6, 6, 3), (6, 6, 4), (6, 6, 5), (6, 6, 6),
    (5, 1, 3), (2, 6, 1), (6, 4, 6), (5, 2, 2), (2, 1, 2), (4, 4, 1), (1, 2, 1), (1, 3, 5),
    (1, 5, 3), (3, 3, 3), (1, 2, 6), (2, 1, 6), (2, 3, 4), (5, 5, 3), (6, 1, 2), (6, 3, 3),(6,5,3),(4,2,2),(1,6,4),(2, 2, 6)
}

# ======================= HÀM XỬ LÝ DỰ ĐOÁN (Thuật toán của bạn) =======================
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
        # Đảo ngược dự đoán nếu là cầu xấu
        prediction = "Xỉu" if prediction == "Tài" else "Tài"
    else:
        loai_cau = "Không xác định" # Giữ nguyên dự đoán nếu không thuộc cả hai

    return {
        "xuc_xac": dice,
        "tong": total,
        "cau": loai_cau,
        "du_doan": prediction,
        "chi_tiet": result_list
    }

# --- Quản lý dữ liệu người dùng, key và lịch sử ---
user_data = {}

def load_user_data():
    global user_data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try:
                user_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Lỗi đọc {DATA_FILE}. Khởi tạo lại dữ liệu người dùng.")
                user_data = {}
    else:
        user_data = {}
    print(f"Loaded {len(user_data)} user records from {DATA_FILE}")

def save_user_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_keys():
    global GENERATED_KEYS
    if os.path.exists(CODES_FILE):
        with open(CODES_FILE, 'r') as f:
            try:
                GENERATED_KEYS = json.load(f)
            except json.JSONDecodeError:
                print(f"Lỗi đọc {CODES_FILE}. Khởi tạo lại mã key.")
                GENERATED_KEYS = {}
    else:
        GENERATED_KEYS = {}
    print(f"Loaded {len(GENERATED_KEYS)} keys from {CODES_FILE}")

def save_keys():
    with open(CODES_FILE, 'w') as f:
        json.dump(GENERATED_KEYS, f, indent=4)

def is_admin(user_id):
    return user_id in ADMIN_IDS

def check_vip_access(user_id):
    user_id_str = str(user_id)
    if is_admin(user_id):
        return True, "Bạn là Admin, quyền truy cập vĩnh viễn."

    if user_id_str not in user_data or user_data[user_id_str].get('expiry_date') is None:
        return False, "⚠️ Bạn chưa kích hoạt hoặc tài khoản VIP của bạn chưa được gia hạn."

    expiry_date_str = user_data[user_id_str]['expiry_date']
    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S')

    if datetime.now() < expiry_date:
        remaining_time = expiry_date - datetime.now()
        days = remaining_time.days
        hours = remaining_time.seconds // 3600
        minutes = (remaining_time.seconds % 3600) // 60
        seconds = remaining_time.seconds % 60
        return True, f"✅ Tài khoản VIP của bạn còn hạn đến: `{expiry_date_str}` ({days} ngày {hours} giờ {minutes} phút {seconds} giây)."
    else:
        return False, "❌ Tài khoản VIP của bạn đã hết hạn."

def user_expiry_date(user_id):
    if str(user_id) in user_data and user_data[str(user_id)].get('expiry_date'):
        return user_data[str(user_id)]['expiry_date']
    return "Không có"

# --- Lấy dữ liệu từ API Sunwin ---
def lay_du_lieu_sunwin():
    try:
        response = requests.get(API_SUNWIN)
        response.raise_for_status() # Báo lỗi nếu status code là lỗi HTTP
        data = response.json()

        # Kiểm tra các khóa cần thiết từ API Sunwin
        if "Phien" in data and "Xuc_xac_1" in data and "Xuc_xac_2" in data and "Xuc_xac_3" in data:
            return data
        else:
            print(f"API Sunwin trả về định dạng không mong muốn.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Lỗi khi lấy dữ liệu từ API Sunwin: {e}")
        return None
    except json.JSONDecodeError:
        print(f"Lỗi giải mã JSON từ API Sunwin. Phản hồi không phải JSON hợp lệ.")
        return None

# --- Logic chính của Bot dự đoán (chạy trong luồng riêng) ---
def prediction_loop(stop_event: Event):
    global LAST_PREDICTION_ID, GAME_HISTORY

    print("Prediction loop started.")
    while not stop_event.is_set():
        if not bot_enabled:
            time.sleep(10) # Ngủ lâu hơn khi bot bị tắt
            continue

        # --- Process Sunwin API ---
        data_sunwin = lay_du_lieu_sunwin()
        if data_sunwin:
            issue_id = str(data_sunwin.get("Phien"))
            dice = (
                data_sunwin.get("Xuc_xac_1"),
                data_sunwin.get("Xuc_xac_2"),
                data_sunwin.get("Xuc_xac_3")
            )

            # Đảm bảo đủ dữ liệu và xúc xắc là số nguyên
            if issue_id and all(isinstance(x, int) for x in dice):
                if issue_id != LAST_PREDICTION_ID:
                    # Tính toán dự đoán bằng thuật toán của bạn
                    prediction_result = du_doan_theo_xi_ngau(dice)
                    
                    # Xác định Tài/Xỉu thực tế từ tổng của phiên hiện tại
                    actual_total = prediction_result['tong']
                    # Bộ ba luôn được coi là Xỉu trong Tài Xỉu truyền thống
                    if dice[0] == dice[1] == dice[2]:
                        ket_qua_tx = "Xỉu"
                    else:
                        ket_qua_tx = "Tài" if actual_total >= 11 else "Xỉu"
                    
                    du_doan_ket_qua = prediction_result['du_doan']

                    # Cập nhật lịch sử game cho lệnh /lichsu
                    if len(GAME_HISTORY) >= 10:
                        GAME_HISTORY.pop(0)
                    GAME_HISTORY.append({
                        "Ma_phien": issue_id,
                        "Ket_qua": ket_qua_tx,
                        "Tong_diem": actual_total,
                        "Du_doan_tiep": du_doan_ket_qua,
                        "Thoi_gian": datetime.now().strftime('%H:%M:%S')
                    })

                    # Gửi tin nhắn dự đoán tới tất cả người dùng CÓ QUYỀN VÀ ĐÃ BẬT NHẬN THÔNG BÁO CHO SUNWIN
                    for user_id_str, user_info in list(user_data.items()):
                        user_id = int(user_id_str)
                        is_sub, _ = check_vip_access(user_id)
                        user_auto_send = user_info.get('auto_send_predictions', False)
                        user_selected_game = user_info.get('selected_game') # Sẽ luôn là "Sunwin" hoặc None

                        if is_sub and user_auto_send and user_selected_game == "Sunwin":
                            try:
                                prediction_message = (
                                    f"🎮 **KẾT QUẢ PHIÊN HIỆN TẠI [SUNWIN]** 🎮\n"
                                    f"Phiên: `{issue_id}` | Kết quả: **{ket_qua_tx}** (Tổng: **{actual_total}**)\n\n"
                                    f"**Dự đoán cho phiên tiếp theo:**\n"
                                    f"🔢 Phiên: `{str(int(issue_id) + 1).zfill(len(issue_id))}`\n"
                                    f"🤖 Dự đoán: **{du_doan_ket_qua}**\n"
                                    f"⚠️ **Hãy đặt cược sớm trước khi phiên kết thúc!**"
                                )
                                bot.send_message(user_id, prediction_message, parse_mode='Markdown')
                            except telebot.apihelper.ApiTelegramException as e:
                                if "bot was blocked by the user" in str(e) or "user is deactivated" in str(e):
                                    print(f"Người dùng {user_id} đã chặn bot hoặc bị vô hiệu hóa. Xóa user khỏi danh sách.")
                                    # Optionally remove the user if they've blocked the bot
                                    del user_data[user_id_str] 
                                else:
                                    print(f"Lỗi gửi tin nhắn cho user {user_id}: {e}")
                            except Exception as e:
                                print(f"Lỗi không xác định khi gửi tin nhắn cho user {user_id}: {e}")

                    print("-" * 50)
                    print(f"🎮 Kết quả phiên hiện tại [SUNWIN]: {ket_qua_tx} (Tổng: {actual_total})")
                    print(f"🔢 Phiên: {issue_id} → {str(int(issue_id) + 1).zfill(len(issue_id))}")
                    print(f"🤖 Dự đoán: {du_doan_ket_qua}")
                    print(f"⚠️ Hãy đặt cược sớm trước khi phiên kết thúc!")
                    print("-" * 50)

                    LAST_PREDICTION_ID = issue_id
                    save_user_data(user_data) # Lưu lại trạng thái user nếu có thay đổi (ví dụ user bị block)
        time.sleep(5) # Đợi 5 giây trước khi kiểm tra phiên mới
    print("Prediction loop stopped.")

# --- Xử lý lệnh Telegram ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    username = message.from_user.username or message.from_user.first_name

    if user_id not in user_data:
        user_data[user_id] = {
            'username': username,
            'expiry_date': None,
            'auto_send_predictions': False, # Mặc định không gửi tự động
            'selected_game': None # Mặc định chưa chọn game nào
        }
        save_user_data(user_data)
        bot.reply_to(message,
                     "Chào mừng bạn đến với **BOT DỰ ĐOÁN TÀI XỈU**!\n"
                     "Hãy dùng lệnh /help để xem danh sách các lệnh hỗ trợ.",
                     parse_mode='Markdown')
    else:
        user_data[user_id]['username'] = username # Cập nhật username nếu có thay đổi
        save_user_data(user_data)
        bot.reply_to(message, "Bạn đã khởi động bot rồi. Dùng /help để xem các lệnh.")

@bot.message_handler(commands=['help'])
def show_help(message):
    help_text = (
        "🔔 **HƯỚNG DẪN SỬ DỤNG BOT**\n"
        "══════════════════════════\n"
        "🔑 **Lệnh cơ bản:**\n"
        "- `/start`: Hiển thị thông tin chào mừng\n"
        "- `/key <key>`: Nhập key để kích hoạt bot\n"
        "- `/chaybot`: Bật nhận thông báo dự đoán tự động cho **Sunwin**\n"
        "- `/tatbot`: Tắt nhận thông báo dự đoán tự động\n"
        "- `/lichsu`: Xem lịch sử 10 phiên gần nhất của **Sunwin**\n\n"
    )

    if is_admin(message.chat.id):
        help_text += (
            "🛡️ **Lệnh admin:**\n"
            "- `/taokey <tên_key> [giới_hạn] [thời_gian]`: Tạo key mới. Ví dụ: `/taokey MYKEY123 1 ngày`, `/taokey VIPKEY 24 giờ`\n"
            "- `/lietkekey`: Liệt kê tất cả key và trạng thái sử dụng\n"
            "- `/xoakey <key>`: Xóa key khỏi hệ thống\n"
            "- `/themadmin <id>`: Thêm ID người dùng làm admin\n"
            "- `/xoaadmin <id>`: Xóa ID người dùng khỏi admin\n"
            "- `/danhsachadmin`: Xem danh sách các ID admin\n"
            "- `/broadcast [tin nhắn]`: Gửi thông báo đến tất cả người dùng\n"
            "- `/tatbot_main [lý do]`: Tắt bot dự đoán chính (ảnh hưởng tất cả user)\n"
            "- `/mokbot_main`: Mở lại bot dự đoán chính\n"
        )
    help_text += "\n══════════════════════════\n"
    help_text += "👥 Liên hệ admin để được hỗ trợ thêm."

    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['key'])
def use_key(message):
    key_str = telebot.util.extract_arguments(message.text)
    user_id = str(message.chat.id)

    if not key_str:
        bot.reply_to(message, "Vui lòng nhập key. Ví dụ: `/key ABCXYZ`", parse_mode='Markdown')
        return

    if key_str not in GENERATED_KEYS:
        bot.reply_to(message, "❌ Key không tồn tại hoặc đã hết hạn.")
        return

    key_info = GENERATED_KEYS[key_str]
    if key_info.get('used_by') is not None:
        bot.reply_to(message, "❌ Key này đã được sử dụng rồi.")
        return

    current_expiry_str = user_data.get(user_id, {}).get('expiry_date')
    if current_expiry_str:
        current_expiry_date = datetime.strptime(current_expiry_str, '%Y-%m-%d %H:%M:%S')
        if datetime.now() > current_expiry_date:
            new_expiry_date = datetime.now()
        else:
            new_expiry_date = current_expiry_date
    else:
        new_expiry_date = datetime.now()

    value = key_info['value']
    if key_info['type'] == 'ngày':
        new_expiry_date += timedelta(days=value)
    elif key_info['type'] == 'giờ':
        new_expiry_date += timedelta(hours=value)

    user_data.setdefault(user_id, {})['expiry_date'] = new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    user_data[user_id]['username'] = message.from_user.username or message.from_user.first_name

    GENERATED_KEYS[key_str]['used_by'] = user_id
    GENERATED_KEYS[key_str]['used_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    save_user_data(user_data)
    save_keys()

    bot.reply_to(message,
                 f"🎉 Bạn đã đổi key thành công! Tài khoản của bạn đã được kích hoạt/gia hạn thêm **{value} {key_info['type']}**.\n"
                 f"Ngày hết hạn mới: `{user_expiry_date(user_id)}`",
                 parse_mode='Markdown')

@bot.message_handler(commands=['chaybot'])
def enable_auto_predictions(message):
    user_id = str(message.chat.id)
    is_vip, vip_message = check_vip_access(int(user_id))

    if not is_vip:
        bot.reply_to(message, vip_message + "\nVui lòng liên hệ Admin để được hỗ trợ.", parse_mode='Markdown')
        return

    if not bot_enabled:
        bot.reply_to(message, f"❌ Bot hiện đang tạm dừng bởi Admin. Lý do: `{bot_disable_reason}`", parse_mode='Markdown')
        return

    user_data[user_id]['auto_send_predictions'] = True
    user_data[user_id]['selected_game'] = "Sunwin" # Chỉ có Sunwin
    save_user_data(user_data)

    bot.reply_to(message, "✅ Tài khoản của bạn còn hạn. Bạn đã chọn nhận dự đoán tự động cho game **Sunwin**.\n"
                          "Bot sẽ bắt đầu gửi thông báo dự đoán các phiên mới nhất tại đây.",
                          parse_mode='Markdown')


@bot.message_handler(commands=['tatbot'])
def disable_auto_predictions(message):
    user_id = str(message.chat.id)
    if user_id in user_data:
        user_data[user_id]['auto_send_predictions'] = False
        user_data[user_id]['selected_game'] = None # Reset selected game
        save_user_data(user_data)
        bot.reply_to(message, "❌ Bạn đã tắt nhận thông báo dự đoán tự động.")
    else:
        bot.reply_to(message, "Bạn chưa khởi động bot. Dùng /start.")

@bot.message_handler(commands=['lichsu'])
def show_game_history(message):
    user_id = str(message.chat.id)
    is_vip, vip_message = check_vip_access(int(user_id))

    if not is_vip:
        bot.reply_to(message, vip_message, parse_mode='Markdown')
        return

    user_selected_game = user_data.get(user_id, {}).get('selected_game')
    if not user_selected_game or user_selected_game != "Sunwin":
        bot.reply_to(message, "Bạn chưa bật nhận dự đoán cho **Sunwin**. Vui lòng dùng `/chaybot` để bật.", parse_mode='Markdown')
        return

    if not GAME_HISTORY:
        bot.reply_to(message, f"Lịch sử 10 phiên gần nhất cho game **Sunwin** hiện chưa có dữ liệu.", parse_mode='Markdown')
        return

    history_text = f"📜 **LỊCH SỬ 10 PHIÊN GẦN NHẤT CỦA SUNWIN** 📜\n"
    history_text += "```\n"
    history_text += "Phiên       KQ   Tổng   Dự đoán   Thời gian\n"
    history_text += "---------------------------------------------------\n"
    for entry in GAME_HISTORY:
        history_text += (
            f"{entry['Ma_phien']:<10} {entry['Ket_qua'][:1]:<4} {entry['Tong_diem']:<6} "
            f"{entry['Du_doan_tiep'][:1]:<9} {entry['Thoi_gian']}\n"
        )
    history_text += "```"
    bot.reply_to(message, history_text, parse_mode='Markdown')

# --- Lệnh Admin ---

@bot.message_handler(commands=['taokey'])
def generate_key_command(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = telebot.util.extract_arguments(message.text).split()
    if not (2 <= len(args) <= 4): # <tên_key> <giá_trị> <đơn_vị> [số_lượng]
        bot.reply_to(message, "Cú pháp sai. Ví dụ:\n"
                              "`/taokey MYKEY123 1 ngày` (tạo 1 key MYKEY123 hạn 1 ngày)\n"
                              "`/taokey VIPKEY 24 giờ` (tạo 1 key VIPKEY hạn 24 giờ)\n"
                              "`/taokey BATCHCODE 7 ngày 5` (tạo 5 key ngẫu nhiên hạn 7 ngày)", parse_mode='Markdown')
        return

    key_name = args[0]
    if len(args) == 4: # User provided a specific key name and a quantity
        try:
            value = int(args[1])
            unit = args[2].lower()
            quantity = int(args[3])
        except ValueError:
            bot.reply_to(message, "Giá trị, đơn vị, hoặc số lượng không hợp lệ. Vui lòng nhập đúng.", parse_mode='Markdown')
            return
        if unit not in ['ngày', 'giờ'] or value <= 0 or quantity <= 0:
            bot.reply_to(message, "Đơn vị (ngày/giờ), giá trị (>0), hoặc số lượng (>0) không hợp lệ.", parse_mode='Markdown')
            return

        generated_keys_list = []
        for _ in range(quantity):
            # If quantity > 1, generate random keys, ignore the provided key_name
            # If quantity == 1, use the provided key_name if it's unique
            if quantity > 1 or key_name in GENERATED_KEYS: # Only generate new key if quantity > 1 or if provided key_name already exists
                new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                while new_key in GENERATED_KEYS: # Ensure uniqueness
                     new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            else:
                new_key = key_name # Use the provided key_name for single key creation if not exists

            if new_key in GENERATED_KEYS: # Double check if it exists after generation
                continue # Skip if already exists, or handle as error for single key

            GENERATED_KEYS[new_key] = {
                "value": value,
                "type": unit,
                "used_by": None,
                "used_time": None
            }
            generated_keys_list.append(new_key)

        save_keys()
        response_text = f"✅ Đã tạo thành công {len(generated_keys_list)} mã key gia hạn **{value} {unit}**:\n\n"
        response_text += "\n".join([f"`{key}`" for key in generated_keys_list])
        response_text += "\n\n_(Các key này chưa được sử dụng)_"
        bot.reply_to(message, response_text, parse_mode='Markdown')

    elif len(args) == 3: # User provided key_name, value, unit (single key)
        try:
            value = int(args[1])
            unit = args[2].lower()
        except ValueError:
            bot.reply_to(message, "Giá trị hoặc đơn vị không hợp lệ. Vui lòng nhập đúng.", parse_mode='Markdown')
            return
        if unit not in ['ngày', 'giờ'] or value <= 0:
            bot.reply_to(message, "Đơn vị (ngày/giờ) hoặc giá trị (>0) không hợp lệ.", parse_mode='Markdown')
            return

        if key_name in GENERATED_KEYS:
            bot.reply_to(message, f"❌ Key `{key_name}` đã tồn tại. Vui lòng chọn tên khác hoặc xóa key cũ nếu muốn tạo lại.", parse_mode='Markdown')
            return

        GENERATED_KEYS[key_name] = {
            "value": value,
            "type": unit,
            "used_by": None,
            "used_time": None
        }
        save_keys()
        bot.reply_to(message, f"✅ Đã tạo thành công key `{key_name}` gia hạn **{value} {unit}**.\n\n_(Key này chưa được sử dụng)_", parse_mode='Markdown')
    else: # Invalid number of arguments
        bot.reply_to(message, "Cú pháp sai. Vui lòng kiểm tra lại /help.", parse_mode='Markdown')


@bot.message_handler(commands=['lietkekey'])
def list_keys(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    if not GENERATED_KEYS:
        bot.reply_to(message, "Hiện chưa có key nào được tạo.")
        return

    response_text = "🔑 **DANH SÁCH CÁC KEY ĐÃ TẠO** 🔑\n\n"
    for key, info in GENERATED_KEYS.items():
        status = "Chưa sử dụng"
        if info.get('used_by'):
            user_id = info['used_by']
            user_info = user_data.get(user_id, {})
            username = user_info.get('username', f"ID: {user_id}")
            used_time = info.get('used_time', 'Không rõ')
            status = f"Đã dùng bởi @{username} (ID: `{user_id}`) lúc {used_time}"

        response_text += (
            f"`{key}` (Hạn: {info['value']} {info['type']})\n"
            f"  Trạng thái: {status}\n\n"
        )
    bot.reply_to(message, response_text, parse_mode='Markdown')


@bot.message_handler(commands=['xoakey'])
def delete_key(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    key_to_delete = telebot.util.extract_arguments(message.text)
    if not key_to_delete:
        bot.reply_to(message, "Vui lòng nhập key muốn xóa. Ví dụ: `/xoakey ABCXYZ`", parse_mode='Markdown')
        return

    if key_to_delete in GENERATED_KEYS:
        del GENERATED_KEYS[key_to_delete]
        save_keys()
        bot.reply_to(message, f"✅ Đã xóa key `{key_to_delete}` khỏi hệ thống.")
    else:
        bot.reply_to(message, f"❌ Key `{key_to_delete}` không tồn tại.")


@bot.message_handler(commands=['themadmin'])
def add_admin(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = telebot.util.extract_arguments(message.text).split()
    if not args or not args[0].isdigit():
        bot.reply_to(message, "Cú pháp sai. Ví dụ: `/themadmin <id_nguoi_dung>`", parse_mode='Markdown')
        return

    target_user_id = int(args[0])
    if target_user_id not in ADMIN_IDS:
        ADMIN_IDS.append(target_user_id)
        bot.reply_to(message, f"✅ Đã thêm user ID `{target_user_id}` vào danh sách admin.")
        try:
            bot.send_message(target_user_id, "🎉 Bạn đã được cấp quyền Admin!")
        except Exception:
            pass
    else:
        bot.reply_to(message, f"User ID `{target_user_id}` đã là admin rồi.")


@bot.message_handler(commands=['xoaadmin'])
def remove_admin(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    args = telebot.util.extract_arguments(message.text).split()
    if not args or not args[0].isdigit():
        bot.reply_to(message, "Cú pháp sai. Ví dụ: `/xoaadmin <id_nguoi_dung>`", parse_mode='Markdown')
        return

    target_user_id = int(args[0])
    if target_user_id in ADMIN_IDS:
        if target_user_id == message.chat.id:
            bot.reply_to(message, "Bạn không thể tự xóa quyền admin của mình.")
            return
        ADMIN_IDS.remove(target_user_id)
        bot.reply_to(message, f"✅ Đã xóa quyền admin của user ID `{target_user_id}`.")
        try:
            bot.send_message(target_user_id, "❌ Quyền Admin của bạn đã bị gỡ bỏ.")
        except Exception:
            pass
    else:
        bot.reply_to(message, f"User ID `{target_user_id}` không phải là admin.")


@bot.message_handler(commands=['danhsachadmin'])
def list_admins(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    if not ADMIN_IDS:
        bot.reply_to(message, "Hiện chưa có admin nào được thiết lập.")
        return

    admin_list_text = "🛡️ **DANH SÁCH ADMIN:** 🛡️\n"
    for admin_id in ADMIN_IDS:
        user_info = user_data.get(str(admin_id), {})
        username = user_info.get('username', 'Không rõ')
        admin_list_text += f"- ID: `{admin_id}` (Username: @{username})\n"
    bot.reply_to(message, admin_list_text, parse_mode='Markdown')


@bot.message_handler(commands=['broadcast'])
def send_broadcast(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    broadcast_text = telebot.util.extract_arguments(message.text)
    if not broadcast_text:
        bot.reply_to(message, "Vui lòng nhập nội dung thông báo. Ví dụ: `/broadcast Bot sẽ bảo trì vào 2h sáng mai.`", parse_mode='Markdown')
        return

    success_count = 0
    fail_count = 0
    for user_id_str in list(user_data.keys()):
        try:
            bot.send_message(int(user_id_str), f"📢 **THÔNG BÁO TỪ ADMIN** 📢\n\n{broadcast_text}", parse_mode='Markdown')
            success_count += 1
            time.sleep(0.1) # Tránh bị rate limit
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Không thể gửi thông báo cho user {user_id_str}: {e}")
            fail_count += 1
            if "bot was blocked by the user" in str(e) or "user is deactivated" in str(e):
                print(f"Người dùng {user_id_str} đã chặn bot hoặc bị vô hiệu hóa.")
        except Exception as e:
            print(f"Lỗi không xác định khi gửi thông báo cho user {user_id_str}: {e}")
            fail_count += 1

    bot.reply_to(message, f"Đã gửi thông báo đến {success_count} người dùng. Thất bại: {fail_count}.")
    save_user_data(user_data)


# Các lệnh tatbot/mokbot của bot chung, không phải cho từng user
@bot.message_handler(commands=['tatbot_main'])
def disable_main_bot_predictions(message):
    global bot_enabled, bot_disable_reason, bot_disable_admin_id
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    reason = telebot.util.extract_arguments(message.text)
    if not reason:
        bot.reply_to(message, "Vui lòng nhập lý do tắt bot chính. Ví dụ: `/tatbot_main Bot đang bảo trì.`", parse_mode='Markdown')
        return

    bot_enabled = False
    bot_disable_reason = reason
    bot_disable_admin_id = message.chat.id
    bot.reply_to(message, f"✅ Bot dự đoán chính đã được tắt bởi Admin `{message.from_user.username or message.from_user.first_name}`.\nLý do: `{reason}`", parse_mode='Markdown')

@bot.message_handler(commands=['mokbot_main'])
def enable_main_bot_predictions(message):
    global bot_enabled, bot_disable_reason, bot_disable_admin_id
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    if bot_enabled:
        bot.reply_to(message, "Bot dự đoán chính đã và đang hoạt động rồi.")
        return

    bot_enabled = True
    bot_disable_reason = "Không có"
    bot_disable_admin_id = None
    bot.reply_to(message, "✅ Bot dự đoán chính đã được mở lại bởi Admin.")


# --- Flask Routes cho Keep-Alive ---
@app.route('/')
def home():
    return "Bot is alive and running!"

@app.route('/health')
def health_check():
    return "OK", 200

# --- Khởi tạo bot và các luồng khi Flask app khởi động ---
@app.before_request
def start_bot_threads():
    global bot_initialized
    with bot_init_lock:
        if not bot_initialized:
            print("Initializing bot and prediction threads...")
            # Load initial data
            load_user_data()
            load_keys()

            # Start prediction loop in a separate thread
            prediction_thread = Thread(target=prediction_loop, args=(prediction_stop_event,))
            prediction_thread.daemon = True
            prediction_thread.start()
            print("Prediction loop thread started.")

            # Start bot polling in a separate thread
            polling_thread = Thread(target=bot.infinity_polling, kwargs={'none_stop': True})
            polling_thread.daemon = True
            polling_thread.start()
            print("Telegram bot polling thread started.")

            bot_initialized = True

# --- Điểm khởi chạy chính cho Gunicorn/Render ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask app locally on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
