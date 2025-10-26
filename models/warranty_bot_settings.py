# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import logging
_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # --- YANGI: sahna (stage) ID’lari ---
    stage_accept_id = fields.Many2one(
        "crm.stage",
        string="Qabul qilingani bosqichi",
        config_parameter="warranty_bot.stage_accept_id",
    )
    stage_progress_id = fields.Many2one(
        "crm.stage",
        string="Jarayonda bosqichi",
        config_parameter="warranty_bot.stage_progress_id",
    )
    stage_done_id = fields.Many2one(
        "crm.stage",
        string="Tasdiqlash/Yakun bosqichi",
        config_parameter="warranty_bot.stage_done_id",
    )
    # param nomlari
    _P_ACCEPT = "warranty_bot.stage_accept_id"
    _P_PROGRESS = "warranty_bot.stage_progress_id"
    _P_DONE = "warranty_bot.stage_done_id"

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env["ir.config_parameter"].sudo()
        def _int(name):
            val = ICP.get_param(name)
            try:
                return int(val) if val else False
            except Exception:
                return False

        res.update(
            stage_accept_id=_int(self._P_ACCEPT),
            stage_progress_id=_int(self._P_PROGRESS),
            stage_done_id=_int(self._P_DONE),
        )
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param(self._P_ACCEPT, str(self.stage_accept_id.id or ""))
        ICP.set_param(self._P_PROGRESS, str(self.stage_progress_id.id or ""))
        ICP.set_param(self._P_DONE, str(self.stage_done_id.id or ""))
