"""Stage-A test: base game stays functional; saloon settings never silently enable unfinished effects.
No live Telegram connection required. Telegram classes are stubbed for UI/callback tests.
"""
import asyncio
import sys
import types

from game_engine import Game, add_ai, setup_game
from old_saloon import (
    ExpansionConfig, MODULE_KEYS, ReactionWindow,
    REACTION_WINDOW_SECONDS, TARGET_SELECTION_SECONDS,
)

assert REACTION_WINDOW_SECONDS == 3.0 and TARGET_SELECTION_SECONDS == 10.0
base = Game(chat_id=-102, host_id=1)
for i in range(5):
    assert add_ai(base)
setup_game(base)
assert base.phase == 'turn_start' and len(base.players) == 5

for n in range(3,9):
    for key in MODULE_KEYS:
        g = Game(chat_id=-n, host_id=1, expansion_config=ExpansionConfig('saloon', {key}))
        for i in range(n): add_ai(g)
        ok, reason = g.expansion_config.playable_status(n)
        if key != "ghost" or n >= 5:
            assert ok
            setup_game(g)
            assert g.phase == "turn_start"
            continue
        assert not ok
        try: setup_game(g)
        except ValueError: pass
        else: raise AssertionError(f'Unimplemented expansion was started: {key}')
        assert g.phase == 'lobby'

c = ExpansionConfig('saloon', {'new_characters'})
assert len(c.eligible_new_characters()) == 5
c.modules.add('saloon_dice')
assert len(c.eligible_new_characters()) == 7
c.modules.add('chief_arrow')
assert len(c.eligible_new_characters()) == 8
c.modules.clear()
assert c.playable_status(4)[0]

w = ReactionWindow(4, 'after_roll', {111}, 1.0, 4.0)
assert w.can_claim(111, 2.5)
assert not w.can_claim(222, 2.5)
assert not w.can_claim(111, 4.0)

# Minimal UI shim, validates markup, full lobby callback behaviour, and host-only settings.
tg = types.ModuleType('telegram')
class Key:
    def __init__(self,text,callback_data=None,**kw):
        self.text=text;self.callback_data=callback_data
class Markup:
    def __init__(self,inline_keyboard): self.inline_keyboard=inline_keyboard
class Dummy:
    def __init__(self,*args,**kwargs): self.args=args;self.kwargs=kwargs
for name, value in {'InlineKeyboardButton':Key,'InlineKeyboardMarkup':Markup}.items():setattr(tg,name,value)
for name in ['Update','InputFile','InputMediaPhoto','BotCommand','BotCommandScopeAllGroupChats','BotCommandScopeAllPrivateChats']:
    setattr(tg,name,Dummy)
sys.modules['telegram']=tg
const=types.ModuleType('telegram.constants');const.ChatType=types.SimpleNamespace(PRIVATE='private',GROUP='group');sys.modules['telegram.constants']=const
errs=types.ModuleType('telegram.error')
for name in ['BadRequest','Forbidden','TimedOut','NetworkError']:
    setattr(errs,name,type(name,(Exception,),{}))
sys.modules['telegram.error']=errs
ext=types.ModuleType('telegram.ext')
for name in ['Application','CommandHandler','CallbackQueryHandler','ContextTypes']:
    setattr(ext,name,Dummy if name!='ContextTypes' else types.SimpleNamespace(DEFAULT_TYPE=object))
sys.modules['telegram.ext']=ext

import bot
b = bot

async def check_ui():
    chat=-808
    g=Game(chat_id=chat,host_id=333)
    for i in range(3):add_ai(g)
    b.GAMES[chat]=g
    class Q:
        def __init__(self,action,uid):
            self.data=action;self.message=types.SimpleNamespace(chat=types.SimpleNamespace(id=chat))
            self.from_user=types.SimpleNamespace(id=uid,full_name='Host')
            self.reply=None
        async def answer(self,text='',show_alert=False):self.reply=text
    context=types.SimpleNamespace(bot=object())
    async def dummy_update(context,game):pass
    b.update_lobby=dummy_update
    b.update_board=dummy_update
    async def dummy_start_cards(context,game):pass
    b.send_start_cards=dummy_start_cards
    async def dummy_ai(context,game):pass
    b.run_ai_chain=dummy_ai
    context.application=types.SimpleNamespace(create_task=lambda coro, name=None:asyncio.create_task(coro))
    async def click(action, uid=333):
        q=Q(action,uid)
        await b.callback_impl(types.SimpleNamespace(callback_query=q), context)
        return q.reply
    assert '老酒館' in [x.text for row in b.lobby_keyboard(g).inline_keyboard for x in row]
    await click('lobby:mode:saloon')
    assert g.expansion_config.mode=='saloon' and g.expansion_config.modules=={'saloon_dice','chief_arrow'}
    labels=[x.text for row in b.lobby_keyboard(g).inline_keyboard for x in row]
    assert any('鬼魂模式' in s for s in labels)
    assert '只有建立者' in await click('lobby:mod:ghost',999)
    assert not g.expansion_config.enabled('ghost')
    assert '5' in await click('lobby:mod:ghost')
    assert not g.expansion_config.enabled('ghost')
    await click('lobby:mod:new_characters')
    assert g.expansion_config.playable_status(3)[0]
    assert g.phase=='lobby'
    await click('lobby:none')
    assert g.expansion_config.modules==set()
    await click('lobby:start')
    assert g.phase=='turn_start'
    assert '大廳已結束' in await click('lobby:mod:chief_arrow')
    # No special skill entry in base-mode games.
    assert not any(x.callback_data=='special:open' for row in b.game_keyboard(g).inline_keyboard for x in row)
    # Separate game with saloon subset for future UI gets fixed skill button (without changing data).
    g2=Game(chat_id=-809,host_id=333,phase='turn_start',expansion_config=ExpansionConfig('saloon', {'special_roles'}))
    from game_engine import Player
    g2.players=[Player(1,'a',False,'sheriff','lucky_duke',8,10)]
    assert any(x.callback_data=='special:open' for row in b.game_keyboard(g2).inline_keyboard for x in row)

asyncio.run(check_ui())
print('PASS v0.8.0: base-game setup, 3–8 player module safety, dependencies, 3s reaction model, host-only Telegram lobby controls')
