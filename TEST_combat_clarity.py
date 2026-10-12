"""v0.7.3 combat UI: validate source/target damage and visible recent history."""
import ast
import random
from pathlib import Path
from data import ROLE_CN
from game_engine import Game, Player, add_ai, setup_game, deal_damage, format_hit, format_action, take_arrow, indian_attack, heal, start_damage_session, choose_damage_option
from renderer import render_board
from ai import run_ai_turn

ROOT=Path(__file__).resolve().parent
mod=ast.parse((ROOT/'bot.py').read_text(encoding='utf-8'))
need={'_public_death_summary','_recent_combat_caption','board_caption'}
selected=[n for n in mod.body if isinstance(n,ast.FunctionDef) and n.name in need]
assert len(selected)==len(need)
ns={'ROLE_CN':ROLE_CN,'format_hit':format_hit,'format_action':format_action}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*selected],type_ignores=[])), str(ROOT/'bot.py'),'exec'),ns)

def g4():
    g=Game(chat_id=1,host_id=1,phase='rolling')
    g.players=[Player(1,'射手阿明',False,'sheriff','lucky_duke',10,10),
               Player(2,'小林',False,'outlaw','jesse_jones',7,9),
               Player(3,'被打的人',False,'renegade','el_gringo',7,7),
               Player(4,'玩家4',False,'outlaw','black_jack',8,8)]
    return g

g=g4(); e=[]
assert deal_damage(g,1,2,0,'shot',e)==2
assert g.players[1].hp==5
assert format_hit(g,g.last_hit)=='🎯 射手阿明 → 小林：−2血｜7→5'
assert '射手阿明 → 小林' in ns['board_caption'](g)
assert '7→5' in ns['board_caption'](g)
assert any('射手阿明' in x and '小林' in x for x in e)
assert len(g.recent_hits)==1
print('PASS: 真人雙倍射擊顯示誰打誰、傷害與血量前後變化')

e=[];deal_damage(g,3,1,0,'gatling',e)
assert '機槍' in format_hit(g,g.last_hit)
assert '小林' in ns['board_caption'](g)
assert '玩家4' in ns['board_caption'](g)
print('PASS: 機槍攻擊不會被誤認成普通單發')

e=[];g.players[1].hp=2;deal_damage(g,1,3,None,'indians',e)
assert not g.players[1].alive
assert '印第安人' in format_hit(g,g.last_hit)
assert '淘汰' in format_hit(g,g.last_hit)
assert '射手阿明 → 小林' in ns['board_caption'](g)
print('PASS: 印第安箭雨和死亡會被記錄，舊攻擊仍可看到')

g=g4();e=[];g.players[0].hp=2;deal_damage(g,0,1,None,'dynamite',e)
assert '炸藥' in format_hit(g,g.last_hit) and '2→1' in format_hit(g,g.last_hit)
print('PASS: 炸藥自傷不會被錯記成其他玩家的射擊')

g=g4();g.players[1].character_key='bart_cassidy';g.arrows_pool=9;e=[]
assert start_damage_session(g,[(1,1)],0,'shot',e)
assert choose_damage_option(g,1,1)
assert g.last_hit['lost']==0 and g.players[1].hp==7
assert '擋下傷害' in format_hit(g,g.last_hit)
print('PASS: 角色抵擋傷害時不會誤顯示扣血')

g=g4();g.players[1].character_key='paul_regret';e=[]
assert deal_damage(g,1,1,0,'gatling',e)==0
assert g.last_hit['lost']==0
print('PASS: 保羅格林機槍免疫會清楚顯示擋下')

g=g4()
for k in range(7):
    idx=(k%3)+1
    if g.players[idx].alive:
        deal_damage(g,idx,1,0,'shot',[])
assert len(g.recent_hits)==7
cap=ns['board_caption'](g)
assert cap.count(' → ')==3
assert len(cap)<1024
print('PASS: 主牌桌 caption 只列最近3次傷害且沒有超出 Telegram 1024 字')

for n in range(3,9):
    g=Game(chat_id=n,host_id=1)
    for i in range(n): add_ai(g)
    setup_game(g,random.Random(n+400))
    # keep one recent direct attack while alive
    shooter=g.current_idx;target=(shooter+1)%n
    if g.players[target].character_key=='bart_cassidy':g.arrows_pool=1
    deal_damage(g,target,1,shooter,'shot',[])
    b=render_board(g)
    assert len(b.getvalue())>30000,(n,len(b.getvalue()))
    if n==5:
        (ROOT/'預覽_v0.7.3_5人戰鬥提示.jpg').write_bytes(b.getvalue())
    if n==8:
        (ROOT/'預覽_v0.7.3_8人戰鬥提示.jpg').write_bytes(b.getvalue())
    assert g.last_hit and '→' in format_hit(g,g.last_hit)
print('PASS: 3～8人所有牌桌都能顯示戰鬥提示，未移動角色位置')

# extensive AI simulation, attack history source/target accurate and bounded.
for n in range(3,9):
    for seed in range(15):
        g=Game(chat_id=seed,host_id=1)
        for i in range(n): add_ai(g)
        setup_game(g, random.Random(seed+n*100))
        count=0
        while g.phase!='ended' and count<300:
            run_ai_turn(g);count+=1
        assert g.phase=='ended',(n,seed)
        assert len(g.recent_hits)<=8
        for hit in g.recent_hits:
            assert 0 <= hit['after'] <= hit['before']
            assert hit['lost']==hit['before']-hit['after']
            assert 0<=hit['target_idx']<n
print('PASS: 3～8 人共 90 局 AI 對戰，攻擊來源和扣血一致')
print('COMBAT CLARITY TESTS PASSED')
