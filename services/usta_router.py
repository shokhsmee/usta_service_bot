# -*- coding: utf-8 -*-
import os, tempfile, logging, base64
from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.exceptions import TelegramBadRequest
from odoo import fields

from .runtime import open_env
from .usta_services import (
    find_usta_by_tg, find_usta_by_phone, upsert_usta_tg, _lead_address,
    transition_lead_stage, is_ready_to_start, list_active_requests,
    request_stage, format_rq_card, list_usta_open_leads, expense_total_for_lead,
    get_stage_ids, move_lead_to_stage, finance_exists_for_lead,  # <-- added import
)
from .state import Reg, Work
from .keyboards import (
    _safe_edit_message, main_kb, share_phone_kb, request_actions_kb,
    refresh_lead_card, photo_done_kb, expense_type_kb
)
from .middlewares import UstaStatusMiddleware

router = Router()
_logger = logging.getLogger(__name__)

router.message.middleware(UstaStatusMiddleware())
router.callback_query.middleware(UstaStatusMiddleware())


def get_stage_names():
    return {
        "waiting": ["Kutilmoqda", "Waiting", "Pending", "Qabul"],
        "progress": ["Jarayonda", "In Progress", "Boshlandi"],
        "done": ["Yakunlandi", "Done", "Finished", "Tugadi"],
        "confirmed": ["Tasdiqlangan", "Confirmed", "Approved"],
    }


def _paginate(items, page: int, per_page: int = 8):
    total = len(items)
    start = max(page * per_page, 0)
    end = min(start + per_page, total)
    return items[start:end], total


def _parts_kb(rq_id: int, items, page: int, total: int, per_page: int = 8):
    rows = []
    for it in items:
        rows.append([
            InlineKeyboardButton(
                text=f"{it[1]} • {it[3]} {it[2]}",
                callback_data=f"zp:pick:{rq_id}:{it[0]}:{page}"
            )
        ])

    nav = []
    max_page = (total - 1) // per_page if total else 0
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"zp:pg:{rq_id}:{page-1}"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"zp:pg:{rq_id}:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="🔙 Ortga", callback_data=f"zp:back:{rq_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_parts_page(message_or_cb, rq_id: int, page: int = 0):
    with open_env() as env:
        from_user = getattr(message_or_cb, "from_user", None) or getattr(message_or_cb.message, "from_user")
        usta = find_usta_by_tg(env, from_user.id)
        if not usta:
            return await message_or_cb.answer("Ro‘yxatdan o‘ting: /start")

        lines = env["cc.employee.zapchast"].sudo().search(
            [("employee_id", "=", usta.id), ("qty", ">", 0)],
            order="zapchast_code asc, zapchast_name asc, id asc",
        )
        data = [(l.zapchast_id.id, f"[{l.zapchast_code}] {l.zapchast_name}", l.uom, l.qty) for l in lines]
        page_items, total = _paginate(data, page)

        text = "🔩 <b>Ustaga biriktirilgan zapchastlar</b>\nTanlang:"
        kb = _parts_kb(rq_id, page_items, page, total)
        msg = getattr(message_or_cb, "message", message_or_cb)
        if isinstance(message_or_cb, types.CallbackQuery):
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await message_or_cb.answer()
        else:
            await msg.answer(text, reply_markup=kb, parse_mode="HTML")


async def _register_or_link_usta(env, tg_user_id: int, tg_chat_id: int, phone_plus: str, full_name: str):
    usta = find_usta_by_phone(env, phone_plus)
    if usta:
        upsert_usta_tg(env, usta, tg_user_id, tg_chat_id)
        return usta, True

    Usta = env["cc.employee"].sudo()
    vals = {
        "name": full_name or "Telegram foydalanuvchisi",
        "phone": phone_plus,
        "tg_user_id": str(tg_user_id),
        "tg_chat_id": str(tg_chat_id),
        "active": False,
    }
    if "state" in Usta._fields:
        vals["state"] = "pending"
    usta = Usta.create(vals)
    return usta, False


def _digits_only(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _compact_uz_phone(raw):
    d = _digits_only(raw)
    if not d:
        return ""
    if len(d) == 9:
        d = "998" + d
    return "+" + d


@router.message(CommandStart())
async def cmd_start(m: types.Message, state: FSMContext):
    with open_env() as env:
        usta = find_usta_by_tg(env, m.from_user.id)
        if not usta:
            await state.set_state(Reg.Phone)
            return await m.answer(
                "👋 Assalomu alaykum!\n\nRo'yxatdan o'tish uchun telefon raqamingizni yuboring.",
                reply_markup=share_phone_kb()
            )
        if not getattr(usta, "active", False):
            return await m.answer(
                "⏳ Arizangiz qabul qilindi.\nAdministrator tasdiqlaganidan so'ng, bot funksiyalari ochiladi.",
                reply_markup=ReplyKeyboardRemove()
            )
    await m.answer("✅ Assalomu alaykum! Kerakli bo'limni tanlang.", reply_markup=main_kb())


@router.message(Reg.Phone, F.contact)
async def reg_phone_contact(m: types.Message, state: FSMContext):
    phone_plus = _compact_uz_phone(m.contact.phone_number)
    if not phone_plus:
        return await m.answer("❌ Iltimos, to'g'ri telefon raqam yuboring.", reply_markup=share_phone_kb())
    with open_env() as env:
        usta = find_usta_by_phone(env, phone_plus)
        if usta:
            usta.sudo().write({"tg_user_id": str(m.from_user.id), "tg_chat_id": str(m.chat.id)})
            await state.clear()
            if usta.active:
                return await m.answer("✅ Siz muvaffaqiyatli ro'yxatdan o'tdingiz!", reply_markup=main_kb())
            return await m.answer(
                "⏳ Hisobingiz topildi, lekin hali faollashtirilmagan.\nAdministrator tasdiqlaganidan so'ng xabar beramiz.",
                reply_markup=ReplyKeyboardRemove(),
            )

        await state.update_data(phone=phone_plus)
        await state.set_state(Reg.Viloyat)
        states = env["res.country.state"].sudo().search([("country_id.code", "=", "UZ")], order="name")
        if not states:
            await state.clear()
            return await m.answer("❌ Viloyatlar topilmadi. Adminga murojaat qiling.")
        kb = _build_viloyat_kb(states)
        await m.answer("📍 Ish hududingizni tanlang.\n\nAvval <b>Viloyatni</b> tanlang:", reply_markup=kb, parse_mode="HTML")


@router.message(Reg.Phone, F.text)
async def reg_phone_text(m: types.Message, state: FSMContext):
    phone_plus = _compact_uz_phone(m.text)
    if not phone_plus:
        return await m.answer("❌ Iltimos, telefon raqamini to'g'ri kiriting yoki kontakt ulashing.", reply_markup=share_phone_kb())

    with open_env() as env:
        usta = find_usta_by_phone(env, phone_plus)
        if usta:
            usta.sudo().write({"tg_user_id": str(m.from_user.id), "tg_chat_id": str(m.chat.id)})
            await state.clear()
            if usta.active:
                return await m.answer("✅ Siz muvaffaqiyatli ro'yxatdan o'tdingiz!", reply_markup=main_kb())
            return await m.answer(
                "⏳ Hisobingiz topildi, lekin hali faollashtirilmagan.\nAdministrator tasdiqlaganidan so'ng xabar beramiz.",
                reply_markup=ReplyKeyboardRemove(),
            )

        await state.update_data(phone=phone_plus)
        await state.set_state(Reg.Viloyat)
        states = env["res.country.state"].sudo().search([("country_id.code", "=", "UZ")], order="name")
        if not states:
            await state.clear()
            return await m.answer("❌ Viloyatlar topilmadi.")
        kb = _build_viloyat_kb(states)
        await m.answer("📍 Ish hududingizni tanlang.\n\nAvval <b>Viloyatni</b> tanlang:", reply_markup=kb, parse_mode="HTML")


def _build_viloyat_kb(states):
    rows = []
    for state in states:
        rows.append([InlineKeyboardButton(text=state.name, callback_data=f"reg:vil:{state.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("reg:vil:"), Reg.Viloyat)
async def reg_viloyat(c: types.CallbackQuery, state: FSMContext):
    state_id = int(c.data.split(":")[2])
    with open_env() as env:
        viloyat = env["res.country.state"].sudo().browse(state_id)
        if not viloyat.exists():
            return await c.answer("❌ Viloyat topilmadi.", show_alert=True)

        await state.update_data(state_id=state_id, state_name=viloyat.name, region_ids=[], region_names=[])
        await state.set_state(Reg.Tuman)

        tumans = env["cc.region"].sudo().search([("state_id", "=", state_id), ("active", "=", True)], order="name")
        if not tumans:
            await c.answer("❌ Bu viloyat uchun tumanlar topilmadi.", show_alert=True)
            await state.set_state(Reg.Viloyat)
            return

        kb = _build_tuman_kb(tumans, selected_ids=set())
        await c.message.edit_text(
            f"📍 Viloyat: <b>{viloyat.name}</b>\n\nEndi <b>Tuman(lar)</b> ni tanlang (bir nechta tanlash mumkin), so‘ng «✅ Tasdiqlash»:",
            reply_markup=kb, parse_mode="HTML"
        )
    await c.answer()


def _build_tuman_kb(regions, selected_ids: set[int] | None = None):
    selected_ids = selected_ids or set()
    rows = []
    for region in regions:
        checked = "✅ " if region.id in selected_ids else ""
        rows.append([InlineKeyboardButton(text=f"{checked}{region.name}", callback_data=f"reg:tum:{region.id}")])
    rows.append([
        InlineKeyboardButton(text="⬅️ Ortga", callback_data="reg:back:vil"),
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="reg:tum:ok"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.regexp(r"^reg:tum:\d+$"), Reg.Tuman)
async def reg_tuman_toggle(c: types.CallbackQuery, state: FSMContext):
    region_id = int(c.data.rsplit(":", 1)[1])
    with open_env() as env:
        region = env["cc.region"].sudo().browse(region_id)
        if not region.exists():
            return await c.answer("❌ Tuman topilmadi.", show_alert=True)

        data = await state.get_data()
        selected: list[int] = list(data.get("region_ids") or [])
        selected_names: list[str] = list(data.get("region_names") or [])

        if region_id in selected:
            idx = selected.index(region_id)
            selected.pop(idx)
            try:
                selected_names.remove(region.name)
            except ValueError:
                pass
        else:
            selected.append(region_id)
            selected_names.append(region.name)

        await state.update_data(region_ids=selected, region_names=selected_names)

        tumans = env["cc.region"].sudo().search(
            [("state_id", "=", data.get("state_id")), ("active", "=", True)], order="name"
        )
        kb = _build_tuman_kb(tumans, selected_ids=set(selected))
        sel_count = len(selected)
        await c.message.edit_text(
            f"📍 Viloyat: <b>{data.get('state_name')}</b>\n"
            f"✅ Tanlangan tumanlar: <b>{sel_count}</b>\n\n"
            f"Tuman(lar) ni tanlang, so‘ng «✅ Tasdiqlash» tugmasini bosing.",
            reply_markup=kb, parse_mode="HTML"
        )
    await c.answer()


@router.callback_query(F.data == "reg:tum:ok", Reg.Tuman)
async def reg_tuman_confirm(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected: list[int] = list(data.get("region_ids") or [])
    state_name = data.get("state_name")

    if not selected:
        return await c.answer("Iltimos, kamida bitta tuman tanlang.", show_alert=True)

    await state.set_state(Reg.Location)
    from .keyboards import share_location_kb
    await c.message.edit_text(
        f"📍 Viloyat: <b>{state_name}</b>\n"
        f"✅ Tuman(lar) tanlandi: <b>{len(selected)}</b>\n\n"
        f"Endi <b>jonli joylashuvingizni</b> yuboring:",
        parse_mode="HTML"
    )
    await c.message.answer("📍 \"Joylashuvni ulashish\" tugmasini bosing (telefoningizdan GPS yoqilgan bo‘lsin).",
                           reply_markup=share_location_kb())
    await c.answer()


@router.message(Reg.Location, F.location)
async def reg_location_received(m: types.Message, state: FSMContext):
    lat = m.location.latitude
    lng = m.location.longitude
    await state.update_data(geo_lat=lat, geo_lng=lng)
    await state.set_state(Reg.FullName)
    await m.answer("✅ Joylashuv qabul qilindi.\n\n👤 Endi to'liq ismingizni kiriting:\n(Masalan: Abdullayev Sardor Akramovich)",
                   reply_markup=ReplyKeyboardRemove())


@router.message(Reg.Location, F.text == "⬅️ Ortga")
async def reg_location_back(m: types.Message, state: FSMContext):
    with open_env() as env:
        data = await state.get_data()
        state_id = data.get("state_id")
        if not state_id:
            await state.set_state(Reg.Viloyat)
            states = env["res.country.state"].sudo().search([("country_id.code", "=", "UZ")], order="name")
            kb = _build_viloyat_kb(states)
            return await m.answer("📍 Ish hududingizni tanlang.\n\nAvval <b>Viloyatni</b> tanlang:", reply_markup=kb, parse_mode="HTML")

        tumans = env["cc.region"].sudo().search([("state_id", "=", state_id), ("active", "=", True)], order="name")
        sel_ids = set(data.get("region_ids") or [])
        kb = _build_tuman_kb(tumans, selected_ids=sel_ids)
        await state.set_state(Reg.Tuman)
        await m.answer(
            f"📍 Viloyat: <b>{data.get('state_name')}</b>\n"
            f"✅ Tanlangan tumanlar: <b>{len(sel_ids)}</b>\n\n"
            f"Tuman(lar) ni tanlang, so‘ng «✅ Tasdiqlash».",
            reply_markup=kb, parse_mode="HTML"
        )


@router.callback_query(F.data == "reg:back:vil", Reg.Tuman)
async def reg_back_to_viloyat(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(Reg.Viloyat)
    with open_env() as env:
        states = env["res.country.state"].sudo().search([("country_id.code", "=", "UZ")], order="name")
        kb = _build_viloyat_kb(states)
        await c.message.edit_text("📍 Ish hududingizni tanlang.\n\nAvval <b>Viloyatni</b> tanlang:", reply_markup=kb, parse_mode="HTML")
    await c.answer()


@router.message(Reg.FullName, F.text)
async def reg_fullname(m: types.Message, state: FSMContext):
    full_name = (m.text or "").strip()
    if len(full_name) < 3:
        return await m.answer("❌ Iltimos, to'liq ism-familiyangizni kiriting.\n(Kamida 3 ta harf)")
    data = await state.get_data()
    phone: str | None = data.get("phone")
    state_id: int | None = data.get("state_id")
    region_ids: list[int] = list(data.get("region_ids") or [])
    region_names: list[str] = list(data.get("region_names") or [])
    geo_lat = data.get("geo_lat")
    geo_lng = data.get("geo_lng")

    if not phone or not state_id or not region_ids:
        await state.clear()
        return await m.answer("❌ Ma'lumotlar to‘liq emas (telefon/viloyat/tumanlar). Qaytadan /start bosing.")

    with open_env() as env:
        try:
            User = env["res.users"].sudo()
            base_group = env.ref("base.group_user")
            user_vals = {
                "name": full_name,
                "login": phone,
                "phone": phone,
                "active": True,
                "groups_id": [(4, base_group.id)] if base_group else [],
            }
            user = User.search([("login", "=", phone)], limit=1)
            if user:
                user.write({"name": full_name, "phone": phone})
            else:
                user = User.create(user_vals)

            Employee = env["cc.employee"].sudo()
            emp_vals = {
                "name": full_name,
                "phone": phone,
                "is_usta": True,
                "active": True,
                "usta_status": False,
                "tg_user_id": str(m.from_user.id),
                "tg_chat_id": str(m.chat.id),
                "user_id": user.id,
                "service_region_ids": [(6, 0, region_ids)],
                "state_ids": [(4, state_id)],
            }
            if geo_lat and geo_lng:
                emp_vals["geo_lat"] = float(geo_lat)
                emp_vals["geo_lng"] = float(geo_lng)
            if "state" in Employee._fields:
                emp_vals["state"] = "pending"

            usta = Employee.create(emp_vals)

            await state.clear()
            regions_txt = ", ".join(region_names) if region_names else f"{len(region_ids)} ta tuman"
            loc_txt = f"\n📍 Joylashuv: {geo_lat:.6f}, {geo_lng:.6f}" if (geo_lat and geo_lng) else ""
            await m.answer(
                "✅ <b>Ro'yxatdan o'tish muvaffaqiyatli!</b>\n\n"
                f"👤 Ism: {full_name}\n"
                f"📞 Telefon: {phone}\n"
                f"📍 Hudud: {data.get('state_name')} / {regions_txt}"
                f"{loc_txt}\n\n"
                "⏳ Arizangiz administratorga yuborildi.\n"
                "Tasdiqlangandan so'ng sizga xabar beramiz.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
            _logger.info(f"New usta registered: {full_name} ({phone}) - ID: {usta.id}")
        except Exception as e:
            _logger.exception("Registration failed")
            await state.clear()
            await m.answer("❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring: /start\n\n" f"Xato: {str(e)}")


@router.message(F.text == "📝 Aktiv zayafkalar")
async def show_active_requests(m: types.Message, state: FSMContext):
    with open_env() as env:
        usta = find_usta_by_tg(env, m.from_user.id)
        if not usta:
            await state.set_state(Reg.Phone)
            return await m.answer("Ro‘yxatdan o‘tish uchun telefon raqamingizni yuboring.", reply_markup=share_phone_kb())

        leads = list_usta_open_leads(env, usta, limit=20)
        if not leads:
            return await m.answer("Hozircha sizga biriktirilgan, yakunlanmagan zayavkalar yo‘q ✅", reply_markup=main_kb())

        for lead in leads:
            stage = request_stage(lead)
            ready = is_ready_to_start(lead) if stage == "accepted" else False
            text = format_rq_card(lead)
            kb = request_actions_kb(lead.id, stage, ready)
            msg = await m.answer(text, reply_markup=kb, parse_mode="HTML")
            lead.sudo().write({"tg_card_chat_id": str(m.chat.id), "tg_card_msg_id": str(msg.message_id)})


@router.callback_query(F.data.startswith("rq:accept:"))
async def rq_accept(c: types.CallbackQuery):
    rq_id = int(c.data.split(":")[2])
    with open_env() as env:
        lead = env["crm.lead"].sudo().browse(rq_id)
        stage_ids = get_stage_ids(env)
        target_id = stage_ids.get("waiting") or stage_ids.get("accept") or 0

        if target_id:
            ok = move_lead_to_stage(env, lead, target_id)
        else:
            new_id = transition_lead_stage(env, lead, "waiting") or transition_lead_stage(env, lead, "accepted")
            ok = bool(new_id)

        from .aiogram_app import _BOT
        await refresh_lead_card(_BOT, env, lead)
    await c.answer("✅ Zayavka qabul qilindi. Kutilmoqda.", show_alert=not ok)


@router.callback_query(F.data.startswith("rq:start:"))
async def rq_start(c: types.CallbackQuery):
    rq_id = int(c.data.split(":")[2])
    with open_env() as env:
        lead = env["crm.lead"].sudo().browse(rq_id)
        stage_ids = get_stage_ids(env)
        ok = move_lead_to_stage(env, lead, stage_ids["progress"])
        from .aiogram_app import _BOT
        await refresh_lead_card(_BOT, env, lead)
    await c.answer("🔧 Ish boshlandi. TZMda: Jarayonda" if ok else "❗️ Xatolik", show_alert=False)


async def _refresh_card(c_message, lead_id):
    with open_env() as env:
        lead = env["crm.lead"].sudo().browse(lead_id)
        stage = request_stage(lead)
        ready = is_ready_to_start(lead) if stage == "accepted" else False
        await c_message.edit_text(
            format_rq_card(lead),
            reply_markup=request_actions_kb(lead.id, stage, ready),
            parse_mode="HTML"
        )


@router.message(Work.Amount)
async def set_amount(m: types.Message, state: FSMContext):
    data = await state.get_data()
    rq_id = data["rq_id"]
    amt_text = m.text.replace(" ", "")
    if not amt_text.isdigit():
        return await m.answer("Faqat raqam kiriting. Masalan: 120000")
    amount = int(amt_text)

    with open_env() as env:
        lead = env["crm.lead"].sudo().browse(rq_id)
        lead.write({"work_amount": amount})

        usta = find_usta_by_tg(env, m.from_user.id)
        ft_id = False
        try:
            ft_id = env["cc.finance.type"].sudo().search([
                ("name", "ilike", "Xizmatdan tushum"),
                ("direction", "=", "income"),
                ("active", "=", True),
            ], limit=1).id
        except Exception:
            ft_id = False

        vals = {
            "date": fields.Date.context_today(env.user),
            "employee_id": usta.id if usta else False,
            "direction": "income",
            "amount": amount,
            "lead_id": rq_id,
            "note": "Xizmatdan tushum",
        }
        if "type_id" in env["cc.finance"]._fields and ft_id:
            vals["type_id"] = ft_id

        env["cc.finance"].sudo().create(vals)

        from .aiogram_app import _BOT
        await refresh_lead_card(_BOT, env, lead)

    await state.clear()
    await m.answer("Saqlandi ✅")


@router.callback_query(F.data.startswith("rq:amount:"))
async def rq_amount(c: types.CallbackQuery, state: FSMContext):
    rq_id = int(c.data.split(":")[2])
    await state.update_data(rq_id=rq_id)
    await state.set_state(Work.Amount)
    await c.message.answer("Xizmat summasini kiriting (faqat raqam):\nMasalan: 120000")
    await c.answer()


@router.callback_query(F.data.startswith("rq:finish:"))
async def rq_finish(c: types.CallbackQuery):
    rq_id = int(c.data.split(":")[2])
    with open_env() as env:
        lead = env["crm.lead"].sudo().browse(rq_id)

        has_amount = bool(getattr(lead, "work_amount", False))
        has_parts = int(getattr(lead, "cc_move_out_count", 0) or 0) > 0
        any_fin = finance_exists_for_lead(lead)  # <-- income OR expense accepted
        has_photos = bool(getattr(lead, "photo_attachment_ids", []))

        missing = []
        if not has_amount: missing.append("💰 Xizmat summasi")
        if not has_parts: missing.append("🔩 Zapchast")
        if not any_fin: missing.append("🧮 Xarajat / Yo‘l haqi")  # <-- updated wording
        if not has_photos: missing.append("🖼️ Foto")

        if missing:
            from .aiogram_app import _BOT
            await refresh_lead_card(_BOT, env, lead)
            return await c.answer("Ishni yakunlash uchun quyidagilarni to‘ldiring:\n- " + "\n- ".join(missing), show_alert=True)

        stage_ids = get_stage_ids(env)
        ok = move_lead_to_stage(env, lead, stage_ids["done"])
        lead.message_post(body="⏳ Usta ishni yakunladi. Operator tasdiqini kutmoqda.", message_type="notification")

        from .aiogram_app import _BOT
        await refresh_lead_card(_BOT, env, lead)

    await c.answer("✅ Ish yakunlandi! Operator tasdiqlashi kutilmoqda.", show_alert=True)


@router.callback_query(F.data.startswith("rq:parts:"))
async def rq_parts(c: types.CallbackQuery, state: FSMContext):
    rq_id = int(c.data.split(":")[2])
    await state.update_data(rq_id=rq_id, parts_page=0)
    await state.set_state(Work.PartsPick)
    await _show_parts_page(c, rq_id, page=0)


@router.callback_query(F.data.startswith("zp:pg:"), Work.PartsPick)
async def zp_page(c: types.CallbackQuery, state: FSMContext):
    _, _, rq_id, page = c.data.split(":")
    await state.update_data(parts_page=int(page))
    await _show_parts_page(c, int(rq_id), int(page))


@router.callback_query(F.data.startswith("zp:back:"), Work.PartsPick)
async def zp_back(c: types.CallbackQuery, state: FSMContext):
    rq_id = int(c.data.split(":")[2])
    with open_env() as env:
        from .aiogram_app import _BOT
        lead = env["crm.lead"].sudo().browse(rq_id)
        await refresh_lead_card(_BOT, env, lead)
    await state.clear()
    await c.answer()


@router.callback_query(F.data.startswith("zp:pick:"), Work.PartsPick)
async def zp_pick(c: types.CallbackQuery, state: FSMContext):
    _, _, rq_id, zp_id, page = c.data.split(":")
    await state.update_data(rq_id=int(rq_id), zp_id=int(zp_id), parts_page=int(page))
    await state.set_state(Work.PartsQty)
    await c.message.answer("Miqdor kiriting (faqat raqam). Masalan: 2")
    await c.answer()


@router.callback_query(F.data.startswith("rq:finish_yes:"))
async def rq_finish_yes(c: types.CallbackQuery):
    rq_id = int(c.data.split(":")[2])
    with open_env() as env:
        lead = env["crm.lead"].sudo().browse(rq_id)
        ok = move_lead_to_stage(env, lead, get_stage_ids(env)["done"])
        await c.message.edit_reply_markup(reply_markup=None)
        await c.message.answer("✅ Zayavka yakunlandi." if ok else "❗️ Yakunlab bo‘lmadi.")
    await c.answer()


@router.callback_query(F.data.startswith("rq:finish_no:"))
async def rq_finish_no(c: types.CallbackQuery):
    rq_id = int(c.data.split(":")[2])
    with open_env() as env:
        from .aiogram_app import _BOT
        lead = env["crm.lead"].sudo().browse(rq_id)
        await refresh_lead_card(_BOT, env, lead)
    await c.answer("Bekor qilindi.")


@router.message(Work.PartsQty)
async def zp_qty(m: types.Message, state: FSMContext):
    raw = (m.text or "").replace(" ", "")
    if not raw or not raw.replace(".", "", 1).isdigit():
        return await m.answer("Iltimos, faqat son kiriting. Masalan: 1 yoki 2.5")
    qty = float(raw)
    if qty <= 0:
        return await m.answer("Miqdor ijobiy bo‘lishi kerak.")
    await state.update_data(qty=qty)
    await state.set_state(Work.PartsPrice)
    await m.answer("Narx (UZS) kiriting yoki 0 yozing (standart narx olinadi).")


@router.message(Work.PartsPrice)
async def zp_price(m: types.Message, state: FSMContext):
    raw = (m.text or "").replace(" ", "")
    if not raw.isdigit():
        return await m.answer("Iltimos, butun UZS kiriting (masalan: 120000) yoki 0.")
    price = int(raw)

    data = await state.get_data()
    rq_id = int(data["rq_id"])
    zp_id = int(data["zp_id"])
    qty = float(data["qty"])

    with open_env() as env:
        usta = find_usta_by_tg(env, m.from_user.id)
        if not usta:
            await state.clear()
            return await m.answer("Ro‘yxatdan o‘ting: /start")

        line = env["cc.employee.zapchast"].sudo().search(
            [("employee_id", "=", usta.id), ("zapchast_id", "=", zp_id)], limit=1
        )
        avail = float(getattr(line, "qty", 0) or 0)
        if qty > avail:
            await m.answer(f"❌ Qoldiq yetarli emas.\nMavjud: {avail:g}\nQayta miqdor kiriting (≤ {avail:g}).")
            await state.set_state(Work.PartsQty)
            return

        vals = {
            "date": fields.Datetime.now(),
            "move_type": "out",
            "employee_id": usta.id,
            "zapchast_id": zp_id,
            "qty": qty,
            "unit_price_uzs": price or 0,
            "crm_service_id": rq_id,
            "state": "posted",
            "note": "Telegram: ustadan sarf",
        }
        env["cc.zapchast.move"].sudo().create(vals)

        from .aiogram_app import _BOT
        lead = env["crm.lead"].sudo().browse(rq_id)
        await refresh_lead_card(_BOT, env, lead)

    await state.clear()
    await m.answer("Zapchast sarfi saqlandi ✅")


# =========================
#   XARAJAT / INCOME FLOW
# =========================
@router.callback_query(F.data.startswith("rq:travel:"))
async def rq_travel(c: types.CallbackQuery, state: FSMContext):
    rq_id = int(c.data.split(":")[2])
    await state.update_data(rq_id=rq_id, exp_direction="expense", exp_note=None)
    await state.set_state(Work.ExpType)
    await c.message.answer(
        "🧮 <b>Xarajat qo‘shish</b>\n"
        "Xarajat turini <b>Tugma</b> orqali tanlang yoki <b>o‘zingiz yozib kiriting</b>.",
        parse_mode="HTML",
        reply_markup=expense_type_kb(rq_id)
    )
    await c.answer()


@router.callback_query(F.data.startswith("exp:type:fare:"), Work.ExpType)
async def exp_pick_fare(c: types.CallbackQuery, state: FSMContext):
    rq_id = int(c.data.split(":")[3])
    await state.update_data(rq_id=rq_id, exp_direction="income", exp_note="Yo‘l haqi")
    await state.set_state(Work.ExpAmount)
    await c.message.answer("Summani kiriting (faqat raqam):\nMasalan: 45000")
    await c.answer()


@router.callback_query(F.data.startswith("exp:type:back:"), Work.ExpType)
async def exp_type_back(c: types.CallbackQuery, state: FSMContext):
    rq_id = int(c.data.split(":")[3])
    with open_env() as env:
        from .aiogram_app import _BOT
        lead = env["crm.lead"].sudo().browse(rq_id)
        await refresh_lead_card(_BOT, env, lead)
    await state.clear()
    await c.answer()


@router.message(Work.ExpType, F.text)
async def exp_type_free_text(m: types.Message, state: FSMContext):
    note = (m.text or "").strip()
    if not note:
        return await m.answer("Xarajat turini yozing yoki tugmadan tanlang.")
    await state.update_data(exp_note=note, exp_direction="expense")
    await state.set_state(Work.ExpAmount)
    await m.answer("Summani kiriting (faqat raqam):\nMasalan: 45000")


@router.message(Work.ExpAmount)
async def expense_amount(m: types.Message, state: FSMContext):
    raw = m.text.replace(" ", "")
    if not raw.isdigit():
        return await m.answer("Raqam kiriting. Masalan: 45000")
    amount = int(raw)
    data = await state.get_data()
    note = (data.get("exp_note") or "").strip()
    await state.update_data(exp_amount=amount)
    if note:
        return await _create_finance_and_refresh(m, state)
    await state.set_state(Work.ExpNote)
    await m.answer("Xarajat izohini yozing (masalan: 'Benzin', 'Mayda detallar' ...).")


@router.message(Work.ExpNote)
async def expense_note(m: types.Message, state: FSMContext):
    note = (m.text or "").strip()
    if not note:
        return await m.answer("Izoh yozing.")
    await state.update_data(exp_note=note, exp_direction="expense")
    await _create_finance_and_refresh(m, state)


async def _create_finance_and_refresh(m: types.Message, state: FSMContext):
    data = await state.get_data()
    rq_id = data.get("rq_id")
    amount = int(data.get("exp_amount") or 0)
    note = (data.get("exp_note") or "Xarajat").strip()
    direction = (data.get("exp_direction") or "expense").strip()
    if amount <= 0:
        return await m.answer("Summani to‘g‘ri kiriting.")

    with open_env() as env:
        usta = find_usta_by_tg(env, m.from_user.id)
        if not usta:
            await state.clear()
            return await m.answer("Ro‘yxatdan o‘ting: /start")

        env["cc.finance"].sudo().create({
            "date": fields.Date.context_today(env.user),
            "employee_id": usta.id,
            "direction": direction,  # 'income' | 'expense'
            "amount": amount,
            "lead_id": rq_id,
            "note": note,
        })

        from .aiogram_app import _BOT
        lead = env["crm.lead"].sudo().browse(rq_id)
        await refresh_lead_card(_BOT, env, lead)

    await state.clear()
    sign = "+" if direction == "income" else "−"
    await m.answer(f"{note} {sign}{amount:,} saqlandi ✅".replace(",", " "))


@router.callback_query(F.data.startswith("rq:photo:"))
async def rq_photo(c: types.CallbackQuery, state: FSMContext):
    rq_id = int(c.data.split(":")[2])
    await state.update_data(rq_id=rq_id)
    await state.set_state(Work.Photo)
    await c.message.answer("📷 Rasmlarni yuboring.\nTugatgach, «✅ Tayyor» ni bosing.", reply_markup=photo_done_kb())
    await c.answer()


@router.message(Work.Photo, F.photo)
async def on_photo(m: types.Message, state: FSMContext):
    data = await state.get_data()
    rq_id = int(data["rq_id"])
    photo = m.photo[-1]
    file = await m.bot.get_file(photo.file_id)

    fd, tmp = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    await m.bot.download(file, destination=tmp)

    with open(tmp, "rb") as f:
        bin_data = f.read()
    os.unlink(tmp)
    data_b64 = base64.b64encode(bin_data).decode()

    with open_env() as env:
        att = env["ir.attachment"].sudo().create({
            "name": "photo.jpg",
            "datas": data_b64,
            "res_model": "crm.lead",
            "res_id": rq_id,
            "mimetype": "image/jpeg",
        })
        env["crm.lead.photo"].sudo().create({
            "lead_id": rq_id,
            "name": "Foto",
            "image_1920": data_b64,
            "note": "",
        })
        lead = env["crm.lead"].sudo().browse(rq_id)
        lead.write({"photo_attachment_ids": [(4, att.id)]})

        from .aiogram_app import _BOT
        await refresh_lead_card(_BOT, env, lead)

    await m.answer("Rasm saqlandi ✅")


@router.message(Work.Photo, F.text == "✅ Tayyor")
async def photo_done_btn(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Foto otchot qabul qilindi ✅", reply_markup=main_kb())


@router.message(Work.Photo, F.text == "⬅️ Ortga")
async def photo_cancel(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Foto yuborish bekor qilindi.", reply_markup=main_kb())


# SINGLE rq:confirm HANDLER (kept this one; removed duplicate)
@router.callback_query(F.data.startswith("rq:confirm:"))
async def rq_confirm(c: types.CallbackQuery):
    rq_id = int(c.data.split(":")[2])
    with open_env() as env:
        lead = env["crm.lead"].sudo().browse(rq_id)
        if not is_ready_to_start(lead):
            return await c.answer("❗️ Iltimos, hamma ma'lumotlarni to'ldiring.", show_alert=True)
        stage_ids = get_stage_ids(env)
        current_stage = request_stage(lead)
        if current_stage == "accepted":
            ok = move_lead_to_stage(env, lead, stage_ids["progress"])
            msg = "🔧 Ish boshlandi"
        else:
            ok = move_lead_to_stage(env, lead, stage_ids["done"])
            lead.message_post(body="⏳ Usta ma'lumotlarni yubordi. Operator tasdiqini kutmoqda.",
                              message_type="notification")
            msg = "✅ Ma'lumotlar operatorga yuborildi"

        from .aiogram_app import _BOT
        await refresh_lead_card(_BOT, env, lead)
    await c.answer(msg if ok else "❗️ Xatolik", show_alert=True)


@router.message(F.text == "💼 Balansim")
async def show_balance(m: types.Message, state: FSMContext):
    with open_env() as env:
        usta = find_usta_by_tg(env, m.from_user.id)
        if not usta:
            await state.set_state(Reg.Phone)
            return await m.answer("Ro‘yxatdan o‘tish uchun telefon raqamingizni yuboring.", reply_markup=share_phone_kb())

        emp = usta.sudo()
        text = (
            f"💼 <b>Balans</b>\n"
            f"— Hozirgi balans: <b>{round(emp.balance_total):,}</b>\n\n"
            f"🔩 Zapchastlar (qoldiq):\n"
        ).replace(",", " ")
        lines = env["cc.employee.zapchast"].sudo().search([("employee_id", "=", emp.id)], limit=10)
        if lines:
            for l in lines:
                text += f"• {l.zapchast_id.name} — {l.qty} {l.uom}\n"
        else:
            text += "— Yo‘q"
    await m.answer(text, parse_mode="HTML", reply_markup=main_kb())


@router.message(F.text == "🗂 Zayafkalar tarixi")
async def history_menu(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ Excel eksport (barcha zayavkalar)", callback_data="hist:export:xlsx")]
    ])
    await m.answer("Tarix menyusi:", reply_markup=kb)


@router.callback_query(F.data == "hist:export:xlsx")
async def history_export(c: types.CallbackQuery):
    import xlsxwriter
    with open_env() as env:
        usta = find_usta_by_tg(env, c.from_user.id)
        if not usta:
            return await c.answer("Ro‘yxatdan o‘ting.", show_alert=True)

        Lead = env["crm.lead"].sudo()
        dom = [
            ("type", "=", "opportunity"),
            "|",
            ("usta_id", "=", usta.id),
            ("user_id", "=", (usta.user_id.id if usta.user_id else False)),
        ]
        leads = Lead.search(dom, order="create_date desc", limit=2000)

        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb = xlsxwriter.Workbook(path)

        f_hdr = wb.add_format({"bold": True, "bg_color": "#F2F2F2", "border": 1})
        f_txt = wb.add_format({"border": 1})
        f_num = wb.add_format({"border": 1, "num_format": "# ##0"})
        f_date = wb.add_format({"border": 1, "num_format": "yyyy-mm-dd hh:mm"})
        ws = wb.add_worksheet("Zayavkalar")

        headers = ["Servis #", "Nomi", "Mijoz", "Telefon", "Manzil",
                   "Yaratilgan", "Holati", "Ish summasi", "Xarajatlar (jami)",
                   "Zapchastlar (soni)", "Izoh"]
        ws.write_row(0, 0, headers, f_hdr)
        widths = [12, 28, 22, 18, 40, 20, 18, 14, 18, 18, 50]
        for i, w in enumerate(widths):
            ws.set_column(i, i, w)

        r = 1
        for l in leads:
            addr = _lead_address(l)
            exp_total = expense_total_for_lead(l)
            parts_cnt = int(getattr(l, "cc_move_out_count", 0) or 0)
            amount = float(getattr(l, "work_amount", 0.0) or 0.0)
            stage = (l.stage_id and l.stage_id.name) or ""

            ws.write(r, 0, (l.service_number or ""), f_txt)
            ws.write(r, 1, (l.name or ""), f_txt)
            ws.write(r, 2, (l.partner_name or (l.partner_id and l.partner_id.name) or ""), f_txt)
            ws.write(r, 3, (l.phone or l.partner_phone or (l.partner_id and l.partner_id.phone) or ""), f_txt)
            ws.write(r, 4, addr, f_txt)
            if l.create_date:
                ws.write_datetime(r, 5, l.create_date, f_date)
            else:
                ws.write(r, 5, "", f_txt)
            ws.write(r, 6, stage, f_txt)
            ws.write_number(r, 7, amount, f_num)
            ws.write_number(r, 8, exp_total, f_num)
            ws.write_number(r, 9, parts_cnt, f_num)
            ws.write(r, 10, (l.description or "")[:2000], f_txt)
            r += 1

        wb.close()

    await c.message.answer_document(
        types.FSInputFile(path, filename="usta_zayavkalar_tarixi.xlsx"),
        caption=f"Jami yozuvlar: {len(leads)}"
    )
    os.unlink(path)
    await c.answer("Eksport tayyor ✅")


@router.message(F.text == "⚙️ Sozlamalar")
async def settings_menu(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Til: O‘zbekcha", callback_data="set:lang:uz")],
        [InlineKeyboardButton(text="🔒 Chiqish", callback_data="logout")],
    ])
    await m.answer("Sozlamalar:", reply_markup=kb)


@router.callback_query(F.data == "logout")
async def logout(c: types.CallbackQuery):
    with open_env() as env:
        usta = find_usta_by_tg(env, c.from_user.id)
        if usta:
            usta.sudo().write({"tg_user_id": False, "tg_chat_id": False})
    await c.message.answer("Hisob ajratildi. Qayta ulash uchun /start bosing.")
    await c.answer()
