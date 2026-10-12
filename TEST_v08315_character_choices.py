"""Check readable options and callback values across all 24 character types."""
import asyncio
from types import SimpleNamespace as N
from saloon_test_helpers import fresh
from data import CHARACTERS,SALOON_CHARACTERS
from saloon_runtime import ROLE_POWERS
import saloon_bot as sb

async def bart_click(block):
 g,r=fresh();g.players[1].character_key='bart_cassidy';g.players[1].is_ai=False;g.players[1].pid=987
 r.gen=r.damage([(1,2)],0,'shot');q=r.step();r.arm()
 buttons=sb.keyboard(g,[]).inline_keyboard
 assert all(not row[0].text.isdigit() for row in buttons)
 assert '不拿箭' in buttons[0][0].text
 assert f'拿 {block} 支' in buttons[block][0].text if block else True
 async def no(*a,**k):pass
 async def board(*a):
  if r.prompt:r.arm()
 old=sb.animate;sb.animate=no
 try:
  query=N(data=buttons[block][0].callback_data,from_user=N(id=987),answer=no)
  await sb.callback(N(callback_query=query),N(),g,N(update_board=board,show_indian_arrow_animation=no,show_gatling_animation=no))
 finally:sb.animate=old
 assert g.players[1].hp==8-(2-block) and g.players[1].arrows==block and g.arrows_pool==9-block
for block in (0,1,2):asyncio.run(bart_click(block))

seen=set();games=0
for char in list(CHARACTERS)+list(SALOON_CHARACTERS):
 for seed in range(3):
  g,r=fresh(seed=seed+31);g.players[0].character_key=char.key
  # Include all special roles across seeds and permit passive/active interaction.
  keys=list(ROLE_POWERS)
  for i,p in enumerate(g.players):p.special_role_key=keys[(i+seed*3)%len(keys)]
  r.step()
  for _ in range(5000):
   if r.done:break
   q=r.prompt;seen.add(q.kind)
   for row in sb.keyboard(g,[]).inline_keyboard:
    for btn in row:
     assert btn.text and not btn.text.isdigit(),(char.key,q.kind,btn.text)
     assert not any(code in btn.text for code in ('double_bull','double_beer','double_gatling','broken_arrow')),(q.kind,btn.text)
     assert len(btn.callback_data.encode())<=64
   r.step(r.ai_value(q))
  assert r.done,(char.key,seed)
  games+=1
print(f'PASS {games} full games covering 24 character types; {len(seen)} prompt kinds: '+', '.join(sorted(seen)))
print('PASS real Bart callback indices 0/1/2 apply exactly the stated HP/arrow choice')
