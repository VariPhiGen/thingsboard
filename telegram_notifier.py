
import os
import sys
import json
import logging
import ipaddress
import threading
import queue
import time
import requests
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Self-contained .env loader (zero external dependencies fallback)
def load_env_file(path: Path):
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            if k not in os.environ:
                os.environ[k] = v
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to read {path}: {e}\n")

ENV_FILE = Path(__file__).resolve().with_name(".env")
load_env_file(ENV_FILE)

# Also try python-dotenv if installed
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
except ImportError:
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
PORT = int(os.getenv("TELEGRAM_NOTIFIER_PORT") or os.getenv("PORT", 5051))
PORTAL_URL = os.getenv("PORTAL_URL", "https://viot.virtuosonetsoft.com").strip()

TEST_DEVICE_PREFIX = "[TEST]"
SKIP_ALARM_TYPES = {t.strip() for t in os.getenv("TELEGRAM_SKIP_ALARM_TYPES", "DG Offline").split(",") if t.strip()}
TELEGRAM_TEST_CHAT_ID = os.getenv("TELEGRAM_TEST_CHAT_ID", "").strip()
ALLOWED_NETWORKS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [TelegramNotifier] %(levelname)s - %(message)s')

# Cache for deduplication: (device_name, alarm_type) -> (action, timestamp)
LAST_SENT_CACHE = {}
CACHE_LOCK = threading.Lock()
DEDUP_COOLDOWN_SECONDS = int(os.getenv("TELEGRAM_DEDUP_COOLDOWN_SECONDS", "600"))

# Asynchronous message delivery queue to prevent blocking ThingsBoard webhook calls
MESSAGE_QUEUE = queue.Queue(maxsize=1000)

def send_telegram_message(message: str, chat_ids=None) -> bool:
    """Dispatches message to Telegram via Bot API with retry and rate-limit handling."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    default_chat_id = os.getenv("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)

    if not token or not (chat_ids or default_chat_id):
        logging.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. Cannot send notification.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    target_chats = chat_ids or [cid.strip() for cid in default_chat_id.split(',') if cid.strip()]
    all_success = True

    for chat_id in target_chats:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        sent = False
        for attempt in range(4):
            try:
                response = requests.post(url, json=payload, timeout=12)
                if response.status_code == 429:
                    wait = response.json().get("parameters", {}).get("retry_after", 5)
                    logging.warning(f"Telegram rate-limited (429). Waiting {wait}s...")
                    time.sleep(min(int(wait), 30))
                    continue
                if not response.ok:
                    logging.error(f"Telegram rejected message to {chat_id}: HTTP {response.status_code} - {response.text[:200]}")
                    break
                logging.info(f"Alarm notification successfully sent to Telegram chat {chat_id}")
                sent = True
                break
            except requests.exceptions.RequestException as e:
                safe_error = str(e).replace(token, "[HIDDEN_TOKEN]")
                logging.warning(f"Attempt {attempt + 1}/4 failed sending to {chat_id}: {safe_error}")
                time.sleep(2 * (attempt + 1))
        
        if not sent:
            all_success = False

    return all_success

def worker_loop():
    """Background worker daemon processing alert messages asynchronously."""
    logging.info("Telegram background dispatch worker started.")
    while True:
        try:
            item = MESSAGE_QUEUE.get()
            if item is None:
                break
            msg, chats, cache_key, action, now_ts = item
            success = send_telegram_message(msg, chats)
            if not success and cache_key:
                # On send failure, evict from dedup cache so retry is allowed
                with CACHE_LOCK:
                    if LAST_SENT_CACHE.get(cache_key) == (action, now_ts):
                        LAST_SENT_CACHE.pop(cache_key, None)
            MESSAGE_QUEUE.task_done()
        except Exception as e:
            logging.error(f"Error in Telegram worker loop: {e}")

def clean_sensor_value(val):
    if val is None:
        return "N/A"
    try:
        num = float(str(val).replace('°C', '').replace('RPM', '').replace('kPa', '').strip())
        if num == 32767 or num >= 30000:
            return "Sensor Fault (32767)"
    except Exception:
        pass
    return str(val)

def format_alarm_message(alarm_data: dict, action: str) -> str:
    """
    Format alarm data into an industry-standard, professional alert layout.
    """
    alarm_type = alarm_data.get("type", "Unknown Alarm")
    severity = str(alarm_data.get("severity") or "UNKNOWN").upper()
    status = alarm_data.get("status", "UNKNOWN")
    
    device_name = (
        alarm_data.get("originatorName") or 
        alarm_data.get("name") or 
        alarm_data.get("deviceName") or 
        "Unknown Device"
    )
    orig = alarm_data.get("originator")
    if isinstance(orig, dict):
        device_name = orig.get("name") or device_name

    details = alarm_data.get("details")
    is_cleared = (action == "CLEARED") or ("CLEARED" in status)
    
    status_mapping = {
        "ACTIVE_UNACK": "Active (Unacknowledged)",
        "ACTIVE_ACK": "Active (Acknowledged)",
        "CLEARED_UNACK": "Resolved (Unacknowledged)",
        "CLEARED_ACK": "Resolved (Acknowledged)"
    }
    display_status = status_mapping.get(status, status)

    # Industry standard header & severity badge
    if is_cleared:
        header = f"✅ <b>INCIDENT RESOLVED: {escape(alarm_type.upper())}</b>"
        sev_badge = "🟢 <b>CLEARED</b>"
    elif severity == "CRITICAL":
        header = f"🚨 <b>CRITICAL INCIDENT: {escape(alarm_type.upper())}</b>"
        sev_badge = "🔴 <b>CRITICAL</b>"
    elif severity in ["MAJOR", "HIGH"]:
        header = f"⚠️ <b>MAJOR ALARM: {escape(alarm_type.upper())}</b>"
        sev_badge = "🟠 <b>MAJOR</b>"
    elif severity in ["MINOR", "MEDIUM"]:
        header = f"⚠️ <b>MINOR ALARM: {escape(alarm_type.upper())}</b>"
        sev_badge = "🟡 <b>MINOR</b>"
    else:
        header = f"ℹ️ <b>OPERATIONAL NOTICE: {escape(alarm_type.upper())}</b>"
        sev_badge = f"🔵 <b>{escape(severity)}</b>"

    msg_parts = [
        header,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🏢 <b>System:</b> Virtuoso NetSoft IoT Operations",
        f"📍 <b>Asset:</b> <code>{escape(str(device_name))}</code>",
        f"🏷️ <b>Alarm Type:</b> <b>{escape(alarm_type)}</b>",
        f"⚡ <b>Severity:</b> {sev_badge}",
        f"🔄 <b>Status:</b> <b>{escape(str(display_status))}</b>"
    ]

    start_ts = alarm_data.get("startTs") or alarm_data.get("createdTime")
    clear_ts = alarm_data.get("clearTs") or alarm_data.get("endTs")

    if is_cleared:
        resolved_ts = clear_ts or int(time.time() * 1000)
        time_str = time.strftime('%d %b %Y, %I:%M:%S %p', time.gmtime(resolved_ts / 1000 + 19800))
        msg_parts.append(f"⏱️ <b>Resolved At:</b> {time_str} IST")
        
        if start_ts and clear_ts and clear_ts > start_ts:
            duration_secs = int((clear_ts - start_ts) / 1000)
            hours, rem = divmod(duration_secs, 3600)
            mins, secs = divmod(rem, 60)
            dur_parts = []
            if hours > 0:
                dur_parts.append(f"{hours}h")
            if mins > 0 or hours > 0:
                dur_parts.append(f"{mins}m")
            dur_parts.append(f"{secs}s")
            msg_parts.append(f"⏳ <b>Incident Duration:</b> {' '.join(dur_parts)}")
    else:
        if start_ts:
            time_str = time.strftime('%d %b %Y, %I:%M:%S %p', time.gmtime(start_ts / 1000 + 19800))
            msg_parts.append(f"⏱️ <b>Triggered At:</b> {time_str} IST")

    # Render incident context / telemetry
    detail_msg = ""
    recommendation = ""
    telemetry_items = {}

    if isinstance(details, dict):
        detail_msg = details.get("message") or details.get("description") or details.get("summary") or ""
        recommendation = details.get("recommendation") or details.get("action") or ""
        for k, v in details.items():
            if k not in ["message", "description", "summary", "recommendation", "action", "ai_mode"]:
                telemetry_items[k] = clean_sensor_value(v)
    elif isinstance(details, str) and details.strip():
        detail_msg = details.strip()

    if detail_msg:
        clean_dt = str(detail_msg).replace("32767", "Sensor Fault (32767)").strip()
        msg_parts.append(f"\n📋 <b>Incident Context:</b>\n<blockquote>{escape(clean_dt)}</blockquote>")

    if telemetry_items:
        msg_parts.append("\n📊 <b>Telemetry Readings:</b>")
        for k, v in telemetry_items.items():
            label = escape(k.replace('_', ' ').title())
            val = escape(str(v))
            msg_parts.append(f"• <b>{label}:</b> <code>{val}</code>")

    if recommendation and not is_cleared:
        msg_parts.append(f"\n🛠️ <b>Operator SOP / Action:</b>\n<blockquote>{escape(str(recommendation))}</blockquote>")

    msg_parts.append(f'\n🔗 <a href="{PORTAL_URL}">Open Virtuoso IoT Portal</a>')

    return "\n".join(msg_parts)

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
            self.send_header("Content-Type", "text/plain")
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

            if alarm_type in SKIP_ALARM_TYPES:
                logging.info(f"Skipped normal operational event: '{device_name}' - '{alarm_type}' ({action})")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"SKIPPED")
                return

            # Smart Deduplication Cache:
            # Prevents alarm flapping/spamming, but ALWAYS allows state changes (CREATED <-> CLEARED)
            cache_key = (str(device_name), str(alarm_type))
            now = time.time()
            with CACHE_LOCK:
                previous = LAST_SENT_CACHE.get(cache_key)
                duplicate = previous and previous[0] == action and (now - previous[1]) < DEDUP_COOLDOWN_SECONDS
                if not duplicate:
                    LAST_SENT_CACHE[cache_key] = (action, now)

            if duplicate:
                logging.info(f"Deduplicated duplicate alarm: '{device_name}' - '{alarm_type}' ({action})")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"DEDUPLICATED")
                return

            message = format_alarm_message(alarm_data, action)
            
            # Route test devices vs production devices
            if str(device_name).startswith(TEST_DEVICE_PREFIX):
                if TELEGRAM_TEST_CHAT_ID:
                    MESSAGE_QUEUE.put(("🧪 <b>[TEST DEVICE ALERT]</b>\n\n" + message, [TELEGRAM_TEST_CHAT_ID], cache_key, action, now))
                else:
                    logging.info(f"Test device alarm (logged, not dispatched):\n{message}")
            else:
                MESSAGE_QUEUE.put((message, None, cache_key, action, now))
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except json.JSONDecodeError:
            logging.error("Received invalid JSON payload")
            self.send_response(400)
            self.end_headers()
        except Exception as e:
            logging.error(f"Error processing webhook request: {e}")
            self.send_response(500)
            self.end_headers()

def run_server(port=5051):
    # Start background worker daemon
    worker_thread = threading.Thread(target=worker_loop, daemon=True)
    worker_thread.start()

    server_address = ('0.0.0.0', port)
    httpd = ThreadingHTTPServer(server_address, WebhookHandler)
    logging.info(f"Starting Virtuoso Telegram Notification Service on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info("Virtuoso Telegram Notification Service stopped.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        logging.info("Running Telegram integration test...")
        test_alarm = {
            "originatorName": "DG SET1",
            "type": "DG No Data",
            "severity": "MAJOR",
            "status": "ACTIVE_UNACK",
            "startTs": int(time.time() * 1000),
            "details": {
                "message": "DG SET1 has sent no telemetry data for over 15 minutes. Controller link or gateway connectivity interrupted.",
                "recommendation": "Check DG gateway power, network connection, and verify the RS485 Modbus wiring to the controller.",
                "battery_voltage": "24.2 V",
                "engine_status": "Standby"
            }
        }
        test_msg = format_alarm_message(test_alarm, "CREATED")
        print("\n--- SAMPLE TELEGRAM ALERT MESSAGE ---")
        print(test_msg)
        print("------------------------------------\n")
        success = send_telegram_message(test_msg, sys.argv[2:] or None)
        if success:
            logging.info("Test message successfully delivered to Telegram!")
            sys.exit(0)
        else:
            logging.error("Failed to send test message. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
            sys.exit(1)
    else:
        run_server(PORT)
