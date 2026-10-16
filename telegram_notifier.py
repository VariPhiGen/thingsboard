import os
import json
import logging
import ipaddress
import threading
import time
import requests
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from the .env next to this script (works whatever the working directory)
load_dotenv(Path(__file__).resolve().with_name(".env"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PORT = int(os.getenv("TELEGRAM_NOTIFIER_PORT") or os.getenv("PORT", 5051))
# Alarms of devices named '[TEST] ...' go only to TELEGRAM_TEST_CHAT_ID (or the log), never to the real chats
TEST_DEVICE_PREFIX = "[TEST]"
TELEGRAM_TEST_CHAT_ID = os.getenv("TELEGRAM_TEST_CHAT_ID", "").strip()
# The rule chain calls this service from a Docker network; nothing outside private networks may post alarms
ALLOWED_NETWORKS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [Telegram] %(levelname)s - %(message)s')

# Cache for deduplication: (device_name, alarm_type) -> (status, timestamp)
LAST_SENT_CACHE = {}
CACHE_LOCK = threading.Lock()
DEDUP_COOLDOWN_SECONDS = 600  # 10 minutes cooldown for active duplicate alarms

def send_telegram_message(message: str, chat_ids=None) -> bool:
    if not TELEGRAM_BOT_TOKEN or not (chat_ids or TELEGRAM_CHAT_ID):
        logging.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. Cannot send notification.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    chat_ids = chat_ids or [cid.strip() for cid in TELEGRAM_CHAT_ID.split(',') if cid.strip()]
    all_success = True

    for chat_id in chat_ids:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        for attempt in range(3):
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 429:  # rate limited: wait as long as Telegram asks
                    wait = response.json().get("parameters", {}).get("retry_after", 5)
                    time.sleep(min(int(wait), 30))
                    continue
                if not response.ok:
                    logging.error(f"Telegram rejected the message to {chat_id}: {response.status_code} {response.text[:300]}")
                    all_success = False
                    break
                logging.info(f"Alarm notification sent successfully to {chat_id}")
                break
            except requests.exceptions.RequestException as e:
                safe_error = str(e).replace(TELEGRAM_BOT_TOKEN, "HIDDEN_TOKEN")
                logging.error(f"Failed to send notification to {chat_id} (attempt {attempt + 1}): {safe_error}")
                time.sleep(2 * (attempt + 1))
        else:
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
    
    # Every value from the alarm is escaped: Telegram rejects HTML messages with a bare '<' (e.g. "RPM <= 100")
    # Header Emoji
    if action == "CLEARED" or "CLEARED" in status:
        msg = f"✅ <b>ALARM CLEARED: {escape(alarm_type.upper())}</b>\n\n"
    elif severity in ["CRITICAL", "HIGH"]:
        msg = f"🚨 <b>CRITICAL ALARM: {escape(alarm_type.upper())}</b>\n\n"
    else:
        msg = f"⚠️ <b>ALARM ALERT: {escape(alarm_type.upper())}</b>\n\n"

    msg += f"<b>Device:</b> {escape(str(device_name))}\n"
    msg += f"<b>Alarm Type:</b> {escape(alarm_type)}\n"
    msg += f"<b>Severity:</b> {escape(str(severity))}\n"
    msg += f"<b>Status:</b> {escape(str(display_status))}\n"
    start_ts = alarm_data.get("startTs") or alarm_data.get("createdTime")
    if start_ts:
        msg += f"<b>Time:</b> {time.strftime('%d %b %Y %H:%M:%S', time.gmtime(start_ts / 1000 + 19800))} IST\n"

    # Render Details if present
    if details:
        if isinstance(details, dict):
            detail_msg = details.get("message") or details.get("description") or details.get("summary")
            if detail_msg:
                # Sanitize 32767 in text
                detail_msg = str(detail_msg).replace("32767", "Sensor Fault (32767)")
                msg += f"<b>Details:</b> {escape(detail_msg)}\n"
            if "recommendation" in details:
                msg += f"<b>Action:</b> {escape(str(details['recommendation']))}\n"
            # Render key values if present
            for k, v in details.items():
                if k not in ["message", "description", "summary", "recommendation", "ai_mode"]:
                    msg += f"<b>{escape(k.replace('_', ' ').title())}:</b> {escape(clean_sensor_value(v))}\n"
        elif isinstance(details, str) and details.strip():
            clean_dt = details.replace("32767", "Sensor Fault (32767)").strip()
            msg += f"<b>Details:</b> {escape(clean_dt)}\n"

    return msg

class WebhookHandler(BaseHTTPRequestHandler):
    def _allowed(self):
        try:
            client = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        if any(client in net for net in ALLOWED_NETWORKS):
            return True
        logging.warning(f"Rejected request from non-private address {client}")
        self.send_response(403)
        self.end_headers()
        return False

    def do_GET(self):
        if not self._allowed():
            return
        if self.path.rstrip("/") == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if not self._allowed():
            return
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
            # Requests are handled in parallel: check and reserve the cache entry atomically
            with CACHE_LOCK:
                previous = LAST_SENT_CACHE.get(cache_key)
                # If same status and within cooldown window, suppress duplicate spam
                duplicate = previous and previous[0] == action and (now - previous[1]) < DEDUP_COOLDOWN_SECONDS
                if not duplicate:
                    LAST_SENT_CACHE[cache_key] = (action, now)
            if duplicate:
                logging.info(f"Skipping duplicate alarm notification for '{device_name}' - '{alarm_type}' ({action})")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"DEDUPLICATED")
                return

            message = format_alarm_message(alarm_data, action)
            if str(device_name).startswith(TEST_DEVICE_PREFIX):
                # Test devices never reach the real recipients: only the test chat, or the log
                if TELEGRAM_TEST_CHAT_ID:
                    sent = send_telegram_message("🧪 TEST\n" + message, [TELEGRAM_TEST_CHAT_ID])
                else:
                    logging.info(f"Test alarm, not sent:\n{message}")
                    sent = True
            else:
                sent = send_telegram_message(message)
            if not sent:
                with CACHE_LOCK:  # let a retry of the same alarm through
                    if LAST_SENT_CACHE.get(cache_key) == (action, now):
                        if previous:
                            LAST_SENT_CACHE[cache_key] = previous
                        else:
                            LAST_SENT_CACHE.pop(cache_key, None)
            
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
    httpd = ThreadingHTTPServer(server_address, WebhookHandler)
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
        # --test [chat_id ...]: test message to the given chats, or to every configured chat
        logging.info("Running Telegram integration test...")
        success = send_telegram_message("✅ ThingsBoard Telegram integration test successful", sys.argv[2:] or None)
        if success:
            logging.info("Test message sent successfully.")
        else:
            logging.error("Failed to send test message.")
    else:
        run_server(PORT)
