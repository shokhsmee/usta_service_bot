# -*- coding: utf-8 -*-
from odoo import fields, models

class CcEmployee(models.Model):
    _inherit = "cc.employee"

    tg_user_id = fields.Char(string="Telegram user id", index=True)
    tg_chat_id = fields.Char(string="Telegram chat id", index=True)
    tg_lang = fields.Selection([("uz","O‘zbekcha"),("ru","Русский")], default="uz", string="TG til")
