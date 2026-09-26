import os
import json
import logging
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PORT = int(os.getenv("PORT", 5050))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [Telegram] %(levelname)s - %(message)s')

def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. Cannot send notification.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logging.info("Alarm notification sent successfully")
        return True
    except requests.exceptions.RequestException as e:
        # Mask the token in error messages just in case
        safe_error = str(e).replace(TELEGRAM_BOT_TOKEN, "HIDDEN_TOKEN")
        logging.error(f"Failed to send notification: {safe_error}")
        return False

def format_alarm_message(alarm_data: dict, action: str) -> str:
    """
    Format the alarm data into a readable Telegram message.
    """
    alarm_type = alarm_data.get("type", "Unknown Alarm")
    severity = alarm_data.get("severity", "UNKNOWN")
    status = alarm_data.get("status", "UNKNOWN")
    device_name = alarm_data.get("originatorName", "Unknown Device")
    
    # Try to get device name from metadata if not in originatorName
    if device_name == "Unknown Device" and "name" in alarm_data:
        device_name = alarm_data.get("name")
        
    details = alarm_data.get("details", {})
    
    # Extract telemetry like TDS if available
    tds = details.get("tds", None)
    if not tds and "tds" in alarm_data:
        tds = alarm_data.get("tds")
        
    # Build the message
    if action == "CLEARED":
        msg = f"✅ <b>{alarm_type.upper()} CLEARED</b>\n\n"
    else:
        msg = f"🚨 <b>{alarm_type.upper()}</b>\n\n"
        
    msg += f"<b>Device:</b> {device_name}\n"
    msg += f"<b>Alarm:</b> {alarm_type}\n"
    # Map ThingsBoard internal status to user-friendly dashboard status
    status_mapping = {
        "ACTIVE_UNACK": "Active (Unacknowledged)",
        "ACTIVE_ACK": "Active (Acknowledged)",
        "CLEARED_UNACK": "Cleared (Unacknowledged)",
        "CLEARED_ACK": "Cleared (Acknowledged)"
    }
    display_status = status_mapping.get(status, status)
    
    msg += f"<b>Severity:</b> {severity}\n"
    msg += f"<b>Status:</b> {display_status}\n"
    
    if tds is not None:
        msg += f"<b>TDS:</b> {tds}\n"
        
    condition = details.get("data", None)
    if condition:
        msg += f"<b>Condition:</b> {condition}\n"
        
    # Append any specific message from details
    if "message" in details:
        msg += f"\n<i>{details['message']}</i>"
        
    return msg

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(post_data.decode('utf-8'))
            logging.info(f"Received payload")
            
            # ThingsBoard rule chain REST API node sends the message as JSON.
            # In TB, the 'msg' is usually the payload itself.
            alarm_data = payload
            
            # Determine action (CREATED, UPDATED, CLEARED). 
            # This can be passed in metadata or inferred from status
            status = alarm_data.get("status", "")
            if status in ["CLEARED_UNACK", "CLEARED_ACK"]:
                action = "CLEARED"
            elif status in ["ACTIVE_UNACK", "ACTIVE_ACK"]:
                action = "CREATED"
            else:
                action = "CREATED"
            
            message = format_alarm_message(alarm_data, action)
            send_telegram_message(message)
            
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

def run_server(port=5050):
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
