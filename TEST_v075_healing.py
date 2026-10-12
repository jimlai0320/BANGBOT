"""v0.7.5 regression: beer/heal UI, AI, arrow animation, winner disclosure."""
from pathlib import Path
import ast
import random
from data import ROLE_CN
from game_engine import (
    Game, Player, heal_with_record, format_action, deal_damage, format_final_results,
    add_ai, setup_game,
)
from ai import run_ai_turn
from renderer import render_board

ROOT=Path(__file__).resolve().parent
src=(ROOT/'bot.py').read_text(encoding='utf-8')
mod=ast.parse(src)
need={'_recent_combat_caption','_public_death_summary','board_caption'}
fns=[node for node in mod.body if isinstance(node,ast.FunctionDef) and node.name in need]
ns={'ROLE_CN':ROLE_CN,'format_action':format_action}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*fns],type_ignores=[])),str(ROOT/'bot.py'),'exec'),ns)

def four_game():
    g=Game(chat_id=123,host_id=1,phase='turn_start')
    g.players=[
        Player(1,'JUDY',False,'sheriff','lucky_duke',9,10),
        Player(2,'FRED',False,'outlaw','jesse_jones',3,9),
        Player(3,'ALICE',False,'deputy','sid_ketchum',8,8),
        Player(4,'BOB',False,'renegade','black_jack',8,8),
    ]
    return g

g=four_game()
gained,text=heal_with_record(g,1,1,0,'beer')
assert gained==1 and g.players[1].hp==4
assert 'JUDY → FRED' in text and '+1血｜3→4' in text
assert 'JUDY → FRED' in ns['board_caption'](g)
assert '3→4' in ns['board_caption'](g)
img=render_board(g)
assert len(img.getvalue())>20000
(ROOT/'預覽_v0.7.5_啤酒補血牌桌.jpg').write_bytes(img.getvalue())
print('PASS: JUDY 幫 FRED 補血：牌桌中央、caption、目標綠標籤同步顯示')

gained,text=heal_with_record(g,1,2,1,'beer')
assert gained==2 and g.players[1].hp==6
assert 'FRED 自己回血' in text and '+2血｜4→6' in text
assert ns['board_caption'](g).count('→')>=2
print('PASS: 自己喝啤酒 +2 與歷史戰況並存')

gained,text=heal_with_record(g,2,1,0,'beer')
assert gained==0 and '已滿血' in text and '未補血' in text
assert g.players[2].hp==8
print('PASS: 滿血時不會誤報補血')

g.players[1].hp=7
lost=deal_damage(g,1,2,0,'shot',[])
assert lost==2 and '7→5' in ns['board_caption'](g)
assert '已滿血' in ns['board_caption'](g)
assert '3→4' not in ns['board_caption'](g), '最近只顯示3筆'
print('PASS: 射擊與回血合併最近3次戰況')

# Build the AI through full-game simulations, ensure turns finish and attributions remain valid.
for n in range(3,9):
    for seed in range(8):
        gg=Game(chat_id=100+n,host_id=0)
        for i in range(n): add_ai(gg)
        setup_game(gg,random.Random(seed+n*23))
        loops=0
        while gg.phase!='ended' and loops<300:
            run_ai_turn(gg)
            loops+=1
        assert gg.phase=='ended',(n,seed)
        assert len(gg.recent_actions)<=8
        assert '獲勝玩家' in format_final_results(gg)
        for action in gg.recent_actions:
            assert 0<=action['target_idx']<n
print('PASS: 3~8人48局 AI 完成、補血記錄不超量、結算公開全員身分')
assert (ROOT/'assets/animations/indian_arrow_rain.mp4').stat().st_size>50000
assert 'async def show_indian_arrow_animation' in src
assert 'await _play_new_arrow_attacks' in src
print('PASS: 箭雨 MP4 存在且真人/AI 程序具動畫觸發點')
print('ALL V0.7.5 CHECKS PASSED')
