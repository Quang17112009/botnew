import telebot
import requests
import time
import json
import os
import random
import string
from datetime import datetime, timedelta
from threading import Thread, Event, Lock

from flask import Flask, request

# --- Cấu hình Bot ---
BOT_TOKEN = "8137068939:AAG19xO92yXsz_d9vz_m2aJW2Wh8JZnvSPQ"
ADMIN_IDS = [6915752059]

DATA_FILE = 'user_data.json'
CODES_FILE = 'codes.json'
PREDICTION_STATS_FILE = 'prediction_stats.json'

# --- Khởi tạo Flask App và Telegram Bot ---
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=False) 

# Global flags và objects
bot_enabled = True
prediction_stop_event = Event() 
bot_initialized = False 
bot_init_lock = Lock() 

# Global data structures
user_data = {}
GENERATED_CODES = {} 
last_prediction_phien = None 
prediction_stats = {"correct": 0, "total": 0} 

# --- Quản lý dữ liệu người dùng và code ---
def load_user_data():
    global user_data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try:
                user_data = json.load(f)
                print(f"[DEBUG] Tải dữ liệu người dùng: {user_data}")
            except json.JSONDecodeError:
                print(f"[ERROR] Lỗi đọc {DATA_FILE}. Khởi tạo lại dữ liệu người dùng.")
                user_data = {}
    else:
        print(f"[DEBUG] File {DATA_FILE} không tồn tại. Khởi tạo dữ liệu người dùng rỗng.")
        user_data = {}
    print(f"Loaded {len(user_data)} user records from {DATA_FILE}")

def save_user_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"[DEBUG] Đã lưu {len(data)} bản ghi người dùng vào {DATA_FILE}")

def load_codes():
    global GENERATED_CODES
    if os.path.exists(CODES_FILE):
        with open(CODES_FILE, 'r') as f:
            try:
                GENERATED_CODES = json.load(f)
                print(f"[DEBUG] Tải dữ liệu codes: {GENERATED_CODES}")
            except json.JSONDecodeError:
                print(f"[ERROR] Lỗi đọc {CODES_FILE}. Khởi tạo lại mã code.")
                GENERATED_CODES = {}
    else:
        print(f"[DEBUG] File {CODES_FILE} không tồn tại. Khởi tạo mã code rỗng.")
        GENERATED_CODES = {}
    print(f"Loaded {len(GENERATED_CODES)} codes from {CODES_FILE}")

def save_codes():
    with open(CODES_FILE, 'w') as f:
        json.dump(GENERATED_CODES, f, indent=4)
    print(f"[DEBUG] Đã lưu {len(GENERATED_CODES)} codes vào {CODES_FILE}")

def load_prediction_stats():
    global prediction_stats
    if os.path.exists(PREDICTION_STATS_FILE):
        with open(PREDICTION_STATS_FILE, 'r') as f:
            try:
                prediction_stats = json.load(f)
            except json.JSONDecodeError:
                print(f"[ERROR] Lỗi đọc {PREDICTION_STATS_FILE}. Khởi tạo lại thống kê dự đoán.")
                prediction_stats = {"correct": 0, "total": 0}
    else:
        print(f"[DEBUG] File {PREDICTION_STATS_FILE} không tồn tại. Khởi tạo thống kê dự đoán rỗng.")
        prediction_stats = {"correct": 0, "total": 0}
    print(f"Loaded prediction stats: Correct {prediction_stats['correct']}, Total {prediction_stats['total']}")

def save_prediction_stats():
    with open(PREDICTION_STATS_FILE, 'w') as f:
        json.dump(prediction_stats, f, indent=4)
    print(f"[DEBUG] Đã lưu thống kê dự đoán: Correct {prediction_stats['correct']}, Total {prediction_stats['total']}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

def check_subscription(user_id):
    user_id_str = str(user_id)
    if is_admin(user_id):
        return True, "Bạn là Admin, quyền truy cập vĩnh viễn."

    if user_id_str not in user_data or user_data[user_id_str].get('expiry_date') is None:
        return False, "⚠️ Bạn chưa kích hoạt gói hoặc gói đã hết hạn."

    expiry_date_str = user_data[user_id_str]['expiry_date']
    if expiry_date_str == "Vĩnh viễn":
        return True, "✅ Gói của bạn là vĩnh viễn."

    try:
        expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        print(f"[ERROR] Định dạng ngày hết hạn không hợp lệ cho user {user_id_str}: {expiry_date_str}")
        return False, "⚠️ Định dạng ngày hết hạn không hợp lệ."

    if datetime.now() < expiry_date:
        remaining_time = expiry_date - datetime.now()
        days = remaining_time.days
        hours = remaining_time.seconds // 3600
        minutes = (remaining_time.seconds % 3600) // 60
        return True, f"✅ Gói của bạn còn hạn đến: `{expiry_date_str}` ({days} ngày {hours} giờ {minutes} phút)."
    else:
        return False, "❌ Gói của bạn đã hết hạn."

def get_subscription_status(user_id_str):
    if user_id_str not in user_data or user_data[user_id_str].get('expiry_date') is None:
        return "Chưa kích hoạt", "Chưa kích hoạt"
    
    expiry_date_str = user_data[user_id_str]['expiry_date']
    
    if expiry_date_str == "Vĩnh viễn":
        return "Vĩnh viễn", "Vĩnh viễn"

    try:
        expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        print(f"[ERROR] Định dạng ngày hết hạn không hợp lệ cho user {user_id_str}: {expiry_date_str}")
        return "Lỗi định dạng", "Lỗi định dạng"

    if datetime.now() < expiry_date:
        return "Đã kích hoạt", expiry_date_str
    else:
        return "Đã hết hạn", expiry_date_str

# --- Lấy dữ liệu từ API mới ---
def lay_du_lieu_tu_api_moi():
    try:
        print("[DEBUG] Đang cố gắng lấy dữ liệu từ API...")
        response = requests.get("https://apiluck2.onrender.com/predict")
        response.raise_for_status() 
        data = response.json()
        print(f"[DEBUG] Đã nhận dữ liệu từ API: {data}")
        return data
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Lỗi khi lấy dữ liệu từ API: {e}")
        return None
    except json.JSONDecodeError:
        print("[ERROR] Lỗi giải mã JSON từ API. Phản hồi không phải JSON hợp lệ.")
        return None

# --- Logic chính của Bot dự đoán (chạy trong luồng riêng) ---
def prediction_loop(stop_event: Event):
    global last_prediction_phien, prediction_stats
    print("[INFO] Prediction loop started.")
    
    # Khởi tạo last_prediction_phien từ API khi khởi động
    initial_api_data = lay_du_lieu_tu_api_moi()
    if initial_api_data:
        last_prediction_phien = initial_api_data.get("phien_du_doan")
        print(f"[INFO] Khởi tạo last_prediction_phien: {last_prediction_phien}")
    else:
        print("[WARNING] Không thể lấy dữ liệu API ban đầu để khởi tạo last_prediction_phien.")

    while not stop_event.is_set():
        if not bot_enabled:
            print("[DEBUG] Bot đang bị tắt, chờ 10 giây.")
            time.sleep(10) 
            continue

        api_data = lay_du_lieu_tu_api_moi()
        if not api_data:
            print("[WARNING] Không có dữ liệu API, chờ 5 giây.")
            time.sleep(5)
            continue

        current_phien_api = api_data.get("Phien_moi")
        phien_du_doan_api = api_data.get("phien_du_doan")

        if not all([current_phien_api, phien_du_doan_api]):
            print(f"[WARNING] Dữ liệu API không đầy đủ: Phien_moi={current_phien_api}, phien_du_doan={phien_du_doan_api}. Bỏ qua phiên này.")
            time.sleep(5)
            continue
        
        print(f"[DEBUG] Phiên API hiện tại: {current_phien_api}, Phiên dự đoán API: {phien_du_doan_api}, last_prediction_phien đã lưu: {last_prediction_phien}")

        # So sánh phiên dự đoán từ API với phiên cuối cùng đã gửi
        if phien_du_doan_api != last_prediction_phien:
            print(f"[INFO] Phát hiện phiên dự đoán mới: {phien_du_doan_api}. Bắt đầu xử lý.")
            
            ket_qua_hien_tai_raw = api_data.get("matches")[0].upper() if api_data.get("matches") else "?"
            if ket_qua_hien_tai_raw == "T":
                ket_qua_text = "TÀI"
            elif ket_qua_hien_tai_raw == "X":
                ket_qua_text = "XỈU"
            else:
                ket_qua_text = "Không rõ"
            
            # API không trả về tổng 3 xúc xắc cụ thể. Dùng tạm "Tổng: XX" nếu có thể suy luận hoặc bỏ qua.
            tong_ket_qua_hien_tai = "??" 

            pattern = api_data.get("pattern", "Không có")
            du_doan_ket_qua = api_data.get("du_doan", "Không rõ")
            
            prediction_message = (
                f"🤖 ʟᴜᴄᴋʏᴡɪɴ\n"
                f"🎯 ᴘʜɪᴇ̂ɴ {current_phien_api}\n"
                f"🎲 ᴋᴇ̂́ᴛ ǫᴜᴀ̉ : {ket_qua_text} {tong_ket_qua_hien_tai}\n"
                f"🧩 ᴘᴀᴛᴛᴇʀɴ : {pattern.upper()}\n"
                f"🎮  ᴘʜɪᴇ̂ɴ {phien_du_doan_api} : {du_doan_ket_qua} (ᴍᴏᴅᴇʟ ʙᴀꜱɪᴄ)\n"
                "————————-"
            )

            # Cập nhật thống kê dự đoán
            if du_doan_ket_qua.lower().strip() == ket_qua_text.lower().strip(): # So sánh dự đoán với kết quả thực tế
                prediction_stats['correct'] += 1
                print(f"[DEBUG] Dự đoán đúng: {du_doan_ket_qua} == {ket_qua_text}")
            else:
                print(f"[DEBUG] Dự đoán sai: {du_doan_ket_qua} != {ket_qua_text}")
            prediction_stats['total'] += 1
            save_prediction_stats()

            # Gửi tin nhắn cho người dùng
            for user_id_str, user_info in list(user_data.items()):
                user_id = int(user_id_str)
                is_sub, sub_message = check_subscription(user_id)
                
                if is_sub and user_info.get('running_prediction'):
                    try:
                        print(f"[DEBUG] Gửi tin nhắn cho user {user_id}...")
                        bot.send_message(user_id, prediction_message)
                        print(f"[INFO] Đã gửi tin nhắn cho user {user_id}.")
                    except telebot.apihelper.ApiTelegramException as e:
                        if "bot was blocked by the user" in str(e) or "user is deactivated" in str(e):
                            print(f"[WARNING] Người dùng {user_id} đã chặn bot hoặc bị vô hiệu hóa.")
                            # Optional: remove user from user_data if blocked permanently
                        else:
                            print(f"[ERROR] Lỗi gửi tin nhắn cho user {user_id}: {e}")
                    except Exception as e:
                        print(f"[ERROR] Lỗi không xác định khi gửi tin nhắn cho user {user_id}: {e}")
                elif not is_sub:
                    print(f"[DEBUG] Bỏ qua user {user_id}: Gói đã hết hạn hoặc chưa kích hoạt.")
                else: # user_info.get('running_prediction') is False
                    print(f"[DEBUG] Bỏ qua user {user_id}: Người dùng chưa bật dự đoán.")
            
            print(f"[INFO] Kết thúc xử lý phiên {phien_du_doan_api}. Cập nhật last_prediction_phien.")
            last_prediction_phien = phien_du_doan_api
        else:
            print(f"[DEBUG] Phiên {phien_du_doan_api} không phải phiên mới. Không gửi tin nhắn.")

        time.sleep(5) 
    print("[INFO] Prediction loop stopped.")

# --- Xử lý lệnh Telegram ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    username = message.from_user.first_name or message.from_user.username
    
    if user_id not in user_data:
        user_data[user_id] = {
            'username': username,
            'expiry_date': None,
            'running_prediction': False 
        }
        save_user_data(user_data)
        print(f"[INFO] Đã thêm người dùng mới: {user_id} - {username}")
    else:
        if user_data[user_id].get('username') != username:
            user_data[user_id]['username'] = username 
            save_user_data(user_data)
            print(f"[INFO] Đã cập nhật username cho người dùng: {user_id} - {username}")


    current_package, expiry_status = get_subscription_status(user_id)

    welcome_message = (
        f"🌟 CHÀO MỪNG {username} 🌟\n"
        "🎉 Chào mừng đến với HeHe Bot 🎉\n"
        f"📦 Gói hiện tại: {current_package}\n"
        f"⏰ Hết hạn: {expiry_status}\n"
        "💡 Dùng /help để xem các lệnh"
    )
    bot.reply_to(message, welcome_message)
    print(f"[INFO] Đã gửi tin nhắn chào mừng cho {user_id}")

@bot.message_handler(commands=['help'])
def show_help(message):
    user_id_str = str(message.chat.id)
    current_package, expiry_status = get_subscription_status(user_id_str)

    help_text = (
        f"📦 Gói hiện tại: {current_package}\n"
        "🔥 Các lệnh hỗ trợ:\n"
        "✅ `/start` - Đăng ký và bắt đầu\n"
        "🔑 `/key [mã]` - Kích hoạt gói\n"
        "🎮 `/chaymodelbasic` - Chạy dự đoán  (LUCK)\n"
        "🛑 `/stop` - Dừng dự đoán\n"
        "🛠️ `/admin` - Lệnh dành cho admin\n"
        "📬 Liên hệ:\n"
        "👤 Admin: t.me/heheviptool\n"
        "——————"
    )
    bot.reply_to(message, help_text, parse_mode='Markdown')
    print(f"[INFO] Đã gửi tin nhắn trợ giúp cho {user_id_str}")

@bot.message_handler(commands=['key'])
def use_code(message):
    code_str = telebot.util.extract_arguments(message.text)
    user_id = str(message.chat.id)
    print(f"[INFO] User {user_id} dùng lệnh /key với code: {code_str}")

    if not code_str:
        bot.reply_to(message, "Vui lòng nhập mã code. Ví dụ: `/key ABCXYZ`", parse_mode='Markdown')
        return
    
    if code_str not in GENERATED_CODES:
        bot.reply_to(message, "❌ Mã code không tồn tại hoặc đã hết hạn.")
        return

    code_info = GENERATED_CODES[code_str]
    if code_info.get('used_by') is not None:
        bot.reply_to(message, "❌ Mã code này đã được sử dụng rồi.")
        return

    # Apply extension
    current_expiry_str = user_data.get(user_id, {}).get('expiry_date')
    
    if code_info['type'] == 'vĩnh_viễn':
        new_expiry_date_str = "Vĩnh viễn"
        value_display = "" 
        unit_display = "vĩnh viễn"
    else:
        if current_expiry_str and current_expiry_str != "Vĩnh viễn":
            try:
                current_expiry_date = datetime.strptime(current_expiry_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                print(f"[ERROR] Định dạng ngày hết hạn cũ không hợp lệ cho user {user_id}: {current_expiry_str}. Bắt đầu từ bây giờ.")
                current_expiry_date = datetime.now() # Reset nếu định dạng cũ lỗi
            
            if datetime.now() > current_expiry_date:
                new_expiry_date = datetime.now()
            else:
                new_expiry_date = current_expiry_date
        else:
            new_expiry_date = datetime.now() 

        value = code_info['value']
        unit = code_info['type']
        value_display = value
        unit_display = unit

        if unit == 'phút':
            new_expiry_date += timedelta(minutes=value)
        elif unit == 'giờ':
            new_expiry_date += timedelta(hours=value)
        elif unit == 'ngày':
            new_expiry_date += timedelta(days=value)
        elif unit == 'tuần':
            new_expiry_date += timedelta(weeks=value)
        elif unit == 'tháng':
            new_expiry_date += timedelta(days=value*30) 
        
        new_expiry_date_str = new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    user_data.setdefault(user_id, {})['expiry_date'] = new_expiry_date_str
    user_data[user_id]['username'] = message.from_user.first_name or message.from_user.username
    
    GENERATED_CODES[code_str]['used_by'] = user_id
    GENERATED_CODES[code_str]['used_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    save_user_data(user_data)
    save_codes()

    bot.reply_to(message, 
                 f"🎉 Bạn đã đổi mã code thành công! Gói của bạn đã được gia hạn thêm **{value_display} {unit_display}**.\n"
                 f"Ngày hết hạn mới: `{user_data[user_id]['expiry_date']}`", 
                 parse_mode='Markdown')
    print(f"[INFO] User {user_id} đã kích hoạt code {code_str}. Hết hạn mới: {new_expiry_date_str}")

@bot.message_handler(commands=['chaymodelbasic'])
def start_prediction_command(message):
    user_id = str(message.chat.id)
    print(f"[INFO] User {user_id} dùng lệnh /chaymodelbasic")
    is_sub, sub_message = check_subscription(int(user_id))
    
    if not is_sub:
        bot.reply_to(message, sub_message + "\nVui lòng liên hệ Admin t.me/heheviptool để được hỗ trợ.", parse_mode='Markdown')
        print(f"[INFO] User {user_id} không đủ điều kiện để chạy dự đoán: {sub_message}")
        return
    
    if not bot_enabled:
        bot.reply_to(message, f"❌ Bot dự đoán hiện đang tạm dừng bởi Admin. Vui lòng thử lại sau.", parse_mode='Markdown')
        print(f"[INFO] User {user_id} không thể chạy dự đoán vì bot bị tắt.")
        return

    user_data[user_id]['running_prediction'] = True
    save_user_data(user_data)
    bot.reply_to(message, "✅ Bạn đã bật chế độ nhận dự đoán từ bot. Bot sẽ tự động gửi dự đoán các phiên mới nhất tại đây.")
    print(f"[INFO] User {user_id} đã bật nhận dự đoán.")

@bot.message_handler(commands=['stop'])
def stop_prediction_command(message):
    user_id = str(message.chat.id)
    user_data[user_id]['running_prediction'] = False
    save_user_data(user_data)
    bot.reply_to(message, "✅ Bạn đã dừng nhận dự đoán từ bot.")
    print(f"[INFO] User {user_id} đã dừng nhận dự đoán.")

# --- Lệnh Admin ---
@bot.message_handler(commands=['admin'])
def admin_menu(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        print(f"[WARNING] User {message.chat.id} không có quyền dùng lệnh /admin.")
        return
    
    admin_help_text = (
        "👑 **LỆNH ADMIN** 👑\n\n"
        "🔹 `/full <id>`: Xem thông tin người dùng (để trống ID để xem của bạn).\n"
        "🔹 `/giahan <id> <số ngày/giờ/tuần/tháng/vĩnh_viễn>`: Gia hạn tài khoản. VD: `/giahan 12345 1 ngày`, `/giahan 67890 vĩnh_viễn`.\n"
        "🔹 `/tb <nội dung>`: Gửi thông báo đến tất cả người dùng.\n"
        "🔹 `/tatbot`: Tắt mọi hoạt động dự đoán của bot.\n"
        "🔹 `/mokbot`: Mở lại hoạt động dự đoán của bot.\n"
        "🔹 `/taokey <giá trị> <phút/giờ/ngày/tuần/tháng/vĩnh_viễn> <số lượng>`: Tạo mã key. VD: `/taokey 1 ngày 5`, `/taokey 1 vĩnh_viễn 1`.\n"
        "🔹 `/check`: Kiểm tra thống kê dự đoán của bot.\n"
        "🔹 `/thongke` : Thống kê số lượng người dùng và key đã dùng."
    )
    bot.reply_to(message, admin_help_text, parse_mode='Markdown')
    print(f"[INFO] Admin {message.chat.id} yêu cầu menu admin.")

@bot.message_handler(commands=['full'])
def get_user_info(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    args = telebot.util.extract_arguments(message.text).split()
    target_user_id_str = str(message.chat.id)
    if args and args[0].isdigit():
        target_user_id_str = args[0]
    
    if target_user_id_str not in user_data:
        bot.reply_to(message, f"Không tìm thấy thông tin cho người dùng ID `{target_user_id_str}`.")
        return

    user_info = user_data[target_user_id_str]
    expiry_date_str = user_info.get('expiry_date', 'Chưa kích hoạt')
    username = user_info.get('username', 'Không rõ')
    running_pred_status = "Đang chạy" if user_info.get('running_prediction') else "Đã dừng"

    info_text = (
        f"**THÔNG TIN NGƯỜI DÙNG**\n"
        f"**ID:** `{target_user_id_str}`\n"
        f"**Tên:** @{username}\n"
        f"**Ngày hết hạn:** `{expiry_date_str}`\n"
        f"**Trạng thái nhận dự đoán:** {running_pred_status}"
    )
    bot.reply_to(message, info_text, parse_mode='Markdown')
    print(f"[INFO] Admin {message.chat.id} yêu cầu thông tin user: {target_user_id_str}")

@bot.message_handler(commands=['giahan'])
def extend_subscription(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    args = telebot.util.extract_arguments(message.text).split()
    if not (len(args) == 3 and args[1].isdigit() and args[2].lower() in ['phút', 'giờ', 'ngày', 'tuần', 'tháng']) and \
       not (len(args) == 2 and args[1].lower() == 'vĩnh_viễn' and args[0].isdigit()):
        bot.reply_to(message, "Cú pháp sai. Ví dụ: `/giahan <id_nguoi_dung> <số_lượng> <phút/giờ/ngày/tuần/tháng>` hoặc `/giahan <id_nguoi_dung> vĩnh_viễn`.\n"
                              "Ví dụ: `/giahan 12345 1 ngày` hoặc `/giahan 67890 vĩnh_viễn`", parse_mode='Markdown')
        return
    
    target_user_id_str = args[0]

    if target_user_id_str not in user_data:
        user_data[target_user_id_str] = {
            'username': "UnknownUser",
            'expiry_date': None,
            'running_prediction': False
        }
        bot.send_message(message.chat.id, f"Đã tạo tài khoản mới cho user ID `{target_user_id_str}`.")
        print(f"[INFO] Admin {message.chat.id} tạo tài khoản mới cho {target_user_id_str}.")

    if args[1].lower() == 'vĩnh_viễn':
        new_expiry_date_str = "Vĩnh viễn"
        value_display = ""
        unit_display = "vĩnh viễn"
    else:
        value = int(args[1])
        unit = args[2].lower()
        value_display = value
        unit_display = unit

        current_expiry_str = user_data[target_user_id_str].get('expiry_date')
        if current_expiry_str and current_expiry_str != "Vĩnh viễn":
            try:
                current_expiry_date = datetime.strptime(current_expiry_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                print(f"[ERROR] Định dạng ngày hết hạn cũ không hợp lệ cho user {target_user_id_str}: {current_expiry_str}. Bắt đầu từ bây giờ.")
                current_expiry_date = datetime.now()
            if datetime.now() > current_expiry_date:
                new_expiry_date = datetime.now()
            else:
                new_expiry_date = current_expiry_date
        else:
            new_expiry_date = datetime.now() 

        if unit == 'phút':
            new_expiry_date += timedelta(minutes=value)
        elif unit == 'giờ':
            new_expiry_date += timedelta(hours=value)
        elif unit == 'ngày':
            new_expiry_date += timedelta(days=value)
        elif unit == 'tuần':
            new_expiry_date += timedelta(weeks=value)
        elif unit == 'tháng':
            new_expiry_date += timedelta(days=value*30) 
        
        new_expiry_date_str = new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')
    
    user_data[target_user_id_str]['expiry_date'] = new_expiry_date_str
    save_user_data(user_data)
    
    bot.reply_to(message, 
                 f"Đã gia hạn thành công cho user ID `{target_user_id_str}` thêm **{value_display} {unit_display}**.\n"
                 f"Ngày hết hạn mới: `{user_data[target_user_id_str]['expiry_date']}`",
                 parse_mode='Markdown')
    print(f"[INFO] Admin {message.chat.id} gia hạn cho user {target_user_id_str} thêm {value_display} {unit_display}. Hết hạn mới: {new_expiry_date_str}")
    
    try:
        bot.send_message(int(target_user_id_str), 
                         f"🎉 Tài khoản của bạn đã được gia hạn thêm **{value_display} {unit_display}** bởi Admin!\n"
                         f"Ngày hết hạn mới của bạn là: `{user_data[target_user_id_str]['expiry_date']}`",
                         parse_mode='Markdown')
        print(f"[INFO] Đã thông báo gia hạn cho user {target_user_id_str}.")
    except telebot.apihelper.ApiTelegramException as e:
        if "bot was blocked by the user" in str(e):
            print(f"[WARNING] Không thể thông báo gia hạn cho user {target_user_id_str}: người dùng đã chặn bot.")
        else:
            print(f"[ERROR] Không thể thông báo gia hạn cho user {target_user_id_str}: {e}")

@bot.message_handler(commands=['tb'])
def send_broadcast(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    broadcast_text = telebot.util.extract_arguments(message.text)
    if not broadcast_text:
        bot.reply_to(message, "Vui lòng nhập nội dung thông báo. Ví dụ: `/tb Bot sẽ bảo trì vào 2h sáng mai.`", parse_mode='Markdown')
        return
    
    success_count = 0
    fail_count = 0
    print(f"[INFO] Admin {message.chat.id} gửi thông báo Broadcast: {broadcast_text}")
    for user_id_str in list(user_data.keys()):
        try:
            bot.send_message(int(user_id_str), f"📢 **THÔNG BÁO TỪ ADMIN** 📢\n\n{broadcast_text}", parse_mode='Markdown')
            success_count += 1
            time.sleep(0.1) 
        except telebot.apihelper.ApiTelegramException as e:
            fail_count += 1
            if "bot was blocked by the user" in str(e) or "user is deactivated" in str(e):
                print(f"[WARNING] Người dùng {user_id_str} đã chặn bot hoặc bị vô hiệu hóa khi gửi broadcast.")
            else:
                print(f"[ERROR] Lỗi không gửi được thông báo broadcast cho user {user_id_str}: {e}")
        except Exception as e:
            print(f"[ERROR] Lỗi không xác định khi gửi thông báo broadcast cho user {user_id_str}: {e}")
            fail_count += 1
                
    bot.reply_to(message, f"Đã gửi thông báo đến {success_count} người dùng. Thất bại: {fail_count}.")
    save_user_data(user_data)

@bot.message_handler(commands=['tatbot'])
def disable_bot_command(message):
    global bot_enabled
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    if not bot_enabled:
        bot.reply_to(message, "Bot dự đoán đã và đang tắt rồi.")
        return

    bot_enabled = False
    bot.reply_to(message, f"✅ Bot dự đoán đã được tắt bởi Admin.")
    print(f"[INFO] Admin {message.chat.id} đã tắt bot.")
    
@bot.message_handler(commands=['mokbot'])
def enable_bot_command(message):
    global bot_enabled
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    if bot_enabled:
        bot.reply_to(message, "Bot dự đoán đã và đang hoạt động rồi.")
        return

    bot_enabled = True
    bot.reply_to(message, "✅ Bot dự đoán đã được mở lại bởi Admin.")
    print(f"[INFO] Admin {message.chat.id} đã mở bot.")
    
@bot.message_handler(commands=['taokey'])
def generate_code_command(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    args = telebot.util.extract_arguments(message.text).split()
    if not (len(args) >= 2 and len(args) <= 3):
        bot.reply_to(message, "Cú pháp sai. Ví dụ:\n"
                              "`/taokey <giá_trị> <phút/giờ/ngày/tuần/tháng> <số_lượng>`\n"
                              "Hoặc: `/taokey 1 vĩnh_viễn <số_lượng>`\n"
                              "Ví dụ: `/taokey 1 ngày 5` (tạo 5 key 1 ngày)\n"
                              "Hoặc: `/taokey 1 vĩnh_viễn 1` (tạo 1 key vĩnh viễn)", parse_mode='Markdown')
        return
    
    try:
        value_arg = args[0]
        unit_arg = args[1].lower()
        quantity = int(args[2]) if len(args) == 3 else 1 
        
        valid_units = ['phút', 'giờ', 'ngày', 'tuần', 'tháng', 'vĩnh_viễn']
        if unit_arg not in valid_units:
            bot.reply_to(message, "Đơn vị không hợp lệ. Chỉ chấp nhận `phút`, `giờ`, `ngày`, `tuần`, `tháng` hoặc `vĩnh_viễn`.", parse_mode='Markdown')
            return
        
        if unit_arg == 'vĩnh_viễn':
            value = 1 
            if not value_arg.isdigit() or int(value_arg) != 1:
                bot.reply_to(message, "Đối với gói `vĩnh_viễn`, giá trị phải là `1`.", parse_mode='Markdown')
                return
        else:
            value = int(value_arg)
            if value <= 0:
                bot.reply_to(message, "Giá trị phải lớn hơn 0.", parse_mode='Markdown')
                return
        
        if quantity <= 0:
            bot.reply_to(message, "Số lượng phải lớn hơn 0.", parse_mode='Markdown')
            return

        generated_keys_list = []
        for _ in range(quantity):
            new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8)) 
            GENERATED_CODES[new_key] = {
                "value": value,
                "type": unit_arg,
                "used_by": None,
                "used_time": None
            }
            generated_keys_list.append(new_key)
        
        save_codes()
        
        response_text = f"✅ Đã tạo thành công {quantity} mã key gia hạn **{value_arg} {unit_arg}**:\n\n"
        response_text += "\n".join([f"`{key}`" for key in generated_keys_list])
        response_text += "\n\n_(Các mã này chưa được sử dụng)_"
        
        bot.reply_to(message, response_text, parse_mode='Markdown')
        print(f"[INFO] Admin {message.chat.id} đã tạo {quantity} key {value_arg} {unit_arg}.")

    except ValueError:
        bot.reply_to(message, "Giá trị hoặc số lượng không hợp lệ. Vui lòng nhập số nguyên.", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"Đã xảy ra lỗi khi tạo key: {e}", parse_mode='Markdown')

@bot.message_handler(commands=['check'])
def check_prediction_stats(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return
    
    total = prediction_stats['total']
    correct = prediction_stats['correct']
    
    if total > 0:
        win_rate = (correct / total) * 100
        stats_text = (
            "📊 **THỐNG KÊ DỰ ĐOÁN BOT** 📊\n\n"
            f"✅ Số phiên dự đoán đúng: `{correct}`\n"
            f"🔢 Tổng số phiên đã dự đoán: `{total}`\n"
            f"📈 Tỷ lệ thắng: `{win_rate:.2f}%`"
        )
    else:
        stats_text = "📊 **THỐNG KÊ DỰ ĐOÁN BOT** 📊\n\nChưa có đủ dữ liệu để thống kê dự đoán."
    
    bot.reply_to(message, stats_text, parse_mode='Markdown')
    print(f"[INFO] Admin {message.chat.id} yêu cầu thống kê dự đoán.")


@bot.message_handler(commands=['thongke'])
def get_stats(message):
    if not is_admin(message.chat.id):
        bot.reply_to(message, "Bạn không có quyền sử dụng lệnh này.")
        return

    total_users = len(user_data)
    active_users = 0
    for user_id_str, user_info in user_data.items():
        is_sub, _ = check_subscription(int(user_id_str))
        if is_sub:
            active_users += 1

    total_codes = len(GENERATED_CODES)
    used_codes = sum(1 for code_info in GENERATED_CODES.values() if code_info.get('used_by') is not None)

    stats_text = (
        "📊 **THỐNG KÊ BOT** 📊\n\n"
        f"👥 Tổng số người dùng: `{total_users}`\n"
        f"🟢 Người dùng đang hoạt động: `{active_users}`\n"
        f"🔑 Tổng số mã key đã tạo: `{total_codes}`\n"
        f"✅ Mã key đã sử dụng: `{used_codes}`"
    )
    bot.reply_to(message, stats_text, parse_mode='Markdown')
    print(f"[INFO] Admin {message.chat.id} yêu cầu thống kê chung.")


# --- Flask Routes cho Webhook và Keep-Alive ---
@app.route('/' + BOT_TOKEN, methods=['POST']) 
def get_message():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "!", 200 
    else:
        print(f"[ERROR] Webhook nhận request không phải JSON: {request.headers.get('content-type')}")
        return "Unsupported Media Type", 415

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
            print("[INIT] Initializing bot and prediction threads...")
            
            load_user_data()
            load_codes()
            load_prediction_stats() 

            # Thiết lập webhook
            WEBHOOK_URL_BASE = os.environ.get('RENDER_EXTERNAL_HOSTNAME') 
            if not WEBHOOK_URL_BASE:
                print("[WARNING] Biến môi trường RENDER_EXTERNAL_HOSTNAME không được tìm thấy. Đang sử dụng URL mặc định. Đảm bảo bạn đã thay thế nó!")
                # Bạn PHẢI thay thế dòng dưới đây bằng URL Render thực tế của bạn
                WEBHOOK_URL_BASE = 'YOUR_RENDER_APP_URL.onrender.com' 
            
            WEBHOOK_URL = f"https://{WEBHOOK_URL_BASE}/{BOT_TOKEN}"
            
            print(f"[INIT] Cố gắng đặt webhook tới: {WEBHOOK_URL}")
            try:
                bot.remove_webhook() 
                time.sleep(0.1) 
                bot.set_webhook(url=WEBHOOK_URL)
                print("[INIT] Webhook đã được đặt thành công.")
            except Exception as e:
                print(f"[ERROR] Lỗi khi đặt webhook: {e}")

            prediction_thread = Thread(target=prediction_loop, args=(prediction_stop_event,))
            prediction_thread.daemon = True
            prediction_thread.start()
            print("[INIT] Prediction loop thread đã khởi động.")
            
            bot_initialized = True
            print("[INIT] Bot đã được khởi tạo hoàn tất.")

# --- Điểm khởi chạy chính cho Gunicorn/Render ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask app locally on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

