import logging
import requests
import asyncio
import os # Thêm thư viện os để lấy biến môi trường
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ApplicationBuilder,
    CallbackContext, # Thêm CallbackContext
)
from flask import Flask, request
from threading import Thread # Có thể loại bỏ nếu không cần keep_alive riêng biệt
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
# Đảm bảo bạn đặt tên dịch vụ trên Render là 'your-bot-name'
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_HOSTNAME") 
if WEBHOOK_URL:
    WEBHOOK_URL = f"https://{WEBHOOK_URL}/{TOKEN}" # Hoặc đường dẫn tùy chỉnh nếu bạn muốn

# Dictionary để lưu trạng thái chạy dự đoán của từng người dùng
user_prediction_status = {}
# Dictionary để lưu ID tin nhắn cuối cùng đã gửi để cập nhật (có thể không cần nếu không cập nhật tin nhắn)
# last_prediction_message_id = {}
# Dictionary để lưu trữ thông tin key và hạn sử dụng
# Cần thay thế bằng cơ sở dữ liệu thực tế trong môi trường production
active_keys = {} # key: { 'expiry_date': datetime.datetime, 'used_by': user_id }
user_active_packages = {} # user_id: key

# Biến để lưu trữ tổng số lần dự đoán và số lần dự đoán đúng
prediction_stats = {
    "total_predictions": 0,
    "correct_predictions": 0,
    "last_actual_result": None, # Kết quả thực tế của phiên cuối cùng
    "last_predicted_result": None # Kết quả dự đoán của phiên cuối cùng
}

# Biến để lưu trữ phiên cuối cùng mà bot đã xử lý từ API
# Để tránh gửi lại dự đoán cho cùng một phiên
last_api_phien_moi_processed = None

# Flask app cho webhook và keep_alive
app = Flask(__name__)
application = None # Sẽ được khởi tạo trong main và gán vào đây

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
                del user_active_packages[user_id] # Xóa gói hết hạn
                del active_keys[key] # Xóa key hết hạn
        
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
            del active_keys[input_key] # Xóa key hết hạn
            if user_id in user_active_packages and user_active_packages[user_id] == input_key:
                del user_active_packages[user_id]
    else:
        await update.message.reply_text("Mã kích hoạt không hợp lệ. Vui lòng kiểm tra lại hoặc liên hệ Admin.")

async def send_prediction_message(chat_id: int, prediction_data: dict, bot_obj) -> None: # Thay ContextTypes.DEFAULT_TYPE bằng bot_obj
    try:
        phien_moi = prediction_data.get("Phien_moi", "N/A")
        matches = prediction_data.get("matches", [])
        
        # Lấy kết quả thực tế và cập nhật thống kê
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
        
        # Cập nhật thống kê dự đoán
        # Chỉ cập nhật nếu có kết quả thực tế và kết quả dự đoán
        if ket_qua != "N/A" and du_doan_ket_qua != "N/A":
            prediction_stats["total_predictions"] += 1
            if (ket_qua == "TÀI" and du_doan_ket_qua == "Tài") or \
               (ket_qua == "XỈU" and du_doan_ket_qua == "Xỉu"):
                prediction_stats["correct_predictions"] += 1
            prediction_stats["last_actual_result"] = ket_qua
            prediction_stats["last_predicted_result"] = du_doan_ket_qua
        
        # Gửi tin nhắn
        await bot_obj.send_message(chat_id=chat_id, text=message_text)

    except Exception as e:
        logger.error(f"Lỗi khi gửi tin nhắn dự đoán cho chat_id {chat_id}: {e}")

# Hàm fetch và gửi dự đoán được sửa đổi để chạy định kỳ
async def fetch_and_send_prediction_task(context: CallbackContext) -> None:
    global last_api_phien_moi_processed
    
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
        current_phien_moi = data.get("Phien_moi")

        if current_phien_moi and current_phien_moi != last_api_phien_moi_processed:
            logger.info(f"Phát hiện phiên mới: {current_phien_moi}. Đang gửi dự đoán...")
            
            # Lấy danh sách người dùng cần gửi dự đoán
            users_to_predict_in_this_cycle = []
            for user_id, status in list(user_prediction_status.items()):
                if status: # Nếu người dùng đã bật dự đoán
                    # Kiểm tra gói kích hoạt
                    if user_id in user_active_packages:
                        key = user_active_packages[user_id]
                        if key in active_keys:
                            key_data = active_keys[key]
                            if key_data['expiry_date'] is None or key_data['expiry_date'] > datetime.datetime.now():
                                users_to_predict_in_this_cycle.append(user_id)
                            else:
                                # Gói hết hạn, tắt dự đoán và thông báo cho người dùng
                                user_prediction_status[user_id] = False
                                await context.bot.send_message(chat_id=user_id, text="⚠️ Gói của bạn đã hết hạn. Vui lòng kích hoạt lại để tiếp tục nhận dự đoán.")
                                del user_active_packages[user_id]
                                del active_keys[key]
                        else: # Key không tồn tại, có thể đã bị xóa admin
                            user_prediction_status[user_id] = False
                            await context.bot.send_message(chat_id=user_id, text="⚠️ Gói của bạn không còn hiệu lực. Vui lòng liên hệ Admin.")
                            del user_active_packages[user_id]
                    else: # Người dùng chưa có gói kích hoạt
                        user_prediction_status[user_id] = False
                        await context.bot.send_message(chat_id=user_id, text="⚠️ Vui lòng kích hoạt gói để sử dụng chức năng dự đoán. Dùng /key [mã].")
            
            for chat_id in users_to_predict_in_this_cycle:
                await send_prediction_message(chat_id, data, context.bot) # Sử dụng context.bot thay vì context.application
                await asyncio.sleep(0.1) # Thêm độ trễ nhỏ để tránh flood limit
            
            last_api_phien_moi_processed = current_phien_moi # Cập nhật phiên cuối cùng đã xử lý
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
    
    # Kiểm tra gói kích hoạt trước khi cho phép chạy dự đoán
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
    
    # Không cần gọi API ngay lập tức ở đây, vì fetch_and_send_prediction_task sẽ chạy định kỳ
    # và gửi dự đoán mới nhất khi có sẵn.
    # Tuy nhiên, nếu bạn muốn gửi dự đoán ngay lập tức khi người dùng bật, bạn có thể gọi:
    # await fetch_and_send_prediction_task(context)
    # Nhưng hãy cẩn thận với tần suất gọi API.

async def stop_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not user_prediction_status.get(user_id):
        await update.message.reply_text("Dự đoán chưa được bật.")
        return

    user_prediction_status[user_id] = False
    await update.message.reply_text("🛑 Đã dừng dự đoán.")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    
    await update.message.reply_text(
        "🛠️ Lệnh dành cho Admin:\n"
        "🔑 /taokey [giờ/ngày/tuần/tháng/năm/vĩnhviễn] [số lượng (nếu là giờ/ngày/tuần/tháng/năm)] - Tạo key kích hoạt.\n"
        "📊 /check - Kiểm tra số lần dự đoán đúng của bot.\n"
        "📢 /tbao [tin nhắn] - Gửi thông báo đến tất cả người dùng đã tương tác với bot.\n"
        # Thêm các lệnh admin khác ở đây
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

    new_key = str(uuid.uuid4()).replace('-', '')[:10].upper() # Tạo key ngẫu nhiên 10 ký tự
    expiry_date = None

    if duration_type == "giờ":
        expiry_date = datetime.datetime.now() + datetime.timedelta(hours=amount)
    elif duration_type == "ngày":
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=amount)
    elif duration_type == "tuần":
        expiry_date = datetime.datetime.now() + datetime.timedelta(weeks=amount)
    elif duration_type == "tháng":
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=amount * 30) # Ước tính 30 ngày/tháng
    elif duration_type == "năm":
        expiry_date = datetime.datetime.now() + datetime.timedelta(days=amount * 365) # Ước tính 365 ngày/năm
    # "vĩnhviễn" thì expiry_date vẫn là None

    active_keys[new_key] = {
        'expiry_date': expiry_date,
        'used_by': None # Chưa được sử dụng
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

    # Thu thập tất cả các chat_id đã tương tác với bot hoặc đang có gói kích hoạt
    all_chat_ids = set(user_prediction_status.keys())
    for user_id in user_active_packages:
        all_chat_ids.add(user_id)
    all_chat_ids.add(ADMIN_ID) # Đảm bảo admin cũng nhận được thông báo

    await update.message.reply_text("Đang gửi thông báo đến người dùng. Vui lòng đợi...")

    for chat_id in all_chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"📢 **THÔNG BÁO TỪ ADMIN** 📢\n\n{message_to_send}", parse_mode='Markdown')
            sent_count += 1
            await asyncio.sleep(0.1) # Tránh bị flood limit
        except Exception as e:
            logger.error(f"Không thể gửi tin nhắn đến chat_id {chat_id}: {e}")
            failed_count += 1
    
    await update.message.reply_text(f"Đã gửi tin nhắn đến {sent_count} người dùng. Thất bại: {failed_count}.")

# Webhook handler
@app.route(f"/{TOKEN}", methods=["POST"])
async def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "ok"

# Route cho Render để kiểm tra trạng thái
@app.route('/')
def index():
    return "Bot is running and listening for webhooks!"

def main() -> None:
    global application # Gán biến global
    
    # Xây dựng ứng dụng bot
    application = ApplicationBuilder().token(TOKEN).build()

    # Đăng ký các trình xử lý lệnh
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("key", activate_key))
    application.add_handler(CommandHandler("chaymodelbasic", chay_model_basic))
    application.add_handler(CommandHandler("stop", stop_prediction))
    application.add_handler(CommandHandler("admin", admin_command))
    
    # Các lệnh admin mới
    application.add_handler(CommandHandler("taokey", tao_key))
    application.add_handler(CommandHandler("check", check_stats))
    application.add_handler(CommandHandler("tbao", send_to_all))

    # Đặt webhook cho bot
    # Cần phải chạy này một lần khi triển khai hoặc khi thay đổi WEBHOOK_URL
    # Có thể đặt nó vào một hàm riêng và gọi thủ công hoặc trong logic khởi tạo
    async def set_my_webhook():
        if WEBHOOK_URL:
            logger.info(f"Setting webhook to: {WEBHOOK_URL}")
            await application.bot.set_webhook(url=WEBHOOK_URL)
        else:
            logger.warning("WEBHOOK_URL not set. Bot might not receive updates correctly.")
    
    # Chạy hàm set_my_webhook
    asyncio.run(set_my_webhook())

    # Schedule the periodic task to fetch predictions
    # interval=5 là 5 giây, có thể điều chỉnh
    application.job_queue.run_repeating(fetch_and_send_prediction_task, interval=5, first=1) 
    
    # Đây là nơi Flask sẽ chạy và nhận các webhook updates từ Telegram
    # Flask app sẽ chạy trên luồng chính, Telegram updates sẽ được xử lý bởi application.process_update
    # và các tác vụ định kỳ của job_queue sẽ chạy trong event loop của application.
    
    # Flask sẽ chạy trên cổng được Render cung cấp
    port = int(os.environ.get("PORT", 8080))
    
    # Khởi chạy Flask app
    # Gunicorn sẽ gọi app.run() thông qua WSGI
    # Đừng gọi app.run() trực tiếp khi dùng Gunicorn, Gunicorn sẽ tự lo
    logger.info(f"Flask app starting on port {port}")
    # Nếu chạy local để test: app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()

