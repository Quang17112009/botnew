import logging
import requests
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ApplicationBuilder,
)
from flask import Flask, request
from threading import Thread
import json
import time
import datetime
import uuid # Để tạo key ngẫu nhiên

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Cấu hình bot
TOKEN = "8137068939:AAG19xO92yXsz_d9vz_m2aJW2Wh8JZnvSPQ"
ADMIN_ID = 6915752059  # ID Telegram của admin
API_URL = "https://apiluck2.onrender.com/predict"

# Dictionary để lưu trạng thái chạy dự đoán của từng người dùng
user_prediction_status = {}
# Dictionary để lưu ID tin nhắn cuối cùng đã gửi để cập nhật
last_prediction_message_id = {}
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

# Flask app cho webhook và keep_alive
app = Flask(__name__)

# Hàm giữ cho bot luôn hoạt động trên Render
@app.route('/')
def keep_alive():
    return "Bot is running!"

# Định nghĩa các hàm xử lý lệnh
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

async def send_prediction_message(chat_id: int, prediction_data: dict, context: Application) -> None:
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
        
        # Gửi tin nhắn và lưu message_id
        message = await context.bot.send_message(chat_id=chat_id, text=message_text)
        last_prediction_message_id[chat_id] = message.message_id

    except Exception as e:
        logger.error(f"Lỗi khi gửi tin nhắn dự đoán cho chat_id {chat_id}: {e}")

async def fetch_and_send_prediction(context: Application) -> None:
    last_processed_phien_moi = {} # Lưu phiên mới nhất đã xử lý cho từng chat_id
    
    while True:
        await asyncio.sleep(5)  # Đợi 5 giây trước khi fetch lại
        
        # Lấy danh sách người dùng cần gửi dự đoán
        users_to_predict = []
        for user_id, status in list(user_prediction_status.items()):
            if status: # Nếu người dùng đã bật dự đoán
                # Kiểm tra gói kích hoạt
                if user_id in user_active_packages:
                    key = user_active_packages[user_id]
                    if key in active_keys:
                        key_data = active_keys[key]
                        if key_data['expiry_date'] is None or key_data['expiry_date'] > datetime.datetime.now():
                            users_to_predict.append(user_id)
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


        if not users_to_predict: # Nếu không có ai cần gửi dự đoán, ngủ lâu hơn
            await asyncio.sleep(10)
            continue
            
        try:
            response = requests.get(API_URL)
            response.raise_for_status()
            data = response.json()
            current_phien_moi = data.get("Phien_moi")

            for chat_id in users_to_predict:
                # Chỉ gửi nếu phiên mới khác với phiên cuối cùng đã xử lý cho chat_id này
                if chat_id not in last_processed_phien_moi or last_processed_phien_moi[chat_id] != current_phien_moi:
                    await send_prediction_message(chat_id, data, context)
                    last_processed_phien_moi[chat_id] = current_phien_moi
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Lỗi khi gọi API: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Lỗi phân tích JSON từ API: {e}")
        except Exception as e:
            logger.error(f"Lỗi không xác định trong fetch_and_send_prediction: {e}")

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
    
    # Lần đầu chạy, gửi dự đoán ngay lập tức
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
        await send_prediction_message(user_id, data, context.application)
        
    except Exception as e:
        logger.error(f"Lỗi ban đầu khi chạy dự đoán cho người dùng {user_id}: {e}")
        await update.message.reply_text("Có lỗi xảy ra khi lấy dự đoán. Vui lòng thử lại sau.")

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


def main() -> None:
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

    # Khởi tạo một task chạy nền để fetch và gửi dự đoán
    application.create_task(fetch_and_send_prediction(application))

    # Khởi chạy bot trong một luồng riêng
    bot_thread = Thread(target=lambda: asyncio.run(application.run_polling()))
    bot_thread.start()
    
    # Khởi chạy Flask app
    app.run(host="0.0.0.0", port=8080) 

if __name__ == "__main__":
    main()

