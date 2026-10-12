from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from old_saloon import ExpansionConfig, ReactionWindow, DieState

LOUD_FACES = ("arrow", "bullet", "double_bull1", "double_bull2", "dynamite", "double_gatling")
COWARD_FACES = ("arrow", "broken_arrow", "bull1", "bull2", "beer", "double_beer")
SPECIAL_DICE = {"loudmouth": LOUD_FACES, "coward": COWARD_FACES}

def count_symbols(game, face):
    return sum((2 if value == "double_" + face else 1 if value == face else 0) for value in game.dice)

def pick_saloon_die(game, kind):
    if game.phase != "turn_start" or kind not in {"base", "loudmouth", "coward"}:
        return False
    if kind != "base" and not game.expansion_config.enabled("saloon_dice"):
        return False
    game.dice_types = [DieState(kind=kind)] + [DieState() for _ in range(4)]
    return True


from data import (
    ARROW, DYNAMITE, BULL1, BULL2, BEER, GATLING,
    DICE_FACES, CHARACTERS, CHAR_BY_KEY,
    ROLE_SETS, THREE_PLAYER_ROLES, THREE_PLAYER_TARGET, ROLE_CN,
)

@dataclass
class Player:
    pid: int
    name: str
    is_ai: bool = False
    role: str = ""
    character_key: str = ""
    hp: int = 0
    max_hp: int = 0
    arrows: int = 0
    alive: bool = True
    special_role_key: str = ""
    role_revealed: bool = False
    role_power_used: bool = False
    is_ghost: bool = False
    ghost_target: Optional[int] = None

    @property
    def character(self):
        return CHAR_BY_KEY[self.character_key] if self.character_key else None


@dataclass
class Game:
    chat_id: int
    host_id: int
    expansion_config: ExpansionConfig = field(default_factory=ExpansionConfig)
    reaction_window: Optional[ReactionWindow] = None
    event_queue: list[dict] = field(default_factory=list)
    dice_types: list[DieState] = field(default_factory=list)
    chief_arrow_owner: Optional[int] = None
    ghost_state: dict = field(default_factory=dict)
    undead_state: dict = field(default_factory=dict)
    players: list[Player] = field(default_factory=list)
    phase: str = "lobby"  # lobby/turn_start/rolling/slab_choice/resolving/ended
    current_idx: int = 0
    arrows_pool: int = 9
    dice: list[str] = field(default_factory=list)
    roll_no: int = 0
    selected: set[int] = field(default_factory=set)
    pending_actions: list[dict] = field(default_factory=list)
    pending_action: Optional[dict] = None
    board_message_id: Optional[int] = None
    winner_text: str = ""
    winner_indices: list[int] = field(default_factory=list)
    final_announcement_sent: bool = False
    indian_attacks: int = 0
    log: list[str] = field(default_factory=list)
    three_player_duel: bool = False
    announced_deaths: set[int] = field(default_factory=set)  # 已向群組公告的死亡玩家索引
    # 保留最近幾次傷害事件，牌桌與 Telegram 說明同步使用。
    # 記錄射手、受傷者及前後血量，避免玩家只能自己比較血條。
    recent_hits: list[dict] = field(default_factory=list)
    last_hit: Optional[dict] = None
    recent_actions: list[dict] = field(default_factory=list)
    last_action: Optional[dict] = None
    slab_used: bool = False
    sid_done: bool = False
    # 真人被攻擊時，暫停傷害並讓能力持有者親自選擇。
    damage_session: Optional[dict] = None
    completed_damage_events: list[str] = field(default_factory=list)

    def alive_indices(self) -> list[int]:
        return [i for i, p in enumerate(self.players) if p.alive]

    def alive_count(self) -> int:
        return sum(1 for p in self.players if p.alive)

    def current_player(self) -> Player:
        return self.players[self.current_idx]

    def add_log(self, text: str):
        self.log.append(text)
        self.log = self.log[-8:]


def add_human(game: Game, user_id: int, name: str) -> bool:
    if game.phase != "lobby" or len(game.players) >= 8:
        return False
    if any(p.pid == user_id and not p.is_ai for p in game.players):
        return False
    game.players.append(Player(user_id, name, False))
    return True


def add_ai(game: Game) -> bool:
    if game.phase != "lobby" or len(game.players) >= 8:
        return False
    used = {abs(p.pid) for p in game.players if p.is_ai}
    n = 1
    while n in used:
        n += 1
    game.players.append(Player(-n, f"電腦{n}", True))
    return True


def remove_ai(game: Game) -> bool:
    if game.phase != "lobby":
        return False
    for i in range(len(game.players) - 1, -1, -1):
        if game.players[i].is_ai:
            game.players.pop(i)
            return True
    return False


def remove_human(game: Game, user_id: int) -> bool:
    if game.phase != "lobby":
        return False
    for i, p in enumerate(game.players):
        if not p.is_ai and p.pid == user_id:
            game.players.pop(i)
            return True
    return False


def setup_game(game: Game, rng=random) -> list[str]:
    n = len(game.players)
    if n < 3 or n > 8:
        raise ValueError("玩家總數必須是 3～8 人")
    # 必須在任何角色／身分分配前驗證，不能以原版邏輯偷跑未完成的擴充。
    playable, why = game.expansion_config.playable_status(n)
    if not playable:
        raise ValueError(why)

    roles = THREE_PLAYER_ROLES[:] if n == 3 else ROLE_SETS[n][:]
    rng.shuffle(roles)
    pool = CHARACTERS + [CHAR_BY_KEY[k] for k in game.expansion_config.eligible_new_characters()]
    chars = rng.sample(pool, n)

    for p, role, char in zip(game.players, roles, chars):
        p.role = role
        p.character_key = char.key
        p.max_hp = char.hp + (2 if role == "sheriff" else 0)
        p.hp = p.max_hp
        p.arrows = 0
        p.alive = True

    from saloon_runtime import assign_special_roles
    assign_special_roles(game, rng)
    game.reaction_window = None
    game.event_queue.clear()
    game.dice_types.clear()
    game.chief_arrow_owner = None
    game.ghost_state.clear()
    game.undead_state.clear()
    game.arrows_pool = 9
    game.dice = []
    game.dice_types = []
    game.roll_no = 0
    game.selected.clear()
    game.pending_actions.clear()
    game.pending_action = None
    game.winner_text = ""
    game.winner_indices.clear()
    game.final_announcement_sent = False
    game.indian_attacks = 0
    game.three_player_duel = False
    game.announced_deaths.clear()
    game.recent_hits.clear()
    game.last_hit = None
    game.recent_actions.clear()
    game.last_action = None
    game.slab_used = False
    game.sid_done = False
    game.damage_session = None
    game.completed_damage_events.clear()
    game.log.clear()

    if n == 3:
        # 三人規則：副警長先手，且身份公開
        game.current_idx = next(i for i, p in enumerate(game.players) if p.role == "deputy")
    else:
        game.current_idx = next(i for i, p in enumerate(game.players) if p.role == "sheriff")

    game.phase = "turn_start"
    game.add_log(f"遊戲開始，{game.current_player().name} 先手。")
    return [f"{p.name}：{p.character.cn}" for p in game.players]


def max_rolls(player: Player) -> int:
    return 4 if player.character_key == "lucky_duke" else 3


def distance(game: Game, a_idx: int, b_idx: int) -> int:
    if a_idx == b_idx:
        return 0
    alive = game.alive_indices()
    if a_idx not in alive or b_idx not in alive:
        return 999
    pa = alive.index(a_idx)
    pb = alive.index(b_idx)
    d = abs(pa - pb)
    return min(d, len(alive) - d)


def valid_targets_for_face(game: Game, shooter_idx: int, face: str) -> list[int]:
    shooter = game.players[shooter_idx]
    alive_n = game.alive_count()
    out = []
    for i, p in enumerate(game.players):
        if i == shooter_idx or not p.alive:
            continue
        d = distance(game, shooter_idx, i)

        if shooter.character_key == "calamity_janet":
            allowed = {1, 2}
        elif shooter.character_key == "rose_doolan":
            allowed = {1, 2} if face == BULL1 else ({1} if alive_n <= 3 else {2, 3})
        else:
            if face == BULL1:
                allowed = {1}
            else:
                allowed = {1} if alive_n <= 3 else {2}

        if d in allowed:
            out.append(i)
    return out


# 將每次傷害顯示為明確的「誰 → 誰、扣幾血、剩幾血」。
# 自動結算的印第安人/炸藥也會記錄，以免誤以為某人開槍。
CAUSE_LABEL = {
    "shot": "🎯", "gatling": "🔫 格林機槍",
    "indians": "🏹 印第安人", "dynamite": "💥 炸藥",
    "duel": "決鬥", "chuck": "查克能力", "bullet": "子彈骰面",
}


def format_hit(game: Game, hit: dict, compact: bool = False, for_image: bool = False) -> str:
    src = hit["source_idx"]
    source = game.players[src].name if src is not None else CAUSE_LABEL.get(hit["cause"], "環境")
    if for_image and src is None:
        source = {"indians": "印第安人", "dynamite": "炸藥", "duel": "決鬥",
                  "chuck": "查克能力", "bullet": "子彈骰面"}.get(hit["cause"], "環境")
    target = game.players[hit["target_idx"]].name
    if compact:
        source, target = source[:9], target[:9]
    if hit["cause"] == "shot":
        prefix = "" if for_image else "🎯 "
    elif hit["cause"] == "gatling":
        prefix = "" if for_image else "🔫 "
        source += "〔機槍〕"
    elif hit["cause"] == "duel":
        prefix = "" if for_image else "⚔️ "
        source += "〔決鬥〕"
    else:
        prefix = ""
    if hit["lost"]:
        result = f"−{hit['lost']}血｜{hit['before']}→{hit['after']}"
        if hit["after"] <= 0:
            result += " 💀淘汰"
    else:
        result = f"擋下傷害｜{hit['after']}血"
    return f"{prefix}{source} → {target}：{result}"


def _record_hit(game: Game, source_idx: Optional[int], target_idx: int,
                cause: str, before: int, lost: int, events: list[str],
                insert_at: int):
    record = {
        "source_idx": source_idx, "target_idx": target_idx,
        "cause": cause, "before": max(0, before),
        "after": max(0, game.players[target_idx].hp), "lost": lost,
    }
    game.recent_hits.append(record)
    game.recent_hits[:] = game.recent_hits[-8:]
    game.last_hit = record
    action = {"kind": "hit", **record}
    game.last_action = action
    game.recent_actions.append(action)
    game.recent_actions[:] = game.recent_actions[-8:]
    events.insert(insert_at, format_hit(game, record))


def heal(game: Game, idx: int, amount: int) -> int:
    p = game.players[idx]
    if not p.alive:
        return 0
    before = p.hp
    p.hp = min(p.max_hp, p.hp + amount)
    return p.hp - before



def format_action(game: Game, action: dict, compact: bool = False, for_image: bool = False) -> str:
    """用一種格式顯示射擊與回血，血量變化直接可讀。"""
    if action.get("kind") != "heal":
        return format_hit(game, action, compact=compact, for_image=for_image)
    source_idx = action.get("source_idx")
    target_idx = action["target_idx"]
    source = game.players[source_idx].name if source_idx is not None else "角色能力"
    target = game.players[target_idx].name
    if compact:
        source, target = source[:9], target[:9]
    prefix = "" if for_image else ("🍺 " if action.get("cause") == "beer" else "💚 ")
    if source_idx == target_idx:
        who = f"{source} 自己回血"
    else:
        who = f"{source} → {target}"
    gained = action["gained"]
    if gained == 0:
        return f"{prefix}{who}：已滿血 {action['after']}/{game.players[target_idx].max_hp}，未補血"
    result = f"+{gained}血｜{action['before']}→{action['after']}"
    return f"{prefix}{who}：{result}"


def heal_with_record(game: Game, idx: int, amount: int, source_idx: Optional[int],
                     cause: str = "beer") -> tuple[int, str]:
    """所有喝啤酒與角色補血都保留來源、目標及前後血量。"""
    before = game.players[idx].hp
    gained = heal(game, idx, amount)
    action = {
        "kind": "heal", "cause": cause, "source_idx": source_idx,
        "target_idx": idx, "before": before,
        "after": game.players[idx].hp, "gained": gained,
    }
    game.last_action = action
    game.recent_actions.append(action)
    game.recent_actions[:] = game.recent_actions[-8:]
    return gained, format_action(game, action)


def _eliminate(game: Game, idx: int, killer_idx: Optional[int], cause: str, events: list[str]):
    p = game.players[idx]
    if not p.alive:
        return
    p.alive = False
    if game.chief_arrow_owner == idx:
        game.chief_arrow_owner = None
    if p.arrows:
        game.arrows_pool += p.arrows
        p.arrows = 0
    events.append(f"💀 {p.name}（{p.character.cn}）被淘汰！🎭 公開身分：{ROLE_CN[p.role]}")

    # 禿鷹山姆：其他玩家被淘汰時回 2
    for j, other in enumerate(game.players):
        if j != idx and other.alive and other.character_key == "vulture_sam":
            gained, line = heal_with_record(game, j, 2, j, "vulture")
            if gained:
                events.append(line)

    # 三人特殊勝利
    if len(game.players) == 3:
        if killer_idx is not None and game.players[killer_idx].alive:
            killer = game.players[killer_idx]
            if THREE_PLAYER_TARGET.get(killer.role) == p.role and not game.three_player_duel:
                game.phase = "ended"
                game.winner_text = f"🏆 {killer.name} 獲勝！"
                game.winner_indices = [killer_idx]
                return
        game.three_player_duel = True


def winning_player_indices(game: Game) -> list[int]:
    """官方勝方：隊伍勝利包含已淘汰隊友；8 人叛徒只算個人。"""
    if game.phase != "ended":
        return []
    if game.winner_indices:
        return list(game.winner_indices)
    if len(game.players) == 3:
        return []  # 三人局勝者在結算當下儲存，無人存活則沒有勝者
    sheriff = next((p for p in game.players if p.role == "sheriff"), None)
    if sheriff and sheriff.alive:
        return [i for i, p in enumerate(game.players) if p.role in {"sheriff", "deputy"}]
    alive = [i for i, p in enumerate(game.players) if p.alive]
    if len(alive) == 1 and game.players[alive[0]].role == "renegade":
        return alive
    return [i for i, p in enumerate(game.players) if p.role == "outlaw"]


def format_final_results(game: Game) -> str:
    """遊戲結束才可公開所有身分，含身分、角色、存活狀態及勝利玩家。"""
    if game.phase != "ended":
        return ""
    winners = winning_player_indices(game)
    winner_labels = "、".join(f"{game.players[i].name}（{ROLE_CN[game.players[i].role]}）" for i in winners)
    lines = [game.winner_text, f"🥇 獲勝玩家：{winner_labels or '無'}", "", "🎭 本局所有玩家身分："]
    for i, p in enumerate(game.players):
        badge = "🏆" if i in winners else "▫️"
        status = "存活" if p.alive else "已淘汰"
        cname = p.character.cn if p.character else "未分配"
        lines.append(f"{badge} {p.name}｜{ROLE_CN[p.role]}｜{cname}｜{status}")
    lines.extend(["", "🎲 本局結束，輸入 /newgame 再來一局。"])
    return "\n".join(lines)


def check_win(game: Game) -> Optional[str]:
    if game.phase == "ended" and game.winner_text:
        return game.winner_text

    alive = [p for p in game.players if p.alive]
    if len(game.players) == 3:
        if not alive:
            game.phase = "ended"
            game.winner_text = "🏁 本局無人生還。"
            return game.winner_text
        if game.three_player_duel and len(alive) == 1:
            game.phase = "ended"
            game.winner_text = f"🏆 {alive[0].name} 成為最後存活者！"
            game.winner_indices = [game.players.index(alive[0])]
            return game.winner_text
        return None

    sheriff = next((p for p in game.players if p.role == "sheriff"), None)
    if not alive or (sheriff and not sheriff.alive):
        game.phase = "ended"
        if len(alive) == 1 and alive[0].role == "renegade":
            game.winner_text = f"🎭 叛徒 {alive[0].name} 獨自存活，獲勝！"
        else:
            # 原版：即使印第安人使全員同時死亡，仍由歹徒獲勝。
            game.winner_text = "🔫 歹徒陣營獲勝！"
        return game.winner_text

    enemies_alive = any(p.alive and p.role in {"outlaw", "renegade"} for p in game.players)
    if not enemies_alive:
        game.phase = "ended"
        game.winner_text = "⭐ 警長與副警長陣營獲勝！"
        return game.winner_text
    return None


def chief_arrow_enabled(game: Game) -> bool:
    return game.expansion_config.enabled("chief_arrow")


def arrow_tokens_remaining(game: Game) -> int:
    return game.arrows_pool + int(chief_arrow_enabled(game) and game.chief_arrow_owner is None)


def get_arrow_weight(game: Game, idx: int) -> int:
    return game.players[idx].arrows + (2 if game.chief_arrow_owner == idx and chief_arrow_enabled(game) else 0)


def take_chief_arrow(game: Game, idx: int, events: list[str]) -> bool:
    if not chief_arrow_enabled(game) or game.chief_arrow_owner is not None or not game.players[idx].alive:
        return False
    game.chief_arrow_owner = idx
    events.append(f"👑🏹 {game.players[idx].name} 取得酋長箭（箭雨傷害算 2 支）！")
    if arrow_tokens_remaining(game) == 0:
        indian_attack(game, events)
    return True


def _resolve_rolled_arrows(game: Game, rolled_indices: list[int], events: list[str], begin: int = 0) -> bool:
    """Return False when awaiting human decision / turn interrupted."""
    for at in range(begin, len(rolled_indices)):
        if game.phase == "ended": return False
        i = rolled_indices[at]
        if game.dice[i] != ARROW: continue
        if chief_arrow_enabled(game) and game.chief_arrow_owner is None and not game.current_player().is_ai:
            game.phase = "chief_arrow_choice"
            game.pending_action = {"type": "chief_arrow", "rolled_indices": rolled_indices, "cursor": at + 1}
            events.append("👑🏹 請選擇拿普通箭，或唯一的酋長箭。")
            return False
        if chief_arrow_enabled(game) and game.chief_arrow_owner is None and (game.arrows_pool == 0 or game.current_player().is_ai):
            take_chief_arrow(game, game.current_idx, events)
        else:
            take_arrow(game, game.current_idx, 1, events)
        if game.phase == "ended" or advance_if_current_eliminated(game, events):
            return False
    return True


def choose_chief_arrow(game: Game, use_chief: bool) -> list[str] | None:
    if game.phase != "chief_arrow_choice" or not game.pending_action or game.pending_action.get("type") != "chief_arrow":
        return None
    if use_chief and game.chief_arrow_owner is not None: return None
    if not use_chief and game.arrows_pool == 0: return None
    pending = game.pending_action
    game.pending_action = None
    game.phase = "rolling"
    events: list[str] = []
    if use_chief: take_chief_arrow(game, game.current_idx, events)
    else: take_arrow(game, game.current_idx, 1, events)
    if game.phase == "ended" or advance_if_current_eliminated(game, events): return events
    if not _resolve_rolled_arrows(game, pending["rolled_indices"], events, pending["cursor"]): return events
    _after_new_roll_other_effects(game, pending["rolled_indices"], events)
    return events


def take_arrow(game: Game, idx: int, count: int = 1, events: Optional[list[str]] = None):
    if events is None:
        events = []
    p = game.players[idx]
    for _ in range(count):
        if not p.alive:
            break
        if game.arrows_pool <= 0:
            # In chief mode the last physical token might be the chief arrow.
            if chief_arrow_enabled(game) and game.chief_arrow_owner is None:
                take_chief_arrow(game, idx, events)
                if game.phase == "ended": return
                continue
            indian_attack(game, events)
            if game.phase == "ended": return
        p.arrows += 1
        game.arrows_pool -= 1
        events.append(f"🏹 {p.name} 拿 1 支箭（身上 {p.arrows}，箭池 {game.arrows_pool}）。")
        if arrow_tokens_remaining(game) == 0:
            indian_attack(game, events)
            if game.phase == "ended":
                return


def indian_attack(game: Game, events: list[str]):
    """印第安人同時結算：全員先扣血，再處理淘汰及勝利。

    不能因為依玩家列表先結算到警長死亡，就跳過其他玩家的
    同次箭雨傷害。印第安人屬環境傷害，三人局也沒有擊殺者。
    """
    game.indian_attacks += 1
    events.append("🏹🏹🏹 印第安人來襲！全場同時結算箭雨。")
    damage_list = []
    weights = {i: get_arrow_weight(game, i) for i in range(len(game.players))}
    largest = max(weights.values(), default=0)
    chief_safe = (game.chief_arrow_owner is not None and
                  weights[game.chief_arrow_owner] == largest and
                  list(weights.values()).count(largest) == 1)
    for i, p in enumerate(game.players):
        if p.alive and weights[i] > 0:
            dmg = 0 if (chief_safe and game.chief_arrow_owner == i) else (1 if p.character_key == "jourdonnais" else weights[i])
            if chief_safe and game.chief_arrow_owner == i:
                events.append(f"👑 {p.name} 持有酋長箭並獨自擁有最多箭，免疫本次印第安人攻擊！")
            damage_list.append((i, dmg))

    # 箭雨之前的箭數已快照；全部箭先歸還箭池。
    game.arrows_pool = 9
    game.chief_arrow_owner = None
    for p in game.players:
        p.arrows = 0

    dying = []
    for i, dmg in damage_list:
        p = game.players[i]
        before = p.hp
        p.hp = max(0, before - dmg)
        lost = before - p.hp
        _record_hit(game, None, i, "indians", before, lost, events, len(events))
        if p.hp <= 0:
            dying.append(i)

    # 同次箭雨所有人的血都先扣完，才一起淘汰，避免任何中途勝負判斷。
    for i in dying:
        p = game.players[i]
        p.alive = False
        events.append(f"💀 {p.name}（{p.character.cn}）被箭雨淘汰！🎭 公開身分：{ROLE_CN[p.role]}")

    # 禿鷹山姆只有活過同次箭雨，才因其他玩家死亡回血。
    if dying:
        for j, other in enumerate(game.players):
            if other.alive and other.character_key == "vulture_sam":
                gained, line = heal_with_record(game, j, 2 * len(dying), j, "vulture")
                if gained:
                    events.append(line)
        if len(game.players) == 3:
            game.three_player_duel = True

    check_win(game)


def deal_damage(
    game: Game,
    target_idx: int,
    amount: int,
    source_idx: Optional[int],
    cause: str,
    events: Optional[list[str]] = None,
) -> int:
    if events is None:
        events = []
    target = game.players[target_idx]
    if not target.alive:
        return 0
    before_hp = target.hp
    start_event = len(events)

    # Paul Regret 免疫格林機槍
    if cause == "gatling" and target.character_key == "paul_regret":
        _record_hit(game, source_idx, target_idx, cause, before_hp, 0, events, start_event)
        events.append(f"🛡 {target.name}（保羅・雷格雷特）免疫格林機槍。")
        return 0

    lost = 0
    for _ in range(amount):
        if not target.alive:
            break

        # 電腦自動選擇；真人受傷由 start_damage_session 等待本人按鈕。
        if (
            target.is_ai and target.character_key == "bart_cassidy"
            and cause in {"shot", "gatling"}
            and game.arrows_pool > 1
        ):
            take_arrow(game, target_idx, 1, events)
            events.append(f"🎩 {target.name}（巴特・卡西迪）用拿箭代替 1 點傷害。")
            if game.phase == "ended":
                _record_hit(game, source_idx, target_idx, cause, before_hp, lost, events, start_event)
                return lost
            continue

        target.hp -= 1
        lost += 1

        # 電腦使用能力；真人可在傷害選擇階段決定是否丟箭。
        if target.is_ai and target.character_key == "pedro_ramirez" and target.arrows > 0:
            target.arrows -= 1
            game.arrows_pool += 1
            events.append(f"🪶 {target.name}（佩德羅）丟掉 1 支箭。")

        if target.hp <= 0:
            _eliminate(game, target_idx, source_idx, cause, events)
            check_win(game)
            break

    # 已確定的本次傷害先記錄；後續特殊能力若引發其他傷害另記錄。
    _record_hit(game, source_idx, target_idx, cause, before_hp, lost, events, start_event)

    # El Gringo：一次傷害事件只讓攻擊者拿 1 支箭
    if (
        lost > 0
        and source_idx is not None
        and source_idx != target_idx
        and target.character_key == "el_gringo"
        and cause in {"shot", "gatling"}
        and game.players[source_idx].alive
        and game.phase != "ended"
    ):
        events.append(f"😠 {target.name}（艾爾・格林哥）反擊效果：{game.players[source_idx].name} 拿 1 支箭。")
        take_arrow(game, source_idx, 1, events)

    return lost


def advance_if_current_eliminated(game: Game, events: list[str]) -> bool:
    """目前行動者在自己回合死亡：立即放棄剩餘骰面，並跳到下一名活人。

    箭雨/炸藥可能淘汰擲骰者但尚未達成勝利條件；此時不能把
    phase 留在 rolling/resolving，也不能繼續讓死人處理擲骰或能力。
    """
    if game.phase == "ended" or game.current_player().alive:
        return False
    if check_win(game):
        return True
    events.append(f"⏭ {game.current_player().name} 已淘汰，回合立即結束。")
    end_turn(game, events)
    return True


def start_turn(game: Game) -> list[str]:
    events = []
    if game.phase == "ended":
        return events
    p = game.current_player()
    game.dice = []
    game.dice_types = []
    game.roll_no = 0
    game.selected.clear()
    game.pending_actions.clear()
    game.pending_action = None
    game.slab_used = False
    game.sid_done = False
    game.damage_session = None
    game.completed_damage_events.clear()
    game.phase = "turn_start"
    events.append(f"🤠 輪到 {p.name}（{p.character.cn}）。")
    return events


def roll_initial(game: Game, rng=random) -> list[str]:
    if game.phase != "turn_start":
        return []
    if not game.dice_types:
        pick_saloon_die(game, "base")
    game.dice = [rng.choice(SPECIAL_DICE.get(d.kind, DICE_FACES)) for d in game.dice_types]
    game.roll_no = 1
    game.selected.clear()
    game.phase = "rolling"
    events = [f"🎲 {game.current_player().name} 第 1 次擲骰。"]
    _after_new_roll(game, list(range(len(game.dice))), events)
    return events


def reroll_selected(game: Game, rng=random) -> list[str]:
    p = game.current_player()
    if game.phase != "rolling" or not game.selected:
        return []
    if game.roll_no >= max_rolls(p):
        return []
    # Older state snapshots may have dice but no per-die metadata.
    if not game.dice_types:
        game.dice_types = [DieState() for _ in game.dice]
    if len(game.dice_types) != len(game.dice):
        raise ValueError("骰面與骰子種類數量不一致")
    indices = sorted(i for i in game.selected if 0 <= i < len(game.dice)
                     and (game.dice[i] != DYNAMITE or
                          (p.character_key == "black_jack" and count_symbols(game, DYNAMITE) < 3)))
    game.selected.clear()
    if not indices:
        return []
    for i in indices:
        game.dice[i] = rng.choice(SPECIAL_DICE.get(game.dice_types[i].kind, DICE_FACES))
    game.roll_no += 1
    game.selected.clear()
    events = [f"🎲 {p.name} 第 {game.roll_no} 次擲骰。"]
    _after_new_roll(game, indices, events)
    return events


def _after_new_roll(game: Game, rolled_indices: list[int], events: list[str]):
    if not _resolve_rolled_arrows(game, rolled_indices, events):
        return
    _after_new_roll_other_effects(game, rolled_indices, events)


def _after_new_roll_other_effects(game: Game, rolled_indices: list[int], events: list[str], begin: int = 0):
    for at in range(begin, len(rolled_indices)):
        i = rolled_indices[at]
        if game.dice[i] != "broken_arrow":
            continue
        choices = [j for j, person in enumerate(game.players) if person.alive and person.arrows > 0]
        if not choices:
            continue
        if not game.current_player().is_ai:
            game.phase = "broken_arrow_choice"
            game.pending_action = {"type": "broken_arrow", "rolled_indices": rolled_indices, "cursor": at + 1}
            events.append("🏹 斷箭：請選擇要移除哪位玩家的 1 支普通箭。")
            return
        target = game.current_idx if game.current_idx in choices else max(choices, key=lambda j: game.players[j].arrows)
        game.players[target].arrows -= 1
        game.arrows_pool += 1
        events.append(f"🏹 斷箭：{game.players[target].name} 移除 1 支箭。")
    # Bullets are evaluated only once, after all broken-arrow choices.
    for i in rolled_indices:
        if game.dice[i] == "bullet":
            events.append(f"🔫 子彈：{game.current_player().name} 自己失去 1 點生命！")
            deal_damage(game, game.current_idx, 1, None, "bullet", events)
            if game.phase == "ended" or advance_if_current_eliminated(game, events):
                return
    _after_new_roll_dynamite(game, events)


def finish_broken_arrow_choice(game: Game, target: int) -> list[str] | None:
    if game.phase != "broken_arrow_choice" or not game.pending_action or game.pending_action.get("type") != "broken_arrow":
        return None
    if target < 0 or target >= len(game.players) or not game.players[target].alive or game.players[target].arrows < 1:
        return None
    pending = game.pending_action
    game.players[target].arrows -= 1
    game.arrows_pool += 1
    game.phase = "rolling"
    game.pending_action = None
    events = [f"🏹 斷箭：{game.players[target].name} 移除 1 支箭。"]
    _after_new_roll_other_effects(game, pending["rolled_indices"], events, pending.get("cursor", len(pending["rolled_indices"])))
    return events


def _after_new_roll_dynamite(game: Game, events: list[str]):
    dyn = count_symbols(game, DYNAMITE)
    if dyn >= 3:
        events.append(f"💥 {game.current_player().name} 出現 {dyn} 個炸藥，失去 1 點生命並停止重擲。")
        deal_damage(game, game.current_idx, 1, None, "dynamite", events)
        if game.phase == "ended" or advance_if_current_eliminated(game, events):
            return
        victim = game.current_player()
        if victim.character_key == "pedro_ramirez" and not victim.is_ai and victim.arrows > 0:
            game.damage_session = {
                "cause": "post_pedro", "source_idx": None, "targets": [],
                "choices": [{"kind": "pedro", "idx": game.current_idx, "max": 1}],
                "cursor": 0, "blocks": {}, "discards": {},
                "events": events, "start_log_index": len(events),
                "origin_phase": "rolling", "finalize_roll": True,
            }
            game.phase = "damage_choice"
            return
        finalize_dice(game, events)


def toggle_die(game: Game, die_index: int) -> bool:
    if game.phase != "rolling" or die_index < 0 or die_index >= len(game.dice):
        return False
    p = game.current_player()
    if game.roll_no >= max_rolls(p):
        return False
    if game.dice[die_index] == DYNAMITE:
        if p.character_key != "black_jack" or game.dice.count(DYNAMITE) >= 3:
            return False
    if die_index in game.selected:
        game.selected.remove(die_index)
    else:
        game.selected.add(die_index)
    return True


def finalize_dice(game: Game, events: Optional[list[str]] = None) -> list[str]:
    if events is None:
        events = []
    if game.phase == "ended":
        return events
    game.selected.clear()

    p = game.current_player()
    b1 = count_symbols(game, BULL1)
    b2 = count_symbols(game, BULL2)
    beer = count_symbols(game, BEER)
    gat = count_symbols(game, GATLING)

    # Slab 選擇：若有人類，交給 bot.py 問；AI 由 AI 邏輯決定
    if p.character_key == "slab_the_killer" and beer > 0 and (b1 + b2) > 0 and not p.is_ai:
        game.phase = "slab_choice"
        game.pending_action = {"type": "slab_choice"}
        return events

    _build_resolution_queue(game, slab_double=False)
    game.phase = "resolving"
    return events


def apply_slab_choice(game: Game, use: bool | str):
    if game.phase != "slab_choice":
        return
    if use is True:
        face = next((f for f in (BULL1, BULL2) if count_symbols(game, f)), None)
    else:
        face = use if use in (BULL1, BULL2) else None
    _build_resolution_queue(game, slab_double=bool(face), slab_face=face)
    game.phase = "resolving"
    game.pending_action = None


def _build_resolution_queue(game: Game, slab_double: bool, slab_face: Optional[str] = None):
    p = game.current_player()
    faces = game.dice[:]
    actions = []
    doubled = False
    if slab_double and slab_face not in {BULL1, BULL2}:
        slab_face = next((f for f in (BULL1, BULL2) if count_symbols(game, f)), None)

    for face in sorted(faces, key=lambda f: 0 if f in {BULL1, "double_bull1"} else 1):
        if face in {BULL1, BULL2, "double_bull1", "double_bull2"}:
            repeats = 2 if face.startswith("double_") else 1
            face = face.removeprefix("double_")
            # Slab doubles one single shooting result (same target), not both halves of a double die.
            if slab_double and not doubled and count_symbols(game, BEER) > 0 and face == slab_face:
                actions.append({"type": "shot", "face": face, "amount": 2})
                doubled = True
                repeats -= 1
            for _ in range(repeats):
                actions.append({"type": "shot", "face": face, "amount": 1})

    beers = count_symbols(game, BEER) - (1 if doubled else 0)
    for _ in range(max(0, beers)):
        actions.append({"type": "beer"})

    gat_count = count_symbols(game, GATLING)
    threshold = 2 if p.character_key == "willy_the_kid" else 3
    if gat_count >= threshold:
        actions.append({"type": "gatling", "count": gat_count})

    if p.character_key == "kit_carlson":
        for _ in range(gat_count):
            actions.append({"type": "kit_discard"})

    actions.append({"type": "end_turn"})
    game.pending_actions = actions
    game.pending_action = None
    game.slab_used = doubled


def pop_next_action(game: Game) -> Optional[dict]:
    if game.phase == "ended":
        return None
    if game.pending_action is not None:
        return game.pending_action
    if not game.pending_actions:
        return None
    game.pending_action = game.pending_actions.pop(0)
    return game.pending_action


def finish_pending_action(game: Game):
    game.pending_action = None


def _resolve_gatling_batch(game: Game, events: list[str], blocks: dict[int, int],
                           pedro: dict[int, int]):
    """同一次機槍先算全員血量，再同時淘汰、最後才觸發山姆回血。"""
    shooter_idx = game.current_idx
    shooter = game.players[shooter_idx]
    events.append(f"🔫 {shooter.name} 發動格林機槍！")
    dying = []
    gringo_targets = []
    # 真人的選擇優先於電腦自動擋傷，確保已點選的箭不會被 AI 搶用。
    actual_blocks = {}
    for i in sorted(blocks, key=lambda j: (game.players[j].is_ai, j)):
        p = game.players[i]
        if not p.alive or p.character_key != "bart_cassidy":
            continue
        block = min(blocks[i], max(0, game.arrows_pool - 1))
        if block > 0:
            game.arrows_pool -= block
            p.arrows += block
            actual_blocks[i] = block
            events.append(f"🎩 {p.name} 拿 {block} 支箭，代替格林機槍傷害。")
    for i, p in enumerate(game.players):
        if i == shooter_idx or not p.alive:
            continue
        before = p.hp
        damage = 0 if p.character_key == "paul_regret" else 1
        damage -= actual_blocks.get(i, 0)
        p.hp = max(0, p.hp - damage)
        lost = before - p.hp
        if p.character_key == "pedro_ramirez" and lost and p.arrows:
            discarded = min(pedro.get(i, 0), lost, p.arrows)
            if discarded:
                p.arrows -= discarded
                game.arrows_pool += discarded
                events.append(f"🪶 {p.name} 選擇丟掉 {discarded} 支箭。")
        _record_hit(game, shooter_idx, i, "gatling", before, lost, events, len(events))
        if p.hp == 0:
            dying.append(i)
        if lost and p.character_key == "el_gringo":
            gringo_targets.append(i)

    # 同時淘汰。已受致命傷的山姆不能靠同批死亡回血自救。
    for i in dying:
        p = game.players[i]
        p.alive = False
        if game.chief_arrow_owner == i:
            game.chief_arrow_owner = None
        if p.arrows:
            game.arrows_pool += p.arrows
            p.arrows = 0
        events.append(f"💀 {p.name}（{p.character.cn}）被淘汰！🎭 公開身分：{ROLE_CN[p.role]}")
    if dying:
        for i, p in enumerate(game.players):
            if p.alive and p.character_key == "vulture_sam":
                gained, line = heal_with_record(game, i, len(dying) * 2, i, "vulture")
                if gained:
                    events.append(line)
        if len(game.players) == 3:
            targets_killed = {game.players[i].role for i in dying}
            if shooter.alive and THREE_PLAYER_TARGET.get(shooter.role) in targets_killed and not game.three_player_duel:
                game.phase = "ended"
                game.winner_text = f"🏆 {shooter.name} 獲勝！"
                game.winner_indices = [shooter_idx]
            else:
                game.three_player_duel = True

    # 格林機槍清自己的箭；艾爾・格林哥的反擊箭在這之後獲得。
    if shooter.alive and shooter.arrows:
        game.arrows_pool += shooter.arrows
        events.append(f"🏹 {shooter.name} 丟掉自己的 {shooter.arrows} 支箭。")
        shooter.arrows = 0
    if shooter.alive and game.chief_arrow_owner == shooter_idx:
        game.chief_arrow_owner = None
        events.append(f"👑🏹 {shooter.name} 丟掉自己的酋長箭。")
    if game.phase != "ended":
        for _ in gringo_targets:
            if not shooter.alive or game.phase == "ended":
                break
            events.append(f"😠 艾爾・格林哥反擊：{shooter.name} 拿 1 支箭。")
            take_arrow(game, shooter_idx, 1, events)
        check_win(game)


def resolve_gatling(game: Game, events: list[str]):
    """沒有等待按鈕的同步結算路徑；電腦自動選擇擋傷及移箭。"""
    blocks = {}
    discards = {}
    available = game.arrows_pool
    for i, p in enumerate(game.players):
        if not p.alive or i == game.current_idx or p.character_key == "paul_regret":
            continue
        if p.character_key == "bart_cassidy" and p.is_ai and available > 1:
            blocks[i] = 1
            available -= 1
        if p.character_key == "pedro_ramirez" and p.is_ai and p.arrows > 0:
            discards[i] = 1
    _resolve_gatling_batch(game, events, blocks, discards)


def start_damage_session(game: Game, targets: list[tuple[int, int]],
                         source_idx: Optional[int], cause: str, events: list[str]) -> bool:
    """真人被攻擊時詢問本人。True 表示需要等待選擇，False 表示已結算。"""
    choices = []
    blocks: dict[int, int] = {}
    discards: dict[int, int] = {}
    reserved_pool = game.arrows_pool
    for idx, amount in targets:
        p = game.players[idx]
        if not p.alive:
            continue
        if cause == "gatling" and p.character_key == "paul_regret":
            continue
        if p.character_key == "bart_cassidy" and cause in {"shot", "gatling"}:
            cap = min(amount, max(0, (reserved_pool if p.is_ai else game.arrows_pool) - 1))
            if p.is_ai:
                blocks[idx] = cap
                reserved_pool -= cap
            elif cap:
                choices.append({"kind": "bart", "idx": idx, "max": cap})
                # 下一個巴特實際可用的箭池數會在選擇後重新判斷。
        if p.character_key == "pedro_ramirez" and p.arrows > 0:
            # 致命一擊時箭會隨淘汰全數丟掉，無需為無意義的選擇停局。
            cap = min(amount, p.arrows) if p.hp > amount else 0
            if p.is_ai:
                discards[idx] = cap
            elif cap:
                choices.append({"kind": "pedro", "idx": idx, "max": cap})

    if not choices:
        if cause == "gatling":
            _resolve_gatling_batch(game, events, blocks, discards)
        else:
            for idx, amount in targets:
                _resolve_selected_shot(game, idx, amount, source_idx, cause, blocks.get(idx, 0), discards.get(idx, 0), events)
        return False
    game.damage_session = {
        "cause": cause, "source_idx": source_idx, "targets": targets,
        "choices": choices, "cursor": 0, "blocks": blocks,
        "discards": discards, "events": events, "origin_phase": game.phase,
        "start_log_index": len(events),
    }
    game.phase = "damage_choice"
    return True


def current_damage_choice(game: Game) -> Optional[dict]:
    session = game.damage_session
    if not session or session["cursor"] >= len(session["choices"]):
        return None
    choice = dict(session["choices"][session["cursor"]])
    if choice["kind"] == "bart":
        choice["max"] = min(choice["max"], max(0, game.arrows_pool - 1))
    return choice


def choose_damage_option(game: Game, idx: int, count: int) -> bool:
    """由受傷玩家本人執行。回傳 True 代表整批已結算。"""
    s = game.damage_session
    choice = current_damage_choice(game)
    if not s or not choice or choice["idx"] != idx or not 0 <= count <= choice["max"]:
        raise ValueError("無效或已過期的能力選擇")
    if choice["kind"] == "bart":
        s["blocks"][idx] = count
        # 箭不能立即拿，以免破壞同時傷害；但下一位巴特可分配的箭池要扣掉保留額度。
        game.arrows_pool -= count
        s["events"].append(f"🎩 {game.players[idx].name} 選擇用 {count} 支箭抵擋傷害。" if count else f"🎩 {game.players[idx].name} 選擇承受傷害。")
    else:
        s["discards"][idx] = count
        s["events"].append(f"🪶 {game.players[idx].name} 選擇丟掉 {count} 支箭。" if count else f"🪶 {game.players[idx].name} 選擇保留箭。")
    s["cursor"] += 1
    if s["cursor"] < len(s["choices"]):
        return False
    # 將預留的箭額度恢復，讓實際結算再扣一次（避免重複扣）。
    game.arrows_pool += sum(s["blocks"].values())
    game.damage_session = None
    if game.phase != "ended":
        game.phase = s["origin_phase"]
    if s["cause"] == "post_pedro":
        p = game.players[idx]
        n = min(s["discards"].get(idx, 0), p.arrows)
        p.arrows -= n
        game.arrows_pool += n
        if s.get("finalize_roll"):
            finalize_dice(game, s["events"])
    elif s["cause"] == "gatling":
        _resolve_gatling_batch(game, s["events"], s["blocks"], s["discards"])
    else:
        for target, amount in s["targets"]:
            _resolve_selected_shot(game, target, amount, s["source_idx"], s["cause"],
                                   s["blocks"].get(target, 0), s["discards"].get(target, 0), s["events"])
    game.completed_damage_events = list(s["events"][s["start_log_index"]:])
    return True


def _resolve_selected_shot(game: Game, idx: int, amount: int, source_idx: Optional[int],
                           cause: str, blocked: int, discard: int, events: list[str]):
    p = game.players[idx]
    blocked = min(blocked, max(0, game.arrows_pool - 1))
    if blocked:
        p.arrows += blocked
        game.arrows_pool -= blocked
    before = p.hp
    lost = max(0, min(before, amount - blocked))
    p.hp -= lost
    discard = min(discard, lost, p.arrows)
    if discard:
        p.arrows -= discard
        game.arrows_pool += discard
    _record_hit(game, source_idx, idx, cause, before, lost, events, len(events))
    if p.hp == 0 and p.alive:
        _eliminate(game, idx, source_idx, cause, events)
        check_win(game)
    if (lost and p.character_key == "el_gringo" and source_idx is not None and
            source_idx != idx and game.players[source_idx].alive and game.phase != "ended"):
        events.append(f"😠 {p.name} 反擊：{game.players[source_idx].name} 拿 1 支箭。")
        take_arrow(game, source_idx, 1, events)


def end_turn(game: Game, events: list[str]):
    p = game.current_player()
    if p.alive and p.character_key == "suzy_lafayette":
        if count_symbols(game, BULL1) + count_symbols(game, BULL2) == 0:
            gained, line = heal_with_record(game, game.current_idx, 2, game.current_idx, "suzy")
            if gained:
                events.append(line)

    if check_win(game):
        return

    if not game.alive_indices():
        return
    n = len(game.players)
    next_idx = None
    for step in range(1, n + 1):
        cand = (game.current_idx + step) % n
        if game.players[cand].alive:
            next_idx = cand
            break
    if next_idx is None:
        return
    game.current_idx = next_idx
    start_turn(game)


def public_role_text(game: Game, p: Player) -> str:
    if len(game.players) == 3:
        return p.role
    return p.role if p.role == "sheriff" or p.role_revealed or not p.alive else "hidden"
