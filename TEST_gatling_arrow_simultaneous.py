"""v0.7.4: 箭雨全場同時受傷、動畫素材/入口、身分規則測試。"""
from pathlib import Path
import ast
import random

from data import GATLING
from game_engine import Game, add_human, setup_game, indian_attack, take_arrow, check_win


def make(n):
    g=Game(chat_id=987,host_id=1)
    for i in range(n):
        add_human(g, i+1, f"player{i+1}")
    setup_game(g,random.Random(11))
    return g


def test_arrows_all_die_together():
    g=make(4)
    sheriff=next(i for i,p in enumerate(g.players) if p.role=='sheriff')
    for i,p in enumerate(g.players):
        p.hp=1
        p.arrows=(2 if i==sheriff else 1)
    events=[]
    indian_attack(g,events)
    assert not any(p.alive for p in g.players), g.players
    assert g.phase=='ended' and '歹徒' in g.winner_text
    assert sum('被箭雨淘汰' in e for e in events)==4
    assert len([h for h in g.recent_hits if h['cause']=='indians'])==4
    assert g.arrows_pool==9 and all(p.arrows==0 for p in g.players)


def test_sheriff_dead_does_not_skip_others():
    g=make(5)
    sheriff=next(i for i,p in enumerate(g.players) if p.role=='sheriff')
    ren=next(i for i,p in enumerate(g.players) if p.role=='renegade')
    g.players[sheriff].hp=1
    g.players[ren].hp=1
    g.players[sheriff].arrows=1
    g.players[ren].arrows=1
    indian_attack(g,[])
    assert not g.players[sheriff].alive
    assert not g.players[ren].alive
    assert g.phase=='ended' and '歹徒' in g.winner_text


def test_jourdonnais_min_damage():
    g=make(4)
    g.players[0].character_key='jourdonnais'
    g.players[0].hp=7
    g.players[0].arrows=4
    indian_attack(g,[])
    assert g.players[0].hp==6


def test_vulture_dies_before_healing():
    g=make(4)
    g.players[0].character_key='vulture_sam'
    g.players[0].hp=1
    g.players[0].arrows=2
    g.players[1].hp=1
    g.players[1].arrows=1
    indian_attack(g,[])
    assert not g.players[0].alive and g.players[0].hp==0


def test_take_ninth_arrow_all_at_once():
    g=make(4)
    for i,p in enumerate(g.players):
        p.arrows=1 if i<3 else 5
    g.arrows_pool=1
    g.players[0].hp=1
    g.players[1].hp=1
    take_arrow(g,3,1,[])
    assert not g.players[0].alive and not g.players[1].alive
    assert g.arrows_pool==9


def test_animation_installed_and_hooked():
    here=Path(__file__).parent
    mp4=here/'assets'/'animations'/'gatling_barrage.mp4'
    assert mp4.is_file() and mp4.stat().st_size>100_000
    bot=(here/'bot.py').read_text(encoding='utf8')
    assert 'async def show_gatling_animation' in bot
    assert 'await show_gatling_animation(context, game, game.current_player().name)' in bot
    assert 'await show_gatling_animation(context, game, ai_name)' in bot
    assert 'gatling_animation_file_ids.json' in bot
    ast.parse(bot)


if __name__=='__main__':
    for name,obj in list(globals().items()):
        if name.startswith('test_'):
            obj()
            print('PASS',name)
