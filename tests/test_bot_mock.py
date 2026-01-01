import os
import sys
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the bot package can be imported
sys.path.append(os.getcwd())

from bot.main import handle_document, handle_scan
import config

# Set dummy config values
config.ALLOWED_USERS = [12345]
config.TEMP_DIR = os.path.join(os.getcwd(), "tests/temp_test")
os.makedirs(config.TEMP_DIR, exist_ok=True)

@pytest.mark.asyncio
async def test_handle_scan_authorized():
    # Mock update and context
    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    context = MagicMock()

    # Call the handler
    await handle_scan(update, context)

    # Verify interaction
    assert update.message.reply_text.called
    # In mock mode (Linux), scan_document writes a dummy file and returns True
    assert update.message.reply_document.called

@pytest.mark.asyncio
async def test_handle_scan_unauthorized():
    update = MagicMock()
    update.effective_user.id = 99999
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await handle_scan(update, context)

    update.message.reply_text.assert_called_with("⛔ Доступ запрещен.")

@pytest.mark.asyncio
async def test_handle_document_authorized():
    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    
    # Mock document object
    doc_mock = MagicMock()
    doc_mock.file_name = "test_doc.docx"
    doc_mock.get_file = AsyncMock(return_value=MagicMock(download_to_drive=AsyncMock()))
    update.message.document = doc_mock
    update.message.photo = []
    
    context = MagicMock()

    with patch('bot.services.printer.print_file', new_callable=AsyncMock) as mock_print:
        mock_print.return_value = True
        await handle_document(update, context)
        
        # Verify print was called
        mock_print.assert_called_once()
        assert update.message.reply_text.called
