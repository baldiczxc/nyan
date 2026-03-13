import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters as Filters, ContextTypes

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message if update.message else update.channel_post
    if not msg:
        return
    if getattr(msg, 'forward_origin', None):
        from telegram import MessageOriginChannel
        if isinstance(msg.forward_origin, MessageOriginChannel):
            await msg.reply_text(f'Forwarded from channel, ID: {msg.forward_origin.chat.id}')
        else:
            await msg.reply_text(f'Forwarded from unknown origin type')
    else:
        if getattr(msg, 'chat', None):
           await msg.reply_text(f'Chat ID: {msg.chat.id}')

if __name__ == '__main__':
    app = ApplicationBuilder().token('8785400748:AAHylzfnfAaclikD_t8qcdvO6jj8V7KhiKU').build()
    app.add_handler(MessageHandler(Filters.ALL, handle_msg))
    print('Bot started. Send/forward a message to it to get chat ID.')
    app.run_polling()
