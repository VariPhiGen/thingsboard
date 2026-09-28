import os
import json
import logging
import time
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PORT = int(os.getenv("PORT", 5051))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [Telegram] %(levelname)s - %(message)s')

# Cache for deduplication: (device_name, alarm_type) -> (status, timestamp)
LAST_SENT_CACHE = {}
DEDUP_COOLDOWN_SECONDS = 600  # 10 minutes cooldown for active duplicate alarms

def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. Cannot send notification.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    chat_ids = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(',') if cid.strip()]
    all_success = True
    
    for chat_id in chat_ids:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logging.info(f"Alarm notification sent successfully to {chat_id}")
        except requests.exceptions.RequestException as e:
            safe_error = str(e).replace(TELEGRAM_BOT_TOKEN, "HIDDEN_TOKEN")
            logging.error(f"Failed to send notification to {chat_id}: {safe_error}")
            all_success = False
            
    return all_success

def clean_sensor_value(val):
    if val is None:
        return "N/A"
    try:
        num = float(str(val).replace('°C', '').replace('RPM', '').replace('kPa', '').strip())
        if num == 32767 or num >= 30000:
            return "Sensor Fault / Disconnected (32767)"
    except Exception:
        pass
    return str(val)

def format_alarm_message(alarm_data: dict, action: str) -> str:
    alarm_type = alarm_data.get("type", "Unknown Alarm")
    severity = alarm_data.get("severity", "UNKNOWN")
    status = alarm_data.get("status", "UNKNOWN")
    
    device_name = alarm_data.get("originatorName") or alarm_data.get("name") or alarm_data.get("deviceName") or "Unknown Device"
    orig = alarm_data.get("originator")
    if isinstance(orig, dict):
        device_name = orig.get("name") or device_name

    details = alarm_data.get("details")
    
    status_mapping = {
        "ACTIVE_UNACK": "Active (Unacknowledged)",
        "ACTIVE_ACK": "Active (Acknowledged)",
        "CLEARED_UNACK": "Cleared (Unacknowledged)",
        "CLEARED_ACK": "Cleared (Acknowledged)"
    }
    display_status = status_mapping.get(status, status)
    
    # Header Emoji
    if action == "CLEARED" or "CLEARED" in status:
        msg = f"✅ <b>ALARM CLEARED: {alarm_type.upper()}</b>\n\n"
    elif severity in ["CRITICAL", "HIGH"]:
        msg = f"🚨 <b>CRITICAL ALARM: {alarm_type.upper()}</b>\n\n"
    else:
        msg = f"⚠️ <b>ALARM ALERT: {alarm_type.upper()}</b>\n\n"
        
    msg += f"<b>Device:</b> {device_name}\n"
    msg += f"<b>Alarm Type:</b> {alarm_type}\n"
    msg += f"<b>Severity:</b> {severity}\n"
    msg += f"<b>Status:</b> {display_status}\n"
    
    # Render Details if present
    if details:
        if isinstance(details, dict):
            detail_msg = details.get("message") or details.get("description") or details.get("summary")
            if detail_msg:
                # Sanitize 32767 in text
                detail_msg = str(detail_msg).replace("32767", "Sensor Fault (32767)")
                msg += f"<b>Details:</b> {detail_msg}\n"
            if "recommendation" in details:
                msg += f"<b>Action:</b> {details['recommendation']}\n"
            # Render key values if present
            for k, v in details.items():
                if k not in ["message", "description", "summary", "recommendation", "ai_mode"]:
                    msg += f"<b>{k.replace('_', ' ').title()}:</b> {clean_sensor_value(v)}\n"
        elif isinstance(details, str) and details.strip():
            clean_dt = details.replace("32767", "Sensor Fault (32767)").strip()
            msg += f"<b>Details:</b> {clean_dt}\n"
            
    return msg

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(post_data.decode('utf-8'))
            alarm_data = payload
            
            status = alarm_data.get("status", "")
            if status in ["CLEARED_UNACK", "CLEARED_ACK"]:
                action = "CLEARED"
            else:
                action = "CREATED"
            
            alarm_type = alarm_data.get("type", "Unknown")
            device_name = alarm_data.get("originatorName") or alarm_data.get("name") or "Unknown Device"
            orig = alarm_data.get("originator")
            if isinstance(orig, dict):
                device_name = orig.get("name") or device_name

            # Check Deduplication Cache
            cache_key = (device_name, alarm_type)
            now = time.time()
            if cache_key in LAST_SENT_CACHE:
                last_status, last_time = LAST_SENT_CACHE[cache_key]
                # If same status and within cooldown window, suppress duplicate spam
                if last_status == action and (now - last_time) < DEDUP_COOLDOWN_SECONDS:
                    logging.info(f"Skipping duplicate alarm notification for '{device_name}' - '{alarm_type}' ({action})")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"DEDUPLICATED")
                    return

            message = format_alarm_message(alarm_data, action)
            sent = send_telegram_message(message)
            if sent:
                LAST_SENT_CACHE[cache_key] = (action, now)
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except json.JSONDecodeError:
            logging.error("Received invalid JSON")
            self.send_response(400)
            self.end_headers()
        except Exception as e:
            logging.error(f"Error processing request: {e}")
            self.send_response(500)
            self.end_headers()

def run_server(port=5051):
    server_address = ('', port)
    httpd = HTTPServer(server_address, WebhookHandler)
    logging.info(f"Starting Telegram notification service on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info("Stopping Telegram notification service.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        logging.info("Running Telegram integration test...")
        success = send_telegram_message("✅ ThingsBoard Telegram integration test successful")
        if success:
            logging.info("Test message sent successfully.")
        else:
            logging.error("Failed to send test message.")
    else:
        run_server(PORT)
