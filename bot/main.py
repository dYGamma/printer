import logging
import os
import uuid
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from bot.services import printer, scanner, preview
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
        "Я покажу превью, и ты сможешь подтвердить печать или отредактировать параметры.\n"
        "📠 **Сканирование**: Напиши /scan.",
        parse_mode="Markdown"
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

    # Store file path in context for later use
    unique_id = str(uuid.uuid4())
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    context.user_data[f"file_{unique_id}"] = local_path
    context.user_data[f"filename_{unique_id}"] = file_name

    try:
        await message.reply_text("📷 Создаю превью...")
        
        # Create preview
        preview_bytes = await preview.create_preview(local_path)
        
        # Create inline keyboard with print options
        keyboard = [
            [
                InlineKeyboardButton("✅ Печать", callback_data=f"print_{unique_id}"),
                InlineKeyboardButton("⚙️ Параметры", callback_data=f"settings_{unique_id}")
            ],
            [
                InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{unique_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_photo(
            photo=preview_bytes,
            caption=f"📄 Превью: {file_name}\n\nВыберите действие:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Failed to create preview: {e}")
        await message.reply_text(
            f"⚠️ Не смог создать превью, но файл готов к печати.\n\n"
            f"Нажми /confirm_{unique_id} для печати."
        )

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


async def handle_print_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles print button click"""
    query = update.callback_query
    await query.answer()
    
    # Extract unique_id from callback data
    unique_id = query.data.split('_', 1)[1]
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    local_path = context.user_data.get(f"file_{unique_id}")
    file_name = context.user_data.get(f"filename_{unique_id}")
    settings = context.user_data.get(f"settings_{unique_id}", preview.get_default_settings())
    
    if not local_path or not os.path.exists(local_path):
        await query.edit_message_caption("❌ Файл не найден или удален.")
        return
    
    try:
        await query.edit_message_caption(f"🖨 Отправляю на печать: {file_name}...\n\nПараметры: {settings['orientation'].capitalize()} ориентация, {settings['scale']} масштаб")
        
        success = await printer.print_file(local_path, settings=settings)
        
        if success:
            await query.edit_message_caption(
                f"✅ Файл отправлен на печать!\n\n"
                f"📄 {file_name}"
            )
        else:
            await query.edit_message_caption(
                f"❌ Ошибка при печати.\n\n"
                f"Проверьте логи сервера."
            )
        
        # Schedule file cleanup
        async def cleanup_file(file_path, delay=15):
            await asyncio.sleep(delay)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.warning(f"Failed to remove temp file {file_path}: {e}")
        
        asyncio.create_task(cleanup_file(local_path))
        
    except Exception as e:
        logger.error(f"Error during print callback: {e}")
        await query.edit_message_caption(f"❌ Ошибка: {str(e)}")


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles settings button click - shows settings menu"""
    query = update.callback_query
    await query.answer()
    
    # Extract unique_id from callback data - handle both patterns
    data = query.data
    if data.startswith('settings_'):
        unique_id = data[9:]  # Remove 'settings_' prefix
    elif data.startswith('s_'):
        unique_id = data[2:]  # Remove 's_' prefix
    else:
        unique_id = data.split('_', 1)[1] if '_' in data else data
    
    logger.info(f"Settings callback received for unique_id: {unique_id}")
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    # Initialize settings if not present
    if f"settings_{unique_id}" not in context.user_data:
        context.user_data[f"settings_{unique_id}"] = preview.get_default_settings()
        logger.info(f"Initialized default settings for {unique_id}")
    
    settings = context.user_data[f"settings_{unique_id}"]
    logger.info(f"Current settings: {settings}")
    
    # Build settings text
    orientation_emoji = "📐"
    orientation_text = "Авто" if settings["orientation"] == "auto" else settings["orientation"].capitalize()
    
    scale_emoji = "🔍"
    scale_text = settings["scale"].capitalize()
    if settings["scale"] == "custom":
        scale_text = f"Custom ({settings['custom_scale']}%)"
    
    color_emoji = "🎨"
    color_map = {"color": "Цветная", "grayscale": "Серая шкала", "black_white": "ЧБ"}
    color_text = color_map.get(settings["color_mode"], "Цветная")
    
    settings_text = (
        "⚙️ **Параметры печати**\n\n"
        f"{orientation_emoji} Ориентация: {orientation_text}\n"
        f"{scale_emoji} Масштаб: {scale_text}\n"
        f"{color_emoji} Цвет: {color_text}\n"
        f"📍 Центрирование: {'Вкл' if settings['center'] else 'Выкл'}\n\n"
        "Нажми на параметр для изменения:"
    )
    
    keyboard = [
        [InlineKeyboardButton(f"📐 {orientation_text}", callback_data=f"orient_{unique_id}")],
        [InlineKeyboardButton(f"🔍 {scale_text}", callback_data=f"scale_{unique_id}")],
        [InlineKeyboardButton(f"🎨 {color_text}", callback_data=f"color_{unique_id}")],
        [InlineKeyboardButton(f"📍 {'✅' if settings['center'] else '❌'}", callback_data=f"center_{unique_id}")],
        [
            InlineKeyboardButton("✅ Печать", callback_data=f"print_{unique_id}"),
            InlineKeyboardButton("↩️ Назад", callback_data=f"back_{unique_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_caption(settings_text, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_orientation_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle orientation selection"""
    query = update.callback_query
    await query.answer()
    
    # Extract unique_id
    parts = query.data.split('_')
    unique_id = '_'.join(parts[1:])  # Get everything after 'orient'
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    if f"settings_{unique_id}" not in context.user_data:
        context.user_data[f"settings_{unique_id}"] = preview.get_default_settings()
    
    settings_text = "📐 **Выбери ориентацию:**"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Авто", callback_data=f"oauto_{unique_id}")],
        [InlineKeyboardButton("📏 Портрет", callback_data=f"oportrait_{unique_id}")],
        [InlineKeyboardButton("📐 Пейзаж", callback_data=f"olandscape_{unique_id}")],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"settings_{unique_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_caption(settings_text, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_scale_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle scale selection"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    unique_id = '_'.join(parts[1:])
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    if f"settings_{unique_id}" not in context.user_data:
        context.user_data[f"settings_{unique_id}"] = preview.get_default_settings()
    
    settings_text = "🔍 **Выбери масштаб:**\n\n💡 Рекомендация для фото: используй 'Заполнить' для максимального использования листа"
    
    keyboard = [
        [InlineKeyboardButton("📐 По размеру", callback_data=f"scfit_{unique_id}")],
        [InlineKeyboardButton("📄 Заполнить", callback_data=f"scfill_{unique_id}")],
        [InlineKeyboardButton("🔲 Растянуть", callback_data=f"scstretch_{unique_id}")],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"settings_{unique_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_caption(settings_text, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_color_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle color mode selection"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    unique_id = '_'.join(parts[1:])
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    if f"settings_{unique_id}" not in context.user_data:
        context.user_data[f"settings_{unique_id}"] = preview.get_default_settings()
    
    settings_text = "🎨 **Выбери режим цвета:**"
    
    keyboard = [
        [InlineKeyboardButton("🌈 Цветная", callback_data=f"ccol_{unique_id}")],
        [InlineKeyboardButton("⚫⚪ Серая", callback_data=f"cgray_{unique_id}")],
        [InlineKeyboardButton("⬛⬜ ЧБ", callback_data=f"cbw_{unique_id}")],
        [InlineKeyboardButton("↩️ Назад", callback_data=f"settings_{unique_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_caption(settings_text, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_setting_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles setting value changes"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    logger.info(f"Setting change received: {data}")
    
    # Parse the setting - format: Xvalue_uniqueid where X is first char
    if '_' not in data:
        await query.answer("❌ Ошибка: некорректный формат", show_alert=True)
        return
    
    # Find the split point - it's the last underscore before a UUID-like string
    parts = data.rsplit('_', 1)
    if len(parts) != 2:
        await query.answer("❌ Ошибка: не найден ID операции", show_alert=True)
        return
    
    prefix_value = parts[0]
    unique_id = parts[1]
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    if f"settings_{unique_id}" not in context.user_data:
        context.user_data[f"settings_{unique_id}"] = preview.get_default_settings()
    
    settings = context.user_data[f"settings_{unique_id}"]
    
    # Parse the setting type and value
    if prefix_value.startswith('o'):  # Orientation
        orient_value = prefix_value[1:]  # Get everything after 'o'
        if orient_value == 'auto':
            settings["orientation"] = 'auto'
        elif orient_value == 'portrait':
            settings["orientation"] = 'portrait'
        elif orient_value == 'landscape':
            settings["orientation"] = 'landscape'
    elif prefix_value.startswith('sc'):  # Scale
        scale_value = prefix_value[2:]  # Get everything after 'sc'
        if scale_value == 'fit':
            settings["scale"] = 'fit'
        elif scale_value == 'fill':
            settings["scale"] = 'fill'
        elif scale_value == 'stretch':
            settings["scale"] = 'stretch'
    elif prefix_value.startswith('c'):  # Color
        color_value = prefix_value[1:]  # Get everything after 'c'
        if color_value == 'col':
            settings["color_mode"] = 'color'
        elif color_value == 'gray':
            settings["color_mode"] = 'grayscale'
        elif color_value == 'bw':
            settings["color_mode"] = 'black_white'
    elif prefix_value == 'center':
        settings["center"] = not settings["center"]
    
    context.user_data[f"settings_{unique_id}"] = settings
    logger.info(f"Updated settings for {unique_id}: {settings}")
    
    # Go back to settings menu
    await handle_settings_callback(update, context)


async def handle_back_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Goes back to preview with current settings"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    unique_id = '_'.join(parts[1:])  # Remove 'back' prefix
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    file_name = context.user_data.get(f"filename_{unique_id}", "Документ")
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Печать", callback_data=f"print_{unique_id}"),
            InlineKeyboardButton("⚙️ Параметры", callback_data=f"settings_{unique_id}")
        ],
        [
            InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{unique_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_caption(
        f"📄 Превью: {file_name}\n\nВыберите действие:",
        reply_markup=reply_markup
    )



async def handle_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles cancel button click"""
    query = update.callback_query
    await query.answer()
    
    unique_id = query.data.split('_', 1)[1]
    
    if not hasattr(context, 'user_data'):
        context.user_data = {}
    
    local_path = context.user_data.get(f"file_{unique_id}")
    
    # Clean up immediately
    if local_path and os.path.exists(local_path):
        try:
            os.remove(local_path)
        except Exception as e:
            logger.warning(f"Failed to remove temp file {local_path}: {e}")
    
    # Clean up context
    if f"file_{unique_id}" in context.user_data:
        del context.user_data[f"file_{unique_id}"]
    if f"filename_{unique_id}" in context.user_data:
        del context.user_data[f"filename_{unique_id}"]
    
    await query.edit_message_caption("❌ Печать отменена.")


def main():
    if not config.TOKEN or config.TOKEN == "YOUR_TOKEN_HERE":
        logger.error("Token not set in config.py or environment variables.")
        return

    application = ApplicationBuilder().token(config.TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    scan_handler = CommandHandler('scan', handle_scan)
    # Handle documents and photos
    doc_handler = MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document)
    
    # Handle callback buttons
    print_callback = CallbackQueryHandler(handle_print_callback, pattern=r'^print_')
    settings_callback = CallbackQueryHandler(handle_settings_callback, pattern=r'^settings_')
    orient_callback = CallbackQueryHandler(handle_orientation_edit, pattern=r'^orient_')
    scale_callback = CallbackQueryHandler(handle_scale_edit, pattern=r'^scale_')
    color_callback = CallbackQueryHandler(handle_color_edit, pattern=r'^color_')
    value_callback = CallbackQueryHandler(handle_setting_change, pattern=r'^[osc]')
    back_callback = CallbackQueryHandler(handle_back_preview, pattern=r'^back_')
    cancel_callback = CallbackQueryHandler(handle_cancel_callback, pattern=r'^cancel_')

    application.add_handler(start_handler)
    application.add_handler(scan_handler)
    application.add_handler(doc_handler)
    application.add_handler(print_callback)
    application.add_handler(settings_callback)
    application.add_handler(orient_callback)
    application.add_handler(scale_callback)
    application.add_handler(color_callback)
    application.add_handler(back_callback)
    application.add_handler(value_callback)
    application.add_handler(cancel_callback)

    logger.info("Bot started polling...")
    application.run_polling()

if __name__ == '__main__':
    main()
