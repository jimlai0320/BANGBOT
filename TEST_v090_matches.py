import random
from game_engine import Game,add_ai,setup_game
from old_saloon import ExpansionConfig
from saloon_runtime import SaloonRuntime
from data import UNDEAD_CHARACTERS

def simulate(n,mods,seed,force=None):
 g=Game(-999,1,ExpansionConfig('saloon',set(mods)))
 for _ in range(n):add_ai(g)
 setup_game(g,random.Random(seed))
 if force:
  p=g.current_player();p.character_key=force;p.hp=p.max_hp=p.character.hp+(2 if p.role=='sheriff' else 0)
 r=SaloonRuntime(g,seed);r.step()
 for steps in range(10000):
  if r.done:break
  q=r.prompt
  assert all(v is not None for v in q.owners)
  value=r.ai_value(q)
  assert value in [v for _,v in q.options] or q.kind=='reaction',(q,value)
  r.step(value)
  assert g.arrows_pool+sum(p.arrows for p in g.players)==9
  assert sum(len(v) for v in r.u['wounds'].values())+len(r.u['wound_pool'])==15
  cards=r.u['deck']+r.u['discard']+r.u['active']+[c for v in r.u['held'].values() for c in v]
  if r.prompt and r.prompt.kind=='pixie':cards+=r.prompt.payload['secret_cards']
  assert sorted(cards)==list(range(18)),(r.prompt,cards)
  assert all(p.hp>=0 for p in g.players)
 assert r.done,(n,mods,seed,r.prompt)
 return steps

newsets=[{'rage'},{'undead_characters'},{'rage','undead_characters'},{'duel_dice','rage'},{'duel_dice','rage','undead_characters'}]
oldsets=[set(),{'saloon_dice','new_characters'},{'chief_arrow','new_characters'},{'saloon_dice','chief_arrow','special_roles','new_characters','ghost'}]
count=0;maximum=0
for n in range(3,9):
 for new in newsets:
  for old in oldsets:
   mods=(new|old)-({'ghost'} if n<5 else set())
   for seed in range(3):maximum=max(maximum,simulate(n,mods,seed));count+=1
for c in UNDEAD_CHARACTERS:
 for seed in range(3):
  mods={'duel_dice','rage','undead_characters','saloon_dice','chief_arrow','special_roles','new_characters','ghost'}
  maximum=max(maximum,simulate(6,mods,seed,c.key));count+=1
print(f'PASS {count} complete matches, 3–8 players; all 8 characters forced; arrow/card/wound conservation; max prompts {maximum}')
