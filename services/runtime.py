# -*- coding: utf-8 -*-
# Global DB konteyner va env ochish utilitilari (thread-safe, import-safe)
from contextlib import contextmanager

_DBNAME = None

def set_dbname(dbname: str):
    """Aiogram ishga tushganda DB nomini saqlab qo'yamiz."""
    global _DBNAME
    _DBNAME = dbname

def get_dbname() -> str:
    return _DBNAME

@contextmanager
def open_env():
    """
    Har chaqirilganda yangi cursor va Environment yaratadi.
    Ish yakunida commit, xatolikda rollback qiladi.
    """
    if not _DBNAME:
        raise RuntimeError("Runtime DB is not configured. Call runtime.set_dbname(db) first.")

    from odoo import api, SUPERUSER_ID  # importni kechiktirib
    from odoo.sql_db import db_connect   # importni kechiktirib

    with db_connect(_DBNAME).cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        try:
            yield env
            cr.commit()
        except Exception:
            cr.rollback()
            raise
