# -*- coding: utf-8 -*-
{
    "name": "Ustalar service Bot",
    "version": "18.0.1.0.0",
    "summary": "Ustalar uchun Telegram bot (ro‘yxatdan o‘tish, aktiv zayafkalar, balans, tarix)",
    "category": "Tools",
    "author": "Shohjahon Obruyev",
    "license": "LGPL-3",
    "depends": [
        "base",
        "crm",
        "call_center_employees", 
        "employee_zapchast",            
        "cc_finance",             
    ],
    "data": [
        # "views/warranty_bot_settings_views.xml"
    ],
    "external_dependencies": {
        "python": [
            "aiogram",
            "xlsxwriter",
            "requests",
        ]
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
