import json
import os
import argparse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

ADMIN_IDS = [int(i) for i in os.environ.get("ADMIN_IDS", "").split(",") if i]
CHANNELS_PATH = os.environ.get("CHANNELS_PATH", "channels.json")

# Conversation states
AWAIT_CHANNEL_NAME, AWAIT_GROUP_NAME, AWAIT_ALIAS_NAME = range(3)

def load_channels():
    with open(CHANNELS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_channels(data):
    with open(CHANNELS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_admin(update):
    if not ADMIN_IDS:
        return True
    return update.effective_user.id in ADMIN_IDS

def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 Список каналов", callback_data="list_channels")],
        [InlineKeyboardButton("➕ Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton("❌ Удалить канал", callback_data="remove_channel_list")],
    ]
    return InlineKeyboardMarkup(keyboard)

def start(update: Update, context: CallbackContext):
    if not is_admin(update):
        return
    update.message.reply_text(
        "👋 Добро пожаловать в панель управления News Aggregator!\nВыберите действие:",
        reply_markup=build_main_menu()
    )

def main_menu_callback(update: Update, context: CallbackContext):
    if not is_admin(update):
        return
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        "👋 Добро пожаловать в панель управления News Aggregator!\nВыберите действие:",
        reply_markup=build_main_menu()
    )

def list_channels_callback(update: Update, context: CallbackContext):
    if not is_admin(update):
        return
    query = update.callback_query
    query.answer()

    try:
        data = load_channels()
        lines = [f"<b>Всего каналов: {len(data['channels'])}</b>\n"]
        for ch in data["channels"]:
            status = " <i>(Отключен)</i>" if ch.get("disabled") else ""
            lines.append(f"• <b>{ch['name']}</b> [{ch['groups'].get('main', 'none')}]{status}")
        
        text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Telegram message length limit is 4096. We split if it exceeds.
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                if i + 4000 >= len(text):
                    query.message.reply_html(text[i:i+4000], reply_markup=reply_markup)
                else:
                    query.message.reply_html(text[i:i+4000])
        else:
            query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        query.edit_message_text(f"Ошибка: {e}")

def add_channel_start(update: Update, context: CallbackContext):
    if not is_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_action")]]
    query.edit_message_text(
        "Введите системное имя канала (например: <code>rian_ru</code>):", 
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AWAIT_CHANNEL_NAME

def add_channel_name_received(update: Update, context: CallbackContext):
    context.user_data['new_channel_name'] = update.message.text.strip()
    
    keyboard = [
        [InlineKeyboardButton("🔴 red (Новости/Политика)", callback_data="group_red")],
        [InlineKeyboardButton("🔵 blue (Либеральные/Оппозиция)", callback_data="group_blue")],
        [InlineKeyboardButton("🟣 purple (Разное/Поп)", callback_data="group_purple")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_action")]
    ]
    update.message.reply_text(
        f"Отлично. Теперь выберите группу (эмодзи-окрас) для канала <b>{context.user_data['new_channel_name']}</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AWAIT_GROUP_NAME

def add_channel_group_received(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    group = query.data.replace("group_", "")
    context.user_data['new_channel_group'] = group
    
    keyboard = [[InlineKeyboardButton("Пропустить (оставить как системное)", callback_data="skip_alias")]]
    query.edit_message_text(
        f"Группа <b>{group}</b> выбрана.\nВведите человекочитаемое название (алиас) канала, которое будет отображаться в постах:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AWAIT_ALIAS_NAME

def add_channel_alias_received(update: Update, context: CallbackContext):
    alias = update.message.text.strip()
    return finish_add_channel(update.message, context, alias)

def add_channel_skip_alias(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    alias = context.user_data['new_channel_name']
    return finish_add_channel(query.message, context, alias, from_query=True)

def finish_add_channel(message, context: CallbackContext, alias: str, from_query=False):
    name = context.user_data['new_channel_name']
    group = context.user_data['new_channel_group']
    
    try:
        data = load_channels()
        # Check uniqueness
        if any(ch["name"] == name for ch in data["channels"]):
             text = f"Канал <b>{name}</b> уже существует!"
        else:
            data["channels"].append({
                "name": name,
                "groups": {
                    "main": group,
                    "tech": "tech" if group == "purple" else "other"
                },
                "alias": alias,
                "issue": "main"
            })
            save_channels(data)
            text = f"✅ Канал <b>{alias}</b> (<code>{name}</code>) успешно добавлен в группу <b>{group}</b>!"
            
        keyboard = [[InlineKeyboardButton("◀️ В главное меню", callback_data="main_menu")]]
        if from_query:
            message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        message.reply_text(f"Ошибка сохранения: {e}")

    return ConversationHandler.END


def remove_channel_start(update: Update, context: CallbackContext):
    if not is_admin(update):
        return
    query = update.callback_query
    query.answer()
    
    data = load_channels()
    keyboard = []
    
    # Due to limits, we show max 50 recent channels, or add a pagination. 
    # For simplicity, we list the last 50 added. 
    channels_to_show = data["channels"][-50:]
    
    for ch in channels_to_show:
        keyboard.append([InlineKeyboardButton(f"🗑 {ch['alias']} ({ch['name']})", callback_data=f"remove_{ch['name']}")])
        
    keyboard.append([InlineKeyboardButton("◀️ Назад в меню", callback_data="main_menu")])
    
    query.edit_message_text(
        "Выберите канал для удаления (показаны последние 50):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def remove_channel_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    channel_name = query.data.replace("remove_", "")
    
    try:
        data = load_channels()
        initial_len = len(data["channels"])
        data["channels"] = [ch for ch in data["channels"] if ch["name"] != channel_name]
        
        keyboard = [[InlineKeyboardButton("◀️ В главное меню", callback_data="main_menu")]]
        
        if len(data["channels"]) < initial_len:
            save_channels(data)
            query.edit_message_text(f"✅ Канал <code>{channel_name}</code> успешно удален!", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            query.edit_message_text(f"Канал <code>{channel_name}</code> не найден.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        query.edit_message_text(f"Ошибка: {e}")

def cancel_action(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        "Действие отменено.\nВыберите команду:",
        reply_markup=build_main_menu()
    )
    return ConversationHandler.END


def main():
    token = os.environ.get("ADMIN_BOT_TOKEN")
    if not token:
        print("Set ADMIN_BOT_TOKEN env variable.")
        return
        
    updater = Updater(token)
    dispatcher = updater.dispatcher
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_channel_start, pattern='^add_channel$')],
        states={
            AWAIT_CHANNEL_NAME: [MessageHandler(Filters.text & ~Filters.command, add_channel_name_received)],
            AWAIT_GROUP_NAME: [CallbackQueryHandler(add_channel_group_received, pattern='^group_')],
            AWAIT_ALIAS_NAME: [
                MessageHandler(Filters.text & ~Filters.command, add_channel_alias_received),
                CallbackQueryHandler(add_channel_skip_alias, pattern='^skip_alias$')
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_action, pattern='^cancel_action$')]
    )

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(main_menu_callback, pattern='^main_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(list_channels_callback, pattern='^list_channels$'))
    dispatcher.add_handler(CallbackQueryHandler(remove_channel_start, pattern='^remove_channel_list$'))
    dispatcher.add_handler(CallbackQueryHandler(remove_channel_confirm, pattern='^remove_'))
    dispatcher.add_handler(conv_handler)
    
    print("Interactive Admin bot started.")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
