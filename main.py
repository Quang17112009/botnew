import logging
import requests
import asyncio
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ApplicationBuilder,
    CallbackContext,
)
from flask import Flask, request
import json
import time
import datetime
import uuid

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Cấu hình bot
TOKEN = "8137068939:AAG19xO92yXsz_d9vz_m2aJW2Wh8JZnvSPQ"
ADMIN_ID = 6915752059  # ID Telegram của admin
API_URL = "https://apiluck2.onrender.com/predict"

# Lấy URL của dịch vụ Render từ biến môi trường (Render tự động cung cấp)
WEBHOOK_URL_BASE = os.environ.get("RENDER_EXTERNAL_HOSTNAME") 
if WEBHOOK_URL_BASE:
    WEBHOOK_URL = f"https://{WEBHOOK_URL_BASE}/{TOKEN}"
else:
    WEBHOOK_URL = None # Cần được cấu hình nếu không phải Render

# Dictionary để lưu trạng thái chạy dự đoán của từng người dùng
user_prediction_status = {}
# Dictionary để lưu trữ thông tin key và hạn sử dụng
active_keys = {} # key: { 'expiry_date': datetime.datetime, 'used_by': user_id }
user_active_packages = {} # user_id: key

# Biến để lưu trữ tổng số lần dự đoán và số lần dự đoán đúng
prediction_stats = {
    "total_predictions": 0,
    "correct_predictions": 0,
    "last_actual_result": None,
    "last_predicted_result": None
}

# Biến để lưu trữ phiên cuối cùng mà bot đã xử lý từ API
last_api_phien_moi_processed = None

# Flask app cho webhook
app = Flask(__name__)
application_instance = None # Sẽ được khởi tạo trong main và gán vào đây

# Định nghĩa các hàm xử lý lệnh (giữ nguyên như trước)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    
    package_info = "Chưa kích hoạt"
    expiry_info = "Chưa kích hoạt"

    if user_id in user_active_packages:
        key = user_active_packages[user_id]
        if key in active_keys:
            key_data = active_keys[key]
            if key_data['expiry_date'] is None:
                expiry_info = "Vĩnh viễn"
                package_info = "Đã kích hoạt"
            elif key_data['expiry_date'] > datetime.datetime.now():
                expiry_info = key_data['expiry_date'].strftime("%H:%M %d-%m-%Y")
                package_info = "Đã kích hoạt"
            else:
                del user_active_packages[user_id]
                del active_keys[key]
        
    await update.message.reply_html(
        f"🌟 CHÀO MỪNG **{user.first_name}** 🌟\n"
        "🎉 Chào mừng đến với HeHe Bot 🎉\n"
        f"📦 Gói hiện tại: {package_info}\n"
        f"⏰ Hết hạn: {expiry_info}\n"
        "💡 Dùng /help để xem các lệnh\n"
        "————————-"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    package_info = "Chưa kích hoạt"
    
    if user_id in user_active_packages:
        key = user_active_packages[user_id]
        if key in active_keys:
            key_data = active_keys[key]
            if key_data['expiry_date'] is None or key_data['expiry_date'] > datetime.datetime.now():
                package_info = "Đã kích hoạt"
            else:
                del user_active_packages[user_id]
                del active_keys[key]

    await update.message.reply_text(
        f"📦 Gói hiện tại: {package_info}\n"
        "🔥 Các lệnh hỗ trợ:\n"
        "✅ /start - Đăng ký và bắt đầu\n"
        "🔑 /key [mã] - Kích hoạt gói\n"
        "🎮 /chaymodelbasic - Chạy dự đoán  (LUCK)\n"
        "🛑 /stop - Dừng dự đoán\n"
        "🛠️ /admin - Lệnh dành cho admin\n"
        "📬 Liên hệ:\n"
        f"👤 Admin: t.me/heheviptool\n"
        "——————"
    )

async def activate_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Vui lòng cung cấp mã kích hoạt. Ví dụ: /key ABCXYZ")
        return
    
    input_key = context.args[0]
    
    if input_key in active_keys:
        key_data = active_keys[input_key]
        if key_data['used_by'] is not None and key_data['used_by'] != user_id:
            await update.message.reply_text("Mã này đã được sử dụng bởi người khác.")
            return

        if key_data['expiry_date'] is None:
            user_active_packages[user_id] = input_key
            active_keys[input_key]['used_by'] = user_id
            await update.message.reply_text("🎉 Gói của bạn đã được kích hoạt vĩnh viễn!")
        elif key_data['expiry_date'] > datetime.datetime.now():
            user_active_packages[user_id] = input_key
            active_keys[input_key]['used_by'] = user_id
            expiry_str = key_data['expiry_date'].strftime("%H:%M %d-%m-%Y")
            await update.message.reply_text(f"🎉 Gói của bạn đã được kích hoạt thành công! Hết hạn vào: {expiry_str}")
        else:
            await update.message.reply_text("Mã này đã hết hạn. Vui lòng liên hệ Admin.")
            del active_keys[input_key]
            if user_id in user_active_packages and user_active_packages[user_id] == input_key:
                del user_active_packages[user_id]
    else:
        await update.message.reply_text("Mã kích hoạt không hợp lệ. Vui lòng kiểm tra lại hoặc liên hệ Admin.")

async def send_prediction_message(chat_id: int, prediction_data: dict, bot_obj) -> None:
    try:
        phien_moi = prediction_data.get("Phien_moi", "N/A")
        matches = prediction_data.get("matches", [])
        
        ket_qua = "TÀI" if "t" in matches else "XỈU" if "x" in matches else "N/A"
        
        pattern = prediction_data.get("pattern", "N/A")
        phien_du_doan = prediction_data.get("phien_du_doan", "N/A")
        du_doan_ket_qua = prediction_data.get("du_doan", "N/A")

        message_text = (
            f"🤖 ʟᴜᴄᴋʏᴡɪɴ \n"
            f"🎯 ᴘʜɪᴇ̂ɴ {phien_moi} \n"
            f"🎲 ᴋᴇ̂́ᴛ ǫᴜ̉ᴀ : {ket_qua} \n"
            f"🧩 ᴘᴀᴛᴛᴇʀɴ : {pattern} \n"
            f"🎮  ᴘʜɪᴇ̂ɴ {phien_du_doan} : {du_doan_ket_qua} (ᴍᴏᴅᴇʟ ʙᴀꜱɪᴄ)\n"
            "————————-"
        )
        
        if ket_qua != "N/A" and du_doan_ket_qua != "N/A":
            prediction_stats["total_predictions"] += 1
            if (ket_qua == "TÀI" and du_doan_ket_qua == "Tài") or \
               (ket_qua == "XỈU" and du_doan_ket_qua == "Xỉu"):
                prediction_stats["correct_predictions"] += 1
            prediction_stats["last_actual_result"] = ket_qua
            prediction_stats["last_predicted_result"] = du_doan_ket_qua
        
        await bot_obj.send_message(chat_id=chat_id, text=message_text)

    except Exception as e:
        logger.error(f"Lỗi khi gửi tin nhắn dự đoán cho chat_id {chat_id}: {e}")

async def fetch_and_send_prediction_task(context: CallbackContext) -> None:
    global last_api_phien_moi_processed
    
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
        current_phien_moi = data.get("Phien_moi")

        if current_phien_moi and current_phien_moi != last_api_phien_moi_processed:
            logger.info(f"Phát hiện phiên mới: {current_phien_moi}. Đang gửi dự đoán...")
            
            users_to_predict_in_this_cycle = []
            for user_id, status in list(user_prediction_status.items()):
                if status:
                    if user_id in user_active_packages:
                        key = user_active_packages[user_id]
                        if key in active_keys:
                            key_data = active_keys[key]
                            if key_data['expiry_date'] is None or key_data['expiry_date'] > datetime.datetime.now():
                                users_to_predict_in_this_cycle.append(user_id)
                            else:
                                user_prediction_status[user_id] = False
                                await context.bot.send_message(chat_id=user_id, text="⚠️ Gói của bạn đã hết hạn. Vui lòng kích hoạt lại để tiếp tục nhận dự đoán.")
                                del user_active_packages[user_id]
                                del active_keys[key]
                        else:
                            user_prediction_status[user_id] = False
                            await context.bot.send_message(chat_id=user_id, text="⚠️ Gói của bạn không còn hiệu lực. Vui lòng liên hệ Admin.")
                            del user_active_packages[user_id]
                    else:
                        user_prediction_status[user_id] = False
                        await context.bot.send_message(chat_id=user_id, text="⚠️ Vui lòng kích hoạt gói để sử dụng chức năng dự đoán. Dùng /key [mã].")
            
            for chat_id in users_to_predict_in_this_cycle:
                await send_prediction_message(chat_id, data, context.bot)
                await asyncio.sleep(0.1)
            
            last_api_phien_moi_processed = current_phien_moi
        else:
            logger.info(f"Phiên API hiện tại ({current_phien_moi}) chưa thay đổi.")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Lỗi khi gọi API: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Lỗi phân tích JSON từ API: {e}")
    except Exception as e:
        logger.error(f"Lỗi không xác định trong fetch_and_send_prediction_task: {e}")

async def chay_model_basic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    if user_id not in user_active_packages:
        await update.message.reply_text("⚠️ Vui lòng kích hoạt gói để sử dụng chức năng dự đoán. Dùng /key [mã].")
        return
    
    key = user_active_packages[user_id]
    if key not in active_keys or (active_keys[key]['expiry_date'] is not None and active_keys[key]['expiry_date'] <= datetime.datetime.now()):
        await update.message.reply_text("⚠️ Gói của bạn đã hết hạn hoặc không còn hiệu lực. Vui lòng kích hoạt lại.")
        del user_active_packages[user_id]
        if key in active_keys: del active_keys[key]
        return

    if user_prediction_status.get(user_id):
        await update.message.reply_text("Dự đoán đã được bật rồi.")
        return
    
    user_prediction_status[user_id] = True
    await update.message.reply_text("⚡️ Đang chạy dự đoán (LUCK) từ Model Basic... Vui lòng đợi kết quả.")
    
async def stop_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not user_prediction_status.get(user_id):
        await update.message.reply_text("Dự đoán chưa được bật.")
        return

    user_prediction_status[user_id] = False
    await update.message.reply_text("🛑 Đã dừng dự đoán.")

async def admin_command(update: Update.Update, context: ContextTypes.DEFAULT_TYPE) -> None: # Sửa Update.Update thành Update
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    
    await update.message.reply_text(
        "🛠️ Lệnh dành cho Admin:\n"
        "🔑 /taokey [giờ/ngày/tuần/tháng/năm/vĩnhviễn] [số lượng (nếu là giờ/ngày/tuần/tháng/năm)] - Tạo key kích hoạt.\n"
        "📊 /check - Kiểm tra số lần dự đoán đúng của bot.\n"
        "📢 /tbao [tin nhắn] - Gửi thông báo đến tất cả người dùng đã tương tác với bot.\n"
    )

async def tao_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Vui lòng cung cấp định dạng và số lượng (nếu có). Ví dụ: /taokey ngày 7 hoặc /taokey vĩnhviễn")
        return
    
    duration_type = context.args[0].lower()
    amount = None
    
    if duration_type not in ["giờ", "ngày", "tuần", "tháng", "năm", "vĩnhviễn"]:
        await update.message.reply_text("Định dạng không hợp lệ. Vui lòng chọn: giờ, ngày, tuần, tháng, năm, vĩnhviễn.")
        return

    if duration_type != "vĩnhviễn":
        if len(context.args) < 2:
            await update.message.reply_text(f"Vui lòng cung cấp số lượng {duration_type}. Ví dụ: /taokey {duration_type} 7")
            return
        try:
            amount = int(context.args[1])
            if amount <= 0:
                await update.message.reply_text("Số lượng phải là một số nguyên dương.")
                return
        except ValueError:
            await update.message.reply_text("Số lượng không hợp lệ. Vui lòng nhập số nguyên.")
            return

    new_key = str(uuid.uuid4()).replace('-', '')[:10].upper()
    expiry_date = None

    if duration_type == "giờ":
        expiry_date = datetime.datetime.now() + datetime.timedelta(hours=amount)
    elif duration_type == "ngày":
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=amount)
    elif duration_type == "tuần":
        expiry_date = datetime.datetime.now() + datetime.timedelta(weeks=amount)
    elif duration_type == "tháng":
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=amount * 30)
    elif duration_type == "năm":
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=amount * 365)

    active_keys[new_key] = {
        'expiry_date': expiry_date,
        'used_by': None
    }
    
    expiry_str = "Vĩnh viễn" if expiry_date is None else expiry_date.strftime("%H:%M %d-%m-%Y")
    await update.message.reply_text(f"Đã tạo key mới: `{new_key}` (Hết hạn: {expiry_str})", parse_mode='Markdown')

async def check_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    total = prediction_stats["total_predictions"]
    correct = prediction_stats["correct_predictions"]
    accuracy = (correct / total * 100) if total > 0 else 0

    last_actual = prediction_stats["last_actual_result"] if prediction_stats["last_actual_result"] else "N/A"
    last_predicted = prediction_stats["last_predicted_result"] if prediction_stats["last_predicted_result"] else "N/A"

    await update.message.reply_text(
        f"📊 Thống kê dự đoán của Bot:\n"
        f"Tổng số dự đoán: {total}\n"
        f"Số lần dự đoán đúng: {correct}\n"
        f"Tỷ lệ chính xác: {accuracy:.2f}%\n"
        f"Kết quả thực tế gần nhất: {last_actual}\n"
        f"Dự đoán gần nhất: {last_predicted}"
    )

async def send_to_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    if not context.args:
        await update.message.reply_text("Vui lòng cung cấp tin nhắn để gửi. Ví dụ: /tbao Thông báo quan trọng!")
        return

    message_to_send = " ".join(context.args)
    sent_count = 0
    failed_count = 0

    all_chat_ids = set(user_prediction_status.keys())
    for user_id in user_active_packages:
        all_chat_ids.add(user_id)
    all_chat_ids.add(ADMIN_ID)

    await update.message.reply_text("Đang gửi thông báo đến người dùng. Vui lòng đợi...")

    for chat_id in all_chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"📢 **THÔNG BÁO TỪ ADMIN** 📢\n\n{message_to_send}", parse_mode='Markdown')
            sent_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Không thể gửi tin nhắn đến chat_id {chat_id}: {e}")
            failed_count += 1
    
    await update.message.reply_text(f"Đã gửi tin nhắn đến {sent_count} người dùng. Thất bại: {failed_count}.")

# Webhook handler
@app.route(f"/{TOKEN}", methods=["POST"])
async def telegram_webhook():
    if application_instance is None:
        logger.error("Application instance is None. Webhook cannot be processed.")
        return "Internal server error", 500
    
    update_data = request.get_json(force=True)
    update = Update.de_json(update_data, application_instance.bot)
    
    # Process update asynchronously
    # Use application_instance.update_queue.put(update) or application_instance.process_update(update)
    # The latter is simpler for direct webhook processing.
    await application_instance.process_update(update)
    return "ok"

# Route cho Render để kiểm tra trạng thái
@app.route('/')
def index():
    return "Bot is running and listening for webhooks!"

# Hàm chạy bot Telegram (chỉ bao gồm việc khởi tạo và lên lịch job)
async def run_telegram_bot_tasks(app_instance: Application):
    logger.info("Initializing Telegram bot tasks...")
    # Đặt webhook cho bot
    if WEBHOOK_URL:
        logger.info(f"Setting webhook to: {WEBHOOK_URL}")
        await app_instance.bot.set_webhook(url=WEBHOOK_URL)
    else:
        logger.warning("WEBHOOK_URL not set. Bot might not receive updates correctly.")
    
    # Schedule the periodic task to fetch predictions
    # interval=5 là 5 giây, có thể điều chỉnh
    app_instance.job_queue.run_repeating(fetch_and_send_prediction_task, interval=5, first=1)
    logger.info("Telegram bot tasks scheduled.")

def main() -> None:
    global application_instance
    
    # Xây dựng ứng dụng bot
    application_instance = ApplicationBuilder().token(TOKEN).build()

    # Đăng ký các trình xử lý lệnh
    application_instance.add_handler(CommandHandler("start", start))
    application_instance.add_handler(CommandHandler("help", help_command))
    application_instance.add_handler(CommandHandler("key", activate_key))
    application_instance.add_handler(CommandHandler("chaymodelbasic", chay_model_basic))
    application_instance.add_handler(CommandHandler("stop", stop_prediction))
    application_instance.add_handler(CommandHandler("admin", admin_command))
    
    # Các lệnh admin mới
    application_instance.add_handler(CommandHandler("taokey", tao_key))
    application_instance.add_handler(CommandHandler("check", check_stats))
    application_instance.add_handler(CommandHandler("tbao", send_to_all))

    # Khởi chạy các tác vụ của Telegram bot (webhook và job_queue) trong một background task
    # Điều này đảm bảo chúng chạy trong event loop của application_instance
    # và không chặn Flask server.
    application_instance.create_task(run_telegram_bot_tasks(application_instance))

    # Flask sẽ chạy trên cổng được Render cung cấp
    port = int(os.environ.get("PORT", 8080))
    
    # Khởi chạy Flask app
    # Gunicorn sẽ gọi app.run() thông qua WSGI, nên KHÔNG gọi app.run() ở đây
    logger.info(f"Flask app is ready to serve on port {port}")

if __name__ == "__main__":
    # Đây là điểm khởi đầu khi Gunicorn chạy `bot:app`
    # `app` là đối tượng Flask, và `main()` sẽ được gọi để cấu hình `application_instance`
    main()

