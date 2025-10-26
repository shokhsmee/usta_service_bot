# Usta Service Bot (Odoo 18)

Telegram-based service bot integration for Odoo 18, used to handle warranty and service workflows inside Odoo.  
Built with **aiogram** and Odoo’s HTTP controllers.

---

## Setup

### 1. Clone
```bash
cd /opt/odoo/bot
git clone https://github.com/shokhsmee/usta_service_bot.git
Add the module path to your addons_path in Odoo config.

2. Odoo Config
In your odoo.conf (usually /etc/odoo18.conf):

ini
Copy code
[options]
addons_path = /opt/odoo/addons,/opt/odoo/bot/usta_service_bot
dbfilter = ^your_main_db_name$
list_db = False
Restart Odoo after saving:

bash
Copy code
sudo systemctl restart odoo18
3. System Parameter
Add a system parameter in Settings → Technical → Parameters → System Parameters:

Key	Value
warranty_bot.bot_token	<your_telegram_bot_token>

This connects your Telegram bot (created via BotFather) to Odoo.

Webhooks
The module registers two endpoints:

/warranty/webhook/test
Method: GET

Checks bot and aiogram status.

Example response:

json
Copy code
{
  "status": "OK",
  "db": "your_main_db_name",
  "token_exists": true,
  "aiogram_running": true
}
/warranty/webhook
Methods: POST or GET

Telegram will send updates here.

Controller passes updates to aiogram dispatcher inside Odoo.

Set Telegram Webhook
Replace your domain and token below:

bash
Copy code
curl -F "url=https://your-domain.com/warranty/webhook" \
  https://api.telegram.org/bot<your_telegram_bot_token>/setWebhook
Check status:

bash
Copy code
curl https://api.telegram.org/bot<your_telegram_bot_token>/getWebhookInfo
Notes
Requires Odoo 18.0 and Python 3.11+

HTTPS must be enabled (Telegram requires it)

Keep dbfilter strict to isolate the correct DB

Logs will appear in Odoo logs with [WB] prefix

Test Endpoint
bash
Copy code
curl https://your-domain.com/warranty/webhook/test
Expected output:

json
Copy code
{"status": "OK", "db": "your_main_db_name", "token_exists": true, "aiogram_running": true}
Author
Shokhsmee
Telegram integration for Odoo 18 – Warranty & Service Automation
