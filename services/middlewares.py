# -*- coding: utf-8 -*-
# File: services/middlewares.py (create this new file)

from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from .runtime import open_env
from .usta_services import find_usta_by_tg

class UstaStatusMiddleware(BaseMiddleware):
    """
    Middleware to check if usta has active usta_status.
    If not, blocks all interactions except /start command.
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Get user ID from either Message or CallbackQuery
        user_id = None
        
        if isinstance(event, Message):
            user_id = event.from_user.id
            # Allow /start command to pass through
            if event.text and event.text.startswith('/start'):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            # For other event types, just pass through
            return await handler(event, data)
        
        if not user_id:
            return await handler(event, data)
        
        # Check usta status
        with open_env() as env:
            usta = find_usta_by_tg(env, user_id)
            
            # If no usta found, let registration flow handle it
            if not usta:
                return await handler(event, data)
            
            # Check if usta is active and has usta_status enabled
            if not usta.active or not getattr(usta, 'usta_status', False):
                # Send restriction message
                restricted_msg = (
                    "⚠️ <b>Faoliyat cheklangan</b>\n\n"
                    "Siz botda faoliyatingiz cheklangan.\n"
                    "Iltimos, adminlar bilan aloqalashing.\n\n"
                    "📞 Aloqa: +998 55 801 01 00"
                )
                
                if isinstance(event, Message):
                    await event.answer(restricted_msg, parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.answer(
                        "Faoliyatingiz cheklangan. Adminlar bilan bog'laning.",
                        show_alert=True
                    )
                
                # Block further execution
                return
        
        # If all checks pass, continue to handler
        return await handler(event, data)