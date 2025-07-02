import logging
import requests
import uuid
import datetime
import os # Thêm thư viện os để đọc biến môi trường
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode # Thêm để hỗ trợ định dạng Markdown

# --- Cấu hình Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Cấu hình Bot (Token và ID Admin được tải từ biến môi trường) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID")) # Chuyển đổi sang kiểu số nguyên
API_URL = "https://apiluck2.onrender.com/predict" # Giữ nguyên URL API của bạn
ADMIN_TELEGRAM_LINK = "t.me/heheviptool" # Giữ nguyên link admin của bạn

# --- Cấu hình Webhook cụ thể ---
# Render cung cấp cổng và URL công khai thông qua biến môi trường
WEB_SERVER_PORT = int(os.environ.get("PORT", "8080")) # Mặc định là 8080 nếu không được đặt
WEBHOOK_URL_PATH = "/telegram-webhook" # Có thể là bất kỳ chuỗi nào, nhưng phải nhất quán
WEBHOOK_URL = os.environ.get("PUBLIC_URL") + WEBHOOK_URL_PATH # URL Render của bạn + đường dẫn

if not BOT_TOKEN or not ADMIN_ID or not WEBHOOK_URL:
    logger.error("Thiếu biến môi trường BOT_TOKEN, ADMIN_ID hoặc PUBLIC_URL. Vui lòng kiểm tra cấu hình.")
    exit(1) # Thoát nếu thiếu các biến môi trường cần thiết

# --- Trạng thái dự đoán ---
prediction_active = False

# --- Quản lý Key, Người dùng và Lịch sử dự đoán ---
# Trong một ứng dụng thực tế, bạn nên sử dụng cơ sở dữ liệu (SQLite, PostgreSQL, v.v.)
# để lưu trữ thông tin key, người dùng và lịch sử dự đoán một cách bền vững.
# Ví dụ đơn giản này sẽ lưu trữ trong bộ nhớ (sẽ mất khi bot khởi động lại).
active_keys = {}  # { "key_string": {"expiry_date": datetime_obj, "user_id": None} }
user_subscriptions = {}  # { "user_id": {"key": "key_string", "expiry_date": datetime_obj} }
registered_users = set()  # Tập hợp các user_id đã từng tương tác với bot

# Lịch sử dự đoán để tính toán cho lệnh /check
prediction_history = [] # Lưu trữ {"phien": "2020297", "ket_qua_api": "t" hoặc "x", "du_doan_bot": "Tài" hoặc "Xỉu"}

# Biến để theo dõi phiên cuối cùng đã gửi thông báo
last_known_session_id = None

# --- Hàm xử lý lệnh /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    registered_users.add(user_id)  # Ghi nhận người dùng đã tương tác

    package_status = "Chưa kích hoạt"
    expiry_status = "Chưa kích hoạt"

    if user_id in user_subscriptions:
        sub_info = user_subscriptions[user_id]
        if sub_info["expiry_date"] > datetime.datetime.now():
            package_status = "Đã kích hoạt"
            expiry_status = sub_info["expiry_date"].strftime("%H:%M %d/%m/%Y")
        else:
            # Key đã hết hạn
            del user_subscriptions[user_id]
            # Tìm key trong active_keys để đặt lại user_id = None nếu cần
            for key, info in active_keys.items():
                if info.get("user_id") == user_id:
                    active_keys[key]["user_id"] = None
                    break
            package_status = "Đã hết hạn"
            expiry_status = "Đã hết hạn"

    response_message = (
        f"🌟 CHÀO MỪNG {user_name} 🌟\n\n"
        "🎉 Chào mừng đến với HeHe Bot 🎉\n\n"
        f"📦 Gói hiện tại: {package_status}\n"
        f"⏰ Hết hạn: {expiry_status}\n"
        "💡 Dùng /help để xem các lệnh\n"
        "————————-"
    )
    await update.message.reply_text(response_message)

# --- Hàm xử lý lệnh /help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    package_status = "Chưa kích hoạt"
    if user_id in user_subscriptions and user_subscriptions[user_id]["expiry_date"] > datetime.datetime.now():
        package_status = "Đã kích hoạt"

    response_message = (
        f"📦 Gói hiện tại: {package_status}\n"
        "🔥 Các lệnh hỗ trợ:\n"
        "✅ /start - Đăng ký và bắt đầu\n"
        "🔑 /key [mã] - Kích hoạt gói\n"
        "🎮 /chaymodelbasic - Chạy dự đoán  (LUCK)\n"
        "🛑 /stop - Dừng dự đoán\n"
        "🛠️ /admin - Lệnh dành cho admin\n"
        "📬 Liên hệ:\n"
        f"👤 Admin: {ADMIN_TELEGRAM_LINK}\n"
        "——————"
    )
    await update.message.reply_text(response_message)

# --- Hàm gửi dự đoán từ API ---
async def send_prediction(context: ContextTypes.DEFAULT_TYPE) -> None:
    global prediction_active, last_known_session_id
    chat_id = context.job.chat_id

    # Kiểm tra xem người dùng có gói kích hoạt không
    if chat_id not in user_subscriptions or user_subscriptions[chat_id]["expiry_date"] <= datetime.datetime.now():
        await context.bot.send_message(chat_id=chat_id, text="Gói của bạn đã hết hạn hoặc chưa kích hoạt. Vui lòng kích hoạt gói để tiếp tục nhận dự đoán.")
        # Dừng job nếu gói hết hạn
        context.job.schedule_removal()
        if chat_id in user_subscriptions:
            del user_subscriptions[chat_id]
        return

    if not prediction_active:
        return # Dừng nếu dự đoán không còn hoạt động

    try:
        response = requests.get(API_URL)
        response.raise_for_status()  # Ném lỗi nếu có lỗi HTTP (4xx hoặc 5xx)
        data = response.json()

        phien_moi = data.get("Phien_moi")  # Lấy session ID mới nhất

        # Chỉ gửi thông báo nếu có phiên mới hoặc đây là lần đầu tiên
        if phien_moi and phien_moi != last_known_session_id:
            last_known_session_id = phien_moi  # Cập nhật session ID cuối cùng đã biết

            # Trích xuất thông tin từ API
            matches_list = data.get("matches", [])

            # Chuyển đổi 't' thành 'TÀI', 'x' thành 'XỈU'
            ket_qua_api = ""
            ket_qua_display = "N/A"
            if "t" in matches_list:
                ket_qua_display = "TÀI"
                ket_qua_api = "t"
            elif "x" in matches_list:
                ket_qua_display = "XỈU"
                ket_qua_api = "x"

            pattern = data.get("pattern", "Không có")
            phien_du_doan = data.get("phien_du_doan", "Không có")
            du_doan_ket_qua = data.get("du_doan", "Không có")

            # Ghi lại lịch sử dự đoán cho lệnh /check
            if du_doan_ket_qua != "Không có" and ket_qua_api:
                prediction_history.append({
                    "phien": phien_moi,
                    "ket_qua_api": ket_qua_api,
                    "du_doan_bot": du_doan_ket_qua
                })
                # Giữ lịch sử không quá lớn, ví dụ 100 phiên gần nhất
                if len(prediction_history) > 100:
                    prediction_history.pop(0)

            # Định dạng lại thông báo
            prediction_message = (
                "🤖 ʟᴜᴄᴋʏᴡɪɴ\n"
                f"🎯 ᴘʜɪᴇ̂ɴ {phien_moi}\n"
                f"🎲 ᴋᴇ̂́ᴛ ǫᴜᴀ̉ : {ket_qua_display} {phien_moi}\n"
                f"🧩 ᴘᴀᴛᴛᴇʀɴ : {pattern}\n"
                f"🎮 ᴘʜɪᴇ̂ɴ {phien_du_doan} : {du_doan_ket_qua} (ᴍᴏᴅᴇʟ ʙᴀꜱɪᴄ)\n"
                "————————-"
            )

            await context.bot.send_message(chat_id=chat_id, text=prediction_message)
        # else:
        #     logger.info(f"Phien_moi {phien_moi} trùng với last_known_session_id. Không gửi thông báo.")

    except requests.exceptions.RequestException as e:
        logger.error(f"Lỗi khi gọi API: {e}")
    except Exception as e:
        logger.error(f"Lỗi không xác định: {e}")

# --- Hàm xử lý lệnh /chaymodelbasic ---
async def chay_model_basic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    global prediction_active, last_known_session_id

    if user_id not in user_subscriptions or user_subscriptions[user_id]["expiry_date"] <= datetime.datetime.now():
        await update.message.reply_text("Bạn cần kích hoạt gói để chạy dự đoán. Dùng /key [mã] để kích hoạt.")
        return

    # Kiểm tra xem một job cho chat_id này đã tồn tại chưa để tránh tạo nhiều job
    existing_jobs = context.job_queue.get_jobs_by_chat_id(update.effective_chat.id)
    for job in existing_jobs:
        if job.name == "prediction_job":
            await update.message.reply_text("Dự đoán đã đang chạy rồi.")
            return

    prediction_active = True
    chat_id = update.effective_chat.id
    await update.message.reply_text("Bắt đầu chạy dự đoán (MODEL BASIC). Bot sẽ tự động gửi khi có phiên mới.")

    # Đặt lại last_known_session_id khi bắt đầu chạy mới
    last_known_session_id = None

    if not hasattr(context, 'job_queue') or context.job_queue is None:
        logger.error("context.job_queue is None. This should not happen in a correctly set up Application.")
        await update.message.reply_text("Bot gặp lỗi nội bộ. Vui lòng thử lại sau hoặc liên hệ admin.")
        return

    # Vẫn polling mỗi 1 giây để phát hiện phiên mới nhanh nhất
    context.job_queue.run_repeating(send_prediction, interval=1, first=0, chat_id=chat_id, name="prediction_job")


# --- Hàm xử lý lệnh /stop ---
async def stop_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global prediction_active, last_known_session_id
    if not prediction_active:
        await update.message.reply_text("Dự đoán chưa được chạy.")
        return

    prediction_active = False
    current_jobs = context.job_queue.get_jobs_by_chat_id(update.effective_chat.id)
    removed_count = 0
    for job in current_jobs:
        if job.name == "prediction_job":
            job.schedule_removal()
            removed_count += 1

    if removed_count > 0:
        await update.message.reply_text("Đã dừng dự đoán.")
        last_known_session_id = None # Đặt lại khi dừng
    else:
        await update.message.reply_text("Không tìm thấy dự đoán đang chạy để dừng.")


# --- Hàm xử lý lệnh /key ---
async def activate_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Vui lòng nhập mã kích hoạt. Ví dụ: /key ABC-123-XYZ")
        return

    key_input = context.args[0].upper() # Chuyển sang chữ hoa để nhất quán
    user_id = update.effective_user.id

    if key_input in active_keys:
        key_info = active_keys[key_input]
        if key_info["user_id"] is None: # Key chưa được sử dụng
            expiry_date = key_info["expiry_date"]
            if expiry_date <= datetime.datetime.now(): # Kiểm tra key còn hạn không
                await update.message.reply_text("Mã kích hoạt này đã hết hạn. Vui lòng liên hệ admin.")
                del active_keys[key_input] # Xóa key hết hạn
                return

            active_keys[key_input]["user_id"] = user_id # Đánh dấu key đã dùng
            user_subscriptions[user_id] = {"key": key_input, "expiry_date": expiry_date}

            await update.message.reply_text(
                f"🎉 Kích hoạt gói thành công!\n"
                f"Gói của bạn có hiệu lực đến: **{expiry_date.strftime('%H:%M %d/%m/%Y')}**",
                parse_mode=ParseMode.MARKDOWN # Thêm để hỗ trợ định dạng **text**
            )
            # Cập nhật trạng thái người dùng (ví dụ: bằng cách gọi /start lại)
            await start(update, context)
        elif key_info["user_id"] == user_id:
            await update.message.reply_text("Mã này đã được bạn sử dụng rồi.")
        else:
            await update.message.reply_text("Mã này đã được người khác sử dụng.")
    else:
        await update.message.reply_text("Mã kích hoạt không hợp lệ hoặc đã hết hạn.")

# --- Hàm Admin: /taokey ---
async def create_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    if not context.args:
        await update.message.reply_text("Vui lòng cung cấp thời hạn key. Ví dụ: `/taokey 1d`, `/taokey 2w`, `/taokey vinhvien`", parse_mode=ParseMode.MARKDOWN)
        return

    duration_str = context.args[0].lower()
    expiry_date = None
    # Tạo key ngẫu nhiên đơn giản, có thể thêm tiền tố để dễ phân biệt
    key = "LW-" + str(uuid.uuid4()).split('-')[0].upper()

    now = datetime.datetime.now()

    if duration_str == "vinhvien":
        expiry_date = now + datetime.timedelta(days=365 * 100) # Coi như vĩnh viễn (100 năm)
    else:
        try:
            value = int(duration_str[:-1])
            unit = duration_str[-1]
            if unit == 's': # giây
                expiry_date = now + datetime.timedelta(seconds=value)
            elif unit == 'm': # phút
                expiry_date = now + datetime.timedelta(minutes=value)
            elif unit == 'h': # giờ
                expiry_date = now + datetime.timedelta(hours=value)
            elif unit == 'd': # ngày
                expiry_date = now + datetime.timedelta(days=value)
            elif unit == 'w': # tuần
                expiry_date = now + datetime.timedelta(weeks=value)
            elif unit == 'M': # tháng (ước tính 30 ngày)
                expiry_date = now + datetime.timedelta(days=value * 30)
            elif unit == 'y': # năm (ước tính 365 ngày)
                expiry_date = now + datetime.timedelta(days=value * 365)
            else:
                await update.message.reply_text("Định dạng thời hạn không hợp lệ. Ví dụ: `1s, 5m, 2h, 1d, 3w, 1M, 1y, vinhvien`", parse_mode=ParseMode.MARKDOWN)
                return
        except (ValueError, IndexError): # Bắt cả IndexError nếu chuỗi rỗng
            await update.message.reply_text("Định dạng thời hạn không hợp lệ. Ví dụ: `1s, 5m, 2h, 1d, 3w, 1M, 1y, vinhvien`", parse_mode=ParseMode.MARKDOWN)
            return

    if expiry_date:
        active_keys[key] = {"expiry_date": expiry_date, "user_id": None}
        await update.message.reply_text(
            f"Đã tạo key: `{key}`\n"
            f"Thời hạn: {duration_str}\n"
            f"Hết hạn vào: {expiry_date.strftime('%H:%M %d/%m/%Y')}",
            parse_mode=ParseMode.MARKDOWN # Thêm để hỗ trợ định dạng `code`
        )
    else:
        await update.message.reply_text("Lỗi khi tạo key. Vui lòng kiểm tra lại định dạng.")

# --- Hàm Admin: /tbao ---
async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    if not context.args:
        await update.message.reply_text("Vui lòng nhập nội dung thông báo. Ví dụ: `/tbao Bot sẽ bảo trì vào 23h`", parse_mode=ParseMode.MARKDOWN)
        return

    message_to_send = "📢 **THÔNG BÁO TỪ ADMIN** 📢\n\n" + " ".join(context.args)

    success_count = 0
    fail_count = 0

    for user_id in list(registered_users):
        try:
            await context.bot.send_message(chat_id=user_id, text=message_to_send, parse_mode=ParseMode.MARKDOWN)
            success_count += 1
        except Exception as e:
            logger.error(f"Không thể gửi thông báo tới user {user_id}: {e}")
            fail_count += 1

    await update.message.reply_text(f"Đã gửi thông báo tới {success_count} người dùng. Thất bại: {fail_count}.")

# --- Hàm Admin: /check ---
async def check_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    total_predictions = len(prediction_history)
    correct_predictions = 0
    wrong_predictions = 0

    for record in prediction_history:
        api_result = record.get("ket_qua_api")
        bot_prediction = record.get("du_doan_bot")

        if (api_result == "t" and bot_prediction == "Tài") or \
           (api_result == "x" and bot_prediction == "Xỉu"):
            correct_predictions += 1
        elif api_result and bot_prediction:
            wrong_predictions += 1

    if total_predictions == 0:
        response_message = "Chưa có dữ liệu dự đoán nào để kiểm tra."
    else:
        accuracy = (correct_predictions / total_predictions) * 100 if total_predictions > 0 else 0
        response_message = (
            "📊 **THỐNG KÊ DỰ ĐOÁN** 📊\n\n"
            f"Tổng số phiên dự đoán: {total_predictions}\n"
            f"Số phiên dự đoán đúng: {correct_predictions}\n"
            f"Số phiên dự đoán sai: {wrong_predictions}\n"
            f"Tỷ lệ chính xác: {accuracy:.2f}%\n\n"
            "*(Dữ liệu này chỉ lưu trong bộ nhớ và sẽ reset khi bot khởi động lại)*"
        )
    await update.message.reply_text(response_message, parse_mode=ParseMode.MARKDOWN)


# --- Hàm xử lý lệnh /admin (chỉ admin mới dùng được) ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        admin_help_message = (
            "🛠️ **Lệnh dành cho Admin:**\n"
            "`/taokey [thời_hạn]` - Tạo key kích hoạt gói.\n"
            "   - Thời hạn: `Xs` (giây), `Xm` (phút), `Xh` (giờ), `Xd` (ngày), `Xw` (tuần), `XM` (tháng), `Xy` (năm), `vinhvien`.\n"
            "   - Ví dụ: `/taokey 3d` (3 ngày), `/taokey 1y` (1 năm), `/taokey vinhvien`.\n"
            "`/tbao [nội_dung]` - Gửi thông báo đến tất cả người dùng.\n"
            "   - Ví dụ: `/tbao Bot sẽ cập nhật vào lúc 20h hôm nay.`\n"
            "`/check` - Kiểm tra hiệu suất dự đoán của bot.\n"
            "**Lưu ý:** Dữ liệu key và lịch sử dự đoán hiện tại chỉ lưu tạm thời trong bộ nhớ và sẽ mất khi bot khởi động lại. Nên dùng cơ sở dữ liệu cho bản chính thức."
        )
        await update.message.reply_text(admin_help_message, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")

def main() -> None:
    """Khởi chạy bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    # Đăng ký các trình xử lý lệnh chung
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("chaymodelbasic", chay_model_basic))
    application.add_handler(CommandHandler("stop", stop_prediction))
    application.add_handler(CommandHandler("key", activate_key))

    # Đăng ký các lệnh Admin
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("taokey", create_key))
    application.add_handler(CommandHandler("tbao", send_broadcast))
    application.add_handler(CommandHandler("check", check_performance))

    # Chạy bot bằng webhooks
    logger.info(f"Bot đang chạy với webhooks trên cổng {WEB_SERVER_PORT}")
    application.run_webhook(
        listen="0.0.0.0",
        port=WEB_SERVER_PORT,
        url_path=WEBHOOK_URL_PATH,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
