"""Old Saloon expansion configuration / staged feature gates (v0.8.0 A).

Every selection is lobby-only. Never silently apply the base-game rules to a
selected but unfinished module. The base game remains untouched and playable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

MODULES = (
    ("saloon_dice", "🎲 酒館特殊骰"),
    ("chief_arrow", "🏹 酋長之箭"),
    ("special_roles", "🎭 特殊身分"),
    ("new_characters", "🤠 新增 7 位角色"),
    ("ghost", "👻 鬼魂模式"),
    ("duel_dice", "⚔️ 決鬥骰與傷口"),
    ("rage", "🔥 憤怒卡"),
    ("undead_characters", "🤠 Undead 新增8位角色"),
)
MODULE_LABELS = dict(MODULES)
MODULE_KEYS = tuple(k for k, _ in MODULES)
# 更新這個清單前，必須完成遊戲引擎、AI、畫面、模組獨立測試。
IMPLEMENTED_MODULES: frozenset[str] = frozenset(MODULE_KEYS)
REACTION_WINDOW_SECONDS = 3.0
TARGET_SELECTION_SECONDS = 10.0

# 這兩位原版資料未有特殊骰/酋長箭時不可加入抽角。
NEW_CHARACTER_REQUIREMENTS = {
    "jose_delgado": frozenset({"saloon_dice"}),
    "tequila_joe": frozenset({"saloon_dice"}),
    "apache_kid": frozenset({"chief_arrow"}),
    "bill_noface": frozenset(),
    "elena_fuente": frozenset(),
    "vera_custer": frozenset(),
    "doc_holyday": frozenset(),
    "molly_stark": frozenset(),
}

UNDEAD_CHARACTER_REQUIREMENTS = {
    "belle_star": frozenset(), "chuck_wengam": frozenset(),
    "greg_digger": frozenset({"duel_dice"}),
    "herb_hunter": frozenset({"duel_dice"}),
    "pat_brennan": frozenset({"rage"}),
    "pixie_pete": frozenset({"rage"}),
    "sam_the_healer": frozenset({"duel_dice"}),
    "sean_mallory": frozenset({"duel_dice"}),
}


@dataclass
class ExpansionConfig:
    mode: str = "base"  # "base" / "saloon"
    modules: set[str] = field(default_factory=set)

    def __post_init__(self):
        if self.mode not in {"base", "saloon"}:
            raise ValueError("不支援的遊戲模式")
        if set(self.modules) - set(MODULE_KEYS):
            raise ValueError("未知的老酒館模組")

    def enabled(self, module: str) -> bool:
        return self.mode == "saloon" and module in self.modules

    def toggle(self, key: str, player_count: int):
        if key not in MODULE_KEYS:
            raise ValueError("未知的老酒館模組")
        if key == "ghost" and player_count < 5 and key not in self.modules:
            raise ValueError("鬼魂模式至少需要 5 位玩家")
        if key in self.modules:
            self.modules.remove(key)
            if key == "rage":self.modules.discard("duel_dice")
        else:
            self.modules.add(key)
            if key == "duel_dice":self.modules.add("rage")

    def active_modules(self) -> set[str]:
        return set(self.modules) if self.mode == "saloon" else set()

    def playable_status(self, player_count: int) -> tuple[bool, str]:
        if player_count < 3 or player_count > 8:
            return False, "必須有 3～8 位玩家才能開始。"
        mods = self.active_modules()
        if "duel_dice" in mods and "rage" not in mods:
            return False, "決鬥骰必須搭配憤怒卡。請一起開啟。"
        if "ghost" in mods and player_count < 5:
            return False, "鬼魂模式至少需要 5 人。請先增加玩家或關閉鬼魂模式。"
        pending = mods - IMPLEMENTED_MODULES
        if pending:
            names = "、".join(MODULE_LABELS[k] for k in MODULE_KEYS if k in pending)
            return False, f"這些擴充還在開發，不能開始：{names}。請先關閉，或切回原版。"
        return True, "可以開始。"

    def eligible_new_characters(self) -> tuple[str, ...]:
        active = self.active_modules()
        saloon = tuple(k for k, requirements in NEW_CHARACTER_REQUIREMENTS.items()
                     if k != "molly_stark" and requirements.issubset(active)) if self.enabled("new_characters") else ()
        undead = tuple(k for k, requirements in UNDEAD_CHARACTER_REQUIREMENTS.items()
                     if requirements.issubset(active)) if self.enabled("undead_characters") else ()
        return saloon + undead


@dataclass
class DieState:
    """擴充骰的目標資料模型；現階段不改動原版 Game.dice。"""
    kind: str = "base"  # base / loudmouth / coward
    face: str = ""
    locked: bool = False


@dataclass
class ReactionWindow:
    """給未來 3 秒公開技能反應機制使用，v0.8.0 尚未啟動此流程。"""
    event_id: int
    trigger: str
    qualified_player_ids: set[int]
    opens_at: float
    deadline: float
    claimed_by: Optional[int] = None
    state: str = "open"

    def can_claim(self, pid: int, now: float) -> bool:
        return (self.state == "open" and self.claimed_by is None
                and pid in self.qualified_player_ids
                and self.opens_at <= now < self.deadline)
