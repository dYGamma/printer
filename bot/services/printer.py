import os
import sys
import logging
import asyncio
import subprocess
import ctypes
from ctypes import Structure, POINTER, c_int, c_char_p, c_wchar_p, c_void_p
from PIL import Image
try:
    from PIL import ImageWin
except Exception:
    ImageWin = None

logger = logging.getLogger(__name__)

# Try to import win32 modules, but provide mocks for Linux/Development
try:
    if sys.platform == 'win32':
        import win32com.client
        import win32api
        import win32print
    else:
        raise ImportError("Not on Windows")
except ImportError:
    win32com = None
    win32api = None
    win32print = None
    logger.warning("Windows libraries not found. Printing will be simulated if not on Windows.")

async def print_file(filepath: str):
    """
    Determines the file type and sends it to the printer.
    """
    abs_path = os.path.abspath(filepath)
    ext = os.path.splitext(filepath)[1].lower()

    if sys.platform != 'win32':
        logger.info(f"[MOCK] Printing file: {abs_path}")
        return True

    try:
        if ext in ['.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt']:
            return await _print_office_document(abs_path, ext)
        elif ext in ['.jpg', '.jpeg', '.png']:
            return await _print_image_win32(abs_path)
        elif ext in ['.pdf', '.txt']:
            return await _print_shell_execute(abs_path)
        else:
            logger.error(f"Unsupported file format: {ext}")
            return False
    except Exception as e:
        logger.error(f"Failed to print {filepath}: {e}")
        return False

async def _print_shell_execute(filepath):
    """
    Prints files silently without dialogs using PowerShell and Windows Print Spooler.
    Uses PrintUI.exe for reliable silent printing without confirmation dialogs.
    """
    logger.info(f"Auto-printing file: {filepath}")
    
    if sys.platform != 'win32':
        logger.info(f"[MOCK] Printing file: {filepath}")
        return True
    
    try:
        # Use PowerShell to invoke PrintUI.exe which is more reliable for silent printing
        # PrintUI.exe /pt /dl /in /n:"PrinterName" "FileName"
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _print_via_powershell, filepath)
        return result
            
    except Exception as e:
        logger.error(f"Printing with PowerShell failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return await _print_fallback(filepath)


async def _print_fallback(filepath):
    """
    Fallback printing method using os.startfile.
    """
    try:
        logger.info(f"Using fallback print method for: {filepath}")
        os.startfile(filepath, "print")
        await asyncio.sleep(2)
        return True
    except Exception as e:
        logger.error(f"Fallback printing failed: {e}")
        return False


def _print_via_powershell(filepath):
    """
    Synchronous function to print via PowerShell using Start-Process with hidden window.
    This method is more reliable for silent printing without dialogs.
    """
    try:
        import subprocess
        
        # Use PowerShell to start print process with hidden window
        # This prevents any UI from appearing
        ps_command = f'''
        $filepath = '{filepath.replace("'", "''")}'
        Start-Process -FilePath "$filepath" -Verb Print -WindowStyle Hidden -PassThru -Wait
        '''
        
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True,
            timeout=30,
            check=False
        )
        
        if result.returncode == 0:
            logger.info(f"Print job submitted via PowerShell successfully")
            return True
        else:
            logger.warning(f"PowerShell print returned: {result.returncode}")
            logger.warning(f"Error output: {result.stderr.decode()}")
            return False
            
    except Exception as e:
        logger.error(f"PowerShell printing failed: {e}")
        return False



async def _print_image_win32(filepath: str):
    """
    Print an image (JPG/PNG) silently without dialogs.
    Tries multiple methods: win32 GDI, PowerShell, and fallback.
    """
    logger.info(f"Printing image: {filepath}")

    if sys.platform != 'win32':
        logger.info(f"[MOCK] Printing image: {filepath}")
        return True

    # First try PowerShell method as it's more reliable
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _print_via_powershell, filepath)
        if result:
            await asyncio.sleep(0.5)
            return True
    except Exception as e:
        logger.warning(f"PowerShell image printing failed, trying win32 method: {e}")

    # If PowerShell fails, try win32 GDI method
    if win32print is None:
        logger.error("pywin32 is not available, falling back to default print")
        return await _print_fallback(filepath)

    try:
        # Lazy import win32ui to avoid import errors on non-Windows
        import win32ui
        import win32con

        # Open image with PIL
        img = Image.open(filepath)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        printer_name = win32print.GetDefaultPrinter()
        logger.info(f"Default printer for image: {printer_name}")

        hDC = win32ui.CreateDC()
        hDC.CreatePrinterDC(printer_name)

        # Start doc and page
        hDC.StartDoc(filepath)
        hDC.StartPage()

        # Get printable area
        horzres = hDC.GetDeviceCaps(win32con.HORZRES)
        vertres = hDC.GetDeviceCaps(win32con.VERTRES)

        # Create DIB and draw scaled to printable area
        if ImageWin is None:
            # ImageWin not available; fallback
            logger.warning("ImageWin not available; falling back")
            hDC.EndPage()
            hDC.EndDoc()
            hDC.DeleteDC()
            return await _print_fallback(filepath)

        dib = ImageWin.Dib(img)
        # Destination rectangle
        dest = (0, 0, horzres, vertres)
        dib.draw(hDC.GetHandleOutput(), dest)

        hDC.EndPage()
        hDC.EndDoc()
        hDC.DeleteDC()

        logger.info("Image print job submitted via win32 GDI")
        await asyncio.sleep(0.5)
        return True
    except Exception as e:
        logger.error(f"Silent image printing failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return await _print_fallback(filepath)

async def _print_office_document(filepath, ext):
    """
    Prints Office documents using COM automation.
    """
    logger.info(f"Printing Office doc: {filepath}")
    try:
        # We run this in a thread executor because COM calls are blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _print_office_sync, filepath, ext)
        return True
    except Exception as e:
        logger.error(f"Office print failed: {e}")
        return False

def _print_office_sync(filepath, ext):
    """
    Synchronous COM calls.
    """
    pythoncom_imported = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        pythoncom_imported = True
    except ImportError:
        pass

    try:
        if ext in ['.docx', '.doc']:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(filepath)
            doc.PrintOut()
            doc.Close(False)
            word.Quit()
        elif ext in ['.xlsx', '.xls']:
            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = False
            wb = excel.Workbooks.Open(filepath)
            wb.PrintOut()
            wb.Close(False)
            excel.Quit()
        elif ext in ['.pptx', '.ppt']:
            ppt = win32com.client.Dispatch("PowerPoint.Application")
            # PowerPoint requires visibility to print usually
            ppt.Visible = True 
            presentation = ppt.Presentations.Open(filepath, WithWindow=False)
            # PrintInBackground=False ensures we wait for the job to spool
            presentation.PrintOptions.PrintInBackground = False
            presentation.PrintOut()
            presentation.Close()
            ppt.Quit()
    finally:
        if pythoncom_imported:
            import pythoncom
            pythoncom.CoUninitialize()
