# -*- coding: utf-8 -*-
import logging
from typing import Optional

_logger = logging.getLogger(__name__)

def find_usta_by_tg(env, tg_user_id):
    return env["cc.employee"].sudo().search(
        [("tg_user_id", "=", str(tg_user_id)), ("is_usta", "=", True)],
        limit=1
    )

def find_usta_by_phone(env, phone):
    return env["cc.employee"].sudo().search(
        [("phone", "=", phone), ("is_usta", "=", True)],
        limit=1
    )

def upsert_usta_tg(env, usta, tg_user_id, tg_chat_id):
    usta.sudo().write({"tg_user_id": str(tg_user_id), "tg_chat_id": str(tg_chat_id)})

def list_active_requests(env, usta):
    uid = usta.user_id.id if usta.user_id else False
    domain = [("type", "=", "opportunity")]
    if uid:
        domain.append(("user_id", "=", uid))
    return env["crm.lead"].sudo().search(domain, order="create_date desc", limit=20)

def request_stage(rq):
    """Return one of: new | waiting | accepted | progress | done"""
    try:
        ids = get_stage_ids(rq.env)
        sid = rq.stage_id.id if rq.stage_id else 0
        if sid and ids.get("done") and sid == ids["done"]:
            return "done"
        if sid and ids.get("progress") and sid == ids["progress"]:
            return "progress"
        if sid and ids.get("waiting") and sid == ids["waiting"]:
            return "waiting"
        if sid and ids.get("accept") and sid == ids["accept"]:
            return "accepted"
    except Exception:
        pass

    name = (rq.stage_id.name or "").lower()
    if "yakunlandi" in name or "done" in name or "finished" in name:
        return "done"
    if "jarayonda" in name or "progress" in name:
        return "progress"
    if "kutilmoqda" in name or "waiting" in name or "pending" in name:
        return "waiting"
    if "qabul" in name or "accept" in name:
        return "accepted"
    return "new"

def _lead_address(rq):
    # keep as-is if you still use it elsewhere; safe to leave unchanged
    parts = []
    for val in [rq.street, rq.city, getattr(rq.state_id, "name", None), getattr(rq.country_id, "name", None)]:
        if val:
            parts.append(val)
    addr = ", ".join(parts)
    if not addr and rq.partner_id:
        addr = rq.partner_id.contact_address or rq.partner_id._display_address() or ""
    return addr or "-"

def _sanitize_url(u: str) -> str:
    # very lightweight sanitizer so href is valid in HTML mode
    try:
        u = (u or "").strip()
        if not u:
            return ""
        # Telegram HTML needs & escaped
        return u.replace("&", "&amp;").replace('"', "%22").replace("'", "%27")
    except Exception:
        return ""

def format_rq_card(rq):
    addr = _lead_address(rq)

    try:
        tags = [t.name.strip() for t in rq.tag_ids if (t.name or "").strip()]
    except Exception:
        tags = []

    sn = (getattr(rq, "service_number", None) or rq.id or "")
    title = f"⚙️ <b>#{sn}</b>\n"

    has_amount  = bool(getattr(rq, "work_amount", False))
    has_parts   = int(getattr(rq, "cc_move_out_count", 0) or 0) > 0
    exp_total   = expense_total_for_lead(rq)
    try:
        has_finance = finance_exists_for_lead(rq)
    except Exception:
        has_finance = (exp_total > 0)
    has_photos  = bool(getattr(rq, "photo_attachment_ids", []))
    desc        = (getattr(rq, "work_text", None) or "")

    # >>>>>>> ONLY USE THE SAVED FIELD <<<<<<<
    # No geocoding, no address fallback.
    raw_url = getattr(rq, "location_url", "") or ""
    map_url = _sanitize_url(raw_url)

    # optional product list...
    product_lines = []
    try:
        pls = list(getattr(rq, "product_line_ids", []) or [])
        i = 1
        for l in pls:
            p = getattr(l, "product_id", None)
            if not p:
                continue
            code = (getattr(p, "default_code", None) or "").strip() or (f"#{getattr(p, 'id', '')}" if getattr(p, "id", None) else "—")
            product_lines.append(f"{i}. {code}")
            i += 1
    except Exception:
        product_lines = []

    def _money(v):
        try:
            return f"{int(v):,}".replace(",", " ")
        except Exception:
            return str(v)

    amount_txt = _money(rq.work_amount) if has_amount else "—"
    parts_txt  = "✅" if has_parts else "—"
    exp_txt    = _money(exp_total) if exp_total > 0 else ("✅" if has_finance else "—")
    photo_txt  = "✅" if has_photos else "—"

    parts = [
        title,
        f"📄 <b>{rq.name}</b>",
        f"👤 {(rq.partner_name or (rq.partner_id and rq.partner_id.name) or '—')}",
        f"☎️ {(rq.phone or rq.partner_phone or (rq.partner_id and rq.partner_id.phone) or '—')}",
        f"📍 {addr or '—'}",
    ]

    # Show ONLY the stored link if present
    if map_url:
        parts.append(f"🔗 <a href=\"{map_url}\">Manzil URL</a>")
            
    if pls:
        product_lines = []
        i = 1
        for l in pls:
            p = getattr(l, "product_id", None)
            if not p:
                continue
            code = (getattr(p, "default_code", None) or "").strip() or (f"#{getattr(p, 'id', '')}" if getattr(p, "id", None) else "—")
            name = getattr(p, "name", "")
            sale_dt = ""
            # Try to get sale datetime from sync_line_id
            try:
                sync_line = getattr(l, "sync_line_id", None)
                if sync_line and getattr(sync_line, "sale_date", None):
                    # full timestamp with minutes and seconds
                    sale_dt = sync_line.sale_date.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                sale_dt = ""
            line_txt = f"{i}. {code} — {name}"
            if sale_dt:
                line_txt += f"\n🗓 {sale_dt}"
            product_lines.append(line_txt)
            i += 1

        if product_lines:
            parts.append("\n📦 Mahsulotlar:\n" + "\n".join(product_lines))


    extras = [
        "📋 Qo'shimchalar",
        f"  💰 Ish summasi : {amount_txt}",
        f"  🔩 Zapchast    : {parts_txt}",
        f"  🧮 Xarajat     : {exp_txt}",
        f"  🖼️ Foto        : {photo_txt}",
    ]
    parts.append("<pre>" + "\n".join(extras) + "</pre>")

    if tags:
        parts.append("🏷️ " + " • ".join(tags))
    if desc:
        parts.append(f"\n📝 {desc[:600]}")

    return "\n".join(parts)


def is_ready_to_start(lead) -> bool:
    has_amount = bool(getattr(lead, "work_amount", False))
    has_parts  = int(getattr(lead, "cc_move_out_count", 0) or 0) > 0
    exp_total  = expense_total_for_lead(lead)
    has_photos = bool(getattr(lead, "photo_attachment_ids", []))
    return all([has_amount, has_parts, exp_total > 0, has_photos])

def list_usta_open_leads(env, usta, limit=20):
    if getattr(usta, "company_id", False) and usta.company_id:
        env = env(context=dict(env.context or {}, allowed_company_ids=[usta.company_id.id]))

    Lead = env["crm.lead"].sudo()
    Stage = env["crm.stage"]

    closed_dom = []
    stage_fields = Stage._fields
    if "is_won" in stage_fields:
        closed_dom.append(("stage_id.is_won", "=", False))
    if "is_lost" in stage_fields:
        closed_dom.append(("stage_id.is_lost", "=", False))
    if "fold" in stage_fields:
        closed_dom.append(("stage_id.fold", "=", False))

    domain = [("type", "=", "opportunity"), ("active", "=", True), ("usta_id", "=", usta.id)] + closed_dom
    if "probability" in Lead._fields:
        domain.append(("probability", "<", 100))

    leads = Lead.search(domain, order="priority desc, create_date desc", limit=limit)
    closed_keywords = ["done", "finished", "closed", "cancel", "lost", "won", "yopildi", "tugadi", "bekor"]
    leads = leads.filtered(lambda l: all(kw not in (l.stage_id.name or "").lower() for kw in closed_keywords))

    if not leads:
        uid = usta.user_id.id if usta.user_id else False
        if uid:
            alt_domain = [("type", "=", "opportunity"), ("active", "=", True), ("user_id", "=", uid)] + closed_dom
            if "probability" in Lead._fields:
                alt_domain.append(("probability", "<", 100))
            leads = Lead.search(alt_domain, order="priority desc, create_date desc", limit=limit)
            leads = leads.filtered(lambda l: all(kw not in (l.stage_id.name or "").lower() for kw in closed_keywords))
    return leads

def _team_domain(Stage, team_id):
    dom = []
    if not team_id:
        return dom
    fields = Stage._fields
    if "team_ids" in fields:
        dom += ["|", ("team_ids", "=", False), ("team_ids", "in", [team_id])]
    elif "team_id" in fields:
        dom += ["|", ("team_id", "=", False), ("team_id", "=", team_id)]
    return dom

def _with_company(env, company_id):
    if company_id:
        return env(context=dict(env.context or {}, allowed_company_ids=[company_id]))
    return env

def _find_stage_for_team(env, team_id, company_id, names_like: list[str]) -> Optional[int]:
    env = _with_company(env, company_id)
    Stage = env["crm.stage"].sudo()
    base_dom = _team_domain(Stage, team_id)
    for frag in names_like:
        sid = Stage.search(base_dom + [("name", "ilike", frag)], order="sequence asc", limit=1)
        if sid:
            return sid.id
    return None

def _fallback_next_open_stage(env, lead):
    env = _with_company(env, lead.company_id.id if lead.company_id else False)
    Stage = env["crm.stage"].sudo()
    dom = []
    if "fold" in Stage._fields:
        dom.append(("fold", "=", False))
    dom += _team_domain(Stage, lead.team_id.id if lead.team_id else False)
    stages = Stage.search(dom, order="sequence asc", limit=100)
    if not stages:
        return None
    cur_seq = getattr(lead.stage_id, "sequence", -1) if lead.stage_id else -1
    for st in stages:
        if getattr(st, "sequence", 999999) >= cur_seq and (not lead.stage_id or st.id != lead.stage_id.id):
            return st.id
    for st in stages:
        if not lead.stage_id or st.id != lead.stage_id.id:
            return st.id
    return None

def transition_lead_stage(env, lead, target: str) -> Optional[int]:
    env = _with_company(env, lead.company_id.id if lead.company_id else False)
    name_map = {
        "accepted": ["Qabul", "Accept"],
        "waiting":  ["Kutilmoqda", "Waiting", "Pending", "Qabul"],
        "progress": ["Boshlandi", "Progress", "In Progress"],
        "done":     ["Tasdiq", "Done", "Yakun", "Finished"],
    }
    names_like = name_map.get(target, [])
    stage_id = _find_stage_for_team(env, lead.team_id.id if lead.team_id else False,
                                    lead.company_id.id if lead.company_id else False,
                                    names_like)
    if not stage_id:
        stage_id = _fallback_next_open_stage(env, lead)
    if stage_id and (not lead.stage_id or lead.stage_id.id != stage_id):
        lead.sudo().write({"stage_id": stage_id})
        return stage_id
    return None

def _get_param_int(env, key, default=0):
    ICP = env["ir.config_parameter"].sudo()
    val = ICP.get_param(key, default and str(default) or "")
    try:
        return int(val)
    except Exception:
        return int(default or 0)

def get_stage_ids(env):
    return {
        "waiting":  _get_param_int(env, "warranty_bot.stage_waiting_id", 0),
        "accept":   _get_param_int(env, "warranty_bot.stage_waiting_id", 0),
        "progress": _get_param_int(env, "warranty_bot.stage_progress_id", 0),
        "done":     _get_param_int(env, "warranty_bot.stage_done_id", 0),
    }

def move_lead_to_stage(env, lead, target_stage_id):
    Stage = env["crm.stage"].sudo()
    st = Stage.browse(target_stage_id)
    if not st or not st.exists():
        return False

    team_dom = _team_domain(Stage, lead.team_id.id if lead.team_id else False)
    st_for_team = Stage.search([("name", "=", st.name)] + team_dom, limit=1) or st

    ctx = dict(env.context or {})
    if getattr(lead, "company_id", False) and lead.company_id:
        ctx["allowed_company_ids"] = [lead.company_id.id]

    lead.with_context(ctx).sudo().write({"stage_id": st_for_team.id})
    return True

def expense_total_for_lead(rq) -> int:
    env = rq.env
    if getattr(rq, "company_id", False) and rq.company_id:
        env = env(context=dict(env.context or {}, allowed_company_ids=[rq.company_id.id]))
    Finance = env["cc.finance"].sudo()
    total = 0.0
    try:
        recs = Finance.search([("lead_id", "=", rq.id), ("direction", "=", "expense")])
        total = sum((r.amount or 0.0) for r in recs)
    except Exception:
        total = 0.0
    return int(round(total or 0))

def finance_exists_for_lead(rq) -> bool:
    """True if there is ANY finance line (income or expense) for this lead."""
    env = rq.env
    if getattr(rq, "company_id", False) and rq.company_id:
        env = env(context=dict(env.context or {}, allowed_company_ids=[rq.company_id.id]))
    Finance = env["cc.finance"].sudo()
    try:
        # we only care that something (>0) was recorded
        cnt = Finance.search_count([("lead_id", "=", rq.id), ("amount", ">", 0)])
        return cnt > 0
    except Exception:
        return False
