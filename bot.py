import asyncio
import hashlib
import logging
import json
import hashlib
import os
import sys
from io import BytesIO
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from old_saloon import MODULES, MODULE_KEYS, ExpansionConfig
import saloon_bot
from saloon_runtime import enabled as advanced_saloon, ROLE_POWERS
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputFile, InputMediaPhoto, BotCommand,
    BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
)
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, TimedOut, NetworkError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
)

from data import (
    CHAR_BY_KEY,
    ROLE_CN, FACE_LABELS, ROLE_SETS, THREE_PLAYER_ROLES,
    BULL1, BULL2, BEER, DYNAMITE,
)
from game_engine import (
    count_symbols,
    Game, add_human, add_ai, remove_ai, remove_human, setup_game,
    roll_initial, reroll_selected, toggle_die, finalize_dice, pick_saloon_die, finish_broken_arrow_choice, choose_chief_arrow,
    apply_slab_choice, pop_next_action, finish_pending_action,
    start_damage_session, current_damage_choice, choose_damage_option,
    valid_targets_for_face, deal_damage, heal, heal_with_record, resolve_gatling, format_hit, format_action, format_final_results, winning_player_indices,
    end_turn, check_win, advance_if_current_eliminated,
)
from ai import run_ai_turn, run_ai_resolution
from renderer import render_board, render_lobby, ASSETS, preload_assets
from dice_animation import animation_path, mask_from_indices, preload_dice_animation_assets

load_dotenv()

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
    ],
    force=True,
)
log = logging.getLogger("bang-dice-bot")

TOKEN = os.getenv("BOT_TOKEN", "").strip()
GAMES: dict[int, Game] = {}
DM_READY: set[int] = set()
CHAT_LOCKS: dict[int, asyncio.Lock] = {}
# 玩家個人的私訊角色目錄；不會動群組牌桌的共用按鈕。
BROWSER_DM_MESSAGE_IDS: dict[tuple[int, int], int] = {}
DICE_TRAY_FILE_ID_CACHE = Path(__file__).resolve().parent / "dice_tray_animation_file_ids.json"
GATLING_FILE_ID_CACHE = Path(__file__).resolve().parent / "gatling_animation_file_ids.json"
GATLING_ANIMATION = ASSETS / "animations" / "gatling_barrage.mp4"
INDIAN_ANIMATION = ASSETS / "animations" / "indian_arrow_rain.mp4"
INDIAN_FILE_ID_CACHE = Path(__file__).resolve().parent / "indian_arrow_animation_file_ids.json"
PHOTO_FILE_ID_CACHE = Path(__file__).resolve().parent / "telegram_photo_file_ids.json"
STATIC_FILE_BYTES: dict[str, bytes] = {}


def _preload_private_files() -> dict[str, int]:
    """把私訊卡片先讀進 RAM；遊戲中不再臨時讀硬碟。"""
    total = 0
    files = []
    files.extend((ASSETS / "roles").glob("*.png"))
    files.extend((ASSETS / "cards").glob("*.png"))
    files.extend((ASSETS / "animations").glob("dice_mask_*.mp4"))
    for p in files:
        try:
            data = p.read_bytes()
            STATIC_FILE_BYTES[str(p)] = data
            total += len(data)
        except OSError:
            pass
    return {"files": len(STATIC_FILE_BYTES), "bytes": total}


async def post_init(application: Application):
    # 1) 啟動時一次預熱圖片/字型/骰子/角色素材。
    draw_stats, file_stats, dice_anim_stats = await asyncio.gather(
        asyncio.to_thread(preload_assets),
        asyncio.to_thread(_preload_private_files),
        asyncio.to_thread(preload_dice_animation_assets),
    )
    log.info("素材預載完成 | render=%s | static_files=%s (%.1f MB) | dice_anim=%s",
             draw_stats, file_stats["files"], file_stats["bytes"] / 1024 / 1024, dice_anim_stats)

    # 2) 直接由程式註冊 Telegram / 指令選單，不必再手動 BotFather /setcommands。
    group_commands = [
        BotCommand("newgame", "建立遊戲：原版／老酒館設定"),
        BotCommand("status", "重新整理目前牌桌"),
        BotCommand("rules", "查看遊戲規則"),
        BotCommand("cancel", "取消目前遊戲（房主）"),
        BotCommand("start", "BOT 說明"),
    ]
    private_commands = [
        BotCommand("start", "啟用私訊卡片"),
        BotCommand("role", "查看我的身分卡"),
        BotCommand("character", "查看我的角色能力卡"),
        BotCommand("cacheassets", "預先登記私訊卡片 file_id"),
        BotCommand("previewcard", "預覽指定角色卡"),
        BotCommand("assetversion", "檢查目前素材版本"),
        BotCommand("rules", "查看遊戲規則"),
    ]
    try:
        await application.bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
        await application.bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
        # default scope 也設一份，避免部分 Telegram 客戶端尚未刷新 scope 時完全沒有選單。
        await application.bot.set_my_commands(group_commands)
        log.info("Telegram 指令選單已註冊：群組 %d 個 / 私訊 %d 個", len(group_commands), len(private_commands))
    except (TimedOut, NetworkError, BadRequest) as e:
        log.warning("註冊 Telegram 指令選單失敗，BOT 仍會繼續啟動：%s", e)




def _load_photo_file_id_cache() -> dict[str, str]:
    if PHOTO_FILE_ID_CACHE.exists():
        try:
            data = json.loads(PHOTO_FILE_ID_CACHE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if v}
        except Exception as e:
            log.warning("載入 photo file_id 快取失敗：%s", e)
    return {}


def _save_photo_file_id_cache(cache_map: dict[str, str]):
    try:
        PHOTO_FILE_ID_CACHE.write_text(
            json.dumps(cache_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.warning("儲存 photo file_id 快取失敗：%s", e)


def _photo_cache_key(path: Path) -> str:
    rel = path.relative_to(ASSETS) if path.is_absolute() else path
    return f"{rel.as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()[:20]}"


async def _send_cached_photo_asset(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    asset_path: Path,
    caption: str,
) -> bool:
    if not asset_path.exists():
        await context.bot.send_message(chat_id, caption)
        return True

    cache_map = context.bot_data.get("photo_file_ids")
    if cache_map is None:
        cache_map = _load_photo_file_id_cache()
        context.bot_data["photo_file_ids"] = cache_map

    key = _photo_cache_key(asset_path)
    file_id = cache_map.get(key)

    async def _send_via_upload() -> bool:
        data = STATIC_FILE_BYTES.get(str(asset_path)) or asset_path.read_bytes()
        msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=InputFile(BytesIO(data), filename=asset_path.name),
            caption=caption,
            read_timeout=30,
            write_timeout=45,
            connect_timeout=20,
            pool_timeout=20,
        )
        if getattr(msg, "photo", None):
            try:
                fid = msg.photo[-1].file_id
                cache_map[key] = fid
                _save_photo_file_id_cache(cache_map)
            except Exception:
                pass
        return True

    if file_id:
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=caption,
                read_timeout=30,
                write_timeout=45,
                connect_timeout=20,
                pool_timeout=20,
            )
            return True
        except BadRequest as e:
            log.warning("photo file_id 失效，改用實體檔重傳：%s | %s", asset_path.name, e)
            cache_map.pop(key, None)
            _save_photo_file_id_cache(cache_map)
        except (TimedOut, NetworkError) as e:
            log.warning("用 photo file_id 傳送失敗，改用實體檔重傳：%s | %s", asset_path.name, e)

    await _send_via_upload()
    return True


async def _cache_all_photo_assets(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> tuple[int, int]:
    paths: list[Path] = []
    paths.extend(sorted((ASSETS / "roles").glob("*.png")))
    paths.extend(sorted((ASSETS / "cards").glob("*.png")))
    paths.extend(sorted((ASSETS / "old_saloon" / "cards").glob("*.png")))
    paths.extend(sorted((ASSETS / "undead" / "cards").glob("*.png")))
    ok = 0
    total = 0
    for path in paths:
        if path.name.startswith("放"):
            continue
        total += 1
        try:
            done = await _send_cached_photo_asset(
                context=context,
                chat_id=chat_id,
                asset_path=path,
                caption=f"cache::{path.stem}",
            )
            if done:
                ok += 1
        except (TimedOut, NetworkError, BadRequest, Forbidden) as e:
            log.warning("預先快取素材失敗 %s: %s", path.name, e)
    return ok, total

# ============================================================
# 身分卡新手說明：依「3 人特殊局 / 4～8 人一般局」顯示正確勝利目標。
# 私訊照片的 caption 會連同該張剪影卡送達；快取 file_id 不影響 caption。
# ============================================================
ROLE_HELP_STANDARD = {
    "sheriff": (
        "🎯 勝利目標：消滅全部歹徒與叛徒。\n"
        "⭐ 特殊效果：你的角色原始最大生命值 +2。\n"
        "👁 身分公開：其他玩家從開局就知道你是警長。\n"
        "🏆 所有歹徒與叛徒都被淘汰時，警長與副警長一起獲勝。"
    ),
    "deputy": (
        "🎯 勝利目標：保護警長，協助警長打敗歹徒與叛徒。\n"
        "🤫 身分隱藏：只有自己知道，淘汰後才公開。\n"
        "🏆 警長陣營勝利時，你也會勝利，即使你已被淘汰。"
    ),
    "outlaw": (
        "🎯 勝利目標：讓警長被淘汰。\n"
        "🤫 身分隱藏：歹徒是同一陣營，但不知道彼此的身分。\n"
        "🏆 警長死亡時，只要不是叛徒單獨存活，全部歹徒獲勝；已淘汰的歹徒也算贏。"
    ),
    "renegade": (
        "🎯 勝利目標：成為全場最後一位存活者。\n"
        "🤫 身分隱藏：你是獨立陣營，不與其他身分同隊。\n"
        "⚠️ 必須等其他所有人出局，自己仍活著才能勝利；警長提早死亡通常會讓歹徒獲勝。"
    ),
}

THREE_PLAYER_MISSIONS = {
    "deputy": "叛徒",
    "outlaw": "副警長",
    "renegade": "歹徒",
}


def role_explanation(game: Game, role: str) -> str:
    """傳給私人玩家的完整身分規則；不在公共聊天室揭露玩家身分。"""
    if len(game.players) == 3:
        target = THREE_PLAYER_MISSIONS[role]
        first = "\n🥇 副警長第一個行動。" if role == "deputy" else ""
        return (
            "📘 三人局特殊規則（身分全部公開）\n"
            f"🎯 你的目標：親手淘汰「{target}」，即可立刻獲勝。{first}\n"
            "⚠️ 若目標被第三人淘汰，沒有任何人立即獲勝；"
            "剩下兩人改成決鬥，最後活著的人獲勝。\n"
            "🚫 三人局沒有警長，沒有警長 +2 生命加成。"
        )
    text = ROLE_HELP_STANDARD[role]
    if role == "renegade" and len(game.players) == 8:
        text += "\n⚠️ 8 人局有 2 名叛徒，但兩人不是隊友，只有最後存活的那一人能贏。"
    return text


def role_card_caption(game: Game, role: str) -> str:
    prefix = "🎭 你的公開身分" if len(game.players) == 3 else "🤫 你的秘密身分"
    return f"{prefix}：{ROLE_CN[role]}\n\n{role_explanation(game, role)}\n\n💡 不確定規則？可以再私訊輸入 /role 查看。"


def role_alert(game: Game, role: str) -> str:
    # Telegram answerCallbackQuery 顯示文字上限 200 字元。
    text = f"🎭 你的身分：{ROLE_CN[role]}\n{role_explanation(game, role)}"
    if len(text) <= 200:
        return text
    # 優先讓新手看完整勝利目標，其他細節在私訊卡下方。
    if len(game.players) == 3:
        return (
            f"🎭 {ROLE_CN[role]}（三人局身分公開）\n"
            f"🎯 親手淘汰{THREE_PLAYER_MISSIONS[role]}即勝。"
            "若目標被第三人淘汰，剩下兩人決鬥，最後存活者獲勝。\n"
            "詳細規則請看私訊身分卡或 /role。"
        )
    short = {
        "sheriff": "消滅所有歹徒與叛徒。身分公開，最大生命 +2；全清除後警長與副警長同勝。",
        "deputy": "保護警長。歹徒與叛徒全數淘汰則警長陣營勝，你即使陣亡也算勝利。",
        "outlaw": "讓警長死亡。除非最後只剩叛徒一人，否則所有歹徒都算獲勝。",
        "renegade": "獨立陣營，必須成為最後唯一存活者。8 人局兩位叛徒也不是隊友。",
    }
    return f"🎭 {ROLE_CN[role]}\n🎯 {short[role]}\n更多說明：私訊 /role。"


def chat_lock(chat_id: int) -> asyncio.Lock:
    lock = CHAT_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        CHAT_LOCKS[chat_id] = lock
    return lock

# 根據實際配牌資料自動製作規則表；修改 ROLE_SETS 後 /rules 也會同步。
ROLE_DISTRIBUTION_LINES = ["👥 3～8 人身分牌分配："]
for _players in range(3, 9):
    _roles = THREE_PLAYER_ROLES if _players == 3 else ROLE_SETS[_players]
    _role_counts = Counter(_roles)
    _role_pieces = [
        f"{ROLE_CN[_role]}×{_role_counts[_role]}"
        for _role in ("sheriff", "deputy", "outlaw", "renegade")
        if _role_counts[_role]
    ]
    _suffix = "（身分全部公開）" if _players == 3 else ""
    ROLE_DISTRIBUTION_LINES.append(f"{_players} 人：{'、'.join(_role_pieces)}{_suffix}")
ROLE_DISTRIBUTION_TEXT = "\n".join(ROLE_DISTRIBUTION_LINES)


RULES_TEXT = f"""🤠 BANG! 骰子版 BOT

基本流程：
• 3～8 人；3 人局所有身分公開，4～8 人局警長公開、其他身分保密。
• 每回合先擲 5 顆骰子，最多再重擲 2 次；幸運公爵可多重擲 1 次。
• 💥 炸藥通常不能重擲；累積 3 顆以上會失去 1 點生命並停止重擲。
• 🏹 箭在每次擲出時立刻拿取；拿走最後 1 支箭會觸發印第安人攻擊。
• 看圓桌選目標：射手旁邊一位是 🎯1，隔一位是 🎯2；死亡玩家不佔距離。
• 選射擊時金框是射手、紅框是可以射擊的座位，直接按玩家姓名。
• 只剩 2～3 人時，🎯2 改成可射擊鄰座；特殊角色依各自能力調整。
• 🍺 可讓任一存活玩家回血。
• 🔫 3 個格林機槍會掃射其他所有玩家，並丟掉自己全部的箭。
• 群組牌桌下方可直接查看自己的角色、身分與公開角色能力；看自己的身分不會在群組暴露。

{ROLE_DISTRIBUTION_TEXT}

🎭 4～8 人局：四種身分怎麼贏？
⭐ 警長：開局公開，最大生命 +2；所有歹徒和叛徒淘汰則與副警長同勝。
🛡 副警長：秘密保護警長；警長陣營勝利就算贏，即使自己先淘汰。
🔫 歹徒：秘密身分；讓警長死亡，除非最後只有叛徒活著，否則全部歹徒獲勝。
🃏 叛徒：秘密、獨自作戰；必須成為場上最後的唯一存活者。8 人局兩位叛徒也非同隊。

🧩 3 人特殊局（沒有警長，全部身分公開）：
• 副警長先手，目標親手淘汰叛徒。
• 叛徒目標親手淘汰歹徒。
• 歹徒目標親手淘汰副警長。
• 若目標被第三人淘汰，剩下兩人決鬥，最後存活者獲勝。

📩 開局時 BOT 會私訊你的身分卡與詳細勝利說明；可輸入 /role 再看一次。

目前版本：3～8 人、AI、16 位基本角色＋8 位擴充角色、五項老酒館模組。
"""


def get_game(update: Update) -> Game | None:
    chat = update.effective_chat
    return GAMES.get(chat.id) if chat else None


def short_face(face: str) -> str:
    return {
        "bull1": "🎯1",
        "bull2": "🎯2",
        "beer": "🍺",
        "arrow": "🏹",
        "gatling": "🔫",
        "dynamite": "💥",
        "bullet": "💔",
        "broken_arrow": "🏹−",
        "double_bull1": "🎯1×2",
        "double_bull2": "🎯2×2",
        "double_beer": "🍺×2",
        "double_gatling": "🔫×2",
    }.get(face, "?")


def is_current_human(game: Game, user_id: int) -> bool:
    p = game.current_player()
    return p.alive and not p.is_ai and p.pid == user_id


def find_player_game(user_id: int) -> tuple[Game, int] | tuple[None, None]:
    for g in GAMES.values():
        if g.phase == "ended":
            continue
        for i, p in enumerate(g.players):
            if not p.is_ai and p.pid == user_id:
                return g, i
    return None, None


async def bot_dm_url(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.bot.username
    if not username:
        me = await context.bot.get_me()
        username = me.username
    return f"https://t.me/{username}?start=ready"


def lobby_keyboard(game: Game) -> InlineKeyboardMarkup:
    config = game.expansion_config
    rows = [
        [InlineKeyboardButton("➕ 加入", callback_data="lobby:join"),
         InlineKeyboardButton("➖ 離開", callback_data="lobby:leave")],
        [InlineKeyboardButton("🤖 加電腦", callback_data="lobby:addai"),
         InlineKeyboardButton("🤖 減電腦", callback_data="lobby:delai")],
        [InlineKeyboardButton(("✅ " if config.mode == "base" else "") + "原版", callback_data="lobby:mode:base"),
         InlineKeyboardButton(("✅ " if config.mode == "saloon" else "") + "擴充設定", callback_data="lobby:mode:saloon")],
    ]
    if config.mode == "saloon":
        for key, label in MODULES:
            selected = key in config.modules
            rows.append([InlineKeyboardButton(("✅ " if selected else "▫️ ") + label, callback_data=f"lobby:mod:{key}")])
        rows.append([InlineKeyboardButton("☑️ 全選", callback_data="lobby:all"),
                     InlineKeyboardButton("⬜ 全不選", callback_data="lobby:none")])
    rows.extend([
        [InlineKeyboardButton("▶️ 開始", callback_data="lobby:start"),
         InlineKeyboardButton("📖 規則", callback_data="lobby:rules")],
        [InlineKeyboardButton("❌ 取消", callback_data="lobby:cancel")],
    ])
    return InlineKeyboardMarkup(rows)


def common_info_rows(game: Game | None = None):
    """固定資訊、規則與選用的特殊技能入口。"""
    rows = [
        [
            InlineKeyboardButton("🎭 我的角色", callback_data="info:character"),
            InlineKeyboardButton("🤫 我的身分", callback_data="info:role"),
        ],
        [InlineKeyboardButton("👀 查看角色", callback_data="info:players"),
         InlineKeyboardButton("📖 規則", callback_data="rules:open")],
    ]
    if game is not None and game.expansion_config.enabled("special_roles"):
        rows.append([InlineKeyboardButton("⚡ 特殊技能", callback_data="special:open")])
    return rows


def player_info_rows(game: Game) -> list[list[InlineKeyboardButton]]:
    """公開角色能力查詢。每位玩家都能看，秘密身分不會洩漏。"""
    circled = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"]
    buttons = []
    for i, p in enumerate(game.players[:8]):
        name = p.name.replace("\n", " ")[:7]
        buttons.append(InlineKeyboardButton(f"{circled[i]} {name}", callback_data=f"info:player:{i}"))
    return [buttons[i:i+4] for i in range(0, len(buttons), 4)]


def _public_character_detail(game: Game, idx: int) -> str:
    """角色能力公開；一般對局只有警長和已出局玩家公開身分。"""
    p = game.players[idx]
    c = p.character
    alive = "鬼魂（原角色能力停用）" if getattr(p, "is_ghost", False) else ("存活" if p.alive else "已淘汰")
    role_public = f"\n🎭 公開身分：{ROLE_CN[p.role]}" if len(game.players) == 3 or getattr(p, "role_revealed", False) or p.role == "sheriff" or not p.alive else ""
    return (
        f"👤 {p.name}\n🎭 {c.cn}（{c.en}）\n"
        f"❤️ 生命：{p.hp}/{p.max_hp}　🏹 箭：{p.arrows}　{alive}"
        f"{role_public}\n\n📜 角色能力：\n{c.ability}"
    )


def _public_character_summary(game: Game) -> str:
    """Telegram 警示視窗最多 200 字；只揭露合法公開的身分。"""
    lines = ["👀 目前公開角色資料："]
    for i, p in enumerate(game.players):
        role = f"／{ROLE_CN[p.role]}" if len(game.players) == 3 or getattr(p, "role_revealed", False) or p.role == "sheriff" or not p.alive else ""
        status = "💀" if not p.alive else ""
        lines.append(f"{i+1}.{p.name[:6]}-{p.character.cn}{role}{status}")
    lines.append("私訊 BOT 可看能力全文。")
    result = "\n".join(lines)
    return result[:200]


def _browse_keyboard(game: Game, selected: int | None = None) -> InlineKeyboardMarkup:
    if selected is not None:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅ 返回角色列表", callback_data=f"browse:back:{game.chat_id}"),
        ]])
    rows = []
    for i in range(0, len(game.players), 2):
        row = []
        for j in range(i, min(i+2, len(game.players))):
            p = game.players[j]
            row.append(InlineKeyboardButton(
                f"{j+1} {p.character.cn}", callback_data=f"browse:view:{game.chat_id}:{j}"
            ))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _browse_list_text(game: Game) -> str:
    lines = ["👀 本局公開角色資訊", "點下方角色按鈕，可以查看該角色的生命、箭與完整能力。"]
    for i, p in enumerate(game.players):
        public_role = (f"　🎭{ROLE_CN[p.role]}"
                       if len(game.players) == 3 or getattr(p, "role_revealed", False) or p.role == "sheriff" or not p.alive else "")
        lines.append(f"{i+1}. {p.name[:20]} — {p.character.cn}　♥{p.hp}/{p.max_hp}" + ("（已淘汰）" if not p.alive else "") + public_role)
    lines.append("\n🔒 存活玩家的秘密身分仍保密；已淘汰玩家的身分公開。")
    return "\n".join(lines)


async def _open_private_character_browser(context: ContextTypes.DEFAULT_TYPE, game: Game, user_id: int) -> None:
    """只建立／更新該玩家自己的私訊，切勿 edit 群組共用牌桌的按鈕。"""
    key = (user_id, game.chat_id)
    previous = BROWSER_DM_MESSAGE_IDS.get(key)
    message = _browse_list_text(game)
    keyboard = _browse_keyboard(game)
    if previous:
        try:
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=previous,
                text=message, reply_markup=keyboard,
            )
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            BROWSER_DM_MESSAGE_IDS.pop(key, None)
    msg = await context.bot.send_message(user_id, message, reply_markup=keyboard)
    BROWSER_DM_MESSAGE_IDS[key] = msg.message_id


async def _private_browser_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    parts = (q.data or "").split(":")
    if not q.message or q.message.chat.type != ChatType.PRIVATE or len(parts) not in (3, 4):
        await q.answer("請在 BOT 私訊中查看角色。", show_alert=True)
        return
    try:
        group_id = int(parts[2])
    except ValueError:
        await q.answer("角色列表已失效。", show_alert=True)
        return
    game = GAMES.get(group_id)
    if not game or game.phase == "lobby" or not any(
        not p.is_ai and p.pid == q.from_user.id for p in game.players
    ):
        await q.answer("本局已結束或你不是本局玩家。", show_alert=True)
        return
    if parts[1] == "back" and len(parts) == 3:
        value, keyboard = _browse_list_text(game), _browse_keyboard(game)
    elif parts[1] == "view" and len(parts) == 4:
        try:
            idx = int(parts[3])
        except ValueError:
            await q.answer("角色索引錯誤。", show_alert=True)
            return
        if not 0 <= idx < len(game.players):
            await q.answer("找不到這個角色。", show_alert=True)
            return
        value, keyboard = _public_character_detail(game, idx), _browse_keyboard(game, idx)
    else:
        await q.answer("角色列表已失效。", show_alert=True)
        return
    await q.answer()
    try:
        await q.edit_message_text(text=value, reply_markup=keyboard)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            log.warning("私訊查看角色失敗: %s", exc)


def game_keyboard(game: Game) -> InlineKeyboardMarkup | None:
    if getattr(game, "saloon_runtime", None) and game.phase != "ended":
        return saloon_bot.keyboard(game, common_info_rows(game))
    if game.phase == "ended":
        return InlineKeyboardMarkup(common_info_rows(game))
    if game.phase == "chief_arrow_choice":
        rows = []
        if game.arrows_pool > 0:
            rows.append([InlineKeyboardButton("🏹 拿普通箭", callback_data="chief:normal")])
        if game.chief_arrow_owner is None:
            rows.append([InlineKeyboardButton("👑🏹 拿酋長箭（計 2 支）", callback_data="chief:yes")])
        return InlineKeyboardMarkup(rows + common_info_rows(game))
    if game.phase == "broken_arrow_choice":
        rows = []
        choices = [i for i, p in enumerate(game.players) if p.alive and p.arrows > 0]
        for start in range(0, len(choices), 2):
            rows.append([InlineKeyboardButton(f"🏹 移除 {game.players[i].name} 1支箭", callback_data=f"broken:{i}") for i in choices[start:start+2]])
        return InlineKeyboardMarkup(rows + common_info_rows(game))
    if game.phase == "damage_choice":
        choice = current_damage_choice(game)
        if not choice:
            return InlineKeyboardMarkup(common_info_rows(game))
        rows = []
        for n in range(choice["max"] + 1):
            if choice["kind"] == "bart":
                label = "❤️ 不擋，直接扣血" if n == 0 else f"🏹 用 {n} 支箭擋 {n} 血"
            else:
                label = "🪶 不丟箭" if n == 0 else f"🪶 丟掉 {n} 支箭"
            rows.append([InlineKeyboardButton(label, callback_data=f"dmg:{choice['idx']}:{n}")])
        return InlineKeyboardMarkup(rows + common_info_rows(game))

    p = game.current_player()
    rows = []

    if not p.is_ai:
        if game.phase == "turn_start":
            if p.character_key == "sid_ketchum" and not game.sid_done:
                targets = [i for i, x in enumerate(game.players) if x.alive]
                for start in range(0, len(targets), 2):
                    row = []
                    for i in targets[start:start+2]:
                        x = game.players[i]
                        row.append(InlineKeyboardButton(
                            f"💚 {x.name} {x.hp}/{x.max_hp}",
                            callback_data=f"sid:{i}"
                        ))
                    rows.append(row)
            else:
                if game.expansion_config.enabled("saloon_dice"):
                    rows.append([InlineKeyboardButton("🎲 普通骰（5顆）", callback_data="turn:choose:base")])
                    rows.append([InlineKeyboardButton("🔥 大嘴巴骰（4普通＋1特殊）", callback_data="turn:choose:loudmouth")])
                    rows.append([InlineKeyboardButton("🛡 膽小鬼骰（4普通＋1特殊）", callback_data="turn:choose:coward")])
                else:
                    rows.append([InlineKeyboardButton("🎲 擲骰子", callback_data="turn:roll")])

        elif game.phase == "rolling":
            row = []
            for i, face in enumerate(game.dice):
                locked = face == DYNAMITE and (
                    p.character_key != "black_jack" or game.dice.count(DYNAMITE) >= 3
                )
                mark = "🔒" if locked else ("✅" if i in game.selected else "")
                row.append(InlineKeyboardButton(
                    f"{mark}{i+1}{short_face(face)}",
                    callback_data=f"die:{i}"
                ))
            rows.append(row[:3])
            rows.append(row[3:])
            rows.append([
                InlineKeyboardButton("🎲 重擲選取", callback_data="turn:reroll"),
                InlineKeyboardButton("✅ 確定結果", callback_data="turn:final"),
            ])

        elif game.phase == "slab_choice":
            if count_symbols(game, BULL1):
                rows.append([InlineKeyboardButton("💥 加倍 1 號準心", callback_data="slab:bull1")])
            if count_symbols(game, BULL2):
                rows.append([InlineKeyboardButton("💥 加倍 2 號準心", callback_data="slab:bull2")])
            rows.append([InlineKeyboardButton("🍺 不加倍，保留啤酒回血", callback_data="slab:0")])

        elif game.phase == "resolving":
            a = game.pending_action
            if a:
                typ = a["type"]
                if typ == "shot":
                    valid = valid_targets_for_face(game, game.current_idx, a["face"])
                    # 名字按玩家在圓桌上順時針排列；與紅框座位一一對應。
                    valid.sort(key=lambda i: (i - game.current_idx) % len(game.players))
                    for start in range(0, len(valid), 2):
                        row = []
                        for i in valid[start:start+2]:
                            t = game.players[i]
                            row.append(InlineKeyboardButton(
                                f"🎯 {t.name} ♥{t.hp}",
                                callback_data=f"shot:{i}"
                            ))
                        rows.append(row)
                elif typ == "beer":
                    alive = [i for i, x in enumerate(game.players) if x.alive]
                    for start in range(0, len(alive), 2):
                        row = []
                        for i in alive[start:start+2]:
                            t = game.players[i]
                            row.append(InlineKeyboardButton(
                                f"🍺 {t.name} {t.hp}/{t.max_hp}",
                                callback_data=f"beer:{i}"
                            ))
                        rows.append(row)
                elif typ == "kit_discard":
                    candidates = [i for i, x in enumerate(game.players) if x.alive and x.arrows > 0]
                    for start in range(0, len(candidates), 2):
                        row = []
                        for i in candidates[start:start+2]:
                            t = game.players[i]
                            row.append(InlineKeyboardButton(
                                f"🪶 {t.name} 箭{t.arrows}",
                                callback_data=f"kit:{i}"
                            ))
                        rows.append(row)
                    # 原版為「可以」移除，非強制。可逐次跳過或提早結束所有剩餘移箭。
                    rows.append([InlineKeyboardButton("⏭ 不移除這支箭", callback_data="kit:skip")])
                    rows.append([InlineKeyboardButton("✅ 完成移箭（剩餘全部不使用）", callback_data="kit:done")])

    rows.extend(common_info_rows(game))
    return InlineKeyboardMarkup(rows)


def _public_death_summary(game: Game) -> str:
    """主牌桌持續顯示已陣亡角色的真實身分，無需翻找舊訊息。"""
    dead = [p for p in game.players if not p.alive]
    if not dead:
        return ""
    labels = "、".join(f"{p.name[:14]}【{ROLE_CN[p.role]}】" for p in dead)
    return f"\n💀 已淘汰／身分公開：{labels}"


def _recent_combat_caption(game: Game) -> str:
    """攻擊、啤酒、角色回血依發生順序合併，不用玩家自行比對生命值。"""
    actions = game.recent_actions[-3:]
    if not actions:
        return ""
    return "\n\n⚔️ 最近戰況（新→舊）：\n" + "\n".join(
        format_action(game, action) for action in reversed(actions)
    )


def board_caption(game: Game) -> str:
    if getattr(game, "saloon_runtime", None) and game.phase != "ended":
        return saloon_bot.caption(game)
    death_summary = _public_death_summary(game)
    combat = _recent_combat_caption(game)
    if game.phase == "ended":
        return f"{game.winner_text}{death_summary}{combat}\n\n輸入 /newgame 再開一局。"
    p = game.current_player()
    phase_text = {
        "turn_start": "準備行動",
        "rolling": f"第 {game.roll_no} 次擲骰",
        "slab_choice": "選擇是否使用角色能力",
        "damage_choice": "等待受傷玩家選擇角色能力",
        "resolving": "正在結算骰面",
    }.get(game.phase, game.phase)
    public_role = ""
    if len(game.players) == 3:
        public_role = "\n🎭 三人局身分公開：" + "｜".join(f"{x.name}:{ROLE_CN[x.role]}" for x in game.players)
    else:
        sheriff = next((x for x in game.players if x.role == "sheriff"), None)
        if sheriff:
            public_role = f"\n⭐ 警長：{sheriff.name}"
    if game.phase == "chief_arrow_choice":
        return f"🏹 {p.name}：請選擇普通箭或酋長箭。"
    if game.phase == "broken_arrow_choice":
        return f"🏹 {p.name}：請選擇要移除誰的普通箭。"
    if game.phase == "damage_choice":
        choice = current_damage_choice(game)
        if choice:
            owner = game.players[choice["idx"]]
            title = "巴特・卡西迪：拿箭擋傷" if choice["kind"] == "bart" else "佩德羅・拉米雷斯：失血丟箭"
            return f"🎭 等待 {owner.name} 選擇能力：{title}\n其他玩家請稍候，只有 {owner.name} 能按選項。{public_role}{death_summary}{combat}"
    action = game.pending_action
    if game.phase == "resolving" and action and action.get("type") == "shot":
        valid = valid_targets_for_face(game, game.current_idx, action["face"])
        return (
            f"🎯 {p.name} 正在瞄準｜{short_face(action['face'])}\n"
            f"看圓桌：金框是射手、紅框是射程內玩家。\n"
            f"👇 直接按下方的名字開槍（可選 {len(valid)} 人）{public_role}{death_summary}{combat}"
        )
    return (
        f"🤠 {p.name}｜{p.character.cn}\n"
        f"♥ {p.hp}/{p.max_hp}　🏹 {p.arrows}　中央箭池 {game.arrows_pool}/9\n"
        f"狀態：{phase_text}{public_role}{death_summary}{combat}"
    )


def _message_missing_error(exc: BadRequest) -> bool:
    text = str(exc).lower()
    return any(x in text for x in (
        "message to edit not found",
        "message_id_invalid",
        "message identifier is not specified",
    ))


def _media_photo(img_bytes: bytes, filename: str, caption: str) -> InputMediaPhoto:
    """建立可用於 editMessageMedia 的 multipart 圖片。

    InputMediaPhoto 是巢狀 JSON，重新上傳檔案時必須使用 attach://。
    InputFile(..., attach=True) 會讓 python-telegram-bot 正確產生 multipart attachment，
    避免 Telegram 回傳 `Can't parse inputmedia: media not found`。
    """
    return InputMediaPhoto(
        media=InputFile(img_bytes, filename=filename, attach=True),
        caption=caption,
    )


async def _replace_board_photo(
    context: ContextTypes.DEFAULT_TYPE,
    game: Game,
    img_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup,
):
    """優先編輯原本主牌桌；失敗時安全重建一則新的主牌桌。

    - media not found：改用 sendPhoto 重建，避免按鈕看起來完全沒反應。
    - TimedOut / NetworkError：先重試一次，再重建。
    - 重建成功後嘗試刪除舊主牌桌，避免群組一直刷訊息。
    """
    old_message_id = game.board_message_id

    if old_message_id:
        for attempt in range(2):
            try:
                await context.bot.edit_message_media(
                    chat_id=game.chat_id,
                    message_id=old_message_id,
                    media=_media_photo(img_bytes, filename, caption),
                    reply_markup=reply_markup,
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=20,
                    pool_timeout=20,
                )
                return
            except BadRequest as e:
                msg = str(e).lower()
                if 'not modified' in msg:
                    return
                log.warning('edit media failed: %s', e)
                # 這幾類錯誤都直接改走 sendPhoto 重建。
                if (
                    'media not found' in msg
                    or _message_missing_error(e)
                    or 'wrong file identifier' in msg
                    or 'failed to get http url content' in msg
                ):
                    break
                # 其他 BadRequest 通常重試也沒用；仍重建主訊息，避免介面卡死。
                break
            except (TimedOut, NetworkError) as e:
                log.warning('edit media network error (attempt %s/2): %s', attempt + 1, e)
                if attempt == 0:
                    await asyncio.sleep(0.6)
                    continue
                break
            except Exception as e:
                log.exception('unexpected edit media error: %s', e)
                break

    # editMessageMedia 失敗時的保底：重新送一張新的主牌桌。
    try:
        sent = await context.bot.send_photo(
            chat_id=game.chat_id,
            photo=InputFile(img_bytes, filename=filename),
            caption=caption,
            reply_markup=reply_markup,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=20,
            pool_timeout=20,
        )
    except (TimedOut, NetworkError) as e:
        log.warning('send photo network error, retry once: %s', e)
        await asyncio.sleep(0.8)
        sent = await context.bot.send_photo(
            chat_id=game.chat_id,
            photo=InputFile(img_bytes, filename=filename),
            caption=caption,
            reply_markup=reply_markup,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=20,
            pool_timeout=20,
        )

    game.board_message_id = sent.message_id

    # 新主牌桌送成功後才刪舊訊息；刪不掉也不影響遊戲。
    if old_message_id and old_message_id != sent.message_id:
        try:
            await context.bot.delete_message(game.chat_id, old_message_id)
        except Exception:
            pass


async def update_lobby(context: ContextTypes.DEFAULT_TYPE, game: Game):
    # 快速大廳：圖片是靜態的，加入/離開/加 AI 時只改 caption + buttons，
    # 不再每按一次就重新 render + upload 500KB 圖片。
    names = "、".join(p.name for p in game.players) if game.players else "等待玩家加入"
    cfg = game.expansion_config
    preview = ("🔸 原版（已可遊玩）" if cfg.mode == "base" else "🍺 老酒館＋⚔️ Undead 擴充設定")
    module_lines = ""
    if cfg.mode == "saloon":
        selected = cfg.active_modules()
        module_lines = "\n" + "\n".join(
            ("✅" if key in selected else "▫️") + f" {label}" for key, label in MODULES
        )
        module_lines += f"\n🤠 目前可候選新增角色：{len(cfg.eligible_new_characters())} 位"
    playable, why = cfg.playable_status(len(game.players))
    status = ("✅ 可以開始" if playable else f"🛠 {why}")
    caption = (
        f"🤠 BANG! 骰子版 v0.9.0 大廳\n"
        f"目前 {len(game.players)} / 8 人\n"
        f"玩家：{names}\n"
        f"模式：{preview}{module_lines}\n"
        f"{status}\n"
        "3～8 人可加入真人或 AI。鬼魂模組需5人以上。"
    )

    if game.board_message_id:
        try:
            await context.bot.edit_message_caption(
                chat_id=game.chat_id,
                message_id=game.board_message_id,
                caption=caption,
                reply_markup=lobby_keyboard(game),
                read_timeout=15,
                write_timeout=15,
                connect_timeout=10,
                pool_timeout=10,
            )
            return
        except BadRequest as e:
            if 'not modified' in str(e).lower():
                return
            log.warning('fast lobby caption edit failed, fallback to photo: %s', e)
        except (TimedOut, NetworkError) as e:
            log.warning('fast lobby caption network error, fallback to photo: %s', e)

    img_bytes = await asyncio.to_thread(lambda: render_lobby(game).getvalue())
    await _replace_board_photo(
        context=context,
        game=game,
        img_bytes=img_bytes,
        filename='lobby.jpg',
        caption=caption,
        reply_markup=lobby_keyboard(game),
    )


async def _announce_new_deaths(context: ContextTypes.DEFAULT_TYPE, game: Game):
    runner = getattr(game, "saloon_runtime", None)
    if runner and runner.pending_roll_transaction:return
    """僅第一次淘汰時在群組公告；/status 或後續刷新不重複發送。"""
    newly_dead = [(i, p) for i, p in enumerate(game.players)
                  if not p.alive and i not in game.announced_deaths]
    if not newly_dead:
        return
    lines = [f"💀 {p.name}（{p.character.cn}）已被淘汰！\n🎭 公開身分：{ROLE_CN[p.role]}"
             for _, p in newly_dead]
    lines.append("📋 牌桌和『查看角色』也會顯示已淘汰玩家的身分。")
    if game.phase == "ended":
        lines.append("🏆 本局已結束，完整名單將在結算公告公開。")
    else:
        nxt = game.current_player() if game.current_player().alive else None
        if nxt:
            lines.append(f"⏭ 遊戲繼續，下一位行動者：{nxt.name}")
    try:
        notice = await context.bot.send_message(chat_id=game.chat_id, text="\n\n".join(lines))
    except (BadRequest, Forbidden, TimedOut, NetworkError) as exc:
        # 牌桌 caption 仍有公開資訊，臨時網路失敗則留待下次刷新重試。
        log.warning("淘汰身分公告傳送失敗，稍後將重試：%s", exc)
    else:
        game.announced_deaths.update(i for i, _ in newly_dead)
        # 公告只留 10 秒。背景排程，不等待刪除才繼續回合。
        # 牌桌上已公開的淘汰者身分及遊戲結束的正式結算不刪除。
        context.application.create_task(
            _delete_message_later(context, game.chat_id, notice.message_id, 10.0),
            name=f"delete-elimination-notice-{game.chat_id}-{notice.message_id}",
        )




async def _resume_after_damage_choice(context: ContextTypes.DEFAULT_TYPE, game: Game, before_arrows: int):
    """真人回覆或逾時後恢復原射手流程；不重擲、不重複格林機槍。"""
    if game.pending_action is not None:
        finish_pending_action(game)
    for line in game.completed_damage_events:
        game.add_log(line)
    game.completed_damage_events.clear()
    events = []
    if game.phase != "ended":
        advance_if_current_eliminated(game, events)
    for line in events:
        game.add_log(line)
    await _play_new_arrow_attacks(context, game, before_arrows)
    if game.phase == "ended":
        await update_board(context, game)
    elif game.current_player().is_ai:
        await run_ai_chain(context, game)
    elif game.phase == "resolving":
        await process_until_input(context, game)
    else:
        await update_board(context, game)


async def _timeout_damage_choice(context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                                 game: Game, session: dict, cursor: int):
    """真人若離線，30 秒後使用安全預設，避免整局卡在受傷玩家。"""
    await asyncio.sleep(30)
    async with chat_lock(chat_id):
        if GAMES.get(chat_id) is not game or game.phase != "damage_choice":
            return
        if game.damage_session is not session or session.get("cursor") != cursor:
            return
        choice = current_damage_choice(game)
        if not choice:
            return
        count = 1 if choice["kind"] == "bart" and choice["max"] > 0 else 0
        before_arrows = game.indian_attacks
        try:
            finished = choose_damage_option(game, choice["idx"], count)
        except ValueError:
            return
        game.add_log(f"⏰ {game.players[choice['idx']].name} 未回應，已自動選擇能力（{count}）。")
        if finished:
            await _resume_after_damage_choice(context, game, before_arrows)
        else:
            await update_board(context, game)


def _schedule_damage_choice_timeout(context: ContextTypes.DEFAULT_TYPE, game: Game):
    session = game.damage_session
    if game.phase != "damage_choice" or not session:
        return
    cursor = session["cursor"]
    if session.get("timeout_scheduled_for") == cursor:
        return
    session["timeout_scheduled_for"] = cursor
    context.application.create_task(
        _timeout_damage_choice(context, game.chat_id, game, session, cursor),
        name=f"auto-damage-choice-{game.chat_id}-{cursor}",
    )

async def update_board(context: ContextTypes.DEFAULT_TYPE, game: Game):
    # 圖片合成是 CPU 工作，放到背景執行緒；同一狀態只 render 一次。
    img_bytes = await asyncio.to_thread(lambda: render_board(game).getvalue())
    await _replace_board_photo(
        context=context,
        game=game,
        img_bytes=img_bytes,
        filename='board.jpg',
        caption=board_caption(game),
        reply_markup=game_keyboard(game),
    )
    await _announce_new_deaths(context, game)
    _schedule_damage_choice_timeout(context, game)
    if getattr(game, "saloon_runtime", None):
        saloon_bot.schedule(context, game, sys.modules[__name__])
    if game.phase == "ended" and not game.final_announcement_sent:
        # 已結束時一次性公布全員身份與所有得勝玩家（含已淘汰隊友）。
        try:
            await context.bot.send_message(chat_id=game.chat_id, text=format_final_results(game))
        except (BadRequest, Forbidden, TimedOut, NetworkError) as exc:
            log.warning("完整結算公告失敗，稍後更新牌桌會重試：%s", exc)
        else:
            game.final_announcement_sent = True


async def _send_role_card(context: ContextTypes.DEFAULT_TYPE, game: Game, idx: int) -> bool:
    p = game.players[idx]
    if p.is_ai:
        return True
    role_path = ASSETS / "roles" / f"role_{p.role}.png"
    role_text = role_card_caption(game, p.role)
    if p.is_ghost:
        role_path = ASSETS / "old_saloon" / "ghost" / ("ghost_renegade_card.png" if getattr(p,"ghost_original_role",None)=="renegade" else "ghost_card.png")
        role_text += "\n👻 你現在是鬼魂：擲2顆普通骰並給出標記。原角色與特殊身分能力均停用。"
    elif p.special_role_key:
        role_path = ASSETS / "old_saloon" / "roles" / f"{p.special_role_key}.png"
        title, ability = ROLE_POWERS[p.special_role_key]
        role_text += f"\n🎭 {title}：{ability}\n每局限一次；在技能窗口按群組的特殊技能。"
    try:
        await _send_cached_photo_asset(context, p.pid, role_path, role_text)
        DM_READY.add(p.pid)
        return True
    except (Forbidden, BadRequest):
        return False
    except (TimedOut, NetworkError) as e:
        log.warning("send role card network error for %s: %s", p.name, e)
        return False


async def _send_character_card(context: ContextTypes.DEFAULT_TYPE, game: Game, idx: int) -> bool:
    p = game.players[idx]
    if p.is_ai:
        return True
    c = p.character
    card_path = ASSETS / "cards" / f"{c.key}.png"
    if not card_path.exists(): card_path = ASSETS / "old_saloon" / "cards" / f"{c.key}.png"
    if not card_path.exists(): card_path = ASSETS / "undead" / "cards" / f"{c.key}.png"
    char_text = (
        f"🎭 你的角色：{c.cn}（{c.en}）\n"
        f"♥ 生命：{p.hp}/{p.max_hp}\n\n能力：{c.ability}"
    )
    try:
        await _send_cached_photo_asset(context, p.pid, card_path, char_text)
        DM_READY.add(p.pid)
        return True
    except (Forbidden, BadRequest):
        return False
    except (TimedOut, NetworkError) as e:
        log.warning("send character card network error for %s: %s", p.name, e)
        return False


async def send_role_and_character(context: ContextTypes.DEFAULT_TYPE, game: Game, idx: int) -> bool:
    """開局私訊：先身分卡，再角色能力卡。失敗不阻斷群組遊戲。"""
    p = game.players[idx]
    if p.is_ai:
        return True
    ok_role = await _send_role_card(context, game, idx)
    if not ok_role:
        return False
    ok_char = await _send_character_card(context, game, idx)
    return ok_char


async def _delete_message_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: float = 2.4):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def show_dice_animation(
    context: ContextTypes.DEFAULT_TYPE,
    game: Game,
    caption: str = "🎲 擲骰中…",
    moving_indices: set[int] | None = None,
):
    """小骰盤短動畫：只有要重擲的位置會動。

    31 種選擇組合已在安裝包裡預先做成小 MP4，遊戲時不再即時計算動畫。
    每種動畫第一次上傳後記住 Telegram file_id，之後直接重用。
    """
    try:
        moving = set(range(5)) if moving_indices is None else set(moving_indices)
        mask = mask_from_indices(moving)
        key = str(mask)

        cache_map = context.bot_data.get("dice_tray_animation_file_ids")
        if not isinstance(cache_map, dict):
            cache_map = {}
            if DICE_TRAY_FILE_ID_CACHE.exists():
                try:
                    loaded = json.loads(DICE_TRAY_FILE_ID_CACHE.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        cache_map.update({str(k): str(v) for k, v in loaded.items() if v})
                except Exception:
                    pass
            context.bot_data["dice_tray_animation_file_ids"] = cache_map

        cached = cache_map.get(key)
        if cached:
            msg = await context.bot.send_animation(
                chat_id=game.chat_id,
                animation=cached,
                caption=caption,
                disable_notification=True,
                read_timeout=10,
                write_timeout=10,
                connect_timeout=8,
                pool_timeout=8,
            )
        else:
            path = animation_path(moving)
            if not path.exists():
                return None
            data = STATIC_FILE_BYTES.get(str(path))
            if data is None:
                data = path.read_bytes()
                STATIC_FILE_BYTES[str(path)] = data
            msg = await context.bot.send_animation(
                chat_id=game.chat_id,
                animation=InputFile(BytesIO(data), filename=path.name),
                caption=caption,
                disable_notification=True,
                read_timeout=12,
                write_timeout=15,
                connect_timeout=8,
                pool_timeout=8,
            )
            if getattr(msg, "animation", None) and msg.animation.file_id:
                cache_map[key] = msg.animation.file_id
                try:
                    DICE_TRAY_FILE_ID_CACHE.write_text(
                        json.dumps(cache_map, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception:
                    pass

        context.application.create_task(
            _delete_message_later(context, game.chat_id, msg.message_id, 1.0),
            name=f"delete-dice-tray-animation-{game.chat_id}-{msg.message_id}",
        )
        return msg
    except Exception as e:
        log.warning("dice tray animation skipped: %s", e)
        return None


async def show_gatling_animation(context: ContextTypes.DEFAULT_TYPE, game: Game, shooter_name: str):
    """固定格林機槍動畫只首次上傳，往後 Telegram file_id 秒取；失敗不阻斷遊戲。"""
    try:
        if not GATLING_ANIMATION.exists():
            return None
        cache = context.bot_data.get("gatling_file_ids")
        if not isinstance(cache, dict):
            cache = {}
            if GATLING_FILE_ID_CACHE.exists():
                try:
                    cache = json.loads(GATLING_FILE_ID_CACHE.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    cache = {}
            context.bot_data["gatling_file_ids"] = cache
        # 檔案改版自動換 key，避免 Telegram 繼續顯示舊動畫。
        raw = STATIC_FILE_BYTES.get(str(GATLING_ANIMATION))
        if raw is None:
            raw = GATLING_ANIMATION.read_bytes()
            STATIC_FILE_BYTES[str(GATLING_ANIMATION)] = raw
        key = hashlib.sha256(raw).hexdigest()[:20]
        file_id = cache.get(key)
        async def _upload():
            msg = await context.bot.send_animation(
                game.chat_id, animation=InputFile(BytesIO(raw), filename="gatling_barrage.mp4"),
                caption=f"🔫 {shooter_name} 發動格林機槍！全場掃射！",
                disable_notification=True, read_timeout=20, write_timeout=35,
                connect_timeout=12, pool_timeout=12,
            )
            if getattr(msg, "animation", None) and msg.animation.file_id:
                cache.clear()
                cache[key] = msg.animation.file_id
                try:
                    GATLING_FILE_ID_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError:
                    pass
            return msg
        if file_id:
            try:
                msg = await context.bot.send_animation(
                    game.chat_id, animation=file_id,
                    caption=f"🔫 {shooter_name} 發動格林機槍！全場掃射！",
                    disable_notification=True, read_timeout=12, write_timeout=12,
                    connect_timeout=10, pool_timeout=10,
                )
            except BadRequest:
                cache.pop(key, None)
                msg = await _upload()
        else:
            msg = await _upload()
        context.application.create_task(
            _delete_message_later(context, game.chat_id, msg.message_id, 3.4),
            name=f"delete-gatling-animation-{game.chat_id}-{msg.message_id}",
        )
        return msg
    except (Forbidden, BadRequest, TimedOut, NetworkError, OSError) as e:
        log.warning("格林機槍動畫略過（不影響結算）: %s", e)
        return None


async def show_indian_arrow_animation(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """第九支箭觸發才顯示；固定動畫 file_id 快取，失敗不影響扣血結算。"""
    try:
        if not INDIAN_ANIMATION.is_file():
            return None
        cache = context.bot_data.get("indian_arrow_file_ids")
        if not isinstance(cache, dict):
            cache = {}
            if INDIAN_FILE_ID_CACHE.exists():
                try:
                    loaded = json.loads(INDIAN_FILE_ID_CACHE.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        cache = loaded
                except (ValueError, OSError):
                    pass
            context.bot_data["indian_arrow_file_ids"] = cache
        raw = STATIC_FILE_BYTES.get(str(INDIAN_ANIMATION))
        if raw is None:
            raw = INDIAN_ANIMATION.read_bytes()
            STATIC_FILE_BYTES[str(INDIAN_ANIMATION)] = raw
        key = hashlib.sha256(raw).hexdigest()[:20]
        file_id = cache.get(key)
        caption = ("🏹 印第安人來襲！箭池已空，全場同時結算傷害！" if game.expansion_config.enabled("chief_arrow") else "🏹 印第安人來襲！第 9 支箭觸發，全場同時結算傷害！")

        async def upload():
            msg = await context.bot.send_animation(
                chat_id=game.chat_id,
                animation=InputFile(BytesIO(raw), filename=INDIAN_ANIMATION.name),
                caption=caption, disable_notification=True,
                read_timeout=20, write_timeout=35, connect_timeout=12, pool_timeout=12,
            )
            if getattr(msg, "animation", None) and msg.animation.file_id:
                cache.clear()
                cache[key] = msg.animation.file_id
                try:
                    INDIAN_FILE_ID_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError:
                    pass
            return msg

        if file_id:
            try:
                msg = await context.bot.send_animation(
                    chat_id=game.chat_id, animation=file_id, caption=caption,
                    disable_notification=True, read_timeout=12, write_timeout=12,
                    connect_timeout=10, pool_timeout=10,
                )
            except BadRequest:
                cache.pop(key, None)
                msg = await upload()
        else:
            msg = await upload()
        context.application.create_task(
            _delete_message_later(context, game.chat_id, msg.message_id, 3.7),
            name=f"delete-arrow-rain-{game.chat_id}-{msg.message_id}",
        )
        return msg
    except (Forbidden, BadRequest, TimedOut, NetworkError, OSError) as exc:
        log.warning("箭雨動畫略過（不影響結算）：%s", exc)
        return None


async def _play_new_arrow_attacks(context: ContextTypes.DEFAULT_TYPE, game: Game, before: int):
    # 一次 AI 回合可能發動超過一次，第九支箭每次觸發才播放。
    for _ in range(max(0, game.indian_attacks - before)):
        await show_indian_arrow_animation(context, game)


async def send_start_cards(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """背景送出所有真人的身分卡 + 角色卡；失敗者只在群組給一則短暫提醒。"""
    failed = []
    for idx, p in enumerate(game.players):
        if p.is_ai:
            continue
        ok = await send_role_and_character(context, game, idx)
        if not ok:
            failed.append(p.name)

    if failed:
        try:
            url = await bot_dm_url(context)
            msg = await context.bot.send_message(
                chat_id=game.chat_id,
                text="⚠️ 這些玩家尚未開啟 BOT 私訊，所以卡片暫時無法送達：\n"
                     + "、".join(failed)
                     + "\n請先點下面按鈕進入私訊並按 Start，之後可用 /role、/character 補看。",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤠 開啟 BOT 私訊", url=url)]]),
            )
            context.application.create_task(
                _delete_message_later(context, game.chat_id, msg.message_id, 12.0),
                name=f"delete-dm-warning-{game.chat_id}-{msg.message_id}",
            )
        except Exception as e:
            log.warning("cannot show DM warning: %s", e)


async def process_until_input(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """把不需要玩家選擇的結算一路處理，遇到目標選擇才停。"""
    events = []
    if game.phase == "resolving":
        advance_if_current_eliminated(game, events)
    while game.phase == "resolving":
        action = pop_next_action(game)
        if not action:
            break
        typ = action["type"]

        if typ == "shot":
            valid = valid_targets_for_face(game, game.current_idx, action["face"])
            if not valid:
                finish_pending_action(game)
                continue
            break  # 等人按目標

        if typ == "beer":
            # 即使全滿仍需指定；交給玩家
            break

        if typ == "kit_discard":
            candidates = [i for i, x in enumerate(game.players) if x.alive and x.arrows > 0]
            if not candidates:
                finish_pending_action(game)
                continue
            break

        if typ == "gatling":
            await show_gatling_animation(context, game, game.current_player().name)
            before_arrows = game.indian_attacks
            victims = [(i, 1) for i, p in enumerate(game.players) if i != game.current_idx and p.alive]
            waiting = start_damage_session(game, victims, game.current_idx, "gatling", events)
            if waiting:
                break
            await _play_new_arrow_attacks(context, game, before_arrows)
            finish_pending_action(game)
            if game.phase == "ended" or advance_if_current_eliminated(game, events):
                break
            continue

        if typ == "end_turn":
            finish_pending_action(game)
            end_turn(game, events)
            break

    for e in events:
        game.add_log(e)
    await update_board(context, game)

    if game.phase != "ended" and game.current_player().is_ai and game.phase == "turn_start":
        await run_ai_chain(context, game)


async def continue_after_roll(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """真人擲骰後續處理：死亡跳回合時，也必須自動啟動下一位 AI。"""
    if game.phase == "resolving":
        await process_until_input(context, game)
    else:
        await update_board(context, game)
        if game.phase == "turn_start" and game.current_player().is_ai:
            await run_ai_chain(context, game)


async def run_ai_chain(context: ContextTypes.DEFAULT_TYPE, game: Game):
    """快速 AI 回合：不重複上傳同一張牌桌，每個 AI 回合只更新一次結果。"""
    safety = 0
    while (
        game.phase != "ended"
        and game.current_player().is_ai
        and safety < 20
    ):
        safety += 1
        ai_name = game.current_player().name
        if game.phase == "resolving":
            before_arrows = game.indian_attacks
            events = run_ai_resolution(game)
        else:
            await show_dice_animation(
                context, game, f"🎲 {ai_name} 正在擲骰…", moving_indices=set(range(5))
            )
            await asyncio.sleep(0.10)
            before_arrows = game.indian_attacks
            events = run_ai_turn(game)
        await _play_new_arrow_attacks(context, game, before_arrows)
        if any("發動格林機槍" in e for e in events):
            await show_gatling_animation(context, game, ai_name)
        for e in events:
            game.add_log(e)
        await update_board(context, game)
        if game.phase in {"ended", "damage_choice"}:
            break
        await asyncio.sleep(0.12)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        DM_READY.add(update.effective_user.id)
        await update.message.reply_text(
            "🤠 BANG! 骰子版 BOT 私訊已啟用。\n"
            "開局後我會把你的「秘密身分卡」與「角色能力卡」送到這裡。\n"
            "如果之後想補看，也可輸入 /role 或 /character。"
        )
    else:
        await update.message.reply_text("在群組輸入 /newgame 建立 BANG! 骰子版大廳。")


async def newgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info("/newgame received chat=%s user=%s", getattr(update.effective_chat, "id", None), getattr(update.effective_user, "id", None))
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("請到群組使用 /newgame。")
        return

    chat_id = update.effective_chat.id
    old = GAMES.get(chat_id)
    if old and old.phase not in {"ended"}:
        await update.message.reply_text("這個群組已經有一局正在進行；要重開請先 /cancel。")
        return

    game = Game(chat_id=chat_id, host_id=update.effective_user.id)
    if context.args and context.args[0].casefold() in {"saloon", "oldsaloon", "老酒館"}:
        game.expansion_config.mode = "saloon"
        game.expansion_config.modules = {"saloon_dice", "chief_arrow"}
    add_human(game, update.effective_user.id, update.effective_user.full_name)
    GAMES[chat_id] = game
    await update_lobby(context, game)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = get_game(update)
    if not game:
        await update.message.reply_text("目前沒有遊戲。")
        return
    if update.effective_user.id != game.host_id:
        await update.message.reply_text("只有建立遊戲的人可以取消。")
        return
    GAMES.pop(game.chat_id, None)
    if game.board_message_id:
        try:
            await context.bot.edit_message_caption(
                chat_id=game.chat_id, message_id=game.board_message_id,
                caption="❌ 本局已取消。", reply_markup=None,
            )
            return
        except BadRequest:
            pass
    await update.message.reply_text("❌ 已取消本局。")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = get_game(update)
    if not game:
        await update.message.reply_text("目前沒有遊戲。")
        return
    if game.phase == "lobby":
        await update_lobby(context, game)
    else:
        await update_board(context, game)


SALOON_RULE_PAGES = {
    "saloon_dice": """🎲 老酒館規則｜特殊骰

回合開始、第一次擲骰前，選一種配置：
• 5顆普通骰。
• 4顆普通骰＋1顆大嘴巴。
• 4顆普通骰＋1顆膽小鬼。
同一回合不能同時使用兩種特殊骰，也不能中途換骰；下個回合可以重新選。

大嘴巴：箭、子彈、雙準心1、雙準心2、炸藥、雙格林機槍。
膽小鬼：箭、斷箭、準心1、準心2、啤酒、雙啤酒。

新符號：
• 斷箭：立即移除任意玩家1支普通箭，包括自己；不能移除酋長箭。之後可重擲。
• 子彈：自己立即失去1血。之後可重擲。
• 雙符號：算2個相同符號，可以分別指定不同目標；格林機槍每回合仍最多發動一次。

結算順序：箭 → 斷箭 → 子彈 → 炸藥 → 準心1 → 準心2 → 啤酒 → 格林機槍。
通常最多擲3次；炸藥不能重擲，3個以上炸藥扣1血並停止重擲，其餘骰面仍需結算。角色能力另依角色說明。

六骰例外：荷西選大嘴巴、龍舌蘭喬選膽小鬼時，各保留5顆普通骰，共6顆；選另一種特殊骰時仍為5顆。""",
    "chief_arrow": """🏹 老酒館規則｜酋長之箭

箭池加入1支酋長箭：9支普通箭＋1支酋長箭，共10個實體箭籤。

• 需要拿箭時，可選箭池中的普通箭或酋長箭。
• 酋長箭只消耗1個箭頭骰結果，但箭雨傷害與比較箭數時算2支。
• 箭池全部取空，立即觸發印第安人攻擊。
• 持有酋長箭的人若獨自擁有最多箭，本次箭雨完全免傷；並列最多不免傷。
• 箭雨結算後，全部箭回到箭池。淘汰或格林機槍丟棄自己的全部箭時，也包含酋長箭。
• 膽小鬼的斷箭只能丟普通箭。

例：你有2支普通箭＋酋長箭，合計4；其他玩家最多3，你免傷。若另一人也有4，你仍受4點箭雨傷害（其他能力另計）。""",
    "new_characters": """🤠 老酒館規則｜新增7位角色（茉莉已移除）

開啟後，符合模組條件的新角色會與原版16位角色一起抽取。

• 荷西・德爾加多（7血）：選大嘴巴時保留5顆普通骰，共6顆。
• 龍舌蘭喬（7血）：選膽小鬼時保留5顆普通骰，共6顆。
• 阿帕契小子（9血）：擲出箭頭時，可拿其他玩家的酋長箭。
• 無臉比爾（9血）：只在最後一擲確定後處理箭頭；可以提早停止重擲。
• 艾蓮娜・富恩特（7血）：每次擲出一個以上箭頭，可把其中1支箭交給任意玩家，其餘自己拿。
• 薇拉・卡斯特（7血）：每次受到準心1或2射擊，少失去1血；單次1點傷害可降為0。
• 霍利戴醫生（8血）：一回合使用3個以上準心符號，回復2血；雙準心算2個。
本BOT依設定移除莫莉，不會抽到。

荷西、龍舌蘭喬需同時開啟「酒館特殊骰」；阿帕契需開啟「酋長之箭」，否則不會抽到。
上述是角色原始生命，警長額外生命依所用身分牌計算。""",
    "special_roles": """🎭 老酒館規則｜9種特殊身分

陣營人數比例與原版相同。除警長外，身分起初保密；正式發動能力時公開。每張牌的能力每局限一次。

⭐ 熊警長：開局額外3血，取代原本額外2血，自動生效。
🛡 好人（副警長）：自己回合開始，與警長交換身分牌。雙方目前生命不變；生命上限回到各自角色原始值，新警長不再額外加血。舊警長超過新上限的現有生命不用丟棄。
🛡 醫生（副警長）：擲骰後，將其中一顆改成該骰實際存在的任一骰面。
🛡 法官（副警長）：另一玩家公開特殊身分能力時，取消那次能力；對方仍失去這次使用機會。
🔫 賭徒（歹徒）：另一玩家最後一擲後，忽略該次結果，強迫全部骰子重擲（包含炸藥），並接受新結果。之前各擲已結算的效果保留。
🔫 壞人（歹徒）：另一玩家即將回血時，阻止那次回血。已使用的啤酒不能重新分配。
🔫 醜人（歹徒）：自己回合開始，交換任意兩人的全部箭，包含酋長箭；可以選自己。
🃏 惡魔右手（叛徒）：自己回合結束後，立刻再進行一個完整回合。
🃏 惡魔左手（叛徒）：任何玩家即將淘汰時，使其以2血留在場上；被救者可丟棄自己的全部箭，也能自救。

BOT操作：
1. 符合時機時，群組出現10秒反應窗口。
2. 有資格的玩家按「⚡ 特殊技能」。
3. 取得發動權後，共20秒完成細節選擇；醫生選骰再選骰面共用這20秒。
4. 尚未正式發動就放棄或超時，不消耗能力；正式發動後被法官取消則仍消耗。
窗口在牌桌顯示成功後才開始計時。平常按按鈕不會公開你的身分。""",
    "ghost": """👻 老酒館規則｜鬼魂（至少5人）

第一位淘汰的玩家若不是警長，成為本局唯一鬼魂；後續淘汰者不會再成為鬼魂。

鬼魂：
• 保留原本座位與公開陣營，仍可隨陣營獲勝。
• 沒有生命，不再使用原角色或特殊身分能力，也不計入射擊距離。
• 輪到自己時只擲2顆普通骰，最多擲3次；炸藥仍不能重擲，骰面不直接傷害或治療鬼魂。
• 從最終兩顆骰選1種符號，交給任意存活玩家。
• 兩顆相同時給雙倍標記；不同時只能選其中1種。

收到標記的人：
• 下回合第一次擲骰，有1顆（雙倍為2顆）普通骰固定為標記的骰面，其餘骰子正常擲。
• 固定骰面仍要正常結算；第二次起可以重擲，炸藥例外。
• 若選特殊骰，替換的是其他普通骰，不能替換標記固定的骰子。
• 回合結束後回收標記。

叛徒成為鬼魂時改換陣營：
5人局 → 歹徒；6人局 → 副警長；7人局 → 歹徒；8人局 → 副警長。
以開局總人數判斷，之後存活人數變少不再改變。""",
}


SALOON_RULE_PAGES.update({
    "duel_dice": """⚔️ Undead｜決鬥骰與傷口

決鬥骰模組必須搭配憤怒卡。兩顆普通骰改成兩顆黑色決鬥骰，總數仍是5顆；荷西／龍舌蘭喬的六骰能力仍可搭配。
黑骰六面：箭、炸藥、格林機槍、威士忌、決鬥、決鬥。
老酒館特殊骰仍可替換另一顆普通骰；鬼魂仍只擲2顆普通骰。

威士忌：回復自己1血，並移除自己1枚傷口；没有傷口時改抽1張憤怒卡。滿血時仍處理傷口／抽卡。威士忌在射擊、啤酒、格林機槍前結算。

決鬥：在格林機槍後，為每個決鬥符號選一名存活對手；沒有距離限制，同回合不能重複挑戰同一人。
對手先按「擲決鬥骰」。擲出決鬥就換另一方按，直到有人失敗。失敗者失去1血並抽傷口，該次其他骰面不生效。
BOT自動擲；真人50秒、剩10秒提醒，逾時代擲。

傷口15枚：取消啤酒×3、取消準心1×5、取消準心2×5、額外炸藥×2。
抽到已有的同種傷口洗回、不重抽。傷口在自己的回合抵消1個對應的保留骰面；炸藥傷口則額外算1個炸藥。
雙符號骰可被抵消其中1個符號。憤怒卡的符號不是骰面，不受傷口抵消。
自己回合結束後，所有傷口洗回池中。""",
    "rage": """🔥 Undead｜憤怒卡

每個回合分別累計所有玩家的實際失血；即使有補血也不減少失血累計。回合結束，該回合失去2血以上且仍存活的人抽1張憤怒卡。
取得的卡片保密，可以按「我的憤怒卡／傷口」自己查看。
自己的下回合開始翻開所有憤怒卡，符號加入本回合結果；箭立即拿取，其他符號按結算順序處理。卡片不能重擲。
自己回合結束棄掉已翻開的卡，當回合新抽的卡留到下一回合。牌庫用完才把棄牌洗回。
憤怒可單獨開啟，憤怒卡上的決鬥仍按決鬥流程處理。

依實體18張：準心1×3、準心2×3、啤酒×3、格林機槍×3、決鬥×2；另各1張：
準心1＋啤酒＋炸藥
準心1＋決鬥＋箭
準心2＋決鬥＋炸藥
準心2＋格林機槍＋箭。""",
    "undead_characters": """🤠 Undead｜8位新角色

貝爾・史塔（8）：每次擲骰後，可把1個炸藥改為格林機槍；3個以上炸藥不能改。
查克・溫甘（8）：每回合1次，支付1血，將1顆骰子改成該骰任一面；3個以上炸藥時不能改炸藥。
葛雷格・迪格（7）：每個威士忌使用2次。
赫伯・杭特（8）：自己回合中，其他玩家累計失去2血以上，再抽1枚傷口。
帕特・布倫南（8）：回合開始，可將1張憤怒卡從一人移給另一人，包括自己。自己牌面只對自己顯示。
皮克西・皮特（9）：每次抽憤怒卡時抽2選1，另一張洗回。候選牌私訊本人，群組用A／B按鈕選擇。
治療師山姆（7）：自己回合每使用1個決鬥符號，可讓任意玩家回復1血；被人挑戰的回擊不觸發。
尚恩・馬洛里（8）：自己回合可額外重擲1顆決鬥骰1次，也能保留到決鬥失敗時重擲；别人的回合不能用。

貝爾、查克不需要其他新模組；帕特、皮克西需憤怒；另外4位需決鬥骰，否則不會抽到。""",
})


def rules_view(game: Game | None, page: str = "home"):
    labels = dict(MODULES)
    if page == "base":
        text = RULES_TEXT
    elif page in SALOON_RULE_PAGES:
        status = ""
        if game is not None:
            status = "✅ 本局已開啟\n\n" if game.expansion_config.enabled(page) else "▫️ 本局未開啟（以下為規則參考）\n\n"
        text = status + SALOON_RULE_PAGES[page]
    else:
        page = "home"
        text = "📖 BANG! 骰子版｜規則目錄\n\n"
        if game is None:
            text += "目前沒有本群遊戲；下方可查看原版、老酒館與Undead規則。"
        elif game.expansion_config.mode == "base":
            text += "本局模式：原版。老酒館模組未開啟。"
        else:
            text += "本局模式：擴充設定\n" + "\n".join(
                ("✅ " if game.expansion_config.enabled(key) else "▫️ ") + name for key, name in MODULES
            )
        text += "\n\n老酒館5個模組＋Undead決鬥、憤怒、新角色3個模組；決鬥必須搭配憤怒。鬼魂需至少5人。殭屍與連戰傳承尚未加入。\n\n點下方按鈕查看詳細規則；翻頁只更新這則說明，不會更動牌桌。"
    rows = [[InlineKeyboardButton("📖 原版規則", callback_data="rules:base"), InlineKeyboardButton("🍺 本局／目錄", callback_data="rules:home")]]
    keys = list(labels)
    for at in range(0, len(keys), 2):
        rows.append([InlineKeyboardButton(labels[key], callback_data=f"rules:{key}") for key in keys[at:at+2]])
    return text, InlineKeyboardMarkup(rows)


async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, markup = rules_view(get_game(update))
    await update.effective_message.reply_text(text, reply_markup=markup)


async def private_character_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("請直接按主牌桌下方的『🎭 我的角色』，能力會只對你跳窗顯示。")
        return
    DM_READY.add(update.effective_user.id)
    g, idx = find_player_game(update.effective_user.id)
    if not g:
        await update.message.reply_text("你目前沒有參加進行中的遊戲。")
        return
    if not await _send_character_card(context, g, idx):
        await update.message.reply_text("角色卡暫時傳送失敗，請稍後再試。")




# v0.6.8: 新增私訊素材預覽與版本檢查，可不用開局就驗證實際發送的卡圖。
async def private_assetversion_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("請在 BOT 私訊輸入 /assetversion。")
        return
    rose = ASSETS / "cards" / "rose_doolan.png"
    sig = hashlib.sha256(rose.read_bytes()).hexdigest()[:12] if rose.exists() else "missing"
    await update.message.reply_text(
        "🤠 BANG! 骰子版 v0.9.0（Undead：決鬥／憤怒／新角色）\n"
        "🍺 老酒館5個模組可玩；茉莉已移除。\n"
        "⚔️ 決鬥由雙方輪流點骰，憤怒使用18張實體配比。\n"
        "🧟 殭屍與連戰傳承尚未加入。\n"
        f"蘿絲卡片校驗碼：{sig}\n"
        "輸入 /previewcard rose_doolan 可直接檢查。"
    )


async def private_previewcard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("為保護私訊素材預覽，請到 BOT 私訊使用 /previewcard。")
        return
    key = (context.args[0].strip().lower() if context.args else "rose_doolan")
    character = CHAR_BY_KEY.get(key)
    if not character:
        await update.message.reply_text(
            "找不到角色；請輸入英文字代號，例如 /previewcard rose_doolan 或 /previewcard lucky_duke。"
        )
        return
    path = ASSETS / "cards" / f"{character.key}.png"
    if not path.exists():path = ASSETS / "old_saloon" / "cards" / f"{character.key}.png"
    if not path.exists():path = ASSETS / "undead" / "cards" / f"{character.key}.png"
    try:
        await _send_cached_photo_asset(
            context, update.effective_user.id, path,
            f"🎭 素材預覽：{character.cn}（{character.en}）\n"
            f"原始血量：{character.hp}\n能力：{character.ability}"
        )
    except (Forbidden, BadRequest, TimedOut, NetworkError) as e:
        log.warning("預覽角色卡失敗 %s: %s", key, e)
        await update.message.reply_text("卡片預覽失敗，請稍後再試。")

async def private_cacheassets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("請先私訊 BOT，再執行 /cacheassets。")
        return
    msg = await update.message.reply_text("正在幫你把身分卡與角色卡預先登記成 Telegram file_id，第一次會比較慢，完成後之後就會更順。")
    ok, total = await _cache_all_photo_assets(context, update.effective_user.id)
    await msg.edit_text(
        f"✅ 預先登記完成：{ok}/{total} 張。\n"
        f"之後私訊身分卡 / 角色卡會優先直接使用 Telegram file_id。"
    )


async def private_role_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("請直接按主牌桌下方的『🤫 我的身分』，秘密身分會只對你跳窗顯示。")
        return
    DM_READY.add(update.effective_user.id)
    g, idx = find_player_game(update.effective_user.id)
    if not g:
        await update.message.reply_text("你目前沒有參加進行中的遊戲。")
        return
    if not await _send_role_card(context, g, idx):
        await update.message.reply_text("身分卡暫時傳送失敗，請稍後再試。")


async def callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    chat_id = q.message.chat.id if q.message else None
    game = GAMES.get(chat_id) if chat_id else None
    user = q.from_user

    # Rules live in a separate text message; never edit the main photo board.
    if data.startswith("rules:"):
        page = data.split(":", 1)[1]
        text, markup = rules_view(game, page)
        await q.answer()
        if q.message:
            if page == "open":
                await q.message.reply_text(text, reply_markup=markup)
            else:
                try:
                    await q.edit_message_text(text=text, reply_markup=markup)
                except BadRequest as exc:
                    if "not modified" not in str(exc).lower():
                        raise
        return

    # 私訊角色瀏覽器有獨立訊息與按鈕，不更動群組共用牌桌。
    if data.startswith("browse:"):
        await _private_browser_callback(update, context)
        return

    if game and saloon_bot.runtime(game) and await saloon_bot.callback(update, context, game, sys.modules[__name__]):
        return

    # ===== 群組單人查看資訊：不更動群組的按鈕 =====
    if data.startswith("info:"):
        if not game:
            await q.answer("這局已不存在。", show_alert=True)
            return
        if game.phase == "lobby":
            await q.answer("請等新一局開始後再查看角色。", show_alert=True)
            return

        viewer_idx = next((i for i, p in enumerate(game.players) if not p.is_ai and p.pid == user.id), None)
        if viewer_idx is None:
            await q.answer("你不是本局玩家。", show_alert=True)
            return

        if data == "info:players":
            # 多人同按「查看角色」原本會互相改同一張牌桌的 inline 鍵盤。
            # 現在個別在 BOT 私訊顯示獨立角色瀏覽器，群組按鈕永遠不變。
            try:
                await _open_private_character_browser(context, game, user.id)
                await q.answer("角色清單已送到你的 BOT 私訊；群組牌桌不會改變。", show_alert=True)
            except (Forbidden, BadRequest, TimedOut, NetworkError) as exc:
                log.info("無法開啟私訊角色清單，顯示個人跳窗摘要: %s", exc)
                await q.answer(_public_character_summary(game), show_alert=True)
            return

        if data == "info:back":
            await q.answer("請在 BOT 私訊查看詳細角色能力。", show_alert=True)
            return

        if data == "info:character":
            p = game.players[viewer_idx]
            c = p.character
            text = f"🎭 {c.cn}\n❤️ 目前生命：{p.hp}/{p.max_hp}\n\n能力：{'鬼魂：原角色能力停用' if p.is_ghost else c.ability}"
            await q.answer(text[:200], show_alert=True)
            return

        if data == "info:role":
            p = game.players[viewer_idx]
            detail = role_alert(game, p.role)
            if p.special_role_key:
                title, ability = ROLE_POWERS[p.special_role_key]
                detail = f"{ROLE_CN[p.role]}｜{title}\n{ability}\n能力：{'已使用' if p.role_power_used else '未使用'}"
            if p.is_ghost:detail=f"👻 鬼魂｜{ROLE_CN[p.role]}陣營\n擲2顆普通骰，選一種符號給存活玩家。原角色及特殊身分能力停用。"
            await q.answer(detail[:200], show_alert=True)
            return

        if data.startswith("info:player:"):
            # 舊版訊息上的角色詳細按鈕仍能回覆，但不可再改群組的鍵盤。
            try:
                idx = int(data.rsplit(":", 1)[1])
            except ValueError:
                await q.answer("玩家資料錯誤。", show_alert=True)
                return
            if not (0 <= idx < len(game.players)):
                await q.answer("找不到這位玩家。", show_alert=True)
                return
            await q.answer(_public_character_detail(game, idx)[:200], show_alert=True)
            return

        await q.answer("未知資訊按鈕。", show_alert=True)
        return

    if not game:
        await q.answer("這局已不存在。", show_alert=True)
        return

    if data.startswith("special:"):
        await q.answer("老酒館特殊身分仍在開發，尚未開放使用。", show_alert=True)
        return

    # ===== Lobby =====
    if data.startswith("lobby:"):
        action = data.split(":", 1)[1]
        if game.phase != "lobby":
            await q.answer("這個大廳已結束設定，請用最新牌桌。", show_alert=True)
            return

        if action == "join":
            if not add_human(game, user.id, user.full_name):
                await q.answer("你已加入，或人數已滿。", show_alert=True)
                return
            await q.answer("已加入。")
            await update_lobby(context, game)
            return

        if action == "leave":
            if user.id == game.host_id:
                await q.answer("建立者不能離開；可直接取消遊戲。", show_alert=True)
                return
            if not remove_human(game, user.id):
                await q.answer("你不在大廳裡。", show_alert=True)
                return
            await q.answer("已離開。")
            await update_lobby(context, game)
            return

        if (action in {"addai", "delai", "start", "cancel", "all", "none"} or action.startswith(("mode:", "mod:"))) and user.id != game.host_id:
            await q.answer("只有建立者可以操作。", show_alert=True)
            return

        if action.startswith("mode:"):
            mode = action.split(":", 1)[1]
            if mode not in {"base", "saloon"}:
                await q.answer("未知遊戲模式。", show_alert=True)
                return
            game.expansion_config.mode = mode
            if mode == "saloon" and not game.expansion_config.modules:
                game.expansion_config.modules = {"saloon_dice", "chief_arrow"}
            await q.answer("已選擇原版。" if mode == "base" else "已進入擴充設定，可搭配老酒館及Undead模組。")
            await update_lobby(context, game)
            return

        if action.startswith("mod:"):
            if game.expansion_config.mode != "saloon":
                await q.answer("先選擇擴充設定。", show_alert=True)
                return
            key = action.split(":", 1)[1]
            try:
                game.expansion_config.toggle(key, len(game.players))
            except ValueError as exc:
                await q.answer(str(exc), show_alert=True)
                return
            await q.answer("已更新模組設定。")
            await update_lobby(context, game)
            return

        if action in {"all", "none"}:
            if game.expansion_config.mode != "saloon":
                await q.answer("先選擇擴充設定。", show_alert=True)
                return
            game.expansion_config.modules = set(MODULE_KEYS) if action == "all" else set()
            await q.answer("模組已全選。" if action == "all" else "模組已全部取消。")
            await update_lobby(context, game)
            return

        if action == "addai":
            if not add_ai(game):
                await q.answer("已經 8 人了。", show_alert=True)
                return
            await q.answer("已加入電腦玩家。")
            await update_lobby(context, game)
            return

        if action == "delai":
            if not remove_ai(game):
                await q.answer("目前沒有電腦玩家。", show_alert=True)
                return
            await q.answer("已移除一名電腦玩家。")
            await update_lobby(context, game)
            return

        if action == "rules":
            await q.answer()
            text, markup = rules_view(game)
            await q.message.reply_text(text, reply_markup=markup)
            return

        if action == "cancel":
            await q.answer("已取消本局。")
            GAMES.pop(game.chat_id, None)
            try:
                await context.bot.edit_message_caption(
                    chat_id=game.chat_id,
                    message_id=game.board_message_id,
                    caption="❌ 本局已取消。",
                    reply_markup=None,
                )
            except BadRequest:
                pass
            return

        if action == "start":
            playable, reason = game.expansion_config.playable_status(len(game.players))
            if not playable:
                await q.answer(reason[:200], show_alert=True)
                return
            try:
                setup_game(game)
            except ValueError as exc:
                await q.answer(str(exc)[:200], show_alert=True)
                return
            await q.answer("遊戲開始！角色卡與身分卡會私訊給真人玩家。")
            await update_board(context, game)
            context.application.create_task(
                send_start_cards(context, game),
                name=f"send-start-cards-{game.chat_id}",
            )
            if advanced_saloon(game):
                await saloon_bot.drive(context, game, sys.modules[__name__])
            elif game.current_player().is_ai:
                await run_ai_chain(context, game)
            return

        await q.answer("未知大廳操作。", show_alert=True)
        return

    # ===== Defense choice: 被攻擊者本人可以在別人的回合選擇能力 =====
    if data.startswith("dmg:"):
        choice = current_damage_choice(game)
        if game.phase != "damage_choice" or not choice:
            await q.answer("這個防禦選項已失效。", show_alert=True)
            return
        owner = game.players[choice["idx"]]
        if owner.is_ai or owner.pid != user.id:
            await q.answer("必須由被攻擊的玩家本人選擇。", show_alert=True)
            return
        try:
            _, idx_str, count_str = data.split(":", 2)
            idx, count = int(idx_str), int(count_str)
            attack_count_before_choice = game.indian_attacks
            finished = choose_damage_option(game, idx, count)
        except (ValueError, IndexError):
            await q.answer("選項已失效，請使用最新牌桌。", show_alert=True)
            return
        await q.answer("✅ 已選擇")
        if not finished:
            await update_board(context, game)
            return
        await _resume_after_damage_choice(context, game, attack_count_before_choice)
        return

    # ===== Playing =====
    if not is_current_human(game, user.id):
        await q.answer("現在不是你的回合。", show_alert=True)
        return

    if data.startswith("chief:"):
        result = choose_chief_arrow(game, data == "chief:yes")
        if result is None:
            await q.answer("這支箭目前不能拿。", show_alert=True)
            return
        await q.answer("🏹 已選擇箭矢。")
        for e in result: game.add_log(e)
        await continue_after_roll(context, game)
        return

    if data.startswith("broken:"):
        try:
            target = int(data.split(":", 1)[1])
        except ValueError:
            await q.answer("選項無效。", show_alert=True)
            return
        result = finish_broken_arrow_choice(game, target)
        if result is None:
            await q.answer("目前不能移除這支箭。", show_alert=True)
            return
        await q.answer("🏹 已移除箭矢。")
        for e in result: game.add_log(e)
        await continue_after_roll(context, game)
        return

    if data.startswith("sid:"):
        if game.phase != "turn_start" or game.current_player().character_key != "sid_ketchum" or game.sid_done:
            await q.answer("這個選擇目前無效。", show_alert=True)
            return
        idx = int(data.split(":")[1])
        if 0 <= idx < len(game.players) and game.players[idx].alive:
            await q.answer()
            gained, line = heal_with_record(game, idx, 1, game.current_idx, "sid")
            game.sid_done = True
            game.add_log(line)
            await update_board(context, game)
        else:
            await q.answer("目標無效。", show_alert=True)
        return

    if data.startswith("turn:choose:"):
        kind = data.split(":")[-1]
        if not pick_saloon_die(game, kind):
            await q.answer("目前無法選擇此骰子。", show_alert=True)
            return
        await q.answer("🎲 選擇完成，開始擲骰！")
        await show_dice_animation(context, game, f"🎲 {game.current_player().name} 擲骰…", moving_indices=set(range(5)))
        before_arrows = game.indian_attacks
        events = roll_initial(game)
        await _play_new_arrow_attacks(context, game, before_arrows)
        for e in events:
            game.add_log(e)
        await continue_after_roll(context, game)
        return

    if data == "turn:roll":
        if game.phase != "turn_start":
            await q.answer("目前不能擲骰。", show_alert=True)
            return
        if game.current_player().character_key == "sid_ketchum" and not game.sid_done:
            await q.answer("請先選席德的回血目標。", show_alert=True)
            return
        await q.answer("🎲 擲骰！")
        await show_dice_animation(
            context, game, f"🎲 {game.current_player().name} 正在擲骰…", moving_indices=set(range(5))
        )
        before_arrows = game.indian_attacks
        events = roll_initial(game)
        await _play_new_arrow_attacks(context, game, before_arrows)
        await asyncio.sleep(0.10)
        for e in events:
            game.add_log(e)
        await continue_after_roll(context, game)
        return

    if data.startswith("die:"):
        i = int(data.split(":")[1])
        if not toggle_die(game, i):
            await q.answer("這顆目前不能選。", show_alert=True)
            return
        await q.answer()
        # 選骰只更新按鈕，不重新上傳整張牌桌；✅ 狀態會立即反映。
        try:
            await q.edit_message_reply_markup(reply_markup=game_keyboard(game))
        except BadRequest:
            pass
        return

    if data == "turn:reroll":
        if game.phase != "rolling":
            await q.answer("目前不能重擲。", show_alert=True)
            return
        if not game.selected:
            await q.answer("先點選要重擲的骰子。", show_alert=True)
            return
        moving = set(game.selected)
        selected_nums = "、".join(str(i + 1) for i in sorted(moving))
        await q.answer("🎲 重擲！")
        await show_dice_animation(
            context, game, f"🎲 重擲第 {selected_nums} 顆…", moving_indices=moving
        )
        before_arrows = game.indian_attacks
        events = reroll_selected(game)
        await _play_new_arrow_attacks(context, game, before_arrows)
        await asyncio.sleep(0.10)
        for e in events:
            game.add_log(e)
        await continue_after_roll(context, game)
        return

    if data == "turn:final":
        if game.phase != "rolling":
            await q.answer("目前不能確定骰面。", show_alert=True)
            return
        await q.answer("✅ 確定結果")
        events = finalize_dice(game)
        for e in events:
            game.add_log(e)
        if game.phase == "slab_choice":
            await update_board(context, game)
        else:
            await process_until_input(context, game)
        return

    if data.startswith("slab:"):
        if game.phase != "slab_choice":
            await q.answer("這個選擇目前無效。", show_alert=True)
            return
        face = BULL1 if data == "slab:bull1" else BULL2 if data == "slab:bull2" else None
        if face is not None and not count_symbols(game, face):
            await q.answer("沒有這種準心。", show_alert=True)
            return
        await q.answer()
        apply_slab_choice(game, face or False)
        game.add_log(f"💥 殺手斯萊布選擇加倍 {short_face(face)}。" if face else "🍺 殺手斯萊布保留啤酒。")
        await process_until_input(context, game)
        return

    if data.startswith("shot:"):
        a = game.pending_action
        if game.phase != "resolving" or not a or a["type"] != "shot":
            await q.answer("射擊選擇已失效。", show_alert=True)
            return
        idx = int(data.split(":")[1])
        valid = valid_targets_for_face(game, game.current_idx, a["face"])
        if idx not in valid:
            await q.answer("這個目標不在射程內。", show_alert=True)
            return
        await q.answer("🎯 開火！")
        events = []
        before_arrows = game.indian_attacks
        waiting = start_damage_session(game, [(idx, a.get("amount", 1))], game.current_idx, "shot", events)
        if waiting:
            await update_board(context, game)
            return
        await _play_new_arrow_attacks(context, game, before_arrows)
        for e in events:
            game.add_log(e)
        finish_pending_action(game)
        if check_win(game):
            await update_board(context, game)
        elif advance_if_current_eliminated(game, events):
            for e in events:
                game.add_log(e)
            await continue_after_roll(context, game)
        else:
            await process_until_input(context, game)
        return

    if data.startswith("beer:"):
        a = game.pending_action
        if game.phase != "resolving" or not a or a["type"] != "beer":
            await q.answer("啤酒選擇已失效。", show_alert=True)
            return
        idx = int(data.split(":")[1])
        if idx < 0 or idx >= len(game.players) or not game.players[idx].alive:
            await q.answer("目標無效。", show_alert=True)
            return
        await q.answer("🍺 乾杯！")
        cur = game.current_player()
        amount = 2 if (cur.character_key == "jesse_jones" and idx == game.current_idx and cur.hp <= 4) else 1
        got, line = heal_with_record(game, idx, amount, game.current_idx, "beer")
        game.add_log(line)
        finish_pending_action(game)
        await process_until_input(context, game)
        return

    if data.startswith("kit:"):
        a = game.pending_action
        if game.phase != "resolving" or not a or a["type"] != "kit_discard":
            await q.answer("移除箭的選擇已失效。", show_alert=True)
            return
        choice = data.split(":", 1)[1]
        if choice in {"skip", "done"}:
            if choice == "done":
                # 僅取消基特的可選移箭；不能取消強制發動的格林機槍、啤酒等動作。
                game.pending_actions = [x for x in game.pending_actions if x["type"] != "kit_discard"]
                await q.answer("✅ 已完成移箭，剩餘次數不使用。")
            else:
                await q.answer("⏭ 已跳過本次移箭。")
            finish_pending_action(game)
            await process_until_input(context, game)
            return
        try:
            idx = int(choice)
        except ValueError:
            await q.answer("移箭選項無效。", show_alert=True)
            return
        if 0 <= idx < len(game.players) and game.players[idx].alive and game.players[idx].arrows > 0:
            await q.answer("🪶 移除 1 支箭")
            game.players[idx].arrows -= 1
            game.arrows_pool += 1
            game.add_log(f"🪶 {game.current_player().name} 移除 {game.players[idx].name} 1 支箭。")
        else:
            await q.answer("這位玩家目前沒有箭。", show_alert=True)
            return
        finish_pending_action(game)
        await process_until_input(context, game)
        return

    await q.answer("操作已失效，請以最新牌桌為準。", show_alert=True)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """遊戲操作需要群組鎖；純查看資料應獨立處理，不阻塞骰子或切換群組按鈕。"""
    q = update.callback_query
    data = q.data or "" if q else ""
    chat_id = q.message.chat.id if q and q.message else None
    if chat_id is None or data.startswith(("info:", "browse:")):
        return await callback_impl(update, context)
    async with chat_lock(chat_id):
        return await callback_impl(update, context)


async def locked_newgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type == ChatType.PRIVATE:
        return await newgame_cmd(update, context)
    async with chat_lock(chat.id):
        return await newgame_cmd(update, context)


async def locked_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type == ChatType.PRIVATE:
        return await cancel_cmd(update, context)
    async with chat_lock(chat.id):
        return await cancel_cmd(update, context)


async def locked_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type == ChatType.PRIVATE:
        return await status_cmd(update, context)
    async with chat_lock(chat.id):
        return await status_cmd(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error", exc_info=context.error)


def build_app() -> Application:
    if not TOKEN:
        raise RuntimeError("找不到 BOT_TOKEN。請把 .env.example 複製成 .env，填入 BotFather Token。")
    # 多群組可並行；同群組由 CHAT_LOCKS 保護遊戲狀態。
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .concurrent_updates(8)
        .connect_timeout(20)
        .read_timeout(30)
        .write_timeout(30)
        .media_write_timeout(45)
        .pool_timeout(20)
        .get_updates_connect_timeout(20)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(20)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("newgame", locked_newgame_cmd))
    app.add_handler(CommandHandler("cancel", locked_cancel_cmd))
    app.add_handler(CommandHandler("status", locked_status_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("character", private_character_cmd))
    app.add_handler(CommandHandler("role", private_role_cmd))
    app.add_handler(CommandHandler("cacheassets", private_cacheassets_cmd))
    app.add_handler(CommandHandler("previewcard", private_previewcard_cmd))
    app.add_handler(CommandHandler("assetversion", private_assetversion_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_error_handler(error_handler)
    return app


if __name__ == "__main__":
    # Python 3.14 起，主執行緒可能沒有預設 event loop。
    # 明確建立可避免 run_polling() 出現「There is no current event loop」。
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    application = build_app()
    log.info("BANG! Dice Bot v0.8.1 old-saloon-artwork-foundation started | Python %s", sys.version.split()[0])
    application.run_polling(drop_pending_updates=True)
