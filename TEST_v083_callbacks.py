import asyncio,time,types
import bot as b
import saloon_bot as sb
from saloon_test_helpers import fresh

class Query:
 def __init__(self,g,data,pid):
  self.data=data;self.from_user=types.SimpleNamespace(id=pid)
  self.message=types.SimpleNamespace(chat=types.SimpleNamespace(id=g.chat_id));self.reply=None
 async def answer(self,text='',**kwargs):self.reply=text
 async def edit_message_reply_markup(self,**kw):pass

async def main():
 g,r=fresh();g.players[2].is_ai=False;g.players[2].pid=12345;g.players[2].special_role_key='deputy_doc'
 g.players[0].is_ai=False;g.players[0].pid=111
 g.dice=['beer']*5
 from old_saloon import DieState
 g.dice_types=[DieState() for _ in range(5)]
 r.gen=r.doctor();r.step();r.arm();b.GAMES[g.chat_id]=g
 async def board(ctx,game):
  assert isinstance(sb.caption(game),str)
  mark=sb.keyboard(game,b.common_info_rows(game))
  assert all(len(button.callback_data.encode())<=64 for row in mark.inline_keyboard for button in row)
  if r.prompt:r.arm()
 async def no(*args,**kw):pass
 b.update_board=board;sb.animate=no;b.show_gatling_animation=no;b.show_indian_arrow_animation=no
 ctx=types.SimpleNamespace()
 async def click(data,pid=12345):
  q=Query(g,data,pid);await b.callback_impl(types.SimpleNamespace(callback_query=q),ctx);return q.reply
 serial=r.prompt.serial;prefix=f'x:{r.token}:{serial}:'
 assert '不符合' in await click(prefix+'claim',111)
 assert '過期' in await click(f'x:bad:{serial}:claim')
 assert not g.players[2].role_power_used
 assert '已選擇' in await click(prefix+'claim')
 first=r.prompt;assert first.kind=='doc_die';end=first.deadline
 assert '過期' in await click(prefix+'claim')
 assert '已選擇' in await click(f'x:{r.token}:{first.serial}:0')
 assert r.prompt.kind=='doc_face' and r.prompt.deadline==end
 # Timeout cancels the unfinished skill without consuming the role.
 r.timeout(r.prompt.serial)
 assert r.done and not g.players[2].role_power_used
 # A deadline equal to now rejects (no inclusive-boundary double claim).
 g2,r2=fresh();g2.players[2].special_role_key='deputy_doc';r2.gen=r2.react(['deputy_doc']);q=r2.step();r2.arm(10)
 try:r2.claim(q.serial,2,20)
 except ValueError:pass
 else:raise AssertionError('expired skill accepted')
 print('PASS Telegram callback ownership, game/window tokens, stale clicks, shared 20-second timeout')
asyncio.run(main())
