"""v0.7.1 身分公開回歸測試：流程、隱私、群組訊息與介面。"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from data import ROLE_CN
from game_engine import Game, Player, deal_damage, public_role_text, check_win, format_hit, format_action


root = Path(__file__).parent
src = ast.parse((root / 'bot.py').read_text(encoding='utf-8'))
needed = {'_public_character_detail','_public_character_summary', '_browse_list_text',
          '_public_death_summary', '_recent_combat_caption', 'board_caption', '_announce_new_deaths'}
fns = [item for item in src.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in needed]
assert len(fns) == len(needed)
mod = ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*fns], type_ignores=[])
mod=ast.fix_missing_locations(mod)
class FakeError(Exception): pass
class Log:
    def warning(self,*a,**kw): pass
ns={'ROLE_CN':ROLE_CN,'format_hit':format_hit,'format_action':format_action,'BadRequest':FakeError,'Forbidden':FakeError,'TimedOut':FakeError,'NetworkError':FakeError, 'log':Log()}
exec(compile(mod,str(root/'bot.py'),'exec'),ns)
# v0.7.7: 驗證死亡公告排程為背景刪除，且約 10 秒後刪除；不實際等待 10 秒。
cleanup_requests=[]
async def fake_cleanup(context, chat_id, message_id, delay):
    cleanup_requests.append((chat_id,message_id,delay))
ns['_delete_message_later'] = fake_cleanup
pending_cleanup=[]
class App:
    def create_task(self, coro, name=None):
        task=asyncio.create_task(coro, name=name)
        pending_cleanup.append(task)
        return task


def game4():
    g=Game(chat_id=1234,host_id=1,phase='turn_start')
    g.players=[
        Player(10,'SH',False,'sheriff','black_jack',10,10,0),
        Player(11,'DE',False,'deputy','lucky_duke',8,8,0),
        Player(12,'OUT',False,'outlaw','jesse_jones',1,9,0),
        Player(13,'REN',False,'renegade','el_gringo',7,7,0),
    ]
    return g

async def check():
    g=game4()
    # 玩家未死亡前，只可公開警長，其他人皆不外洩
    assert public_role_text(g,g.players[0])=='sheriff'
    for p in g.players[1:]:
        assert public_role_text(g,p)=='hidden'
    assert '歹徒' not in ns['_public_character_detail'](g,2)
    assert '叛徒' not in ns['_public_character_summary'](g)
    assert '歹徒' not in ns['_browse_list_text'](g)
    assert '已淘汰' not in ns['board_caption'](g)

    events=[]
    deal_damage(g,2,1,source_idx=0,cause='shot',events=events)
    assert '🎭 公開身分：歹徒' in '\n'.join(events)
    assert '🎭 公開身分：歹徒' in ns['_public_character_detail'](g,2)
    assert '歹徒' in ns['_public_character_summary'](g)
    assert '🎭歹徒' in ns['_browse_list_text'](g)
    assert 'OUT【歹徒】' in ns['board_caption'](g)
    assert public_role_text(g,g.players[2])=='outlaw'
    assert public_role_text(g,g.players[3])=='hidden'
    assert '叛徒' not in ns['_public_character_detail'](g,3)

    class Bot:
        def __init__(self): self.messages=[]
        async def send_message(self,chat_id,text):
            self.messages.append((chat_id,text))
            return SimpleNamespace(message_id=len(self.messages))
    bot=Bot();ctx=SimpleNamespace(bot=bot, application=App())
    await ns['_announce_new_deaths'](ctx,g)
    assert len(bot.messages)==1 and 'OUT' in bot.messages[0][1] and '歹徒' in bot.messages[0][1]
    assert 2 in g.announced_deaths
    await ns['_announce_new_deaths'](ctx,g)
    assert len(bot.messages)==1, '刷新牌桌不可重複公告'
    # 連續第二個人死亡只再公告一次，且之前玩家不重複
    deal_damage(g,3,7,source_idx=0,cause='shot',events=[])
    await ns['_announce_new_deaths'](ctx,g)
    assert len(bot.messages)==2 and 'REN' in bot.messages[-1][1] and '叛徒' in bot.messages[-1][1]
    assert 'OUT' not in bot.messages[-1][1]
    assert 'OUT【歹徒】' in ns['board_caption'](g) and 'REN【叛徒】' in ns['board_caption'](g)
    assert g.phase=='ended' and '警長' in g.winner_text

    # 3人局不因死亡公開變更原本的全部公開規則
    h=Game(chat_id=12,host_id=1,phase='turn_start')
    h.players=[Player(1,'A',False,'deputy','black_jack',8,8),
               Player(2,'B',False,'outlaw','lucky_duke',8,8),
               Player(3,'C',False,'renegade','el_gringo',7,7)]
    assert all(public_role_text(h,p)==p.role for p in h.players)
    assert '副警長' in ns['_public_character_detail'](h,0)
    assert '歹徒' in ns['_public_character_detail'](h,1)
    assert '叛徒' in ns['_public_character_detail'](h,2)

    # 同一次箭雨的多名淘汰者只需一則公告，包含每人身份
    k=game4();k.phase='rolling';k.players[2].alive=False;k.players[3].alive=False
    k.phase='ended';k.winner_text='🏆 測試結束'
    bot2=Bot();bot2.messages=[]
    await ns['_announce_new_deaths'](SimpleNamespace(bot=bot2, application=App()),k)
    assert len(bot2.messages)==1 and '歹徒' in bot2.messages[0][1] and '叛徒' in bot2.messages[0][1]
    assert '本局已結束' in bot2.messages[0][1]
    print('PASS: 公開身分只在淘汰時出現，存活者仍保密')
    print('PASS: 死亡群組通知單次發送，多次刷新不重複')
    print('PASS: 多人同時淘汰合併通知，遊戲結束仍可查身分')
    await asyncio.gather(*pending_cleanup)
    assert len(cleanup_requests)==3, cleanup_requests
    assert all(delay == 10.0 for _,_,delay in cleanup_requests), cleanup_requests
    assert [(chat_id,mid) for chat_id,mid,_ in cleanup_requests] == [(1234,1),(1234,2),(1234,1)]
    print('PASS: 每則淘汰公告獨立排程10秒刪除，不阻塞遊戲、不重複公告')
    print('PASS: 三人局所有身分原本就公開')

asyncio.run(check())
