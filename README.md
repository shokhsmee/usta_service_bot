🛠️ Usta Service Bot (Odoo 18)

A Telegram-powered service bot integrated with Odoo 18, designed for managing warranty or service requests via aiogram.
This module exposes secure HTTP endpoints that interact with Telegram’s webhook system.

⚙️ Installation & Setup
1. Clone the Repository
cd /opt/odoo/bot/
git clone https://github.com/shokhsmee/usta_service_bot.git


Place the module inside your Odoo addons path.

2. Configure odoo.conf

Edit your Odoo configuration file (for example /etc/odoo18.conf) and make sure to lock to one database and disable the public database selector:

[options]
addons_path = /opt/odoo/addons,/opt/odoo/bot/usta_service_bot
dbfilter = ^your_main_db_name$
list_db = False


Replace your_main_db_name with your actual database name.

Then restart Odoo:

sudo systemctl restart odoo18

3. Add Bot Token in System Parameters

In Odoo → Settings → Technical → Parameters → System Parameters, create a new key:

Key	Value
warranty_bot.bot_token	<your_telegram_bot_token>

This connects Odoo with your Telegram bot created via @BotFather
.

🌐 Webhook Routes

The module defines two HTTP endpoints:

/warranty/webhook/test

Method: GET
Checks the bot’s current status and aiogram runtime.

Returns JSON like:

{
  "status": "OK",
  "db": "your_main_db_name",
  "token_exists": true,
  "aiogram_running": true
}

/warranty/webhook

Methods: POST and GET
This is the main Telegram webhook receiver.
Telegram will send updates here, and they’ll be forwarded into the aiogram dispatcher inside Odoo.

🔌 Setting Up the Webhook

Once your bot is running and your server is accessible via HTTPS, set the Telegram webhook:

curl -F "url=https://your-domain.com/warranty/webhook" https://api.telegram.org/bot<your_telegram_bot_token>/setWebhook


You can verify it:

curl https://api.telegram.org/bot<your_telegram_bot_token>/getWebhookInfo


If everything is correct, you’ll see "url": "https://your-domain.com/warranty/webhook" and "pending_update_count": 0.

🧠 How It Works

When Telegram sends an update, Odoo’s HTTP controller receives it.

The module ensures that the aiogram app inside Odoo is running (ensure_aiogram_running).

The update is parsed and passed to the aiogram dispatcher (feed_update).

Logs are written to Odoo’s standard logs, prefixed with [WB].

🪶 Example Test

You can quickly verify webhook connectivity:

curl https://your-domain.com/warranty/webhook/test

🧩 Notes

Requires Python 3.11+ and Odoo 18.0.

If running via Docker, expose port 8069 and ensure HTTPS via reverse proxy (e.g. Nginx).

The bot can handle multiple updates asynchronously once aiogram starts.
