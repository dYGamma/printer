import logging
import os
import uuid
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from bot.services import printer, scanner
import config

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def check_auth(update: Update):
    """Checks if the user is authorized."""
    user_id = update.effective_user.id
    # If ALLOWED_USERS is empty, allow all users
    if config.ALLOWED_USERS and user_id not in config.ALLOWED_USERS:
        logger.warning(f"Unauthorized access attempt from {user_id}")
        await update.message.reply_text("⛔ Доступ запрещен.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    await update.message.reply_text(
        "👋 Привет! Я бот для управления МФУ.\n\n"
        "🖨 **Печать**: Просто отправь мне файл (PDF, DOCX, Картинку).\n"
        "📠 **Сканирование**: Напиши /scan."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    message = update.message
    file_obj = None
    file_name = "unknown"

    if message.document:
        file_obj = await message.document.get_file()
        file_name = message.document.file_name
    elif message.photo:
        file_obj = await message.photo[-1].get_file()
        file_name = f"{file_obj.file_unique_id}.jpg"
    
    if not file_obj:
        return

    await message.reply_text(f"📥 Скачиваю файл: {file_name}...")
    
    local_path = os.path.join(config.TEMP_DIR, f"{uuid.uuid4()}_{file_name}")
    await file_obj.download_to_drive(local_path)

    await message.reply_text("🖨 Отправляю на печать...")
    
    success = await printer.print_file(local_path)
    
    if success:
        await message.reply_text("✅ Файл отправлен на печать.")
    else:
        await message.reply_text("❌ Ошибка при печати. Проверьте логи.")
    
    # Clean up
    # Wait a bit to ensure external process (os.startfile) has picked up the file
    await asyncio.sleep(10)
    try:
        if os.path.exists(local_path):
            os.remove(local_path)
    except Exception as e:
        logger.warning(f"Failed to remove temp file {local_path}: {e}")

async def handle_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    await update.message.reply_text("📠 Начинаю сканирование...")
    
    scan_filename = f"scan_{uuid.uuid4()}.jpg"
    scan_path = os.path.join(config.TEMP_DIR, scan_filename)

    success = await scanner.scan_document(scan_path)
    
    if success and os.path.exists(scan_path):
        await update.message.reply_text("📤 Загружаю скан...")
        with open(scan_path, 'rb') as f:
            await update.message.reply_document(document=f, filename=scan_filename)
        
        try:
            os.remove(scan_path)
        except Exception as e:
            logger.warning(f"Failed to remove temp file {scan_path}: {e}")
    else:
        await update.message.reply_text("❌ Ошибка сканирования. Проверьте устройство.")

def main():
    if not config.TOKEN or config.TOKEN == "YOUR_TOKEN_HERE":
        logger.error("Token not set in config.py or environment variables.")
        return

    application = ApplicationBuilder().token(config.TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    scan_handler = CommandHandler('scan', handle_scan)
    # Handle documents and photos
    doc_handler = MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document)

    application.add_handler(start_handler)
    application.add_handler(scan_handler)
    application.add_handler(doc_handler)

    logger.info("Bot started polling...")
    application.run_polling()

if __name__ == '__main__':
    main()
