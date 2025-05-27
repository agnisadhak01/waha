import os
import logging
from datetime import datetime
from pathlib import Path
from pprint import pprint

import requests
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('whatsapp_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
DOWNLOADS_DIR = Path("downloads")
WAHA_BASE_URL = "http://localhost:3000/api"
SESSION_NAME = "default"

# Create downloads directory if it doesn't exist
DOWNLOADS_DIR.mkdir(exist_ok=True)

def send_message(chat_id, text):
    """
    Send message to chat_id.
    :param chat_id: Phone number + "@c.us" suffix - 1231231231@c.us
    :param text: Message for the recipient
    """
    try:
        response = requests.post(
            f"{WAHA_BASE_URL}/sendText",
            json={
                "chatId": chat_id,
                "text": text,
                "session": SESSION_NAME,
            },
        )
        response.raise_for_status()
        logger.info(f"Message sent to {chat_id}: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return False

def send_seen(chat_id, message_id, participant):
    """Mark message as seen"""
    try:
        response = requests.post(
            f"{WAHA_BASE_URL}/sendSeen",
            json={
                "session": SESSION_NAME,
                "chatId": chat_id,
                "messageId": message_id,
                "participant": participant,
            },
        )
        response.raise_for_status()
        logger.info(f"Marked message {message_id} as seen")
        return True
    except Exception as e:
        logger.error(f"Failed to mark message as seen: {e}")
        return False

def get_file_extension(content_type, filename):
    """Get appropriate file extension based on content type or filename"""
    ext_map = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'video/mp4': '.mp4',
        'video/quicktime': '.mov',
        'audio/mpeg': '.mp3',
        'audio/ogg': '.ogg',
        'application/pdf': '.pdf',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    }
    
    # Try to get extension from content type
    if content_type in ext_map:
        return ext_map[content_type]
    
    # Try to get extension from filename
    if filename and '.' in filename:
        return '.' + filename.split('.')[-1].lower()
    
    # Default extension
    return '.bin'

def download_file(media_url, chat_id, message_id):
    """
    Download file from media URL and save it with organized naming
    :param media_url: URL to download the file from
    :param chat_id: Chat ID for organization
    :param message_id: Message ID for unique naming
    :return: tuple (success: bool, file_path: str, error_message: str)
    """
    try:
        # Make request to download file
        response = requests.get(media_url, timeout=30)
        response.raise_for_status()
        
        # Get content type and original filename from URL
        content_type = response.headers.get('content-type', 'application/octet-stream')
        original_filename = media_url.split("/")[-1].split("?")[0]  # Remove query params
        
        # Create organized directory structure
        date_str = datetime.now().strftime("%Y-%m-%d")
        sender_dir = DOWNLOADS_DIR / date_str / chat_id.replace("@c.us", "")
        sender_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp and message ID
        timestamp = datetime.now().strftime("%H%M%S")
        extension = get_file_extension(content_type, original_filename)
        filename = f"{timestamp}_{message_id.split('_')[-1][:8]}{extension}"
        
        file_path = sender_dir / filename
        
        # Save file
        with open(file_path, "wb") as f:
            f.write(response.content)
        
        # Log file info
        file_size = len(response.content)
        logger.info(f"Downloaded file: {file_path} ({file_size} bytes, {content_type})")
        
        return True, str(file_path.absolute()), None
        
    except requests.RequestException as e:
        error_msg = f"Failed to download file from {media_url}: {e}"
        logger.error(error_msg)
        return False, "", error_msg
    except Exception as e:
        error_msg = f"Unexpected error downloading file: {e}"
        logger.error(error_msg)
        return False, "", error_msg

@app.route("/")
def health_check():
    return jsonify({
        "status": "running",
        "bot_name": "Enhanced WhatsApp Download Files Bot",
        "downloads_directory": str(DOWNLOADS_DIR.absolute()),
        "timestamp": datetime.now().isoformat()
    })

@app.route("/stats")
def get_stats():
    """Get download statistics"""
    try:
        total_files = sum(1 for f in DOWNLOADS_DIR.rglob("*") if f.is_file() and f.name != "whatsapp_bot.log")
        total_size = sum(f.stat().st_size for f in DOWNLOADS_DIR.rglob("*") if f.is_file() and f.name != "whatsapp_bot.log")
        
        return jsonify({
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024*1024), 2),
            "downloads_directory": str(DOWNLOADS_DIR.absolute())
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/bot", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        return jsonify({
            "status": "ready",
            "message": "Enhanced WhatsApp Download Files Bot is ready!",
            "endpoints": {
                "health": "/",
                "stats": "/stats",
                "webhook": "/bot"
            }
        })

    try:
        data = request.get_json()
        logger.info(f"Received webhook data: {data.get('event', 'unknown_event')}")
        
        if data["event"] != "message":
            logger.info(f"Ignoring event: {data['event']}")
            return jsonify({"status": "ignored", "reason": f"Event {data['event']} not supported"})

        payload = data["payload"]
        
        # Ignore messages without files
        if not payload.get("mediaUrl"):
            logger.info("Message has no media, ignoring")
            return jsonify({"status": "ignored", "reason": "No media in message"})

        # Extract message details
        chat_id = payload["from"]
        message_id = payload['id']
        participant = payload.get('participant')
        media_url = payload["mediaUrl"]
        
        logger.info(f"Processing media message from {chat_id}, message ID: {message_id}")
        
        # Send seen receipt
        send_seen(chat_id=chat_id, message_id=message_id, participant=participant)
        
        # Download the file
        success, file_path, error_msg = download_file(media_url, chat_id, message_id)
        
        if success:
            # Send success message
            file_size = os.path.getsize(file_path)
            text = f"✅ File downloaded successfully!\n📁 Path: {file_path}\n📊 Size: {file_size} bytes\n🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_message(chat_id=chat_id, text=text)
            
            return jsonify({
                "status": "success",
                "file_path": file_path,
                "file_size": file_size,
                "message": "File downloaded successfully"
            })
        else:
            # Send error message
            error_text = f"❌ Failed to download file: {error_msg}"
            send_message(chat_id=chat_id, text=error_text)
            
            return jsonify({
                "status": "error",
                "error": error_msg
            }), 500
            
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({
            "status": "error",
            "error": f"Internal server error: {str(e)}"
        }), 500

if __name__ == "__main__":
    logger.info("Starting Enhanced WhatsApp Download Files Bot...")
    logger.info(f"Downloads directory: {DOWNLOADS_DIR.absolute()}")
    app.run(host="0.0.0.0", port=5000, debug=True) 