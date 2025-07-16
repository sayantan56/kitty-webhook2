from flask import Flask, request, jsonify
import json
import os
import logging
import telegram
import razorpay
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('webhook.log')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load configuration from environment or config.json
try:
    if os.getenv('CONFIG_PATH'):
        with open(os.getenv('CONFIG_PATH'), 'r') as f:
            config = json.load(f)
    else:
        with open('config.json', 'r') as f:
            config = json.load(f)
except FileNotFoundError as e:
    logger.error(f"Config file not found: {e}")
    raise
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON in config file: {e}")
    raise

BOT_TOKEN = config.get('telegram_bot_token')
CHAT_ID = config.get('telegram_chat_id')
FILE_URL = config.get('s3_file_url')
RAZORPAY_KEY_ID = config.get('razorpay_key_id')
RAZORPAY_KEY_SECRET = config.get('razorpay_key_secret')
RAZORPAY_WEBHOOK_SECRET = config.get('razorpay_webhook_secret')

# Validate configuration
if not all([BOT_TOKEN, CHAT_ID, FILE_URL, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET]):
    logger.error("Missing required configuration values")
    raise ValueError("Incomplete configuration")

# Initialize Telegram bot
try:
    bot = telegram.Bot(token=BOT_TOKEN)
except Exception as e:
    logger.error(f"Failed to initialize Telegram bot: {e}")
    raise

# Initialize Razorpay client
try:
    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
except Exception as e:
    logger.error(f"Failed to initialize Razorpay client: {e}")
    raise

# Set up scheduler with proper timezone
scheduler = BackgroundScheduler(timezone=pytz.UTC)

@app.route('/', methods=['GET'])
def home():
    """Health check endpoint"""
    return '💖 Kitty Webhook is alive 💖', 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle Razorpay webhook events"""
    try:
        # Get raw body and signature
        webhook_body = request.get_data(as_text=True)
        webhook_signature = request.headers.get('X-Razorpay-Signature')
        
        if not webhook_signature:
            logger.warning("Missing X-Razorpay-Signature header")
            return jsonify({'error': 'Missing signature'}), 400

        # Verify webhook signature
        try:
            client.utility.verify_webhook_signature(
                webhook_body,
                webhook_signature,
                RAZORPAY_WEBHOOK_SECRET
            )
        except razorpay.errors.SignatureVerificationError as e:
            logger.warning(f"Signature verification failed: {e}")
            return jsonify({'error': 'Invalid signature'}), 403

        # Parse JSON payload
        try:
            data = request.get_json()
        except Exception as e:
            logger.error(f"Invalid JSON payload: {e}")
            return jsonify({'error': 'Invalid JSON'}), 400

        logger.info(f"Incoming webhook: {data}")

        # Handle payment.captured event
        if data.get('event') == 'payment.captured':
            try:
                msg = f"Thanks for the payment 😘\nHere’s your file: {FILE_URL}"
                bot.send_message(chat_id=CHAT_ID, text=msg)
                logger.info(f"Sent Telegram message to chat_id {CHAT_ID}")
                return jsonify({'status': 'Message sent'}), 200
            except telegram.error.TelegramError as e:
                logger.error(f"Failed to send Telegram message: {e}")
                return jsonify({'error': 'Failed to send message'}), 500

        logger.info("Ignored non-payment.captured event")
        return jsonify({'status': 'Ignored'}), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/test-payment', methods=['POST'])
def test_payment():
    """Manual test endpoint for simulating payment"""
    try:
        data = request.get_json()
        if data.get('text') == 'Paid 💸':
            msg = f"Thanks for the payment \nHere’s your file: {FILE_URL}"
            bot.send_message(chat_id=CHAT_ID, text=msg)
            logger.info("Manual payment test successful")
            return jsonify({'status': 'Message sent'}), 200
        return jsonify({'status': 'Ignored'}), 400
    except Exception as e:
        logger.error(f"Test payment error: {e}")
        return jsonify({'error': 'Server error'}), 500

def check_bot_status():
    """Scheduled task to verify bot connectivity"""
    try:
        bot.get_me()
        logger.info("Telegram bot is online")
    except telegram.error.TelegramError as e:
        logger.error(f"Bot connectivity check failed: {e}")

if __name__ == '__main__':
    # Start scheduler
    try:
        scheduler.add_job(check_bot_status, 'interval', minutes=30)
        scheduler.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
    
    # Run Flask app
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))