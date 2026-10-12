"""v0.7.0：真人/AI 在擲骰途中被箭雨、炸藥淘汰的回合交接回歸測試。"""
import random
from game_engine import Game, Player, roll_initial, reroll_selected, check_win
from ai import run_ai_turn
from data import ARROW, BEER, DYNAMITE, BULL1

class Dice:
    def __init__(self, faces):
        self.faces = iter(faces)
    def choice(self, options):
        return next(self.faces)

def game4(ai=False):
    game = Game(chat_id=123, host_id=1)
    game.players = [
        Player(10, '警長', ai, 'sheriff', 'black_jack', 10, 10, 3),
        Player(11, 'Fred', ai, 'outlaw', 'black_jack', 1, 8, 5),
        Player(12, '下一位', ai, 'renegade', 'lucky_duke', 8, 8, 0),
        Player(13, '最後一位', ai, 'outlaw', 'bart_cassidy', 8, 8, 0),
    ]
    game.current_idx = 1
    game.arrows_pool = 1
    game.phase = 'turn_start'
    return game

g = game4()
events = roll_initial(g, Dice([ARROW, BULL1, BEER, BEER, BEER]))
assert not g.players[1].alive
assert g.players[1].arrows == 0
assert g.current_idx == 2 and g.phase == 'turn_start', (g.phase, g.current_idx, events)
assert '淘汰' in ''.join(events) and '回合立即結束' in ''.join(events)
assert g.arrows_pool == 9 and not g.dice and not g.pending_actions
print('PASS: 第一擲印第安箭雨自殺，直接跳至下一存活者')

g = game4()
g.phase = 'rolling'; g.roll_no = 1
g.dice = [BEER]*5
g.selected = {2}
events = reroll_selected(g, Dice([ARROW]))
assert not g.players[1].alive and g.current_idx == 2 and g.phase == 'turn_start', (g.phase,g.current_idx, events)
print('PASS: 重擲時被箭雨淘汰，自動跳下一位')

g = game4()
g.players[1].arrows = 0
#g.arrows_pool = 9 - sheriff 3

g.arrows_pool = 6
events = roll_initial(g, Dice([DYNAMITE,DYNAMITE,DYNAMITE,BEER,BEER]))
assert not g.players[1].alive and g.phase == 'turn_start' and g.current_idx == 2, (g.phase,g.current_idx,events)
assert not g.dice and not g.pending_actions
print('PASS: 三顆炸藥炸死當前玩家，自動換人，不處理剩餘骰面')

g = game4()
g.players[1].alive = False
g.current_idx = 0
# sheriff 只有 1 點生命，三顆炸藥淘汰即刻結束遊戲
g.players[0].hp = 1
g.arrows_pool = 6
#g current sheriff has 3 arrows but no arrow dice

events = roll_initial(g, Dice([DYNAMITE,DYNAMITE,DYNAMITE,BEER,BEER]))
assert g.phase == 'ended' and '歹徒' in g.winner_text and not g.players[0].alive,(g.phase,g.winner_text,events)
print('PASS: 警長自爆，依身分規則立即結束遊戲')

# 三人局當前玩家自己被箭雨淘汰，沒有殺手達成指定目標，剩下兩人決鬥。
g = Game(chat_id=77, host_id=1)
g.players = [
    Player(1,'副警長',False,'deputy','black_jack',1,8,8),
    Player(2,'歹徒',False,'outlaw','black_jack',8,8,0),
    Player(3,'叛徒',False,'renegade','lucky_duke',8,8,0),
]
g.current_idx=0; g.phase='turn_start'; g.arrows_pool=1
events=roll_initial(g,Dice([ARROW,BEER,BEER,BEER,BEER]))
assert g.phase=='turn_start' and g.current_idx==1 and g.three_player_duel and not g.players[0].alive, (g.phase, g.current_idx, events)
print('PASS: 三人局自殺切換到兩人決鬥與下一位玩家')

# AI 擲骰時遭淘汰，模擬多次運行遊戲，不能卡在已死 AI 的 rolling。
for n in range(3,9):
    for seed in range(30):
        game=Game(chat_id=n*1000+seed,host_id=1)
        from game_engine import add_ai, setup_game
        for i in range(n): add_ai(game)
        setup_game(game, random.Random(n*1000+seed))
        random.seed(n*1000+seed)
        for turn in range(600):
            if game.phase=='ended': break
            before=game.current_idx
            assert game.current_player().alive, (n,seed,turn,before,'dead current before AI')
            run_ai_turn(game)
            if game.phase!='ended':
                assert game.current_player().alive, (n,seed,turn,before,game.phase,'dead current after AI')
                assert game.phase == 'turn_start', (n,seed,turn,game.phase)
        assert game.phase == 'ended', (n,seed,'uncompleted')
print('PASS: 3～8 人共 180 局完整 AI 模擬，不停在死者回合')
print('ALL ELIMINATION TESTS PASSED')
