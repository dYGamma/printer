import os
import sys
import logging
import asyncio

logger = logging.getLogger(__name__)

# WIA Constants
WIA_DEVICE_TYPE_SCANNER = 1
WIA_COMMAND_TAKE_PICTURE = "{AF933CAC-ACAD-11D2-A093-00C04F72DC3C}"
WIA_FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"

async def scan_document(output_path: str):
    """
    Scans a document from the first available scanner and saves it to output_path.
    """
    if sys.platform != 'win32':
        logger.info(f"[MOCK] Scanning document to: {output_path}")
        # Create a dummy file for testing
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (100, 100), color = 'white')
        d = ImageDraw.Draw(img)
        d.text((10,10), "Scanned Doc", fill=(0,0,0))
        img.save(output_path)
        return True

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _scan_sync, output_path)
        return True
    except Exception as e:
        logger.error(f"Scanning failed: {e}")
        return False

def _scan_sync(output_path):
    pythoncom_imported = False
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        pythoncom_imported = True
    except ImportError:
        # Should have been caught earlier if we are on Windows
        raise Exception("win32com not available")

    try:
        device_manager = win32com.client.Dispatch("WIA.DeviceManager")
        
        # Find the first scanner
        scanner_device_info = None
        for i in range(1, device_manager.DeviceInfos.Count + 1):
            if device_manager.DeviceInfos(i).Type == WIA_DEVICE_TYPE_SCANNER:
                scanner_device_info = device_manager.DeviceInfos(i)
                break
        
        if not scanner_device_info:
            raise Exception("No scanner found.")

        # Connect to the device
        device = scanner_device_info.Connect()
        
        # Select the Item (the flatbed or feeder)
        # Usually Item(1) is the flatbed/feeder root
        item = device.Items(1)
        
        # Transfer the image (scan)
        # Transfer() returns an ImageFile object
        image_file = item.Transfer(WIA_FORMAT_JPEG)
        
        # Save process
        # Ideally we should check if file exists and remove it, WIA might fail if exists
        if os.path.exists(output_path):
            os.remove(output_path)
            
        image_file.SaveFile(output_path)
        
    finally:
        if pythoncom_imported:
            import pythoncom
            pythoncom.CoUninitialize()
