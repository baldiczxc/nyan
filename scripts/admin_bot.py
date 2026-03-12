"""
Nyan News Admin Bot — полноценная панель управления через Telegram.

Возможности:
  - Управление каналами (список, добавление, удаление, toggle вкл/выкл)
  - Управление systemd-сервисами (статус, рестарт, стоп, старт)
  - Статистика из MongoDB (документы, кластеры, топ каналов)
  - Просмотр логов (journalctl)

Переменные окружения:
  ADMIN_BOT_TOKEN  — токен Telegram-бота
  ADMIN_IDS        — через запятую Telegram user IDs администраторов
  CHANNELS_PATH    — абсолютный путь к channels.json (по умолчанию channels.json)
  MONGO_CONFIG     — путь к mongo_config.json (по умолчанию configs/mongo_config.json)
"""

import json
import os
import subprocess
import time
from math import ceil
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters as Filters,
)
from telegram.warnings import PTBUserWarning
import warnings

warnings.filterwarnings(
    "ignore",
    category=PTBUserWarning,
    message="If 'per_message=False', 'CallbackQueryHandler' will not be tracked for every message."
)

# ─────────────────────────── Config ───────────────────────────

ADMIN_IDS: List[int] = [int(i) for i in os.environ.get("ADMIN_IDS", "").split(",") if i]
CHANNELS_PATH: str = os.environ.get("CHANNELS_PATH", "channels.json")
MONGO_CONFIG: str = os.environ.get("MONGO_CONFIG", "configs/mongo_config.json")

SERVICES = ["nyan-daemon", "nyan-crawler", "nyan-admin"]
CHANNELS_PER_PAGE = 20

# Conversation states
(
    AWAIT_CHANNEL_NAME,
    AWAIT_GROUP_NAME,
    AWAIT_EXTRA_GROUPS,
    AWAIT_ISSUE,
    AWAIT_ALIAS_NAME,
    AWAIT_SEARCH_QUERY,
) = range(6)

# ─────────────────────────── Helpers ──────────────────────────


def is_admin(update: Update) -> bool:
    if not ADMIN_IDS:
        return True
    user = update.effective_user
    return user is not None and user.id in ADMIN_IDS


def load_channels() -> Dict[str, Any]:
    with open(CHANNELS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_channels(data: Dict[str, Any]) -> None:
    with open(CHANNELS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_cmd(args: List[str], timeout: int = 15) -> str:
    """Run a shell command and return stdout+stderr."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout + result.stderr).strip()
        return output if output else "(пусто)"
    except subprocess.TimeoutExpired:
        return "⏱ Таймаут выполнения команды"
    except Exception as e:
        return f"Ошибка: {e}"


def get_mongo_stats() -> Dict[str, Any]:
    """Fetch basic stats from MongoDB."""
    try:
        from pymongo import MongoClient
        from nyan.mongo import read_config, get_database

        mongo_config = read_config(MONGO_CONFIG)
        db = get_database(mongo_config)

        now = int(time.time())
        one_hour_ago = now - 3600
        one_day_ago = now - 86400

        docs_col = db[mongo_config["documents_collection_name"]]
        clusters_col = db[mongo_config["clusters_collection_name"]]

        docs_total = docs_col.estimated_document_count()
        docs_24h = docs_col.count_documents({"pub_time": {"$gte": one_day_ago}})
        docs_1h = docs_col.count_documents({"pub_time": {"$gte": one_hour_ago}})

        clusters_total = clusters_col.estimated_document_count()
        clusters_24h = clusters_col.count_documents({"create_time": {"$gte": one_day_ago}})

        # Top channels last 24h
        pipeline = [
            {"$match": {"pub_time": {"$gte": one_day_ago}}},
            {"$group": {"_id": "$channel_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top_channels = list(docs_col.aggregate(pipeline))

        return {
            "docs_total": docs_total,
            "docs_24h": docs_24h,
            "docs_1h": docs_1h,
            "clusters_total": clusters_total,
            "clusters_24h": clusters_24h,
            "top_channels": top_channels,
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────── Menus ────────────────────────────


def build_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📋 Каналы", callback_data="channels_menu")],
        [InlineKeyboardButton("🖥 Сервисы", callback_data="services_menu")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("📜 Логи", callback_data="logs_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_channels_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📋 Список каналов", callback_data="ch_list:0")],
        [InlineKeyboardButton("🔍 Поиск канала", callback_data="ch_search")],
        [InlineKeyboardButton("➕ Добавить канал", callback_data="ch_add")],
        [InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_services_menu() -> InlineKeyboardMarkup:
    buttons = []
    for svc in SERVICES:
        buttons.append(
            [InlineKeyboardButton(f"🔧 {svc}", callback_data=f"svc_detail:{svc}")]
        )
    buttons.append([InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def build_logs_menu() -> InlineKeyboardMarkup:
    buttons = []
    for svc in SERVICES:
        buttons.append(
            [InlineKeyboardButton(f"📜 {svc}", callback_data=f"log:{svc}")]
        )
    buttons.append([InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def back_button(callback: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Назад", callback_data=callback)]]
    )


# ─────────────────────────── Handlers: Navigation ─────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    assert update.message is not None
    await update.message.reply_text(
        "👋 <b>Nyan News Admin</b>\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=build_main_menu(),
    )


async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()
    await query.edit_message_text(
        "👋 <b>Nyan News Admin</b>\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=build_main_menu(),
    )


# ─────────────────────────── Handlers: Channels ──────────────


async def cb_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()
    await query.edit_message_text(
        "📋 <b>Управление каналами</b>",
        parse_mode="HTML",
        reply_markup=build_channels_menu(),
    )


async def cb_channel_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show paginated list of channels."""
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()

    page = int(query.data.split(":")[1])  # type: ignore[union-attr]

    try:
        data = load_channels()
        channels = data["channels"]
        total = len(channels)
        total_pages = max(1, ceil(total / CHANNELS_PER_PAGE))
        page = min(page, total_pages - 1)

        start = page * CHANNELS_PER_PAGE
        end = start + CHANNELS_PER_PAGE
        page_channels = channels[start:end]

        active = sum(1 for ch in channels if not ch.get("disabled"))
        disabled = total - active

        lines = [
            f"<b>Каналы</b> (всего {total}: ✅{active} / 🚫{disabled})",
            f"Страница {page + 1}/{total_pages}\n",
        ]
        for ch in page_channels:
            status = "🚫" if ch.get("disabled") else "✅"
            group = ch.get("groups", {}).get("main", "?")
            emoji_map = {"red": "🔴", "blue": "🔵", "purple": "🟣"}
            dot = emoji_map.get(group, "⚪")
            lines.append(f"{status} {dot} <b>{ch.get('alias', ch['name'])}</b> — <code>{ch['name']}</code>")

        keyboard = []
        # Channel action buttons
        action_row = []
        for ch in page_channels:
            short = ch["name"][:20]
            action_row.append(
                InlineKeyboardButton(
                    f"{'🚫' if ch.get('disabled') else '✅'} {short}",
                    callback_data=f"ch_toggle:{ch['name']}:{page}",
                )
            )
            if len(action_row) == 2:
                keyboard.append(action_row)
                action_row = []
        if action_row:
            keyboard.append(action_row)

        # Pagination
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"ch_list:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"ch_list:{page + 1}"))
        keyboard.append(nav_row)

        keyboard.append([
            InlineKeyboardButton("🗑 Удалить канал", callback_data=f"ch_remove_list:{page}"),
        ])
        keyboard.append([
            InlineKeyboardButton("◀️ Назад", callback_data="channels_menu"),
        ])

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n..."

        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {e}", reply_markup=back_button("channels_menu")
        )


async def cb_channel_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle channel enabled/disabled."""
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()

    parts = query.data.split(":")  # type: ignore[union-attr]
    channel_name = parts[1]
    page = int(parts[2])

    try:
        data = load_channels()
        for ch in data["channels"]:
            if ch["name"] == channel_name:
                ch["disabled"] = not ch.get("disabled", False)
                new_status = "🚫 отключён" if ch["disabled"] else "✅ включён"
                save_channels(data)
                await query.answer(f"{ch.get('alias', channel_name)}: {new_status}", show_alert=True)
                break
        else:
            await query.answer("Канал не найден", show_alert=True)

        # Refresh the list
        query.data = f"ch_list:{page}"  # type: ignore[assignment]
        await cb_channel_list(update, context)
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {e}", reply_markup=back_button("channels_menu")
        )


async def cb_channel_remove_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of channels to remove."""
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()

    page = int(query.data.split(":")[1])  # type: ignore[union-attr]

    try:
        data = load_channels()
        channels = data["channels"]
        start = page * CHANNELS_PER_PAGE
        end = start + CHANNELS_PER_PAGE
        page_channels = channels[start:end]

        keyboard = []
        for ch in page_channels:
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 {ch.get('alias', ch['name'])} ({ch['name']})",
                    callback_data=f"ch_remove_confirm:{ch['name']}:{page}",
                )
            ])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"ch_list:{page}")])

        await query.edit_message_text(
            "🗑 <b>Выберите канал для удаления:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {e}", reply_markup=back_button("channels_menu")
        )


async def cb_channel_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm channel removal."""
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()

    parts = query.data.split(":")  # type: ignore[union-attr]
    channel_name = parts[1]
    page = parts[2]

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"ch_remove_do:{channel_name}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"ch_list:{page}"),
        ]
    ]
    await query.edit_message_text(
        f"Вы уверены, что хотите удалить канал <code>{channel_name}</code>?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cb_channel_remove_do(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Actually remove a channel."""
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()

    channel_name = query.data.split(":")[1]  # type: ignore[union-attr]

    try:
        data = load_channels()
        initial_len = len(data["channels"])
        data["channels"] = [ch for ch in data["channels"] if ch["name"] != channel_name]

        if len(data["channels"]) < initial_len:
            save_channels(data)
            text = f"✅ Канал <code>{channel_name}</code> удалён!"
        else:
            text = f"Канал <code>{channel_name}</code> не найден."

        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=back_button("channels_menu")
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {e}", reply_markup=back_button("channels_menu")
        )


# ── Channel search (conversation) ──


async def cb_channel_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    if not is_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    assert query is not None
    await query.answer()
    await query.edit_message_text(
        "🔍 Введите часть имени или алиаса канала:",
        reply_markup=back_button("channels_menu"),
    )
    return AWAIT_SEARCH_QUERY


async def search_query_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    q = update.message.text.strip().lower()

    try:
        data = load_channels()
        results = [
            ch for ch in data["channels"]
            if q in ch["name"].lower() or q in ch.get("alias", "").lower()
        ]

        if not results:
            await update.message.reply_text(
                f"Ничего не найдено по запросу «{q}».",
                reply_markup=back_button("channels_menu"),
            )
            return ConversationHandler.END

        lines = [f"<b>Результаты поиска «{q}» ({len(results)}):</b>\n"]
        keyboard = []
        for ch in results[:30]:
            status = "🚫" if ch.get("disabled") else "✅"
            group = ch.get("groups", {}).get("main", "?")
            emoji_map = {"red": "🔴", "blue": "🔵", "purple": "🟣"}
            dot = emoji_map.get(group, "⚪")
            lines.append(f"{status} {dot} <b>{ch.get('alias', ch['name'])}</b> — <code>{ch['name']}</code>")
            keyboard.append([
                InlineKeyboardButton(
                    f"{'🚫→✅' if ch.get('disabled') else '✅→🚫'} {ch['name'][:25]}",
                    callback_data=f"ch_toggle:{ch['name']}:0",
                )
            ])

        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="channels_menu")])

        await update.message.reply_html(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

    return ConversationHandler.END


# ── Add channel (conversation) ──


async def cb_add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    if not is_admin(update):
        return ConversationHandler.END
    query = update.callback_query
    assert query is not None
    await query.answer()
    await query.edit_message_text(
        "Введите системное имя канала (например: <code>rian_ru</code>):",
        parse_mode="HTML",
        reply_markup=back_button("channels_menu"),
    )
    return AWAIT_CHANNEL_NAME


async def add_channel_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    assert context.user_data is not None
    context.user_data["new_channel_name"] = update.message.text.strip()

    keyboard = [
        [InlineKeyboardButton("🔴 red (Провластные)", callback_data="group_red")],
        [InlineKeyboardButton("🔵 blue (Оппозиция)", callback_data="group_blue")],
        [InlineKeyboardButton("🟣 purple (Нейтральные)", callback_data="group_purple")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_conv")],
    ]
    await update.message.reply_text(
        f"Выберите группу для <b>{context.user_data['new_channel_name']}</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return AWAIT_GROUP_NAME


async def add_channel_group_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None
    assert context.user_data is not None
    await query.answer()
    group = query.data.replace("group_", "")  # type: ignore[union-attr]
    context.user_data["new_channel_group"] = group
    context.user_data["new_channel_extra"] = set()  # extra groups: economy, tech, entertainment

    return await _show_extra_groups(query, context)


def _build_extra_groups_keyboard(selected: set) -> InlineKeyboardMarkup:
    """Build toggle keyboard for extra topic groups."""
    labels = {
        "economy": "📈 Экономика",
        "tech": "💻 Технологии",
        "entertainment": "🎭 Развлечения",
        "svo": "🎖 СВО",
        "protivnik": "⚔️ Противник",
    }
    keyboard = []
    for key, label in labels.items():
        mark = "✅" if key in selected else "☐"
        keyboard.append([
            InlineKeyboardButton(f"{mark} {label}", callback_data=f"extra_{key}")
        ])
    keyboard.append([InlineKeyboardButton("➡️ Далее", callback_data="extra_done")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_conv")])
    return InlineKeyboardMarkup(keyboard)


async def _show_extra_groups(query: Any, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show/refresh the extra groups toggle screen."""
    assert context.user_data is not None
    selected = context.user_data["new_channel_extra"]
    group = context.user_data["new_channel_group"]
    sel_text = ", ".join(sorted(selected)) if selected else "нет"
    await query.edit_message_text(
        f"Основная группа: <b>{group}</b>\n"
        f"Доп. группы: <b>{sel_text}</b>\n\n"
        "Выберите дополнительные тематические группы:",
        parse_mode="HTML",
        reply_markup=_build_extra_groups_keyboard(selected),
    )
    return AWAIT_EXTRA_GROUPS


async def add_channel_extra_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle an extra group on/off."""
    query = update.callback_query
    assert query is not None
    assert context.user_data is not None
    await query.answer()
    key = query.data.replace("extra_", "")  # type: ignore[union-attr]
    selected: set = context.user_data["new_channel_extra"]
    if key in selected:
        selected.discard(key)
    else:
        selected.add(key)
    return await _show_extra_groups(query, context)


async def add_channel_extra_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Extra groups selected, proceed to issue selection."""
    query = update.callback_query
    assert query is not None
    assert context.user_data is not None
    await query.answer()

    # Determine available issues based on selected groups
    keyboard = [
        [InlineKeyboardButton("📰 main", callback_data="issue_main")],
    ]
    extra = context.user_data["new_channel_extra"]
    if "tech" in extra:
        keyboard.append([InlineKeyboardButton("💻 tech", callback_data="issue_tech")])
    if "economy" in extra:
        keyboard.append([InlineKeyboardButton("📈 economy", callback_data="issue_economy")])
    if "svo" in extra:
        keyboard.append([InlineKeyboardButton("🎖 svo", callback_data="issue_svo")])
    if "protivnik" in extra:
        keyboard.append([InlineKeyboardButton("⚔️ protivnik", callback_data="issue_protivnik")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_conv")])

    group = context.user_data["new_channel_group"]
    sel = context.user_data["new_channel_extra"]
    sel_text = ", ".join(sorted(sel)) if sel else "нет"
    await query.edit_message_text(
        f"Основная группа: <b>{group}</b>\n"
        f"Доп. группы: <b>{sel_text}</b>\n\n"
        "Выберите основной выпуск (issue) канала:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return AWAIT_ISSUE


async def add_channel_issue_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Issue selected, proceed to alias."""
    query = update.callback_query
    assert query is not None
    assert context.user_data is not None
    await query.answer()
    issue = query.data.replace("issue_", "")  # type: ignore[union-attr]
    context.user_data["new_channel_issue"] = issue

    keyboard = [
        [InlineKeyboardButton("⏩ Пропустить (= системное имя)", callback_data="skip_alias")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_conv")],
    ]
    await query.edit_message_text(
        f"Issue: <b>{issue}</b>\n"
        "Введите алиас (человекочитаемое название) канала:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return AWAIT_ALIAS_NAME


async def add_channel_alias_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    alias = update.message.text.strip()
    return await _finish_add_channel(update.message, context, alias)


async def add_channel_skip_alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None
    assert context.user_data is not None
    await query.answer()
    alias = context.user_data["new_channel_name"]
    return await _finish_add_channel(query.message, context, alias, from_query=True)


async def _finish_add_channel(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
    alias: str,
    from_query: bool = False,
) -> int:
    assert context.user_data is not None
    name = context.user_data["new_channel_name"]
    group = context.user_data["new_channel_group"]
    extra: set = context.user_data.get("new_channel_extra", set())
    issue = context.user_data.get("new_channel_issue", "main")

    try:
        data = load_channels()
        if any(ch["name"] == name for ch in data["channels"]):
            text = f"⚠️ Канал <code>{name}</code> уже существует!"
        else:
            # Build groups dict like the original template
            groups: Dict[str, str] = {"main": group}
            for ex in sorted(extra):
                groups[ex] = ex

            channel_entry: Dict[str, Any] = {
                "name": name,
                "alias": alias,
                "issue": issue,
                "groups": groups,
            }
            data["channels"].append(channel_entry)
            save_channels(data)

            groups_str = ", ".join(f"{k}={v}" for k, v in groups.items())
            text = (
                f"✅ Канал <b>{alias}</b> (<code>{name}</code>)\n"
                f"Issue: <b>{issue}</b>\n"
                f"Groups: <code>{groups_str}</code>"
            )

        kb = back_button("channels_menu")
        if from_query:
            await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        else:
            await message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await message.reply_text(f"❌ Ошибка: {e}")

    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "Действие отменено.",
            reply_markup=build_channels_menu(),
        )
    return ConversationHandler.END


# ─────────────────────────── Handlers: Services ───────────────


async def cb_services_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()
    await query.edit_message_text(
        "🖥 <b>Управление сервисами</b>\nВыберите сервис:",
        parse_mode="HTML",
        reply_markup=build_services_menu(),
    )


async def cb_service_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()

    svc = query.data.split(":")[1]  # type: ignore[union-attr]

    status_text = run_cmd(["systemctl", "status", svc, "--no-pager", "-l"])
    # Trim for Telegram message limit
    if len(status_text) > 3000:
        status_text = status_text[:3000] + "\n..."

    keyboard = [
        [
            InlineKeyboardButton("🔄 Рестарт", callback_data=f"svc_restart:{svc}"),
            InlineKeyboardButton("⏹ Стоп", callback_data=f"svc_stop:{svc}"),
            InlineKeyboardButton("▶️ Старт", callback_data=f"svc_start:{svc}"),
        ],
        [
            InlineKeyboardButton("🔃 Обновить", callback_data=f"svc_detail:{svc}"),
            InlineKeyboardButton("◀️ Назад", callback_data="services_menu"),
        ],
    ]

    await query.edit_message_text(
        f"🔧 <b>{svc}</b>\n\n<pre>{status_text}</pre>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cb_service_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle restart/stop/start actions on services."""
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None

    data_parts = query.data.split(":")  # type: ignore[union-attr]
    action = data_parts[0].replace("svc_", "")  # restart / stop / start
    svc = data_parts[1]

    await query.answer(f"Выполняю {action} {svc}...")

    output = run_cmd(["sudo", "systemctl", action, svc])
    result_text = f"✅ <code>systemctl {action} {svc}</code>\n\n<pre>{output}</pre>"

    keyboard = [
        [
            InlineKeyboardButton("🔃 Обновить статус", callback_data=f"svc_detail:{svc}"),
            InlineKeyboardButton("◀️ Назад", callback_data="services_menu"),
        ]
    ]

    await query.edit_message_text(
        result_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─────────────────────────── Handlers: Stats ──────────────────


async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer("Загрузка статистики...")

    stats = get_mongo_stats()

    if "error" in stats:
        await query.edit_message_text(
            f"❌ Ошибка MongoDB: <pre>{stats['error']}</pre>",
            parse_mode="HTML",
            reply_markup=back_button(),
        )
        return

    lines = [
        "<b>📊 Статистика</b>\n",
        "<b>Документы:</b>",
        f"  Всего: <code>{stats['docs_total']:,}</code>",
        f"  За 24ч: <code>{stats['docs_24h']:,}</code>",
        f"  За 1ч: <code>{stats['docs_1h']:,}</code>\n",
        "<b>Кластеры:</b>",
        f"  Всего: <code>{stats['clusters_total']:,}</code>",
        f"  За 24ч: <code>{stats['clusters_24h']:,}</code>\n",
    ]

    top = stats.get("top_channels", [])
    if top:
        lines.append("<b>Топ-10 каналов за 24ч:</b>")
        for i, ch in enumerate(top, 1):
            lines.append(f"  {i}. <code>{ch['_id']}</code> — {ch['count']}")

    keyboard = [
        [InlineKeyboardButton("🔃 Обновить", callback_data="stats")],
        [InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─────────────────────────── Handlers: Logs ───────────────────


async def cb_logs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer()
    await query.edit_message_text(
        "📜 <b>Просмотр логов</b>\nВыберите сервис:",
        parse_mode="HTML",
        reply_markup=build_logs_menu(),
    )


async def cb_log_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer("Загрузка логов...")

    svc = query.data.split(":")[1]  # type: ignore[union-attr]

    log_text = run_cmd(
        ["journalctl", "-u", svc, "-n", "50", "--no-pager", "-o", "short-iso"],
        timeout=10,
    )

    if len(log_text) > 3800:
        log_text = log_text[-3800:]

    keyboard = [
        [
            InlineKeyboardButton("🔃 Обновить", callback_data=f"log:{svc}"),
            InlineKeyboardButton("📜 100 строк", callback_data=f"log100:{svc}"),
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data="logs_menu")],
    ]

    await query.edit_message_text(
        f"📜 <b>{svc}</b> (последние 50 строк)\n\n<pre>{log_text}</pre>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cb_log_view_100(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    query = update.callback_query
    assert query is not None
    await query.answer("Загрузка логов...")

    svc = query.data.split(":")[1]  # type: ignore[union-attr]

    log_text = run_cmd(
        ["journalctl", "-u", svc, "-n", "100", "--no-pager", "-o", "short-iso"],
        timeout=10,
    )

    if len(log_text) > 3800:
        log_text = log_text[-3800:]

    keyboard = [
        [
            InlineKeyboardButton("🔃 Обновить", callback_data=f"log100:{svc}"),
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data="logs_menu")],
    ]

    await query.edit_message_text(
        f"📜 <b>{svc}</b> (последние 100 строк)\n\n<pre>{log_text}</pre>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─────────────────────────── Noop ─────────────────────────────


async def cb_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()


# ─────────────────────────── Main ─────────────────────────────


def main() -> None:
    token = os.environ.get("ADMIN_BOT_TOKEN")
    if not token:
        print("ERROR: Set ADMIN_BOT_TOKEN environment variable.")
        return

    app = ApplicationBuilder().token(token).build()

    # ── Conversation: Add channel ──
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_channel_start, pattern=r"^ch_add$")],
        states={
            AWAIT_CHANNEL_NAME: [
                MessageHandler(Filters.TEXT & ~Filters.COMMAND, add_channel_name_received),
            ],
            AWAIT_GROUP_NAME: [
                CallbackQueryHandler(add_channel_group_received, pattern=r"^group_"),
            ],
            AWAIT_EXTRA_GROUPS: [
                CallbackQueryHandler(add_channel_extra_toggle, pattern=r"^extra_(economy|tech|entertainment|svo|protivnik)$"),
                CallbackQueryHandler(add_channel_extra_done, pattern=r"^extra_done$"),
            ],
            AWAIT_ISSUE: [
                CallbackQueryHandler(add_channel_issue_received, pattern=r"^issue_"),
            ],
            AWAIT_ALIAS_NAME: [
                MessageHandler(Filters.TEXT & ~Filters.COMMAND, add_channel_alias_received),
                CallbackQueryHandler(add_channel_skip_alias, pattern=r"^skip_alias$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern=r"^cancel_conv$")],
    )

    # ── Conversation: Search channel ──
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_channel_search_start, pattern=r"^ch_search$")],
        states={
            AWAIT_SEARCH_QUERY: [
                MessageHandler(Filters.TEXT & ~Filters.COMMAND, search_query_received),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_conv, pattern=r"^cancel_conv$")],
    )

    # ── Register handlers (order matters!) ──
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(add_conv)
    app.add_handler(search_conv)

    # Navigation
    app.add_handler(CallbackQueryHandler(cb_main_menu, pattern=r"^main_menu$"))
    app.add_handler(CallbackQueryHandler(cb_channels_menu, pattern=r"^channels_menu$"))
    app.add_handler(CallbackQueryHandler(cb_services_menu, pattern=r"^services_menu$"))
    app.add_handler(CallbackQueryHandler(cb_logs_menu, pattern=r"^logs_menu$"))
    app.add_handler(CallbackQueryHandler(cb_noop, pattern=r"^noop$"))

    # Channels
    app.add_handler(CallbackQueryHandler(cb_channel_list, pattern=r"^ch_list:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_channel_toggle, pattern=r"^ch_toggle:"))
    app.add_handler(CallbackQueryHandler(cb_channel_remove_list, pattern=r"^ch_remove_list:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_channel_remove_confirm, pattern=r"^ch_remove_confirm:"))
    app.add_handler(CallbackQueryHandler(cb_channel_remove_do, pattern=r"^ch_remove_do:"))

    # Services
    app.add_handler(CallbackQueryHandler(cb_service_detail, pattern=r"^svc_detail:"))
    app.add_handler(CallbackQueryHandler(cb_service_action, pattern=r"^svc_(restart|stop|start):"))

    # Stats
    app.add_handler(CallbackQueryHandler(cb_stats, pattern=r"^stats$"))

    # Logs
    app.add_handler(CallbackQueryHandler(cb_log_view_100, pattern=r"^log100:"))
    app.add_handler(CallbackQueryHandler(cb_log_view, pattern=r"^log:"))

    print(f"✅ Nyan Admin Bot started. Admins: {ADMIN_IDS or 'ALL'}")
    print(f"   Channels: {CHANNELS_PATH}")
    print(f"   Mongo config: {MONGO_CONFIG}")
    app.run_polling()


if __name__ == "__main__":
    main()
