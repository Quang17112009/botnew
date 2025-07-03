import os
import requests
import asyncio
import logging
import collections
import copy
import random
import datetime
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Cấu hình bot ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8137068939:AAG19xO92yXsz_d9vz_m2aJW2Wh8JZnvSPQ")
EXTERNAL_API_URL = "https://apib52.up.railway.app/api/taixiumd5"

ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "6915752059")) # VD: 123456789

# Trạng thái bot
bot_running = False
prediction_task = None
current_game_name = "ʙ𝟧𝟤"

# --- Mẫu dữ liệu ban đầu và trạng thái toàn cục cho logic dự đoán ---
initial_api_data_template = {
    "Phien_moi": None,
    "pattern_length": 8,
    "pattern": "xxxxxxxx",
    "matches": ["x"],
    "pattern_tai": 0,
    "pattern_xiu": 0,
    "pattern_percent_tai": 0,
    "pattern_percent_xiu": 0,
    "phan_tram_tai": 50,
    "phan_tram_xiu": 50,
    "tong_tai": 0.0,
    "tong_xiu": 0.0,
    "du_doan": "Không có",
    "ly_do": "Chưa có dữ liệu dự đoán.",
    "phien_du_doan": None,
    "admin_info": "@heheviptool"
}

# Lịch sử các kết quả thực tế (t='Tài', x='Xỉu')
history_results = collections.deque(maxlen=100)

# Lưu trữ trạng thái dự đoán gần nhất để kiểm tra 'consecutive_losses'
last_prediction_info = {
    "predicted_expect": None,
    "predicted_result": None,
    "consecutive_losses": 0,
    "last_actual_result": None
}

# Biến để theo dõi phiên cuối cùng đã xử lý từ API ngoài để tránh xử lý trùng lặp
last_processed_phien = None

# --- Thống kê dự đoán ---
prediction_stats = {
    "total_predictions": 0,
    "correct_predictions": 0,
    "last_checked_phien": None # Phiên cuối cùng được kiểm tra khi tính đúng/sai
}

# --- Quản lý Key ---
# Để đơn giản, key được lưu trong bộ nhớ. Trong thực tế, bạn NÊN dùng database.
active_keys = {} # key: { 'expiry_time': datetime_object, 'user_id': user_id, 'is_active': True }
users_with_active_subscriptions = {} # user_id: key

KEY_FILE = "keys.json" # File để lưu trữ keys (đơn giản, không phải database thực sự)

def load_keys():
    global active_keys, users_with_active_subscriptions
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, 'r') as f:
                data = json.load(f)
                active_keys_loaded = {}
                users_with_active_subscriptions_loaded = {}
                for key, details in data['active_keys'].items():
                    # Chuyển đổi chuỗi ngày thành datetime object
                    if details['expiry_time'] != 'forever':
                        details['expiry_time'] = datetime.datetime.fromisoformat(details['expiry_time'])
                    active_keys_loaded[key] = details
                users_with_active_subscriptions_loaded = {int(uid): k for uid, k in data['users_with_active_subscriptions'].items()}
                
                active_keys = active_keys_loaded
                users_with_active_subscriptions = users_with_active_subscriptions_loaded
                logger.info("Keys loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading keys: {e}")
    else:
        logger.info("No keys file found. Starting with empty keys.")

def save_keys():
    try:
        with open(KEY_FILE, 'w') as f:
            data_to_save = {
                'active_keys': {},
                'users_with_active_subscriptions': {str(uid): k for uid, k in users_with_active_subscriptions.items()}
            }
            for key, details in active_keys.items():
                details_copy = details.copy()
                if details_copy['expiry_time'] != 'forever':
                    details_copy['expiry_time'] = details_copy['expiry_time'].isoformat()
                data_to_save['active_keys'][key] = details_copy
            json.dump(data_to_save, f, indent=4)
            logger.info("Keys saved successfully.")
    except Exception as e:
        logger.error(f"Error saving keys: {e}")

def generate_key(length=16):
    """Tạo một chuỗi key ngẫu nhiên."""
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    return ''.join(random.choice(chars) for _ in range(length))

def get_expiry_time(duration_type, value):
    """Tính toán thời gian hết hạn của key."""
    current_time = datetime.datetime.now()
    if duration_type == 'phut':
        return current_time + datetime.timedelta(minutes=value)
    elif duration_type == 'gio':
        return current_time + datetime.timedelta(hours=value)
    elif duration_type == 'ngay':
        return current_time + datetime.timedelta(days=value)
    elif duration_type == 'tuan':
        return current_time + datetime.timedelta(weeks=value)
    elif duration_type == 'thang':
        # Để đơn giản, 1 tháng = 30 ngày. Trong thực tế cần xử lý chính xác hơn.
        return current_time + datetime.timedelta(days=value * 30)
    elif duration_type == 'vinhvien':
        return 'forever'
    return None

def is_key_valid(key):
    """Kiểm tra xem key có tồn tại và còn hạn không."""
    if key not in active_keys:
        return False
    key_details = active_keys[key]
    if not key_details['is_active']:
        return False
    if key_details['expiry_time'] == 'forever':
        return True
    return datetime.datetime.now() < key_details['expiry_time']

def is_user_subscribed(user_id):
    """Kiểm tra xem người dùng có đăng ký hoạt động không."""
    if user_id not in users_with_active_subscriptions:
        return False
    key = users_with_active_subscriptions[user_id]
    return is_key_valid(key)


# --- Hàm hỗ trợ logic dự đoán (trích từ app.py) ---
def calculate_tai_xiu(xuc_xac_1, xuc_xac_2, xuc_xac_3):
    total_sum = xuc_xac_1 + xuc_xac_2 + xuc_xac_3
    if total_sum >= 4 and total_sum <= 10: return "Xỉu", total_sum
    elif total_sum >= 11 and total_sum <= 17: return "Tài", total_sum
    else: # 3 or 18
        if total_sum == 3: return "Xỉu", total_sum
        if total_sum == 18: return "Tài", total_sum
        return "Không xác định", total_sum

def get_next_phien_code(current_phien_int):
    if isinstance(current_phien_int, int): return current_phien_int + 1
    return None

def update_history_and_state(new_session_data):
    global history_results, initial_api_data_template, last_prediction_info, last_processed_phien, prediction_stats

    current_phien = new_session_data['Phien']
    current_ket_qua = new_session_data['Ket_qua']
    xuc_xac_1 = new_session_data['Xuc_xac_1']
    xuc_xac_2 = new_session_data['Xuc_xac_2']
    xuc_xac_3 = new_session_data['Xuc_xac_3']
    tong_xuc_xac = new_session_data['Tong']

    actual_result_char = "t" if "Tài" in current_ket_qua else "x"

    if current_phien != last_processed_phien:
        history_results.append({
            "Phien": current_phien,
            "Tong": tong_xuc_xac,
            "Xuc_xac_1": xuc_xac_1,
            "Xuc_xac_2": xuc_xac_2,
            "Xuc_xac_3": xuc_xac_3,
            "Result": actual_result_char,
            "Ket_qua": current_ket_qua
        })
        logger.info(f"Added new session to history: Phien {current_phien} - Result: {current_ket_qua}")
        last_processed_phien = current_phien

        # Update prediction stats (after history is updated and before new prediction is made)
        if last_prediction_info["predicted_expect"] is not None and \
           last_prediction_info["predicted_expect"] == current_phien and \
           last_prediction_info["predicted_result"] is not None:
            
            predicted_res = last_prediction_info["predicted_result"]
            
            # Chỉ tăng total_predictions khi có một dự đoán cho phiên này
            if prediction_stats["last_checked_phien"] != current_phien:
                prediction_stats["total_predictions"] += 1
                prediction_stats["last_checked_phien"] = current_phien

            if predicted_res.lower() != actual_result_char:
                last_prediction_info["consecutive_losses"] += 1
                logger.info(f"Prediction '{predicted_res}' for session Phien {current_phien} MISSED. Consecutive losses: {last_prediction_info['consecutive_losses']}")
            else:
                last_prediction_info["consecutive_losses"] = 0
                prediction_stats["correct_predictions"] += 1
                logger.info(f"Prediction '{predicted_res}' for session Phien {current_phien} CORRECT. Resetting losses.")
        else:
            last_prediction_info["consecutive_losses"] = 0
            logger.info("No matching previous prediction to evaluate or app restarted. Resetting losses.")
        
        last_prediction_info["last_actual_result"] = actual_result_char

    initial_api_data_template["Phien_moi"] = current_phien
    next_phien = get_next_phien_code(current_phien)
    initial_api_data_template["phien_du_doan"] = next_phien if next_phien else "Không xác định"

    current_pattern_chars = "".join([entry['Result'] for entry in history_results])
    initial_api_data_template['pattern'] = current_pattern_chars[-initial_api_data_template['pattern_length']:]
    
    tai_count = initial_api_data_template['pattern'].count('t')
    xiu_count = initial_api_data_template['pattern'].count('x')
    
    initial_api_data_template['pattern_tai'] = tai_count
    initial_api_data_template['pattern_xiu'] = xiu_count

    total_pattern_chars = len(initial_api_data_template['pattern'])
    if total_pattern_chars > 0:
        initial_api_data_template['pattern_percent_tai'] = round((tai_count / total_pattern_chars) * 100, 2)
        initial_api_data_template['pattern_percent_xiu'] = round((xiu_count / total_pattern_chars) * 100, 2)
    else:
        initial_api_data_template['pattern_percent_tai'] = 0
        initial_api_data_template['pattern_percent_xiu'] = 0

    if history_results:
        initial_api_data_template['matches'] = [history_results[-1]['Result']]
    else:
        initial_api_data_template['matches'] = []

    initial_api_data_template['phan_tram_tai'] = initial_api_data_template['pattern_percent_tai']
    initial_api_data_template['phan_tram_xiu'] = initial_api_data_template['pattern_percent_xiu']
    
    initial_api_data_template['tong_tai'] = round(initial_api_data_template['phan_tram_tai'] * 1000 / 100, 2)
    initial_api_data_template['tong_xiu'] = round(initial_api_data_template['phan_tram_xiu'] * 1000 / 100, 2)

def analyze_streaks(history_deque):
    if not history_deque: return 0, None
    current_streak_length = 0
    current_streak_type = None
    for i in range(len(history_deque) - 1, -1, -1):
        result = history_deque[i]['Result']
        if current_streak_type is None:
            current_streak_type = result
            current_streak_length = 1
        elif result == current_streak_type:
            current_streak_length += 1
        else: break
    return current_streak_length, current_streak_type

def calculate_conditional_probability(history_deque, lookback_length=3):
    if len(history_deque) < lookback_length + 1: return {}
    probabilities = {}
    results_chars = "".join([entry['Result'] for entry in history_deque])
    for i in range(len(results_chars) - lookback_length):
        prefix = results_chars[i : i + lookback_length]
        next_char = results_chars[i + lookback_length]
        if prefix not in probabilities:
            probabilities[prefix] = {'t': 0, 'x': 0, 'total': 0}
        probabilities[prefix][next_char] += 1
        probabilities[prefix]['total'] += 1
    final_probs = {}
    for prefix, counts in probabilities.items():
        if counts['total'] > 0:
            final_probs[prefix] = {
                't': counts['t'] / counts['total'],
                'x': counts['x'] / counts['total']
            }
        else: final_probs[prefix] = {'t': 0, 'x': 0}
    return final_probs

def perform_prediction_logic():
    global initial_api_data_template, last_prediction_info, history_results

    du_doan_ket_qua = ""
    ly_do_du_doan = ""

    min_streak_for_prediction = 3
    break_streak_threshold = 5
    current_streak_length, current_streak_type = analyze_streaks(history_results)

    if current_streak_type:
        if current_streak_length >= min_streak_for_prediction:
            if current_streak_length < break_streak_threshold:
                du_doan_ket_qua = "Tài" if current_streak_type == 't' else "Xỉu"
                ly_do_du_doan = f"Theo cầu {'Tài' if current_streak_type == 't' else 'Xỉu'} dài ({current_streak_length} lần)."
            else:
                du_doan_ket_qua = "Xỉu" if current_streak_type == 't' else "Tài"
                ly_do_du_doan = f"Bẻ cầu {'Tài' if current_streak_type == 't' else 'Xỉu'} dài ({current_streak_length} lần) có khả năng đảo chiều."
        else: ly_do_du_doan = "Không có cầu rõ ràng."
    else: ly_do_du_doan = "Chưa đủ dữ liệu để phân tích cầu."

    lookback_prob = 3
    if len(history_results) >= lookback_prob:
        recent_prefix_chars = "".join([entry['Result'] for entry in history_results])[-lookback_prob:]
        conditional_probs = calculate_conditional_probability(history_results, lookback_prob)
        if recent_prefix_chars in conditional_probs:
            prob_t = conditional_probs[recent_prefix_chars]['t']
            prob_x = conditional_probs[recent_prefix_chars]['x']
            prob_threshold_strong = 0.6
            if prob_t > prob_x and prob_t >= prob_threshold_strong:
                if not du_doan_ket_qua or (du_doan_ket_qua == "Xỉu" and prob_t > prob_x * 1.2):
                    du_doan_ket_qua = "Tài"
                    ly_do_du_doan = f"Xác suất Tài cao ({round(prob_t*100, 2)}%) sau {recent_prefix_chars}."
            elif prob_x > prob_t and prob_x >= prob_threshold_strong:
                if not du_doan_ket_qua or (du_doan_ket_qua == "Tài" and prob_x > prob_t * 1.2):
                    du_doan_ket_qua = "Xỉu"
                    ly_do_du_doan = f"Xác suất Xỉu cao ({round(prob_x*100, 2)}%) sau {recent_prefix_chars}."
        
    reverse_threshold = 3
    if last_prediction_info["consecutive_losses"] >= reverse_threshold:
        if du_doan_ket_qua == "Tài": du_doan_ket_qua = "Xỉu"
        elif du_doan_ket_qua == "Xỉu": du_doan_ket_qua = "Tài"
        else:
            if last_prediction_info["last_actual_result"] == 't': du_doan_ket_qua = "Xỉu"
            else: du_doan_ket_qua = "Tài"
        ly_do_du_doan += f" | Đang trật {last_prediction_info['consecutive_losses']} lần → Auto đảo ngược."
    
    if not du_doan_ket_qua or du_doan_ket_qua == "Không có":
        if initial_api_data_template['pattern_percent_tai'] > initial_api_data_template['pattern_percent_xiu']:
            du_doan_ket_qua = "Tài"
            ly_do_du_doan = "Mặc định: Theo tỷ lệ pattern Tài lớn hơn (không có tín hiệu mạnh khác)."
        elif initial_api_data_template['pattern_percent_xiu'] > initial_api_data_template['pattern_percent_tai']:
            du_doan_ket_qua = "Xỉu"
            ly_do_du_doan = "Mặc định: Theo tỷ lệ pattern Xỉu lớn hơn (không có tín hiệu mạnh khác)."
        else:
            du_doan_ket_qua = random.choice(["Tài", "Xỉu"])
            ly_do_du_doan = "Mặc định: Các tín hiệu cân bằng, dự đoán ngẫu nhiên."

    initial_api_data_template['du_doan'] = du_doan_ket_qua
    initial_api_data_template['ly_do'] = ly_do_du_doan

    last_prediction_info["predicted_expect"] = initial_api_data_template["phien_du_doan"]
    last_prediction_info["predicted_result"] = du_doan_ket_qua
    
    return copy.deepcopy(initial_api_data_template)


# --- Hàm hỗ trợ bot ---
async def fetch_and_process_prediction_data():
    global last_processed_phien
    try:
        response = requests.get(EXTERNAL_API_URL, timeout=10)
        response.raise_for_status()
        external_data = response.json()
        logger.info(f"Fetched raw data: {external_data}")

        if all(k in external_data for k in ['Ket_qua', 'Phien', 'Tong', 'Xuc_xac_1', 'Xuc_xac_2', 'Xuc_xac_3']):
            if external_data['Phien'] != last_processed_phien:
                update_history_and_state(external_data)
                prediction_data = perform_prediction_logic()
                return prediction_data
            else:
                logger.info(f"Session {external_data['Phien']} already processed. Waiting for new session.")
                return None
        else:
            logger.error(f"Invalid data structure from external API. Missing expected keys. Raw response: {external_data}")
            return None
    except Exception as e:
        logger.error(f"Error fetching or processing prediction data: {e}")
        return None

def format_prediction_message(prediction_data, game_name):
    if not prediction_data:
        return "Không thể lấy dữ liệu dự đoán. Vui lòng thử lại sau."

    phien_moi = prediction_data.get('Phien_moi', 'N/A')
    
    current_session_info = next((item for item in history_results if item['Phien'] == phien_moi), None)
    
    ket_qua = current_session_info.get('Ket_qua', 'N/A') if current_session_info else 'N/A'
    tong_xuc_xac = current_session_info.get('Tong', 'N/A') if current_session_info else 'N/A'
    xuc_xac_1 = current_session_info.get('Xuc_xac_1', 'N/A') if current_session_info else 'N/A'
    xuc_xac_2 = current_session_info.get('Xuc_xac_2', 'N/A') if current_session_info else 'N/A'
    xuc_xac_3 = current_session_info.get('Xuc_xac_3', 'N/A') if current_session_info else 'N/A'

    pattern = prediction_data.get('pattern', 'xxxxxxxx')
    phien_du_doan = prediction_data.get('phien_du_doan', 'N/A')
    du_doan = prediction_data.get('du_doan', 'Không có')

    display_pattern = pattern.replace('t', 'T').replace('x', 'X')

    xuc_xac_info = f" ({xuc_xac_1},{xuc_xac_2},{xuc_xac_3})" if xuc_xac_1 != 'N/A' else ''

    # Hàm chuyển đổi số sang dạng Unicode Fullwidth
    def convert_to_fullwidth_digits(num):
        return "".join(chr(ord(digit) + 0xFEE0) for digit in str(num))

    message = (
        f"🤖 {game_name}\n"
        f"🎯 ᴘʜɪᴇ̂ɴ {convert_to_fullwidth_digits(phien_moi)}\n"
        f"🎲 ᴋᴇ̂́ᴛ ǫᴜ̉ᴀ : {ket_qua} {convert_to_fullwidth_digits(tong_xuc_xac)}{xuc_xac_info}\n"
        f"🧩 ᴘᴀᴛᴛᴇʀɴ : {display_pattern}\n"
        f"🎮  ᴘʜɪᴇ̂ɴ {convert_to_fullwidth_digits(phien_du_doan)} : {du_doan} (ᴍᴏᴅᴇʟ ʙᴀꜱɪᴄ)"
    )
    return message

# --- Các lệnh của bot ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    response_message = (
        f"🌟 CHÀO MỪNG {user_name} 🌟\n"
        f"🎉 Chào mừng đến với HeHe Bot 🎉\n"
        f"📦 Gói hiện tại: {'Đã kích hoạt' if is_user_subscribed(update.effective_user.id) else 'Chưa kích hoạt'}\n"
        f"⏰ Hết hạn: {'Vĩnh viễn' if (update.effective_user.id in users_with_active_subscriptions and active_keys[users_with_active_subscriptions[update.effective_user.id]]['expiry_time'] == 'forever') else (active_keys[users_with_active_subscriptions[update.effective_user.id]]['expiry_time'].strftime('%H:%M %d/%m/%Y') if update.effective_user.id in users_with_active_subscriptions else 'Chưa kích hoạt')}\n"
        f"💡 Dùng /help để xem các lệnh"
    )
    await update.message.reply_text(response_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    response_message = (
        f"📦 Gói hiện tại: {'Đã kích hoạt' if is_user_subscribed(update.effective_user.id) else 'Chưa kích hoạt'}\n"
        f"🔥 Các lệnh hỗ trợ:\n"
        f"✅ /start - Đăng ký và bắt đầu\n"
        f"🔑 /key [mã] - Kích hoạt gói\n"
        f"🎮 /chaymodelbasic - Chạy dự đoán  (LUCK)\n"
        f"🛑 /stop - Dừng dự đoán\n"
        f"🛠️ /admin - Lệnh dành cho admin\n"
        f"📊 /check - Xem thống kê dự đoán\n"
        f"📬 Liên hệ:\n"
        f"👤 Admin: t.me/heheviptool"
    )
    await update.message.reply_text(response_message)

async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Vui lòng cung cấp mã key. Ví dụ: /key ABCXYZ123456")
        return
    
    user_id = update.effective_user.id
    provided_key = context.args[0]

    if provided_key not in active_keys:
        await update.message.reply_text("Mã key không hợp lệ hoặc không tồn tại.")
        return
    
    key_details = active_keys[provided_key]

    if not key_details['is_active']:
        await update.message.reply_text("Mã key này đã được sử dụng hoặc bị vô hiệu hóa.")
        return
    
    if key_details['user_id'] is not None and key_details['user_id'] != user_id:
        await update.message.reply_text("Mã key này đã được kích hoạt bởi người dùng khác.")
        return
    
    if is_key_valid(provided_key):
        # Nếu key đã được kích hoạt bởi người dùng này và còn hạn
        if key_details['user_id'] == user_id:
            expiry_str = "Vĩnh viễn" if key_details['expiry_time'] == 'forever' else key_details['expiry_time'].strftime('%H:%M %d/%m/%Y')
            await update.message.reply_text(f"Gói của bạn đã được kích hoạt với key này và còn hạn đến: {expiry_str}.")
        else: # Kích hoạt key mới cho người dùng
            active_keys[provided_key]['user_id'] = user_id
            active_keys[provided_key]['is_active'] = False # Vô hiệu hóa key sau khi dùng (có thể thay đổi logic này)
            users_with_active_subscriptions[user_id] = provided_key
            save_keys()
            expiry_str = "Vĩnh viễn" if key_details['expiry_time'] == 'forever' else key_details['expiry_time'].strftime('%H:%M %d/%m/%Y')
            await update.message.reply_text(f"Chúc mừng! Gói của bạn đã được kích hoạt thành công đến: {expiry_str}.")
    else:
        await update.message.reply_text("Mã key đã hết hạn hoặc không hợp lệ.")


async def chaymodelbasic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global bot_running, prediction_task
    user_id = update.effective_user.id

    if not is_user_subscribed(user_id):
        await update.message.reply_text("Bạn cần kích hoạt gói để sử dụng chức năng này. Vui lòng dùng /key [mã] để kích hoạt.")
        return

    if bot_running:
        await update.message.reply_text("Bot dự đoán đã và đang chạy rồi. Dùng /stop để dừng trước khi chạy lại.")
        return

    bot_running = True
    await update.message.reply_text("Bot dự đoán đã được khởi động. Bot sẽ gửi dự đoán liên tục.")
    logger.info(f"Bot started by user {user_id}")

    async def send_predictions_loop():
        nonlocal update
        while bot_running:
            prediction_data = await fetch_and_process_prediction_data()
            if prediction_data:
                message_text = format_prediction_message(prediction_data, current_game_name)
                try:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, parse_mode='HTML')
                    logger.info(f"Sent prediction for session {prediction_data.get('Phien_moi')}")
                except Exception as e:
                    logger.error(f"Error sending message to chat {update.effective_chat.id}: {e}")
            await asyncio.sleep(20)

    prediction_task = asyncio.create_task(send_predictions_loop())


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global bot_running, prediction_task
    if not bot_running:
        await update.message.reply_text("Bot dự đoán hiện không chạy.")
        return

    bot_running = False
    if prediction_task:
        prediction_task.cancel()
        prediction_task = None
    await update.message.reply_text("Bot dự đoán đã được dừng.")
    logger.info(f"Bot stopped by user {update.effective_user.id}")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        logger.warning(f"Unauthorized admin access attempt by user {update.effective_user.id}")
        return
    
    response_message = (
        "Chào mừng Admin! Các lệnh admin:\n"
        "  /admin setgamename [tên_game_mới] - Đổi tên game hiển thị\n"
        "  /admin getstatus - Xem trạng thái bot và API\n"
        "  /admin createkey [số_lượng] [thời_gian] [loại: phut|gio|ngay|tuan|thang|vinhvien] - Tạo key mới\n"
        "     VD: /admin createkey 1 30 phut (tạo 1 key hạn 30 phút)\n"
        "     VD: /admin createkey 5 1 ngay (tạo 5 key hạn 1 ngày)\n"
        "     VD: /admin createkey 1 1 vinhvien (tạo 1 key vĩnh viễn)\n"
        "  /admin listkeys - Liệt kê các key đang hoạt động/chưa dùng\n"
        "  /admin revoke_key [mã_key] - Thu hồi/vô hiệu hóa một key\n"
        "  /admin reset_stats - Đặt lại thống kê dự đoán"
    )
    await update.message.reply_text(response_message)

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    if not context.args:
        await admin_command(update, context) # Show admin help if no arguments
        return

    sub_command = context.args[0].lower()
    args = context.args[1:]

    if sub_command == "setgamename":
        await setgamename_command_admin(update, context, args)
    elif sub_command == "getstatus":
        await get_status_command(update, context)
    elif sub_command == "createkey":
        await createkey_command(update, context, args)
    elif sub_command == "listkeys":
        await listkeys_command(update, context)
    elif sub_command == "revoke_key":
        await revoke_key_command(update, context, args)
    elif sub_command == "reset_stats":
        await reset_stats_command(update, context)
    else:
        await update.message.reply_text("Lệnh admin không hợp lệ. Vui lòng dùng `/admin` để xem các lệnh.")

async def setgamename_command_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list) -> None:
    global current_game_name
    if not args:
        await update.message.reply_text("Vui lòng cung cấp tên game mới. Ví dụ: `/admin setgamename SunWin`")
        return
    
    new_game_name = " ".join(args)
    def convert_to_fancy(text):
        fancy_chars_map = {
            'A': 'ᴀ', 'B': 'ʙ', 'C': 'ᴄ', 'D': 'ᴅ', 'E': 'ᴇ', 'F': 'ꜰ', 'G': 'ɢ', 'H': 'ʜ', 'I': 'ɪ', 
            'J': 'ᴊ', 'K': 'ᴋ', 'L': 'ʟ', 'M': 'ᴍ', 'N': 'ɴ', 'O': 'ᴏ', 'P': 'ᴘ', 'Q': 'Q', 'R': 'ʀ', 
            'S': 'ꜱ', 'T': 'ᴛ', 'U': 'ᴜ', 'V': 'ᴠ', 'W': 'ᴡ', 'X': 'x', 'Y': 'ʏ', 'Z': 'ᴢ',
            'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 
            'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'Q', 'r': 'ʀ', 
            's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ',
            ' ': ' '
        }
        converted_text = "".join(fancy_chars_map.get(char.upper(), char) for char in text)
        return converted_text

    current_game_name = convert_to_fancy(new_game_name)
    await update.message.reply_text(f"Tên game đã được đổi thành: {current_game_name}")
    logger.info(f"Game name set to: {current_game_name} by admin {update.effective_user.id}")

async def createkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list) -> None:
    if len(args) != 3:
        await update.message.reply_text("Cú pháp không đúng. Dùng: `/admin createkey [số_lượng] [thời_gian] [loại]`")
        return
    
    try:
        num_keys = int(args[0])
        duration_value = int(args[1])
        duration_type = args[2].lower()

        if num_keys <= 0 or duration_value <= 0 and duration_type != 'vinhvien':
            await update.message.reply_text("Số lượng key hoặc giá trị thời gian phải lớn hơn 0.")
            return

        if duration_type not in ['phut', 'gio', 'ngay', 'tuan', 'thang', 'vinhvien']:
            await update.message.reply_text("Loại thời gian không hợp lệ. Chọn: `phut, gio, ngay, tuan, thang, vinhvien`.")
            return

        generated_keys = []
        for _ in range(num_keys):
            new_key = generate_key()
            expiry = get_expiry_time(duration_type, duration_value)
            active_keys[new_key] = {
                'expiry_time': expiry,
                'user_id': None, # Null until activated
                'is_active': True # Key is ready to be used
            }
            generated_keys.append(new_key)
        
        save_keys()

        response = f"Đã tạo {num_keys} key mới:\n"
        for key in generated_keys:
            expiry_str = "Vĩnh viễn" if active_keys[key]['expiry_time'] == 'forever' else active_keys[key]['expiry_time'].strftime('%H:%M %d/%m/%Y')
            response += f"`{key}` (Hạn: {expiry_str})\n"
        await update.message.reply_text(response, parse_mode='MarkdownV2')
        logger.info(f"Generated {num_keys} keys by admin {update.effective_user.id}")

    except ValueError:
        await update.message.reply_text("Số lượng hoặc thời gian không hợp lệ. Vui lòng nhập số nguyên.")
    except Exception as e:
        await update.message.reply_text(f"Có lỗi xảy ra khi tạo key: {e}")
        logger.error(f"Error creating key: {e}")

async def listkeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key_list_message = "Danh sách Keys:\n\n"
    if not active_keys:
        key_list_message += "Không có key nào được tạo."
    else:
        for key, details in active_keys.items():
            status = "Đang hoạt động" if is_key_valid(key) else "Hết hạn/Đã dùng"
            expiry_str = "Vĩnh viễn" if details['expiry_time'] == 'forever' else details['expiry_time'].strftime('%H:%M %d/%m/%Y')
            user_info = f" (Sử dụng bởi User ID: {details['user_id']})" if details['user_id'] else ""
            key_list_message += f"`{key}` - Hạn: {expiry_str} - Trạng thái: {status}{user_info}\n"
    await update.message.reply_text(key_list_message, parse_mode='MarkdownV2')

async def revoke_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list) -> None:
    if len(args) != 1:
        await update.message.reply_text("Cú pháp không đúng. Dùng: `/admin revoke_key [mã_key]`")
        return
    
    key_to_revoke = args[0]
    if key_to_revoke not in active_keys:
        await update.message.reply_text("Mã key không tồn tại.")
        return
    
    active_keys[key_to_revoke]['is_active'] = False
    if active_keys[key_to_revoke]['user_id'] in users_with_active_subscriptions:
        del users_with_active_subscriptions[active_keys[key_to_revoke]['user_id']]
    save_keys()
    await update.message.reply_text(f"Key `{key_to_revoke}` đã được thu hồi/vô hiệu hóa.")
    logger.info(f"Key {key_to_revoke} revoked by admin {update.effective_user.id}")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    total = prediction_stats["total_predictions"]
    correct = prediction_stats["correct_predictions"]
    accuracy = (correct / total * 100) if total > 0 else 0

    message = (
        f"📊 THỐNG KÊ DỰ ĐOÁN BOT 📊\n"
        f"Tổng số phiên đã dự đoán: {total}\n"
        f"Số phiên dự đoán đúng: {correct}\n"
        f"Tỷ lệ dự đoán đúng: {accuracy:.2f}%\n\n"
        f"Lưu ý: Thống kê này được reset khi bot khởi động lại (trừ khi có database)."
    )
    await update.message.reply_text(message)

async def reset_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global prediction_stats
    prediction_stats = {
        "total_predictions": 0,
        "correct_predictions": 0,
        "last_checked_phien": None
    }
    await update.message.reply_text("Thống kê dự đoán đã được đặt lại.")
    logger.info(f"Prediction stats reset by admin {update.effective_user.id}")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Xin lỗi, tôi không hiểu lệnh này. Vui lòng dùng /help để xem các lệnh hỗ trợ.")

def main() -> None:
    load_keys() # Load keys when bot starts
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Đăng ký các trình xử lý lệnh
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("key", key_command))
    application.add_handler(CommandHandler("chaymodelbasic", chaymodelbasic_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("admin", handle_admin_commands)) # Lệnh admin chính
    application.add_handler(CommandHandler("check", check_command))

    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

