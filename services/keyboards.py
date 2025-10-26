# -*- coding: utf-8 -*-
import logging
from aiogram import Router, F, types, Bot
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.exceptions import TelegramBadRequest

from .usta_services import (
    find_usta_by_tg, find_usta_by_phone, upsert_usta_tg, _lead_address,
    transition_lead_stage, is_ready_to_start, list_active_requests,
    request_stage, format_rq_card, list_usta_open_leads,
)

router = Router()
_logger = logging.getLogger(__name__)

def expense_type_kb(rq_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚌 Yo‘l haqi", callback_data=f"exp:type:fare:{rq_id}")],
        [InlineKeyboardButton(text="🔙 Ortga",     callback_data=f"exp:type:back:{rq_id}")],
    ])

async def _safe_edit_message(bot: Bot, chat_id: int, msg_id: int, text: str, markup):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:  # ignore benign
            return
        if "message to edit not found" in msg:
            return
        raise

def main_kb():
    kb = [
        [KeyboardButton(text="📝 Aktiv zayafkalar")],
        [KeyboardButton(text="💼 Balansim"), KeyboardButton(text="🗂 Zayafkalar tarixi")],
        [KeyboardButton(text="⚙️ Sozlamalar")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def share_phone_kb():
    kb = [[KeyboardButton(text="📱 Kontakt ulashish", request_contact=True)]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

def share_location_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Joylashuvni ulashish", request_location=True)],
            [KeyboardButton(text="⬅️ Ortga")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def request_actions_kb(rq_id: int, stage: str, ready: bool=False) -> InlineKeyboardMarkup:
    rows = []
    if stage in ("new", "assigned", "draft"):
        rows.append([InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"rq:accept:{rq_id}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    if stage in ("accepted", "waiting"):
        rows.append([InlineKeyboardButton(text="🔧 Ishni boshlash", callback_data=f"rq:start:{rq_id}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "progress":
        rows.append([InlineKeyboardButton(text="✅ Ishni yakunlash", callback_data=f"rq:finish:{rq_id}")])
        rows.append([
            InlineKeyboardButton(text="💰 Xizmat summasi", callback_data=f"rq:amount:{rq_id}"),
            InlineKeyboardButton(text="🔩 Zapchast",       callback_data=f"rq:parts:{rq_id}"),
        ])
        rows.append([
            InlineKeyboardButton(text="🧮 Xarajatlar",     callback_data=f"rq:travel:{rq_id}"),
            InlineKeyboardButton(text="📷 Foto",           callback_data=f"rq:photo:{rq_id}"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    if stage == "done":
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏳ Operator tasdiqini kutmoqda...", callback_data="noop")
        ]])
    return InlineKeyboardMarkup(inline_keyboard=[])

async def refresh_lead_card(bot: Bot, env, lead):
    lead = lead.sudo()
    if not (lead.tg_card_chat_id and lead.tg_card_msg_id):
        return
    stage = request_stage(lead)
    ready = is_ready_to_start(lead) if stage == "accepted" else False
    text = format_rq_card(lead)
    markup = request_actions_kb(lead.id, stage, ready)
    await _safe_edit_message(bot, int(lead.tg_card_chat_id), int(lead.tg_card_msg_id), text, markup)

def _finish_confirm_kb(rq_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, yakunla",  callback_data=f"rq:finish_yes:{rq_id}"),
        InlineKeyboardButton(text="↩️ Yo‘q, ortga", callback_data=f"rq:finish_no:{rq_id}"),
    ]])

def photo_done_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Tayyor")],
            [KeyboardButton(text="⬅️ Ortga")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
