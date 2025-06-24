import requests
import time
import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)

# Bật ghi nhật ký (logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ======================= CẤU HÌNH BOT & API =======================
# Lấy BOT_TOKEN từ biến môi trường
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN chưa được thiết lập trong biến môi trường!")
    exit(1) # Thoát nếu không có token

API_URL = "https://wanglinapiws.up.railway.app/api/taixiu"

# Lấy ADMIN_IDS từ biến môi trường và chuyển đổi thành danh sách số nguyên
ADMIN_IDS_STR = os.getenv("ADMIN_IDS")
if ADMIN_IDS_STR:
    try:
        ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(',') if x.strip()]
    except ValueError:
        logger.error("ADMIN_IDS trong biến môi trường không phải là các số nguyên hợp lệ!")
        ADMIN_IDS = [] # Gán rỗng nếu có lỗi
else:
    ADMIN_IDS = [] # Mặc định là danh sách rỗng nếu không có biến môi trường

# Trạng thái bot và dữ liệu tạm thời (lưu ý: sẽ bị mất khi bot khởi động lại)
USER_STATES = {}  # {user_id: {"bot_running": False, "game_selected": None}}
KEY_DATA = {}  # {key_name: {"user_id": None, "expiry_time": None, "created_by": None, "activation_time": None}}
GAME_HISTORY = {} # {user_id: [message1, message2, ...]}

# Trạng thái hội thoại cho /chaybot
SELECTING_GAME = 1

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

# ======================= HÀM XỬ LÝ LOGIC DỰ ĐOÁN =======================
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
    else:
        loai_cau = "Cầu xấu"
        # Đảo ngược dự đoán nếu là cầu xấu
        prediction = "Xỉu" if prediction == "Tài" else "Tài"

    return {
        "xuc_xac": dice,
        "tong": total,
        "cau": loai_cau,
        "du_doan": prediction,
        "chi_tiet": result_list,
        "ket_qua_phien_hien_tai": "Tài" if total >= 11 else "Xỉu" # Xác định kết quả Tài/Xỉu của phiên hiện tại
    }

async def lay_du_lieu_api():
    """Lấy dữ liệu xúc xắc mới nhất từ API."""
    try:
        response = requests.get(API_URL, timeout=5)
        response.raise_for_status() # Ném lỗi HTTPError cho các phản hồi lỗi (4xx hoặc 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Lỗi khi kết nối API: {e}")
        return None

async def job_tai_xiu_prediction(context: ContextTypes.DEFAULT_TYPE):
    """Job chạy định kỳ để gửi thông báo dự đoán Tài Xỉu tự động."""
    data = await lay_du_lieu_api()
    if not data:
        return

    current_session = data.get("Phien")
    current_dice = (
        data.get("Xuc_xac_1"),
        data.get("Xuc_xac_2"),
        data.get("Xuc_xac_3")
    )

    if current_session and all(isinstance(x, int) for x in current_dice):
        for user_id, user_data in list(USER_STATES.items()):
            if user_data.get("bot_running") and user_data.get("game_selected") == "taixiu":
                # Kiểm tra xem key còn hợp lệ không
                if not is_key_valid(user_id) and not is_admin(user_id):
                    USER_STATES[user_id]["bot_running"] = False
                    USER_STATES[user_id]["game_selected"] = None
                    try:
                        await context.bot.send_message(chat_id=user_id, text="Key của bạn đã hết hạn hoặc không còn hợp lệ. Bot tự động tắt thông báo. Vui lòng liên hệ admin.")
                        logger.info(f"Đã tắt bot cho người dùng {user_id} vì key hết hạn.")
                    except Exception as e:
                        logger.error(f"Không thể gửi tin nhắn key hết hạn cho {user_id}: {e}")
                    continue

                last_session_key = f"last_session_{user_id}"
                last_sent_session = context.bot_data.get(last_session_key)

                if current_session != last_sent_session:
                    context.bot_data[last_session_key] = current_session
                    
                    # Tính toán kết quả của phiên hiện tại (vừa ra)
                    ket_qua_phien_hien_tai = du_doan_theo_xi_ngau(current_dice)
                    
                    # Dự đoán cho phiên TIẾP THEO dựa trên current_dice
                    # Logic dự đoán của bạn đã dùng current_dice để dự đoán
                    du_doan_phien_tiep_theo = ket_qua_phien_hien_tai['du_doan'] # Dự đoán từ hàm du_doan_theo_xi_ngau

                    message = (
                        f"🎮 **KẾT QUẢ PHIÊN HIỆN TẠI Sunwin** 🎮\n"
                        f"Phiên: `{current_session}` | Kết quả: **{ket_qua_phien_hien_tai['ket_qua_phien_hien_tai']}** (Tổng: {ket_qua_phien_hien_tai['tong']})\n"
                        f"Chi tiết: {ket_qua_phien_hien_tai['xuc_xac']} | Loại cầu: {ket_qua_phien_hien_tai['cau']}\n\n"
                        f"**Dự đoán cho phiên tiếp theo:**\n"
                        f"🔢 Phiên: `{current_session + 1}`\n"
                        f"🤖 Dự đoán: **{du_doan_phien_tiep_theo}**"
                    )
                    
                    # Lưu vào lịch sử phiên
                    if user_id not in GAME_HISTORY:
                        GAME_HISTORY[user_id] = []
                    GAME_HISTORY[user_id].insert(0, message) # Thêm vào đầu danh sách
                    if len(GAME_HISTORY[user_id]) > 10: # Giữ 10 phiên gần nhất
                        GAME_HISTORY[user_id].pop()

                    try:
                        await context.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown")
                        logger.info(f"Đã gửi thông báo cho người dùng {user_id} về phiên {current_session} và dự đoán {current_session + 1}")
                    except Exception as e:
                        logger.error(f"Không thể gửi tin nhắn cho người dùng {user_id}: {e}")
                else:
                    logger.info(f"Phiên {current_session} chưa thay đổi hoặc đã được gửi cho người dùng {user_id}.")
            else:
                logger.debug(f"Bot không chạy hoặc chưa chọn game cho người dùng {user_id}.")
    else:
        logger.warning("⚠️ Dữ liệu API không đầy đủ hoặc không hợp lệ.")


# ======================= HÀM HỖ TRỢ KIỂM TRA QUYỀN =======================
def is_admin(user_id):
    """Kiểm tra xem người dùng có phải admin không."""
    return user_id in ADMIN_IDS

def is_key_valid(user_id):
    """Kiểm tra xem người dùng có key hợp lệ và còn hạn không."""
    for key, data in KEY_DATA.items():
        if data["user_id"] == user_id:
            # Nếu key không có thời gian hết hạn hoặc còn hạn
            if data["expiry_time"] is None or data["expiry_time"] > time.time():
                return True
    return False

# ======================= HÀM XỬ LÝ LỆNH BOT =======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hiển thị thông tin chào mừng và hướng dẫn sử dụng."""
    user = update.effective_user
    await update.message.reply_html(
        f"Xin chào {user.mention_html()}! 👋\n"
        "Chào mừng bạn đến với bot dự đoán Tài Xỉu.\n"
        "Sử dụng các lệnh bên dưới để tương tác với bot.\n"
        "🔔 **HƯỚNG DẪN SỬ DỤNG BOT**\n"
        "══════════════════════════\n"
        "🔑 **Lệnh cơ bản:**\n"
        "- `/start`: Hiển thị thông tin chào mừng\n"
        "- `/key <key>`: Nhập key để kích hoạt bot\n"
        "- `/chaybot`: Bật nhận thông báo dự đoán tự động (sẽ hỏi chọn game)\n"
        "- `/tatbot`: Tắt nhận thông báo dự đoán tự động\n"
        "- `/lichsu`: Xem lịch sử 10 phiên gần nhất của game bạn đang chọn\n\n"
        "🛡️ **Lệnh admin:**\n"
        "- `/taokey <tên_key> [số_lượng] [đơn_vị_thời_gian]`: Tạo key mới. Ví dụ: `/taokey MYKEY123 1 ngày`, `/taokey VIPKEY 24 giờ`\n"
        "- `/lietkekey`: Liệt kê tất cả key và trạng thái sử dụng\n"
        "- `/xoakey <key>`: Xóa key khỏi hệ thống\n"
        "- `/themadmin <id>`: Thêm ID người dùng làm admin\n"
        "- `/xoaadmin <id>`: Xóa ID người dùng khỏi admin\n"
        "- `/danhsachadmin`: Xem danh sách các ID admin\n"
        "- `/broadcast [tin nhắn]`: Gửi thông báo đến tất cả người dùng\n\n"
        "══════════════════════════\n"
        "👥 Liên hệ admin để được hỗ trợ thêm."
    )

async def handle_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh nhập key để kích hoạt bot."""
    user_id = update.effective_user.id
    if len(context.args) == 1:
        key = context.args[0]
        if key in KEY_DATA:
            if KEY_DATA[key]["user_id"] is None:
                KEY_DATA[key]["user_id"] = user_id
                KEY_DATA[key]["activation_time"] = time.time()
                await update.message.reply_text(f"Key `{key}` đã được kích hoạt thành công cho bạn! 🎉", parse_mode="Markdown")
                logger.info(f"Key {key} activated by user {user_id}")
            elif KEY_DATA[key]["user_id"] == user_id:
                await update.message.reply_text(f"Key `{key}` đã được kích hoạt bởi bạn trước đó rồi. 👍", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"Key `{key}` đã được sử dụng bởi người khác. Vui lòng liên hệ admin. 😢", parse_mode="Markdown")
        else:
            await update.message.reply_text("Key không hợp lệ hoặc không tồn tại. Vui lòng kiểm tra lại. 🤔")
    else:
        await update.message.reply_text("Vui lòng nhập key sau lệnh /key. Ví dụ: `/key YOURKEY123`", parse_mode="Markdown")

async def chaybot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bắt đầu quá trình bật bot và chọn game bằng nút inline."""
    user_id = update.effective_user.id
    if not is_key_valid(user_id) and not is_admin(user_id):
        await update.message.reply_text("Bạn cần có key hợp lệ hoặc là admin để sử dụng chức năng này. Vui lòng nhập key bằng lệnh /key hoặc liên hệ admin.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("Tài Xỉu", callback_data="game_taixiu")],
        # Thêm các game khác ở đây nếu có
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Vui lòng chọn game bạn muốn nhận thông báo:", reply_markup=reply_markup)
    return SELECTING_GAME

async def select_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xử lý lựa chọn game từ người dùng thông qua callback query."""
    query = update.callback_query
    await query.answer() # Báo hiệu đã nhận callback
    
    user_id = query.from_user.id
    game_selected = query.data.replace("game_", "")

    if user_id not in USER_STATES:
        USER_STATES[user_id] = {}
    
    USER_STATES[user_id]["bot_running"] = True
    USER_STATES[user_id]["game_selected"] = game_selected

    await query.edit_message_text(f"Bạn đã chọn game **{game_selected.upper()}**. Bot sẽ bắt đầu gửi thông báo dự đoán tự động cho bạn. 🚀", parse_mode="Markdown")
    logger.info(f"Bot started for user {user_id} for game {game_selected}")
    return ConversationHandler.END


async def tatbot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tắt nhận thông báo dự đoán tự động."""
    user_id = update.effective_user.id
    if user_id in USER_STATES and USER_STATES[user_id].get("bot_running"):
        USER_STATES[user_id]["bot_running"] = False
        USER_STATES[user_id]["game_selected"] = None
        await update.message.reply_text("Bot đã ngừng gửi thông báo dự đoán tự động cho bạn. 👋")
        logger.info(f"Bot stopped for user {user_id}")
    else:
        await update.message.reply_text("Bot hiện không chạy. Bạn có thể bật lại bằng lệnh /chaybot.")

async def lichsu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem lịch sử 10 phiên gần nhất của game bạn đang chọn."""
    user_id = update.effective_user.id
    if user_id not in GAME_HISTORY or not GAME_HISTORY[user_id]:
        await update.message.reply_text("Bạn chưa có lịch sử dự đoán nào. Vui lòng chạy bot trước bằng lệnh /chaybot.")
        return

    history_messages = GAME_HISTORY[user_id]
    # Lịch sử được lưu dưới dạng Markdown, nên chỉ cần nối chuỗi
    response = "📜 **Lịch sử 10 phiên gần nhất:**\n\n" + "\n---\n".join(history_messages)
    await update.message.reply_text(response, parse_mode="Markdown")

# ======================= LỆNH ADMIN =======================

async def taokey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tạo key mới. Ví dụ: /taokey MYKEY123 1 ngày, /taokey VIPKEY 24 giờ."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này. 🚫")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Cú pháp: `/taokey <tên_key> [số_lượng] [đơn_vị_thời_gian]`\nVí dụ: `/taokey MYKEY123 1 ngày`, `/taokey VIPKEY 24 giờ`", parse_mode="Markdown")
        return

    key_name = context.args[0]
    expiry_time = None

    if len(context.args) >= 3:
        try:
            amount = int(context.args[1])
            unit = context.args[2].lower()
            if unit in ["ngày", "day"]:
                expiry_time = time.time() + amount * 24 * 3600
            elif unit in ["giờ", "h", "hour", "hours"]:
                expiry_time = time.time() + amount * 3600
            elif unit in ["phút", "m", "minute", "minutes"]:
                expiry_time = time.time() + amount * 60
            else:
                await update.message.reply_text("Đơn vị thời gian không hợp lệ. Vui lòng dùng 'ngày', 'giờ', 'phút'.")
                return
        except ValueError:
            await update.message.reply_text("Số lượng không hợp lệ. Vui lòng nhập một số nguyên.")
            return

    if key_name in KEY_DATA:
        await update.message.reply_text(f"Key `{key_name}` đã tồn tại. Vui lòng chọn tên khác.", parse_mode="Markdown")
        return

    KEY_DATA[key_name] = {
        "user_id": None,
        "expiry_time": expiry_time,
        "created_by": user_id,
        "created_at": time.time(),
        "activation_time": None # Khởi tạo là None
    }
    expiry_msg = f"hết hạn vào `{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expiry_time))}`" if expiry_time else "không có thời gian hết hạn"
    await update.message.reply_text(f"Key `{key_name}` đã được tạo thành công, {expiry_msg}. 🎉", parse_mode="Markdown")
    logger.info(f"Key {key_name} created by admin {user_id} with expiry {expiry_time}")

async def lietkekey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Liệt kê tất cả key và trạng thái sử dụng."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này. 🚫")
        return

    if not KEY_DATA:
        await update.message.reply_text("Chưa có key nào được tạo.")
        return

    response = "🔑 **Danh sách Key:**\n\n"
    for key, data in KEY_DATA.items():
        status = "Chưa sử dụng"
        user_info = ""
        expiry_info = ""
        activation_info = ""

        if data["user_id"]:
            status = "Đã sử dụng"
            user_info = f" bởi `{data['user_id']}`"
            if data["activation_time"]:
                activation_info = f" (kích hoạt: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data['activation_time']))})"
            
        if data["expiry_time"]:
            if data["expiry_time"] > time.time():
                expiry_info = f" | Hạn: `{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data['expiry_time']))}`"
            else:
                expiry_info = " | Đã hết hạn ⏳"
                status = "Đã hết hạn" # Cập nhật trạng thái nếu key đã hết hạn

        response += f"- `{key}`: {status}{user_info}{activation_info}{expiry_info}\n"
    await update.message.reply_text(response, parse_mode="Markdown")

async def xoakey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xóa key khỏi hệ thống."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này. 🚫")
        return

    if len(context.args) == 1:
        key_to_delete = context.args[0]
        if key_to_delete in KEY_DATA:
            del KEY_DATA[key_to_delete]
            await update.message.reply_text(f"Key `{key_to_delete}` đã được xóa. ✅", parse_mode="Markdown")
            logger.info(f"Key {key_to_delete} deleted by admin {update.effective_user.id}")
        else:
            await update.message.reply_text("Key không tồn tại. 🤔")
    else:
        await update.message.reply_text("Vui lòng cung cấp key cần xóa. Ví dụ: `/xoakey MYKEY123`", parse_mode="Markdown")

async def themadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Thêm ID người dùng làm admin."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này. 🚫")
        return

    if len(context.args) == 1:
        try:
            new_admin_id = int(context.args[0])
            if new_admin_id not in ADMIN_IDS:
                ADMIN_IDS.append(new_admin_id)
                await update.message.reply_text(f"ID `{new_admin_id}` đã được thêm vào danh sách admin. 🛡️", parse_mode="Markdown")
                logger.info(f"Admin {new_admin_id} added by admin {update.effective_user.id}")
            else:
                await update.message.reply_text("ID này đã là admin rồi. 😊")
        except ValueError:
            await update.message.reply_text("ID không hợp lệ. Vui lòng nhập một số nguyên.")
    else:
        await update.message.reply_text("Vui lòng cung cấp ID người dùng cần thêm. Ví dụ: `/themadmin 123456789`", parse_mode="Markdown")

async def xoaadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xóa ID người dùng khỏi admin."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này. 🚫")
        return

    if len(context.args) == 1:
        try:
            admin_id_to_remove = int(context.args[0])
            if admin_id_to_remove in ADMIN_IDS:
                ADMIN_IDS.remove(admin_id_to_remove)
                await update.message.reply_text(f"ID `{admin_id_to_remove}` đã được xóa khỏi danh sách admin. 🗑️", parse_mode="Markdown")
                logger.info(f"Admin {admin_id_to_remove} removed by admin {update.effective_user.id}")
            else:
                await update.message.reply_text("ID này không phải là admin. 🤔")
        except ValueError:
            await update.message.reply_text("ID không hợp lệ. Vui lòng nhập một số nguyên.")
    else:
        await update.message.reply_text("Vui lòng cung cấp ID người dùng cần xóa. Ví dụ: `/xoaadmin 123456789`", parse_mode="Markdown")

async def danhsachadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem danh sách các ID admin."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này. 🚫")
        return
    
    if not ADMIN_IDS:
        await update.message.reply_text("Chưa có admin nào được thêm.")
        return

    response = "🛡️ **Danh sách Admin:**\n"
    for admin_id in ADMIN_IDS:
        response += f"- `{admin_id}`\n"
    await update.message.reply_text(response, parse_mode="Markdown")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gửi thông báo đến tất cả người dùng."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này. 🚫")
        return

    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("Vui lòng cung cấp nội dung tin nhắn để broadcast. Ví dụ: `/broadcast Chào mọi người, bot đang cập nhật tính năng mới!`", parse_mode="Markdown")
        return

    success_count = 0
    fail_count = 0
    sent_to_users = set() # Dùng set để tránh gửi trùng lặp nếu user có nhiều key hoặc được lưu nhiều lần

    # Gửi đến tất cả user đã từng tương tác với bot hoặc có key
    # Tạo một set duy nhất chứa tất cả user_id
    all_known_users = set(USER_STATES.keys())
    for key_data in KEY_DATA.values():
        if key_data["user_id"]:
            all_known_users.add(key_data["user_id"])

    for user_id in all_known_users:
        if user_id in sent_to_users: # Nếu đã gửi cho user này rồi, bỏ qua
            continue 

        try:
            await context.bot.send_message(chat_id=user_id, text=f"📢 **THÔNG BÁO TỪ ADMIN:**\n\n{message_text}", parse_mode="Markdown")
            success_count += 1
            sent_to_users.add(user_id) # Đánh dấu đã gửi
        except Exception as e:
            logger.error(f"Không thể gửi broadcast đến người dùng {user_id}: {e}")
            fail_count += 1
    
    await update.message.reply_text(f"Đã gửi broadcast thành công đến {success_count} người dùng, thất bại {fail_count} người dùng.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Phản hồi khi người dùng gửi lệnh không xác định."""
    await update.message.reply_text("Xin lỗi, tôi không hiểu lệnh đó. Vui lòng xem `/start` để biết các lệnh được hỗ trợ.")

# ======================= CHẠY BOT =======================
def main() -> None:
    """Hàm chính để chạy bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    # Thêm JobQueue để chạy job định kỳ
    # Job này sẽ được gọi mỗi 2 giây để kiểm tra API và gửi thông báo
    job_queue = application.job_queue
    job_queue.run_repeating(job_tai_xiu_prediction, interval=2, first=0)


    # Handlers cho lệnh cơ bản
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("key", handle_key))

    # ConversationHandler cho /chaybot để quản lý luồng chọn game
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("chaybot", chaybot_start)],
        states={
            SELECTING_GAME: [CallbackQueryHandler(select_game, pattern="^game_")],
        },
        fallbacks=[CommandHandler("cancel", tatbot)], # Lệnh để thoát khỏi hội thoại
    )
    application.add_handler(conv_handler)
    
    application.add_handler(CommandHandler("tatbot", tatbot))
    application.add_handler(CommandHandler("lichsu", lichsu))

    # Handlers cho lệnh admin
    application.add_handler(CommandHandler("taokey", taokey))
    application.add_handler(CommandHandler("lietkekey", lietkekey))
    application.add_handler(CommandHandler("xoakey", xoakey))
    application.add_handler(CommandHandler("themadmin", themadmin))
    application.add_handler(CommandHandler("xoaadmin", xoaadmin))
    application.add_handler(CommandHandler("danhsachadmin", danhsachadmin))
    application.add_handler(CommandHandler("broadcast", broadcast))

    # Handler cho các tin nhắn không phải lệnh
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Khởi động bot
    logger.info("Bot đang khởi động...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
