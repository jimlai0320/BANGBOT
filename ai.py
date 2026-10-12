import random

from data import BULL1, BULL2, BEER, GATLING, ARROW, DYNAMITE
from game_engine import (
    Game, max_rolls, pick_saloon_die, count_symbols, valid_targets_for_face, heal, heal_with_record, take_arrow,
    deal_damage, resolve_gatling, end_turn, advance_if_current_eliminated, pop_next_action,
    finish_pending_action, apply_slab_choice, finalize_dice,
    roll_initial, reroll_selected, start_damage_session,
)

def choose_ai_rerolls(game: Game) -> set[int]:
    p = game.current_player()
    keep = set()
    gat = count_symbols(game, GATLING)
    threshold = 2 if p.character_key == "willy_the_kid" else 3

    for i, face in enumerate(game.dice):
        if face == DYNAMITE:
            if p.character_key != "black_jack":
                keep.add(i)
            continue
        if face in {ARROW, "bullet", "broken_arrow"}:
            continue
        if face in {BULL1, BULL2, "double_bull1", "double_bull2"}:
            face = face.removeprefix("double_")
            if valid_targets_for_face(game, game.current_idx, face):
                keep.add(i)
            continue
        if face in {BEER, "double_beer"}:
            if any(x.alive and x.hp < x.max_hp for x in game.players):
                keep.add(i)
            continue
        if face in {GATLING, "double_gatling"}:
            if gat >= threshold - 1:
                keep.add(i)

    return set(range(len(game.dice))) - keep


def _enemy_score(game: Game, target_idx: int) -> float:
    me = game.current_player()
    t = game.players[target_idx]
    score = 0.0

    if me.role == "outlaw":
        if t.role == "sheriff":
            score += 100
        elif t.role == "deputy":
            score += 20
    elif me.role == "deputy":
        if t.role in {"outlaw", "renegade"}:
            score += 40
        if t.role == "sheriff":
            score -= 100
    elif me.role == "sheriff":
        if t.role in {"outlaw", "renegade"}:
            score += 35
        elif t.role == "deputy":
            score -= 50
    elif me.role == "renegade":
        # 叛徒傾向維持平衡，最後才收掉警長
        if game.alive_count() <= 2 and t.role == "sheriff":
            score += 100
        else:
            score += t.hp * 2
            if t.role == "sheriff" and t.hp <= 2:
                score -= 30

    score += max(0, 10 - t.hp)
    return score


def choose_shot_target(game: Game, face: str) -> int | None:
    valid = valid_targets_for_face(game, game.current_idx, face)
    if not valid:
        return None
    return max(valid, key=lambda i: (_enemy_score(game, i), -game.players[i].hp, random.random()))


def choose_beer_target(game: Game) -> int | None:
    me = game.current_player()
    candidates = [i for i, p in enumerate(game.players) if p.alive and p.hp < p.max_hp]
    if not candidates:
        return None

    def score(i):
        p = game.players[i]
        s = (p.max_hp - p.hp) * 5
        if i == game.current_idx:
            s += 12
        if me.role == "deputy" and p.role == "sheriff":
            s += 20
        if me.role == "outlaw" and p.role == "sheriff":
            s -= 100
        if me.role == "sheriff" and p.role == "deputy":
            s += 8
        return s

    return max(candidates, key=score)


def choose_kit_target(game: Game) -> int | None:
    candidates = [i for i, p in enumerate(game.players) if p.alive and p.arrows > 0]
    if not candidates:
        return None
    # 優先自己，其次箭最多的人
    if game.current_idx in candidates:
        return game.current_idx
    return max(candidates, key=lambda i: game.players[i].arrows)


def sid_auto_heal(game: Game, events: list[str]):
    p = game.current_player()
    if p.character_key != "sid_ketchum":
        return
    idx = choose_beer_target(game)
    if idx is None:
        idx = game.current_idx
    gained, line = heal_with_record(game, idx, 1, game.current_idx, "sid")
    if gained:
        events.append(line)
    game.sid_done = True


def run_ai_turn(game: Game) -> list[str]:
    events = []
    p = game.current_player()
    if not p.is_ai or not p.alive:
        return events

    sid_auto_heal(game, events)

    if game.phase == "turn_start" and game.expansion_config.enabled("saloon_dice"):
        pick_saloon_die(game, "coward" if p.hp <= 3 else "loudmouth")
    events += roll_initial(game)
    # 擲骰可能因箭雨或炸藥讓當前 AI 淘汰，直接交棒下一位。
    if game.phase == "ended" or not p.alive or game.current_player() is not p:
        return events

    while game.phase == "rolling" and game.roll_no < max_rolls(p):
        game.selected = choose_ai_rerolls(game)
        if not game.selected:
            break
        events += reroll_selected(game)
        if game.phase != "rolling" or not p.alive or game.current_player() is not p:
            break

    if game.phase == "rolling":
        if p.character_key == "slab_the_killer":
            use = count_symbols(game, BEER) > 0 and (count_symbols(game, BULL1) + count_symbols(game, BULL2)) > 0
            # finalize_dice 會把 AI 直接建 queue，不進 slab_choice
            finalize_dice(game)
            if use and not game.slab_used:
                # 電腦優先選擇能攻擊到目標的準心類型。
                from game_engine import _build_resolution_queue
                best = max((f for f in (BULL1, BULL2) if count_symbols(game, f)),
                           key=lambda f: max((_enemy_score(game, t) for t in valid_targets_for_face(game, game.current_idx, f)), default=-1000))
                _build_resolution_queue(game, True, best)
                game.phase = "resolving"
        else:
            finalize_dice(game)

    events += run_ai_resolution(game)
    return events


def run_ai_resolution(game: Game) -> list[str]:
    """恢復被真人的擋傷選擇中斷的電腦擲骰，不再重擲新一輪。"""
    events = []
    p = game.current_player()
    while game.phase == "resolving":
        action = pop_next_action(game)
        if not action:
            break
        typ = action["type"]

        if typ == "shot":
            target = choose_shot_target(game, action["face"])
            if target is not None:
                waiting = start_damage_session(game, [(target, action.get("amount", 1))], game.current_idx, "shot", events)
                if waiting:
                    break
            finish_pending_action(game)

        elif typ == "beer":
            target = choose_beer_target(game)
            if target is not None:
                amount = 2 if (p.character_key == "jesse_jones" and target == game.current_idx and p.hp <= 4) else 1
                got, line = heal_with_record(game, target, amount, game.current_idx, "beer")
                events.append(line)
            finish_pending_action(game)

        elif typ == "gatling":
            victims = [(i, 1) for i, x in enumerate(game.players) if x.alive and i != game.current_idx]
            waiting = start_damage_session(game, victims, game.current_idx, "gatling", events)
            if waiting:
                break
            finish_pending_action(game)

        elif typ == "kit_discard":
            target = choose_kit_target(game)
            if target is not None and game.players[target].arrows > 0:
                game.players[target].arrows -= 1
                game.arrows_pool += 1
                events.append(f"🪶 {p.name}（基特・卡爾森）移除 {game.players[target].name} 1 支箭。")
            finish_pending_action(game)

        elif typ == "end_turn":
            finish_pending_action(game)
            end_turn(game, events)
            break

        if game.phase == "ended" or advance_if_current_eliminated(game, events):
            break

    return events
