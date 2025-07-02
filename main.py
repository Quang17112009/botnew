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

# Lấy URL của dịch vụ Render từ biến môi trường
WEBHOOK_URL_BASE = os.environ.get("RENDER_EXTERNAL_HOSTNAME") 
WEBHOOK_PATH = f"/{TOKEN}"
if WEBHOOK_URL_BASE:
    WEBHOOK_URL = f"https://{WEBHOOK_URL_BASE}{WEBHOOK_PATH}"
else:
    WEBHOOK_URL = None # Cần được cấu hình nếu không phải Render (ví dụ: cho local testing)

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

# Flask app
app = Flask(__name__)
# Application instance sẽ được tạo và gán sau
application_instance: Application = None

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

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # Đã sửa lỗi Update.Update thành Update
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

# Function to setup the bot and schedule jobs
async def setup_bot():
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
    
    application_instance.add_handler(CommandHandler("taokey", tao_key))
    application_instance.add_handler(CommandHandler("check", check_stats))
    application_instance.add_handler(CommandHandler("tbao", send_to_all))

    # Đặt webhook cho bot
    if WEBHOOK_URL:
        logger.info(f"Setting webhook to: {WEBHOOK_URL}")
        await application_instance.bot.set_webhook(url=WEBHOOK_URL)
    else:
        logger.warning("WEBHOOK_URL not set. Bot might not receive updates correctly.")
    
    # Schedule the periodic task to fetch predictions
    application_instance.job_queue.run_repeating(fetch_and_send_prediction_task, interval=5, first=1)
    logger.info("Telegram bot tasks scheduled.")

# Webhook handler
@app.route(WEBHOOK_PATH, methods=["POST"])
async def telegram_webhook():
    if application_instance is None:
        logger.error("Application instance is None. Webhook cannot be processed.")
        return "Internal server error", 500
    
    update_data = request.get_json(force=True)
    update = Update.de_json(update_data, application_instance.bot)
    
    # Process update asynchronously
    await application_instance.process_update(update)
    return "ok"

# Route cho Render để kiểm tra trạng thái
@app.route('/')
def index():
    return "Bot is running and listening for webhooks!"

# Function to run the Flask app and set up bot.
# This function will be the entry point for Gunicorn.
def run_app():
    # Setup bot asynchronously
    asyncio.run(setup_bot())
    # Gunicorn will manage the Flask app lifecycle.
    # We do NOT call app.run() here when using Gunicorn.
    # This function should simply exist for Gunicorn to call `bot:app`
    # and the Flask app will then handle incoming requests,
    # while the job_queue runs in the background within the
    # python-telegram-bot Application's event loop.
    logger.info("Flask app is ready to serve. Bot tasks are running.")

# Dòng này cần được đặt ở cuối file và là entry point cho Gunicorn
if __name__ == "__main__":
    # If running locally, you might want to call app.run() directly for testing.
    # But for Render/Gunicorn, this block is typically not executed directly for Flask part.
    # Instead, Gunicorn imports the `app` object and runs it.
    
    # For local testing, you can uncomment this:
    # asyncio.run(setup_bot())
    # port = int(os.environ.get("PORT", 8080))
    # app.run(host="0.0.0.0", port=port)
    
    # When Gunicorn runs `gunicorn bot:app`, it imports `app` directly.
    # The `setup_bot()` needs to be called to initialize the telegram bot
    # and its JobQueue.
    # A common pattern for Gunicorn is to have a `main` function or similar
    # that sets up the application.
    
    # The `setup_bot` will run and schedule jobs.
    # The Flask app (`app`) will then listen for requests.
    # The problem is that Gunicorn runs `app` directly, not `main()`.
    # So `setup_bot()` needs to be called when `app` is initialized.
    
    # Let's ensure setup_bot is called when the module is loaded if
    # Gunicorn is importing it, or directly if __name__ == "__main__"
    # To handle both, we'll call setup_bot as part of the app lifecycle
    # which is tricky with Flask and ptb's async nature.

    # A better approach for Gunicorn with async initialization:
    # Use Flask's `@app.before_first_request` or similar, but that's for sync Flask.
    # For async Flask, we need to manually manage the lifecycle.

    # Let's try to initialize the bot application when the module is first loaded
    # and then ensure its async parts are run.

    # This structure is often best handled by creating the Application outside main
    # and using a custom command for Gunicorn or a specific entrypoint.
    
    # For simplicity and to directly address the error:
    # The `setup_bot()` should be called when `app` is run by Gunicorn.
    # Gunicorn uses a WSGI server model. A common way is to make `app` callable
    # and have it perform the setup.

    # Let's define an async function to do the setup and make Flask run it.
    # This requires a bit of a Flask ASGI server setup.
    # But the current python-telegram-bot Application is designed for its own loop.

    # Let's revert to a simpler method that sometimes works with Gunicorn
    # by ensuring the `Application` is fully built and running its background tasks
    # before Flask starts accepting requests.

    # --- FINAL ATTEMPT FOR SIMPLICITY AND COMPATIBILITY ---
    # The core issue is that `application_instance.job_queue` is `None` until
    # `application_instance.run_polling()` or `application_instance.run_webhook()`
    # has started its event loop.
    # When using Gunicorn, you typically expose the Flask `app` object.
    # The `python-telegram-bot` `Application` needs its own event loop to manage `JobQueue`.

    # Let's try to run the bot's event loop in a background thread
    # and the Flask app in the main thread (managed by Gunicorn).
    # This was the initial approach that led to the `no running event loop` error.
    # The reason for that error was trying to create `asyncio.run()` in a new thread
    # which conflicts with the default policy.

    # The most robust way is to make the Flask application itself asynchronous (ASGI)
    # and then start the Telegram bot's async loop within Flask's async context.
    # This means using `Quart` or `Flask-Async` with an ASGI server like `Uvicorn`.

    # However, if we stick to `Flask` with `Gunicorn` (WSGI), then we must run the
    # bot's event loop in a separate, dedicated thread, and ensure the `asyncio`
    # policies are set correctly for that thread.

    # Let's try to restart the threading approach with proper asyncio policy setting.

    # Re-introducing threading for the bot's background tasks
    # This is often where the 'no running event loop' comes from if not handled correctly.
    # The key is to create a NEW event loop for the new thread.
    
    # The original structure:
    # bot_thread = Thread(target=lambda: asyncio.run(application.run_polling()))
    # bot_thread.start()
    # app.run(...)

    # This failed because `asyncio.run` tries to create/get a loop.
    # Instead, we need to create a new loop explicitly for the thread.

    def run_telegram_bot_in_thread(app_instance: Application):
        # Create a new event loop for this new thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Now run the Telegram bot's webhook and job_queue setup
        # in this new event loop.
        loop.run_until_complete(setup_bot_initialization(app_instance))
        
        # Start processing webhook updates for the Telegram bot in this loop.
        # This will keep the loop running and process incoming updates.
        # For webhooks, the application doesn't need to run_polling().
        # It just needs its job_queue to be active and set_webhook to be called.
        # The actual updates are processed by the Flask webhook handler.
        
        # The job_queue will continue to run in this loop.
        loop.run_forever() # Keep the event loop running for job_queue

    async def setup_bot_initialization(app_instance: Application):
        if WEBHOOK_URL:
            logger.info(f"Setting webhook to: {WEBHOOK_URL}")
            await app_instance.bot.set_webhook(url=WEBHOOK_URL)
        else:
            logger.warning("WEBHOOK_URL not set. Bot might not receive updates correctly.")
        
        # Schedule the periodic task to fetch predictions
        app_instance.job_queue.run_repeating(fetch_and_send_prediction_task, interval=5, first=1)
        logger.info("Telegram bot tasks scheduled in its own event loop.")


    global application_instance
    application_instance = ApplicationBuilder().token(TOKEN).build()

    # Register handlers
    application_instance.add_handler(CommandHandler("start", start))
    application_instance.add_handler(CommandHandler("help", help_command))
    application_instance.add_handler(CommandHandler("key", activate_key))
    application_instance.add_handler(CommandHandler("chaymodelbasic", chay_model_basic))
    application_instance.add_handler(CommandHandler("stop", stop_prediction))
    application_instance.add_handler(CommandHandler("admin", admin_command))
    application_instance.add_handler(CommandHandler("taokey", tao_key))
    application_instance.add_handler(CommandHandler("check", check_stats))
    application_instance.add_handler(CommandHandler("tbao", send_to_all))


    # Start the Telegram bot's event loop and tasks in a separate thread
    bot_thread = Thread(target=run_telegram_bot_in_thread, args=(application_instance,))
    bot_thread.daemon = True # Allow the main program to exit even if this thread is running
    bot_thread.start()
    
    # For Gunicorn, `app` itself is the entry point, so we don't call `app.run()` here.
    # Gunicorn will import `app` and serve it.
    logger.info("Flask app initialized. Waiting for Gunicorn to start serving.")

# Dòng này cần nằm ngoài main() để Gunicorn có thể import `app`
# Gunicorn sẽ gọi `app` như một WSGI callable.
# Khi Gunicorn chạy file này, `if __name__ == "__main__"` sẽ không chạy.
# Tuy nhiên, `application_instance` và `app` phải được cấu hình.
# Để xử lý điều này một cách sạch sẽ, chúng ta có thể đặt logic khởi tạo vào
# một hàm và gọi nó một cách thích hợp.

# Let's use a setup function that Gunicorn can call implicitly or explicitly.

# The current structure: `main()` initializes everything, and `app` is just a global.
# When Gunicorn imports `bot.py`, it executes the top-level code.
# So `application_instance = ApplicationBuilder().token(TOKEN).build()`
# and all `add_handler` calls run.
# The `bot_thread` is also started.
# This should be the most robust way.

# This `if __name__ == "__main__":` block is for local testing.
# When deployed with Gunicorn, Gunicorn imports the module and calls `app`.
# So the code outside any function definitions will be executed once.
# Let's ensure the `main()` function is what sets up the global `app` and `application_instance`.

# Let's use a simple pattern where Gunicorn imports `app` and we ensure `application_instance`
# is set up by executing `main()` at the module level.

main() # Call main() directly so it runs when the module is imported by Gunicorn.

