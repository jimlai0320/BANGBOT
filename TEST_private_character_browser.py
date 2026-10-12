"""僅測試 GUI 信息流程，不需 BOT_TOKEN/Telegram 網路：兩個玩家查角色不修改群組訊息。"""
from __future__ import annotations
import ast
import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import logging

src=Path(__file__).with_name('bot.py').read_text(encoding='utf-8')
module=ast.parse(src)
names={'_public_character_detail','_public_character_summary','_browse_keyboard','_browse_list_text','_open_private_character_browser','_private_browser_callback'}
selected=[n for n in module.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
assert len(selected)==len(names)
code=compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*selected],type_ignores=[])), 'bot.py', 'exec')
class Button:
    def __init__(self,text,callback_data=None):
        self.text=text
        self.callback_data=callback_data
class Markup:
    def __init__(self,rows): self.inline_keyboard=rows
class BadRequest(Exception): pass
class Forbidden(Exception): pass
class TimedOut(Exception): pass
class NetworkError(Exception): pass

ns={
    'InlineKeyboardButton':Button,'InlineKeyboardMarkup':Markup,
    'BROWSER_DM_MESSAGE_IDS':{},'BadRequest':BadRequest,
    'Forbidden':Forbidden,'TimedOut':TimedOut,'NetworkError':NetworkError,
    'ChatType':SimpleNamespace(PRIVATE='private'),
    'log':logging.getLogger('character-browse-test'),
    'ROLE_CN':{'sheriff':'警長','outlaw':'歹徒','deputy':'副警長','renegade':'叛徒'},
}
exec(code,ns)

@dataclass
class Char:
    cn:str
    en:str
    ability:str='射擊後可以回血。'
@dataclass
class Player:
    pid:int
    name:str
    role:str
    character:Char
    is_ai:bool=False
    hp:int=8
    max_hp:int=8
    arrows:int=0
    alive:bool=True

players=[
    Player(11,'Alpha','sheriff',Char('警長角色','Sheriff Hero')),
    Player(22,'Beta','outlaw',Char('黑傑克','Black Jack')),
    Player(33,'Gamma','deputy',Char('蘇西','Suzy')),
    Player(44,'Delta','renegade',Char('禿鷹山姆','Vulture Sam')),
]
game=SimpleNamespace(chat_id=-100020,players=players,phase='turn_start')
ns['GAMES']={game.chat_id:game}
class FakeBot:
    def __init__(self): self.calls=[]; self.count=0
    async def send_message(self, chat_id, text, reply_markup):
        self.count+=1
        self.calls.append(('send_private',chat_id,self.count,text))
        return SimpleNamespace(message_id=self.count)
    async def edit_message_text(self, chat_id, message_id, text, reply_markup):
        self.calls.append(('edit_private',chat_id,message_id,text))
bot=FakeBot()
ctx=SimpleNamespace(bot=bot)

class FakeQuery:
    def __init__(self,pid,data):
        self.from_user=SimpleNamespace(id=pid)
        self.message=SimpleNamespace(chat=SimpleNamespace(id=pid,type='private'))
        self.data=data
        self.edits=[]; self.answers=[]
    async def answer(self,*args,**kwargs): self.answers.append((args,kwargs))
    async def edit_message_text(self, text, reply_markup): self.edits.append((text,reply_markup))

async def main():
    f=ns['_open_private_character_browser']
    await f(ctx,game,11)
    await f(ctx,game,22)
    assert bot.calls[0][1]==11 and bot.calls[1][1]==22,bot.calls
    await f(ctx,game,11)
    assert bot.calls[-1][0]=='edit_private' and bot.calls[-1][1]==11,bot.calls[-1]
    assert ns['BROWSER_DM_MESSAGE_IDS'].keys()=={(11,game.chat_id),(22,game.chat_id)}
    q=FakeQuery(11,f'browse:view:{game.chat_id}:1')
    await ns['_private_browser_callback'](SimpleNamespace(callback_query=q),ctx)
    assert q.edits and '黑傑克' in q.edits[-1][0]
    assert '身分：' not in q.edits[-1][0],q.edits[-1][0]
    q2=FakeQuery(22,f'browse:view:{game.chat_id}:0')
    await ns['_private_browser_callback'](SimpleNamespace(callback_query=q2),ctx)
    assert '身分：警長' in q2.edits[-1][0]
    q3=FakeQuery(99,f'browse:view:{game.chat_id}:0')
    await ns['_private_browser_callback'](SimpleNamespace(callback_query=q3),ctx)
    assert not q3.edits and q3.answers[0][1].get('show_alert')
    q4=FakeQuery(11,f'browse:back:{game.chat_id}')
    await ns['_private_browser_callback'](SimpleNamespace(callback_query=q4),ctx)
    assert '本局公開角色資訊' in q4.edits[-1][0]
    assert all(c[1] in (11,22) for c in bot.calls),'some group chat accidentally edited'
    assert len(ns['_public_character_summary'](game))<=200
    # 直接回群組 inline 鍵盤會造成所有玩家共享同個查詢介面，現版本不得如此。
    tree=ast.parse(src)
    impl=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='callback_impl')
    infobranch=next(n for n in ast.walk(impl) if isinstance(n,ast.If) and isinstance(n.test,ast.Compare)
                    and isinstance(n.test.left,ast.Name) and n.test.left.id=='data'
                    and len(n.test.comparators)==1 and isinstance(n.test.comparators[0],ast.Constant)
                    and n.test.comparators[0].value=='info:players')
    assert not any(isinstance(n,ast.Attribute) and n.attr=='edit_message_reply_markup' for n in ast.walk(infobranch))
    print('PASS: A/B 玩家獨立私訊清單，重複查詢只更新本人私訊')
    print('PASS: 私訊能力查詢不洩漏其他人的秘密身分；警長公開身分可顯示')
    print('PASS: 非參與玩家無法查看；私訊上一頁正常')
    print('PASS: 群組「查看角色」不會改掉整張共用牌桌按鈕')
if __name__=='__main__': asyncio.run(main())
