# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class WarrantyWebhookController(http.Controller):

    @http.route(
        ["/warranty/webhook/test", "/warranty/webhook/test/"],
        type="http", auth="public", csrf=False, methods=["GET"]
    )
    def warranty_webhook_test(self, **kwargs):
        token = request.env["ir.config_parameter"].sudo().get_param("warranty_bot.bot_token")
        # aiogram ishga tushirish (agar hali tushmagan bo‘lsa)
        try:
            from ..services.aiogram_app import ensure_aiogram_running
            ensure_aiogram_running(request.env)
            aio = True
        except Exception as e:
            _logger.warning(f"[WB/TEST] aiogram init warn: {e}")
            aio = False

        payload = {
            "status": "OK",
            "db": request.db,
            "token_exists": bool(token),
            "aiogram_running": aio,
        }
        return request.make_response(
            json.dumps(payload, indent=2),
            headers=[("Content-Type", "application/json")]
        )

    @http.route(
        ["/warranty/webhook", "/warranty/webhook/"],
        type="http", auth="public", csrf=False, methods=["POST","GET"]
    )
    def warranty_webhook(self, **kwargs):
        """
        Telegram webhook: kelgan update'ni aiogram dispatcher'ga feed qilamiz.
        """
        try:
            raw = request.httprequest.data or b""
            text = raw.decode("utf-8", "ignore")
            _logger.info(f"[WB] Incoming {request.httprequest.method} raw={text[:500]}")

            # aiogram ishga tushsin
            from ..services.aiogram_app import ensure_aiogram_running, feed_update
            ensure_aiogram_running(request.env)

            if raw:
                try:
                    upd = json.loads(text)
                except Exception as e:
                    _logger.warning(f"[WB] JSON parse warn: {e}")
                    upd = {}
                # aiogram dispatcher'ga yuboramiz
                feed_update(upd)
            return request.make_response("OK", headers=[("Content-Type", "text/plain")])
        except Exception as e:
            _logger.error(f"[WB] webhook error: {e}", exc_info=True)
            return request.make_response("OK", headers=[("Content-Type", "text/plain")])
