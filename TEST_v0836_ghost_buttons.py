import asyncio
from types import SimpleNamespace as N
import saloon_bot as sb
from saloon_test_helpers import fresh

async def main():
 for locked in (False,True):
  g,r=fresh();g.current_idx=1;p=g.players[1]
  p.alive=False;p.is_ghost=True;p.is_ai=False;p.pid=42
  seq=iter(['dynamite' if locked else 'beer','bull1','arrow','beer','bull2','beer'])
  r.rng=N(choice=lambda _:next(seq));r.gen=r.ghost_turn(1);r.step();r.arm()
  async def no(*a,**kw):pass
  async def board(*a):r.arm()
  sb.animate=no
  b=N(update_board=board,show_indian_arrow_animation=no,show_gatling_animation=no)
  for roll in (1,2):
   assert g.roll_no==roll and r.prompt.kind=='roll'
   keys=[x for row in sb.keyboard(g,[]).inline_keyboard for x in row]
   title='重擲第2顆' if locked else '兩顆一起重擲'
   button=next(x for x in keys if title in x.text)
   if locked:assert not any('第1顆' in x.text or '兩顆' in x.text for x in keys)
   q=N(data=button.callback_data,from_user=N(id=42),answer=no)
   await sb.callback(N(callback_query=q),N(),g,b)
  assert g.roll_no==3 and r.prompt.kind=='ghost_face'
  assert g.arrows_pool==9
  if locked:assert g.dice[0]=='dynamite'
 print('PASS ghost human callbacks: two rerolls, locked dynamite, final symbol selection')
asyncio.run(main())
