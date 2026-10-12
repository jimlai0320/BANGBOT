"""v0.7.9 回合中斷/恢復：真人可在電腦回合選能力，處理完正確恢復同次骰面。"""
from data import BULL1, GATLING
from game_engine import Game, Player, current_damage_choice, choose_damage_option, finish_pending_action
from ai import run_ai_resolution


def new_game():
    g=Game(chat_id=-100,host_id=88,phase='resolving')
    g.players=[Player(1,'AI射手',True,'outlaw','willy_the_kid',8,8),
               Player(2,'真人巴特',False,'sheriff','bart_cassidy',7,7),
               Player(3,'淘汰者3',True,'outlaw','black_jack',0,8,0,False),
               Player(4,'淘汰者4',True,'renegade','jesse_jones',0,9,0,False)]
    return g

g=new_game();g.pending_actions=[{'type':'shot','face':BULL1,'amount':1},{'type':'end_turn'}]
run_ai_resolution(g)
assert g.phase=='damage_choice' and g.pending_action['type']=='shot'
assert current_damage_choice(g)['idx']==1
assert choose_damage_option(g,1,1)
finish_pending_action(g)
run_ai_resolution(g)
assert g.phase!='damage_choice' and g.current_idx==1 and g.players[1].hp==7 and g.players[1].arrows==1
print('PASS: AI 準心打真人巴特 -> 玩家選擇 -> 同一回合繼續')

g=new_game();g.pending_actions=[{'type':'gatling','count':3},{'type':'end_turn'}]
run_ai_resolution(g)
assert g.phase=='damage_choice' and g.pending_action['type']=='gatling'
assert choose_damage_option(g,1,0)
finish_pending_action(g)
run_ai_resolution(g)
assert g.phase!='damage_choice' and g.players[1].hp==6 and g.current_idx==1
print('PASS: AI 格林機槍打真人巴特 -> 玩家選擇 -> 同次機槍結算後換人')

from pathlib import Path
src=(Path(__file__).parent/'bot.py').read_text('utf-8')
assert src.index('if data.startswith("dmg:")') < src.index('if not is_current_human(game, user.id):')
assert 'owner.pid != user.id' in src
assert 'slab:bull1' in src and 'slab:bull2' in src
assert '_schedule_damage_choice_timeout(context, game)' in src
print('PASS: 群組僅由受傷者回應、斯萊布可選兩種準心、30秒安全逾時')
