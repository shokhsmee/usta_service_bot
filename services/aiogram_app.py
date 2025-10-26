# -*- coding: utf-8 -*-
import asyncio
import logging
import threading
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update

from . import usta_router
from . import runtime  # <-- MUHIM

_logger = logging.getLogger(__name__)

_AIO_LOOP = None
_BOT = None
_DP = None

def _create_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop

def ensure_aiogram_running(env):
    """
    aiogram 3 dispatcher/botni bir marta ishga tushiramiz.
    Env'dagi cursorni saqlamaymiz! Faqat DB nomini saqlaymiz.
    """
    global _AIO_LOOP, _BOT, _DP
    if _BOT and _DP and _AIO_LOOP and _AIO_LOOP.is_running():
        return True

    token = env["ir.config_parameter"].sudo().get_param("warranty_bot.bot_token")
    if not token:
        _logger.warning("[AIO] warranty_bot.bot_token topilmadi")
        return False

    # DB nomini runtime’ga joylaymiz (keyin open_env() orqali env ochamiz)
    runtime.set_dbname(env.cr.dbname)

    _BOT = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    _DP = Dispatcher()
    _DP.include_router(usta_router.router)

    _AIO_LOOP = _create_loop()
    _AIO_LOOP.create_task(_dp_startup())
    threading.Thread(target=_AIO_LOOP.run_forever, daemon=True).start()

    _logger.info("[AIO] Aiogram 3 loop/dispatcher ishga tushdi.")
    return True

async def _dp_startup():
    await asyncio.sleep(0)

def feed_update(update_dict: dict):
    """
    Controllerdan kelgan update (dict) -> aiogram Update -> Dispatcher.
    """
    global _AIO_LOOP, _BOT, _DP
    if not (_AIO_LOOP and _AIO_LOOP.is_running() and _BOT and _DP):
        _logger.warning("[AIO] feed_update: loop/bot/dispatcher tayyor emas")
        return False

    async def _feed():
        try:
            upd = Update.model_validate(update_dict)
            await _DP.feed_update(_BOT, upd)
        except Exception as e:
            _logger.error(f"[AIO] feed_update error: {e}", exc_info=True)

    _AIO_LOOP.call_soon_threadsafe(lambda: asyncio.create_task(_feed()))
    return True
