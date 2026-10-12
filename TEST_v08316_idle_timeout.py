import asyncio
from types import SimpleNamespace as N
from saloon_test_helpers import fresh
import saloon_bot as sb

async def test():
 g,r=fresh();g.players[0].is_ai=False;g.players[0].pid=55
 r.rng=N(choice=lambda _: 'beer');r.gen=r.rolling(0);r.step();r.step('base')
 q=r.prompt;assert q.kind=='roll';clock=[100.0];q.deadline=150
 real_sleep=sb.asyncio.sleep;real_time=sb.time.monotonic;real_drive=sb.drive
 warnings=[];driven=[];locks={g.chat_id:asyncio.Lock()};calls=[0]
 async def no(*a,**k):pass
 async def board(ctx,game):warnings.append(clock[0])
 async def drive(*args):driven.append(clock[0])
 b=N(GAMES={g.chat_id:g},chat_lock=lambda _:locks[g.chat_id],update_board=board,common_info_rows=lambda _:[])
 async def sleep(delay):
  clock[0]+=delay;calls[0]+=1
  if calls[0]==1:
   query=N(data=f'x:{r.token}:{q.serial}:t0',from_user=N(id=55),answer=no,edit_message_caption=no)
   await sb.callback(N(callback_query=query),N(),g,b)
   assert q.deadline==190 and r.selected=={0}
 sb.asyncio.sleep=sleep;sb.time.monotonic=lambda:clock[0];sb.drive=drive
 try:
  await sb.expire(N(),g,b,r,q)
  assert warnings==[180] and driven==[190],(warnings,driven)
  assert any('選擇逾時' in s for s in g.log)
  # Same game but a replacement prompt: an old task must do nothing.
  g,r=fresh();r.rng=N(choice=lambda _: 'beer');r.gen=r.rolling(0);r.step();r.step('base')
  old=r.prompt;old.deadline=clock[0];r.step(1);current=r.prompt
  b.GAMES[g.chat_id]=g;driven.clear();before=g.current_idx
  await sb.expire(N(),g,b,r,old)
  assert r.prompt is current and g.current_idx==before and not driven
 finally:sb.asyncio.sleep=real_sleep;sb.time.monotonic=real_time;sb.drive=real_drive
 print('PASS valid click renews idle timeout; old wakeup waits; warning at 10s; timeout logged; stale task cannot advance prompt')
asyncio.run(test())
