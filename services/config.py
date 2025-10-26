# -*- coding: utf-8 -*-
def get_stage_ids(env):
    ICP = env["ir.config_parameter"].sudo()
    def _gi(key):
        v = ICP.get_param(key)
        try:
            return int(v) if v else False
        except Exception:
            return False

    return {
        "accept": _gi("warranty_bot.stage_accept_id"),
        "progress": _gi("warranty_bot.stage_progress_id"),
        "done": _gi("warranty_bot.stage_done_id"),
    }
