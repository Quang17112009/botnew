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
from telegram.constants import ParseMode # Import ParseMode

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Cấu hình bot ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
EXTERNAL_API_URL = "https://apib52.up.railway.app/api/taixiumd5"

# !!! QUAN TRỌNG: Thay thế bằng Telegram ID của bạn !!!
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "123456789")) # VD: 123456789 (Đây phải là số ID của bạn)

# Trạng thái bot
bot_running = False
prediction_task = None
current_game_name = "ʟᴜᴄᴋʏᴡɪɴ" # Tên game mặc định, có thể thay đổi bằng lệnh admin

# --- Mẫu dữ liệu ban đầu và trạng thái toàn cục cho logic dự đoán ---
initial_api_data_template = {
    "Phien_moi": None, # Sẽ được cập nhật từ new_session_data['Phien']
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
    "phien_du_doan": None, # Sẽ được tính toán từ Expect của phiên hiện tại
    "admin_info": "@heheviptool"
}

# Lịch sử các kết quả thực tế (t='Tài', x='Xỉu')
history_results = collections.deque(maxlen=100) # Ví dụ: 100 phiên gần nhất

# Lưu trữ trạng thái dự đoán gần nhất để kiểm tra 'consecutive_losses'
last_prediction_info = {
    "predicted_expect": None, # 'Phien' của phiên đã được dự đoán trong lần chạy trước
    "predicted_result": None, # "Tài" hoặc "Xỉu"
    "consecutive_losses": 0, # Số lần dự đoán sai liên tiếp
    "last_actual_result": None # Kết quả thực tế của phiên vừa rồi
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
# Để đơn giản, key được lưu trong bộ nhớ và một file JSON.
# Trong thực tế sản phẩm, bạn NÊN dùng database bền vững hơn (PostgreSQL, SQLite, MongoDB, v.v.).
active_keys = {} # key: { 'expiry_time': datetime_object or 'forever', 'user_id': user_id or None, 'is_active': True/False }
users_with_active_subscriptions = {} # user_id: key (chỉ key đang hoạt động)

KEY_FILE = "keys.json" # File để lưu trữ keys (đơn giản, không phải database thực sự)

def load_keys():
    """Tải dữ liệu key từ file JSON."""
    global active_keys, users_with_active_subscriptions
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, 'r') as f:
                data = json.load(f)
                active_keys_loaded = {}
                # Chuyển đổi chuỗi ngày thành datetime object
                for key, details in data.get('active_keys', {}).items():
                    if details['expiry_time'] != 'forever':
                        details['expiry_time'] = datetime.datetime.fromisoformat(details['expiry_time'])
                    active_keys_loaded[key] = details
                # Chuyển đổi user_id sang int
                users_with_active_subscriptions_loaded = {int(uid): k for uid, k in data.get('users_with_active_subscriptions', {}).items()}
                
                active_keys = active_keys_loaded
                users_with_active_subscriptions = users_with_active_subscriptions_loaded
                logger.info("Keys loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading keys: {e}")
            # Nếu có lỗi, khởi tạo lại rỗng để tránh crash
            active_keys = {}
            users_with_active_subscriptions = {}
    else:
        logger.info("No keys file found. Starting with empty keys.")
        active_keys = {}
        users_with_active_subscriptions = {}

def save_keys():
    """Lưu dữ liệu key vào file JSON."""
    try:
        with open(KEY_FILE, 'w') as f:
            data_to_save = {
                'active_keys': {},
                'users_with_active_subscriptions': {str(uid): k for uid, k in users_with_active_subscriptions.items()}
            }
            # Chuyển đổi datetime object thành chuỗi để lưu
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
        # Để đơn giản, 1 tháng = 30 ngày. Trong thực tế cần xử lý chính xác hơn (vd: dateutil.relativedelta).
        return current_time + datetime.timedelta(days=value * 30)
    elif duration_type == 'vinhvien':
        return 'forever'
    return None

def is_key_valid(key):
    """Kiểm tra xem key có tồn tại và còn hạn không."""
    if key not in active_keys:
        return False
    key_details = active_keys[key]
    if not key_details['is_active']: # Nếu key đã bị vô hiệu hóa
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
    """
    Tính tổng xúc xắc và xác định Tài/Xỉu từ các giá trị riêng lẻ.
    Trả về ('Tài'/'Xỉu', tổng)
    """
    try:
        total_sum = xuc_xac_1 + xuc_xac_2 + xuc_xac_3

        if total_sum >= 4 and total_sum <= 10:
            return "Xỉu", total_sum
        elif total_sum >= 11 and total_sum <= 17:
            return "Tài", total_sum
        else: # Tổng 3 hoặc 18 (Bộ ba) - Gộp vào Tài/Xỉu để đơn giản logic pattern
            if total_sum == 3: return "Xỉu", total_sum
            if total_sum == 18: return "Tài", total_sum
            return "Không xác định", total_sum # Trường hợp lý thuyết, không nên xảy ra
    except TypeError as e:
        logger.error(f"Error calculating Tai/Xiu from dice values: {e}")
        return "Lỗi", 0

def get_next_phien_code(current_phien_int):
    """
    Tính toán Phien code của phiên tiếp theo bằng cách tăng phần số cuối cùng.
    Giả định 'Phien' là một số nguyên tăng dần.
    """
    if isinstance(current_phien_int, int):
        return current_phien_int + 1
    else:
        logger.warning(f"Warning: Current 'Phien' '{current_phien_int}' is not an integer.")
        return None

def update_history_and_state(new_session_data):
    """
    Cập nhật lịch sử và trạng thái dự đoán toàn cục dựa trên dữ liệu phiên mới.
    Đồng thời cập nhật thống kê đúng/sai của dự đoán.
    """
    global history_results, initial_api_data_template, last_prediction_info, last_processed_phien, prediction_stats

    current_phien = new_session_data['Phien']
    current_ket_qua = new_session_data['Ket_qua']
    xuc_xac_1 = new_session_data['Xuc_xac_1']
    xuc_xac_2 = new_session_data['Xuc_xac_2']
    xuc_xac_3 = new_session_data['Xuc_xac_3']
    tong_xuc_xac = new_session_data['Tong']

    actual_result_char = "t" if "Tài" in current_ket_qua else "x"

    # Chỉ thêm vào lịch sử nếu đây là phiên mới (kiểm tra bằng 'Phien')
    # và chưa được xử lý trong lần gọi trước
    if current_phien != last_processed_phien:
        history_results.append({
            "Phien": current_phien,
            "Tong": tong_xuc_xac,
            "Xuc_xac_1": xuc_xac_1,
            "Xuc_xac_2": xuc_xac_2,
            "Xuc_xac_3": xuc_xac_3,
            "Result": actual_result_char,
            "Ket_qua": current_ket_qua # Giữ nguyên kết quả từ API để hiển thị
        })
        logger.info(f"Added new session to history: Phien {current_phien} - Result: {current_ket_qua}")
        last_processed_phien = current_phien # Cập nhật phiên cuối cùng đã xử lý

        # --- Cập nhật Thống Kê Dự Đoán ---
        # Logic này kiểm tra xem dự đoán của phiên TRƯỚC ĐÓ (predicted_expect)
        # có khớp với 'Phien' của phiên HIỆN TẠI mà ta vừa nhận được kết quả hay không.
        if last_prediction_info["predicted_expect"] is not None and \
           last_prediction_info["predicted_expect"] == current_phien and \
           last_prediction_info["predicted_result"] is not None:
            
            predicted_res = last_prediction_info["predicted_result"]
            
            # Tăng tổng số dự đoán mỗi khi có một dự đoán cho phiên này được đánh giá
            # Đảm bảo không đếm trùng nếu update_history_and_state được gọi nhiều lần cho cùng một phiên
            if prediction_stats["last_checked_phien"] != current_phien:
                prediction_stats["total_predictions"] += 1
                prediction_stats["last_checked_phien"] = current_phien # Ghi lại phiên đã kiểm tra

            if predicted_res.lower() != actual_result_char:
                last_prediction_info["consecutive_losses"] += 1
                logger.info(f"Prediction '{predicted_res}' for session Phien {current_phien} MISSED. Consecutive losses: {last_prediction_info['consecutive_losses']}")
            else:
                last_prediction_info["consecutive_losses"] = 0
                prediction_stats["correct_predictions"] += 1 # Tăng số dự đoán đúng
                logger.info(f"Prediction '{predicted_res}' for session Phien {current_phien} CORRECT. Resetting losses.")
        else:
            # Nếu không có dự đoán trước đó hoặc phiên không khớp (ví dụ: khởi động lại app), reset loss
            last_prediction_info["consecutive_losses"] = 0
            logger.info("No matching previous prediction to evaluate or app restarted. Resetting losses.")
        
        last_prediction_info["last_actual_result"] = actual_result_char # Cập nhật kết quả thực tế mới nhất

    # Cập nhật các trường chính trong initial_api_data_template
    initial_api_data_template["Phien_moi"] = current_phien # Hiển thị 'Phien' làm "phiên mới"
    
    # Tính toán Phien_du_doan bằng cách tăng 'Phien' của phiên hiện tại
    next_phien = get_next_phien_code(current_phien)
    initial_api_data_template["phien_du_doan"] = next_phien if next_phien else "Không xác định"

    # --- Cập nhật pattern và pattern percentages ---
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

    # Cập nhật 'matches' (giả định là kết quả của phiên mới nhất)
    if history_results:
        initial_api_data_template['matches'] = [history_results[-1]['Result']]
    else:
        initial_api_data_template['matches'] = []

    # Giả định phan_tram_tai/xiu và tong_tai/xiu dựa trên pattern_percent
    initial_api_data_template['phan_tram_tai'] = initial_api_data_template['pattern_percent_tai']
    initial_api_data_template['phan_tram_xiu'] = initial_api_data_template['pattern_percent_xiu']
    
    # Giả định tổng tiền theo tỷ lệ phần trăm (chỉ để điền vào mẫu JSON)
    initial_api_data_template['tong_tai'] = round(initial_api_data_template['phan_tram_tai'] * 1000 / 100, 2)
    initial_api_data_template['tong_xiu'] = round(initial_api_data_template['phan_tram_xiu'] * 1000 / 100, 2)

def analyze_streaks(history_deque):
    """Phân tích các chuỗi (streaks) Tài/Xỉu trong lịch sử gần đây."""
    if not history_deque:
        return 0, None # current_streak_length, current_streak_type

    current_streak_length = 0
    current_streak_type = None

    # Đi ngược từ kết quả gần nhất để tìm chuỗi
    for i in range(len(history_deque) - 1, -1, -1):
        result = history_deque[i]['Result']
        if current_streak_type is None:
            current_streak_type = result
            current_streak_length = 1
        elif result == current_streak_type:
            current_streak_length += 1
        else:
            break # Chuỗi bị phá vỡ

    return current_streak_length, current_streak_type

def calculate_conditional_probability(history_deque, lookback_length=3):
    """
    Tính xác suất có điều kiện của 't' hoặc 'x' dựa trên 'lookback_length' kết quả trước đó.
    Trả về dict: { 'prefix': {'t': probability_of_next_is_t, 'x': probability_of_next_is_x} }
    """
    if len(history_deque) < lookback_length + 1:
        return {} # Không đủ dữ liệu

    probabilities = {}
    
    # Lấy chuỗi các ký tự kết quả
    results_chars = "".join([entry['Result'] for entry in history_deque])

    for i in range(len(results_chars) - lookback_length):
        prefix = results_chars[i : i + lookback_length]
        next_char = results_chars[i + lookback_length]

        if prefix not in probabilities:
            probabilities[prefix] = {'t': 0, 'x': 0, 'total': 0}
        
        probabilities[prefix][next_char] += 1
        probabilities[prefix]['total'] += 1
    
    # Chuyển đổi số đếm thành xác suất
    final_probs = {}
    for prefix, counts in probabilities.items():
        if counts['total'] > 0:
            final_probs[prefix] = {
                't': counts['t'] / counts['total'],
                'x': counts['x'] / counts['total']
            }
        else:
            final_probs[prefix] = {'t': 0, 'x': 0}

    return final_probs


def perform_prediction_logic():
    """
    Thực hiện logic dự đoán thông minh cho phiên tiếp theo và cập nhật 'du_doan', 'ly_do'.
    """
    global initial_api_data_template, last_prediction_info, history_results

    du_doan_ket_qua = ""
    ly_do_du_doan = ""

    # --- Tín hiệu 1: Phân tích cầu (Streaks) ---
    min_streak_for_prediction = 3 # Ví dụ: Dự đoán theo cầu nếu cầu >= 3
    break_streak_threshold = 5 # Ví dụ: Cân nhắc bẻ cầu nếu cầu >= 5 (có thể điều chỉnh)

    current_streak_length, current_streak_type = analyze_streaks(history_results)

    if current_streak_type: # Đảm bảo có cầu để phân tích
        if current_streak_length >= min_streak_for_prediction:
            if current_streak_length < break_streak_threshold:
                # Nếu cầu chưa quá dài, tiếp tục theo cầu
                if current_streak_type == 't':
                    du_doan_ket_qua = "Tài"
                    ly_do_du_doan = f"Theo cầu Tài dài ({current_streak_length} lần)."
                else:
                    du_doan_ket_qua = "Xỉu"
                    ly_do_du_doan = f"Theo cầu Xỉu dài ({current_streak_length} lần)."
            else:
                # Nếu cầu quá dài, cân nhắc bẻ cầu (dự đoán ngược lại)
                if current_streak_type == 't':
                    du_doan_ket_qua = "Xỉu"
                    ly_do_du_doan = f"Bẻ cầu Tài dài ({current_streak_length} lần) có khả năng đảo chiều."
                else:
                    du_doan_ket_qua = "Tài"
                    ly_do_du_doan = f"Bẻ cầu Xỉu dài ({current_streak_length} lần) có khả năng đảo chiều."
        else:
            ly_do_du_doan = "Không có cầu rõ ràng."
    else:
        ly_do_du_doan = "Chưa đủ dữ liệu để phân tích cầu."


    # --- Tín hiệu 2: Xác suất có điều kiện (Conditional Probability) ---
    # Ưu tiên xác suất có điều kiện nếu có đủ dữ liệu và tín hiệu mạnh hơn
    lookback_prob = 3 # Nhìn vào N phiên trước đó để tính xác suất (có thể điều chỉnh)
    
    if len(history_results) >= lookback_prob:
        recent_prefix_chars = "".join([entry['Result'] for entry in history_results])[-lookback_prob:]
        conditional_probs = calculate_conditional_probability(history_results, lookback_prob)

        if recent_prefix_chars in conditional_probs:
            prob_t = conditional_probs[recent_prefix_chars]['t']
            prob_x = conditional_probs[recent_prefix_chars]['x']

            # Yêu cầu xác suất đủ cao để ghi đè (ví dụ: >60%)
            prob_threshold_strong = 0.6
            
            if prob_t > prob_x and prob_t >= prob_threshold_strong:
                # Ghi đè dự đoán nếu xác suất có điều kiện mạnh hơn hoặc nếu chưa có dự đoán
                if not du_doan_ket_qua or \
                   (du_doan_ket_qua == "Xỉu" and prob_t > prob_x * 1.2): # Ghi đè Xỉu nếu Tài mạnh hơn đáng kể
                    du_doan_ket_qua = "Tài"
                    ly_do_du_doan = f"Xác suất Tài cao ({round(prob_t*100, 2)}%) sau {recent_prefix_chars}."
            elif prob_x > prob_t and prob_x >= prob_threshold_strong:
                if not du_doan_ket_qua or \
                   (du_doan_ket_qua == "Tài" and prob_x > prob_t * 1.2): # Ghi đè Tài nếu Xỉu mạnh hơn đáng kể
                    du_doan_ket_qua = "Xỉu"
                    ly_do_du_doan = f"Xác suất Xỉu cao ({round(prob_x*100, 2)}%) sau {recent_prefix_chars}."
        
    # --- Tín hiệu 3: Logic "Đang trật X lần → Auto đảo ngược" ---
    # Đây là cơ chế quản lý rủi ro cuối cùng, sẽ ghi đè các dự đoán khác nếu ngưỡng bị đạt.
    reverse_threshold = 3 # Ngưỡng đảo ngược (có thể điều chỉnh)
    if last_prediction_info["consecutive_losses"] >= reverse_threshold:
        if du_doan_ket_qua == "Tài":
            du_doan_ket_qua = "Xỉu"
        elif du_doan_ket_qua == "Xỉu":
            du_doan_ket_qua = "Tài"
        else: # Nếu chưa có dự đoán nào từ các logic trên, và đang trật, thì cứ đảo ngược theo kết quả gần nhất
            if last_prediction_info["last_actual_result"] == 't':
                du_doan_ket_qua = "Xỉu"
            else:
                du_doan_ket_qua = "Tài"

        ly_do_du_doan += f" | Đang trật {last_prediction_info['consecutive_losses']} lần → Auto đảo ngược."
    
    # --- Tín hiệu cuối cùng nếu không có tín hiệu mạnh nào ---
    # Nếu sau tất cả các logic trên mà vẫn chưa có dự đoán chắc chắn
    if not du_doan_ket_qua or du_doan_ket_qua == "Không có":
        # Dùng tỷ lệ pattern chung (ít thông minh hơn nhưng là fallback)
        if initial_api_data_template['pattern_percent_tai'] > initial_api_data_template['pattern_percent_xiu']:
            du_doan_ket_qua = "Tài"
            ly_do_du_doan = "Mặc định: Theo tỷ lệ pattern Tài lớn hơn (không có tín hiệu mạnh khác)."
        elif initial_api_data_template['pattern_percent_xiu'] > initial_api_data_template['pattern_percent_tai']:
            du_doan_ket_qua = "Xỉu"
            ly_do_du_doan = "Mặc định: Theo tỷ lệ pattern Xỉu lớn hơn (không có tín hiệu mạnh khác)."
        else:
            # Nếu tất cả các tín hiệu đều cân bằng, dự đoán ngẫu nhiên để tránh bị động
            du_doan_ket_qua = random.choice(["Tài", "Xỉu"])
            ly_do_du_doan = "Mặc định: Các tín hiệu cân bằng, dự đoán ngẫu nhiên."

    initial_api_data_template['du_doan'] = du_doan_ket_qua
    initial_api_data_template['ly_do'] = ly_do_du_doan

    # Lưu dự đoán này để kiểm tra ở phiên tiếp theo
    last_prediction_info["predicted_expect"] = initial_api_data_template["phien_du_doan"]
    last_prediction_info["predicted_result"] = du_doan_ket_qua
    
    # Trả về bản sao của trạng thái hiện tại dưới dạng dict để bot sử dụng
    return copy.deepcopy(initial_api_data_template)


# --- Hàm hỗ trợ bot và định dạng tin nhắn ---
async def fetch_and_process_prediction_data():
    """Lấy dữ liệu từ API gốc, xử lý và tạo dự đoán."""
    global last_processed_phien
    try:
        response = requests.get(EXTERNAL_API_URL, timeout=10) # Thêm timeout
        response.raise_for_status() # Ném lỗi nếu status code không phải 2xx
        external_data = response.json()
        logger.info(f"Fetched raw data: {external_data}")

        # Kiểm tra cấu trúc dữ liệu từ API bên ngoài
        if all(k in external_data for k in ['Ket_qua', 'Phien', 'Tong', 'Xuc_xac_1', 'Xuc_xac_2', 'Xuc_xac_3']):
            # Chỉ xử lý nếu đây là một phiên mới chưa từng được xử lý
            if external_data['Phien'] != last_processed_phien:
                update_history_and_state(external_data)
                prediction_data = perform_prediction_logic()
                return prediction_data
            else:
                logger.info(f"Session {external_data['Phien']} already processed. Waiting for new session.")
                return None # Không có phiên mới để xử lý
        else:
            logger.error(f"Invalid data structure from external API. Missing expected keys. Raw response: {external_data}")
            return None

    except requests.exceptions.Timeout:
        logger.error("External API request timed out.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error connecting to external API: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error decoding JSON from external API response: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during prediction logic: {e}")
        return None

def convert_to_fullwidth_digits(num):
    """Chuyển đổi số Latin (0-9) sang dạng Unicode Fullwidth (𝟢-𝟫)."""
    return "".join(chr(ord(digit) + 0xFEE0) for digit in str(num))

def convert_to_fancy_chars(text):
    """Chuyển đổi chữ cái và số sang dạng 'small caps' hoặc tương tự."""
    fancy_chars_map = {
        'A': 'ᴀ', 'B': 'ʙ', 'C': 'ᴄ', 'D': 'ᴅ', 'E': 'ᴇ', 'F': 'ꜰ', 'G': 'ɢ', 'H': 'ʜ', 'I': 'ɪ', 
        'J': 'ᴊ', 'K': 'ᴋ', 'L': 'ʟ', 'M': 'ᴍ', 'N': 'ɴ', 'O': 'ᴏ', 'P': 'ᴘ', 'Q': 'Q', 'R': 'ʀ', 
        'S': 'ꜱ', 'T': 'ᴛ', 'U': 'ᴜ', 'V': 'ᴠ', 'W': 'ᴡ', 'X': 'x', 'Y': 'ʏ', 'Z': 'ᴢ',
        'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 
        'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'Q', 'r': 'ʀ', 
        's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ',
        ' ': ' ' # Giữ khoảng trắng
    }
    converted_text = "".join(fancy_chars_map.get(char.upper(), char) for char in text)
    return converted_text

def format_prediction_message(prediction_data, game_name):
    """Định dạng tin nhắn dự đoán."""
    if not prediction_data:
        return "Không thể lấy dữ liệu dự đoán. Vui lòng thử lại sau."

    phien_moi = prediction_data.get('Phien_moi', 'N/A')
    
    # Lấy thông tin kết quả thực tế từ lịch sử (history_results)
    current_session_info = next((item for item in history_results if item['Phien'] == phien_moi), None)
    
    ket_qua = current_session_info.get('Ket_qua', 'N/A') if current_session_info else 'N/A'
    tong_xuc_xac = current_session_info.get('Tong', 'N/A') if current_session_info else 'N/A'
    xuc_xac_1 = current_session_info.get('Xuc_xac_1', 'N/A') if current_session_info else 'N/A'
    xuc_xac_2 = current_session_info.get('Xuc_xac_2', 'N/A') if current_session_info else 'N/A'
    xuc_xac_3 = current_session_info.get('Xuc_xac_3', 'N/A') if current_session_info else 'N/A'

    pattern = prediction_data.get('pattern', 'xxxxxxxx')
    phien_du_doan = prediction_data.get('phien_du_doan', 'N/A')
    du_doan = prediction_data.get('du_doan', 'Không có')

    # Chuyển đổi pattern để hiển thị dễ đọc hơn, ví dụ 't' thành 'T' và 'x' thành 'X'
    display_pattern = pattern.replace('t', 'T').replace('x', 'X')

    xuc_xac_info = f" ({convert_to_fullwidth_digits(xuc_xac_1)},{convert_to_fullwidth_digits(xuc_xac_2)},{convert_to_fullwidth_digits(xuc_xac_3)})" if xuc_xac_1 != 'N/A' else ''

    # Tạo tin nhắn theo mẫu bạn yêu cầu, sử dụng các ký tự Unicode đặc biệt
    message = (
        f"🤖 {game_name}\n"
        f"🎯 ᴘʜɪᴇ̂ɴ {convert_to_fullwidth_digits(phien_moi)}\n"
        f"🎲 ᴋᴇ̂́ᴛ ǫᴜ̉ᴀ : {ket_qua} {convert_to_fullwidth_digits(tong_xuc_xac)}{xuc_xac_info}\n"
        f"🧩 ᴘᴀᴛᴛᴇʀɴ : {display_pattern}\n"
        f"🎮  ᴘʜɪᴇ̂ɴ {convert_to_fullwidth_digits(phien_du_doan)} : {du_doan} (ᴍᴏᴅᴇʟ ʙᴀꜱɪᴄ)"
    )
    return message

def escape_markdown_v2(text):
    """Escape characters for MarkdownV2.
    See https://core.telegram.org/bots/api#markdownv2-style
    """
    if not isinstance(text, str): # Đảm bảo đầu vào là string
        text = str(text)
    
    # Ký tự cần thoát: _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r'_*[]()~`>#+-=|{}.!' 
    return "".join('\\' + char if char in escape_chars else char for char in text)


# --- Các lệnh của bot ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /start."""
    user_name = update.effective_user.first_name
    user_id = update.effective_user.id
    
    subscription_status = "Chưa kích hoạt"
    expiry_info = "Chưa kích hoạt"

    if user_id in users_with_active_subscriptions:
        key = users_with_active_subscriptions[user_id]
        if is_key_valid(key):
            subscription_status = "Đã kích hoạt"
            key_details = active_keys[key]
            if key_details['expiry_time'] == 'forever':
                expiry_info = "Vĩnh viễn"
            else:
                expiry_info = key_details['expiry_time'].strftime('%H:%M %d/%m/%Y')
        else:
            # Nếu key hết hạn hoặc không hợp lệ, xóa khỏi danh sách người dùng đã đăng ký
            del users_with_active_subscriptions[user_id]
            save_keys() # Lưu lại thay đổi
    
    # Sửa lỗi: Bỏ escape cho '!' nếu nó là dấu cảm thán thông thường
    response_message = (
        f"🌟 CHÀO MỪNG {escape_markdown_v2(user_name)} 🌟\n"
        f"🎉 Chào mừng đến với HeHe Bot 🎉\n" # Bỏ '\' trước '!'
        f"📦 Gói hiện tại: {escape_markdown_v2(subscription_status)}\n"
        f"⏰ Hết hạn: {escape_markdown_v2(expiry_info)}\n"
        f"💡 Dùng /help để xem các lệnh"
    )
    await update.message.reply_text(response_message, parse_mode=ParseMode.MARKDOWN_V2)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /help."""
    user_id = update.effective_user.id
    subscription_status = "Chưa kích hoạt"
    if is_user_subscribed(user_id):
        subscription_status = "Đã kích hoạt"

    response_message = (
        f"📦 Gói hiện tại: {escape_markdown_v2(subscription_status)}\n"
        f"🔥 Các lệnh hỗ trợ:\n"
        f"✅ /start \\- Đăng ký và bắt đầu\n"
        f"🔑 /key \\[`mã`\\] \\- Kích hoạt gói\n"
        f"🎮 /chaymodelbasic \\- Chạy dự đoán  \\(LUCK\\)\n"
        f"🛑 /stop \\- Dừng dự đoán\n"
        f"🛠️ /admin \\- Lệnh dành cho admin\n"
        f"📊 /check \\- Xem thống kê dự đoán\n"
        f"📬 Liên hệ:\n"
        f"👤 Admin: t\\.me/heheviptool" # Thoát dấu chấm
    )
    await update.message.reply_text(response_message, parse_mode=ParseMode.MARKDOWN_V2)

async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /key để kích hoạt gói."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Vui lòng cung cấp mã key\\. Ví dụ: `/key ABCXYZ123456`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    user_id = update.effective_user.id
    provided_key = context.args[0].upper() # Chuyển sang chữ hoa để khớp với key đã tạo

    if provided_key not in active_keys:
        await update.message.reply_text("Mã key không hợp lệ hoặc không tồn tại\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    key_details = active_keys[provided_key]

    if not key_details['is_active']:
        await update.message.reply_text("Mã key này đã được sử dụng hoặc bị vô hiệu hóa\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    if key_details['user_id'] is not None and key_details['user_id'] != user_id:
        await update.message.reply_text("Mã key này đã được kích hoạt bởi người dùng khác\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    # Kiểm tra hạn sử dụng ngay lập tức
    if not is_key_valid(provided_key):
        await update.message.reply_text("Mã key đã hết hạn\\.", parse_mode=ParseMode.MARKDOWN_V2)
        # Nếu hết hạn, có thể đánh dấu là không hoạt động
        active_keys[provided_key]['is_active'] = False
        save_keys()
        return

    # Nếu key hợp lệ và chưa được dùng hoặc đang được dùng bởi chính user này
    if key_details['user_id'] == user_id:
        expiry_str = "Vĩnh viễn" if key_details['expiry_time'] == 'forever' else key_details['expiry_time'].strftime('%H:%M %d/%m/%Y')
        await update.message.reply_text(f"Gói của bạn đã được kích hoạt với key này và còn hạn đến: {escape_markdown_v2(expiry_str)}\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else: # Kích hoạt key mới cho người dùng
        active_keys[provided_key]['user_id'] = user_id
        # active_keys[provided_key]['is_active'] = False # Tùy chọn: vô hiệu hóa key sau khi dùng lần đầu nếu là key 1 lần
        users_with_active_subscriptions[user_id] = provided_key
        save_keys()
        # Dòng này đã được sửa lỗi "invalid escape sequence \!"
        await update.message.reply_text(f"Chúc mừng! Gói của bạn đã được kích hoạt thành công đến: {escape_markdown_v2(expiry_str)}\\.", parse_mode=ParseMode.MARKDOWN_V2)
    

async def chaymodelbasic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /chaymodelbasic để bắt đầu dự đoán liên tục."""
    global bot_running, prediction_task
    user_id = update.effective_user.id

    if not is_user_subscribed(user_id):
        await update.message.reply_text("Bạn cần kích hoạt gói để sử dụng chức năng này\\. Vui lòng dùng `/key [mã]` để kích hoạt\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    if bot_running:
        await update.message.reply_text("Bot dự đoán đã và đang chạy rồi\\. Dùng /stop để dừng trước khi chạy lại\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    bot_running = True
    await update.message.reply_text("Bot dự đoán đã được khởi động\\. Bot sẽ gửi dự đoán liên tục\\.", parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"Bot started by user {user_id}")

    async def send_predictions_loop():
        nonlocal update # Để truy cập update từ hàm cha
        global bot_running # Đặt khai báo global lên đầu hàm này để tránh SyntaxError

        while bot_running:
            # Kiểm tra lại trạng thái đăng ký của người dùng trong vòng lặp
            if not is_user_subscribed(user_id):
                logger.info(f"User {user_id} subscription expired or revoked. Stopping prediction loop.")
                await context.bot.send_message(chat_id=update.effective_chat.id, 
                                               text="Gói của bạn đã hết hạn hoặc bị vô hiệu hóa\\. Bot dự đoán đã dừng\\.", 
                                               parse_mode=ParseMode.MARKDOWN_V2)
                bot_running = False # Dừng vòng lặp
                break # Thoát khỏi vòng lặp
                
            prediction_data = await fetch_and_process_prediction_data()
            if prediction_data: # Chỉ gửi nếu có dữ liệu dự đoán mới được tạo
                message_text = format_prediction_message(prediction_data, current_game_name)
                try:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text) # Không cần parse_mode cho mẫu này
                    logger.info(f"Sent prediction for session {prediction_data.get('Phien_moi')}")
                except Exception as e:
                    logger.error(f"Error sending message to chat {update.effective_chat.id}: {e}")
            await asyncio.sleep(20) # Đợi 20 giây trước khi kiểm tra API gốc lần nữa

    prediction_task = asyncio.create_task(send_predictions_loop())


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /stop để dừng dự đoán."""
    global bot_running, prediction_task
    if not bot_running:
        await update.message.reply_text("Bot dự đoán hiện không chạy\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    bot_running = False
    if prediction_task:
        prediction_task.cancel()
        prediction_task = None
    await update.message.reply_text("Bot dự đoán đã được dừng\\.", parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"Bot stopped by user {update.effective_user.id}")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lệnh dành cho admin (để hiển thị các lệnh admin)."""
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này\\.", parse_mode=ParseMode.MARKDOWN_V2)
        logger.warning(f"Unauthorized admin access attempt by user {update.effective_user.id}")
        return
    
    response_message = (
        "Chào mừng Admin\\! Các lệnh admin:\n"
        "`/admin setgamename` \\[`tên_game_mới`\\] \\- Đổi tên game hiển thị\n"
        "`/admin getstatus` \\- Xem trạng thái bot và API\n"
        "`/admin createkey` \\[`số_lượng`\\] \\[`thời_gian`\\] \\[`loại: phut|gio|ngay|tuan|thang|vinhvien`\\] \\- Tạo key mới\n"
        "     VD: `/admin createkey 1 30 phut` \\(tạo 1 key hạn 30 phút\\)\n"
        "     VD: `/admin createkey 5 1 ngay` \\(tạo 5 key hạn 1 ngày\\)\n"
        "     VD: `/admin createkey 1 1 vinhvien` \\(tạo 1 key vĩnh viễn\\)\n"
        "`/admin listkeys` \\- Liệt kê các key đang hoạt động/chưa dùng\n"
        "`/admin revoke_key` \\[`mã_key`\\] \\- Thu hồi/vô hiệu hóa một key\n"
        "`/admin reset_stats` \\- Đặt lại thống kê dự đoán"
    )
    await update.message.reply_text(response_message, parse_mode=ParseMode.MARKDOWN_V2)

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý các lệnh con của admin."""
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này\\.", parse_mode=ParseMode.MARKDOWN_V2)
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
        await update.message.reply_text("Lệnh admin không hợp lệ\\. Vui lòng dùng `/admin` để xem các lệnh\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def setgamename_command_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list) -> None:
    """Lệnh admin để đổi tên game hiển thị."""
    global current_game_name
    if not args:
        await update.message.reply_text("Vui lòng cung cấp tên game mới\\. Ví dụ: `/admin setgamename SunWin`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    new_game_name = " ".join(args)
    current_game_name = convert_to_fancy_chars(new_game_name)
    await update.message.reply_text(f"Tên game đã được đổi thành: {current_game_name}", parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"Game name set to: {current_game_name} by admin {update.effective_user.id}")

async def createkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list) -> None:
    """Lệnh admin để tạo key mới."""
    if len(args) != 3:
        await update.message.reply_text("Cú pháp không đúng\\. Dùng: `/admin createkey [số_lượng] [thời_gian] [loại: phut|gio|ngay|tuan|thang|vinhvien]`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    try:
        num_keys = int(args[0])
        duration_value = int(args[1])
        duration_type = args[2].lower()

        if num_keys <= 0 or (duration_value <= 0 and duration_type != 'vinhvien'):
            await update.message.reply_text("Số lượng key hoặc giá trị thời gian phải lớn hơn 0\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if duration_type not in ['phut', 'gio', 'ngay', 'tuan', 'thang', 'vinhvien']:
            await update.message.reply_text("Loại thời gian không hợp lệ\\. Chọn: `phut, gio, ngay, tuan, thang, vinhvien`\\.", parse_mode=ParseMode.MARKDOWN_V2)
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
            response += f"`{escape_markdown_v2(key)}` \\(Hạn: {escape_markdown_v2(expiry_str)}\\)\n"
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"Generated {num_keys} keys by admin {update.effective_user.id}")

    except ValueError:
        await update.message.reply_text("Số lượng hoặc thời gian không hợp lệ\\. Vui lòng nhập số nguyên\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        await update.message.reply_text(f"Có lỗi xảy ra khi tạo key: {escape_markdown_v2(str(e))}\\.", parse_mode=ParseMode.MARKDOWN_V2)
        logger.error(f"Error creating key: {e}")

async def listkeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lệnh admin để liệt kê các key đang hoạt động/chưa dùng."""
    key_list_message = "Danh sách Keys:\n\n"
    if not active_keys:
        key_list_message += "Không có key nào được tạo\\."
    else:
        for key, details in active_keys.items():
            status = "Đang hoạt động" if is_key_valid(key) else "Hết hạn/Đã dùng"
            expiry_str = "Vĩnh viễn" if details['expiry_time'] == 'forever' else details['expiry_time'].strftime('%H:%M %d/%m/%Y')
            user_info = f" \\(Sử dụng bởi User ID: {escape_markdown_v2(str(details['user_id']))}\\)" if details['user_id'] else ""
            key_list_message += f"`{escape_markdown_v2(key)}` \\- Hạn: {escape_markdown_v2(expiry_str)} \\- Trạng thái: {escape_markdown_v2(status)}{user_info}\n"
    await update.message.reply_text(key_list_message, parse_mode=ParseMode.MARKDOWN_V2)

async def revoke_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list) -> None:
    """Lệnh admin để thu hồi/vô hiệu hóa một key."""
    if len(args) != 1:
        await update.message.reply_text("Cú pháp không đúng\\. Dùng: `/admin revoke_key [mã_key]`", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    key_to_revoke = args[0].upper() # Chuyển sang chữ hoa để khớp với key đã tạo
    if key_to_revoke not in active_keys:
        await update.message.reply_text("Mã key không tồn tại\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    active_keys[key_to_revoke]['is_active'] = False
    # Nếu key đang được sử dụng bởi ai đó, loại bỏ người dùng đó khỏi danh sách đăng ký
    if active_keys[key_to_revoke]['user_id'] in users_with_active_subscriptions:
        del users_with_active_subscriptions[active_keys[key_to_revoke]['user_id']]
    save_keys()
    await update.message.reply_text(f"Key `{escape_markdown_v2(key_to_revoke)}` đã được thu hồi/vô hiệu hóa\\.", parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"Key {key_to_revoke} revoked by admin {update.effective_user.id}")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem thống kê dự đoán của bot."""
    total = prediction_stats["total_predictions"]
    correct = prediction_stats["correct_predictions"]
    accuracy = (correct / total * 100) if total > 0 else 0

    message = (
        f"📊 THỐNG KÊ DỰ ĐOÁN BOT 📊\n"
        f"Tổng số phiên đã dự đoán: {total}\n"
        f"Số phiên dự đoán đúng: {correct}\n"
        f"Tỷ lệ dự đoán đúng: {accuracy:.2f}%\n\n"
        f"Lưu ý: Thống kê này được reset khi bot khởi động lại \\(trừ khi có database\\)\\."
    )
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)

async def reset_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lệnh admin để đặt lại thống kê dự đoán."""
    global prediction_stats
    prediction_stats = {
        "total_predictions": 0,
        "correct_predictions": 0,
        "last_checked_phien": None
    }
    await update.message.reply_text("Thống kê dự đoán đã được đặt lại\\.", parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"Prediction stats reset by admin {update.effective_user.id}")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý các lệnh không xác định."""
    await update.message.reply_text("Xin lỗi, tôi không hiểu lệnh này\\. Vui lòng dùng /help để xem các lệnh hỗ trợ\\.", parse_mode=ParseMode.MARKDOWN_V2)

def main() -> None:
    """Khởi chạy bot."""
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

    # Xử lý các tin nhắn không phải là lệnh (tùy chọn)
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

