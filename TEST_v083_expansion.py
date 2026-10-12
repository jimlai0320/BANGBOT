from saloon_test_helpers import *

# Six dice, and the other saloon die never grants the extra die.
for char,kind,count in [('jose_delgado','loudmouth',6),('jose_delgado','coward',5),('tequila_joe','coward',6),('tequila_joe','loudmouth',5)]:
    g,r=fresh();g.players[0].character_key=char
    run(r,r.rolling(0),{'dice':kind,'roll':0})
    assert len(g.dice)==count,(char,kind,g.dice)
# Bill only takes arrows on the final roll; kept final arrow counts exactly once.
g,r=fresh();g.players[0].character_key='bill_noface';g.dice=[ARROW,BEER,BEER,BEER,BEER]
run(r,r.roll_effects([0],False));assert sum(p.arrows for p in g.players)==0
g,r=fresh();g.players[0].character_key='bill_noface';g.dice=[ARROW,BEER,BEER,BEER,BEER]
run(r,r.roll_effects([],True),{'chief':'normal'});assert g.players[0].arrows==1
# Apache can take the chief from another player, without changing normal pool.
g,r=fresh();g.players[0].character_key='apache_kid';g.chief_arrow_owner=1
run(r,r.take_arrow(0,True),{'chief':'chief'});assert g.chief_arrow_owner==0 and g.arrows_pool==9
# Elena gives only one of two rolled arrows away.
g,r=fresh();g.players[0].character_key='elena_fuente';g.dice=[ARROW,ARROW,BEER,BEER,BEER]
run(r,r.roll_effects([0,1]),{'elena':1,'chief':'normal'});assert [p.arrows for p in g.players][:2]==[1,1]
# Vera reduces each shot event, not an entire turn or Gatling.
g,r=fresh();g.players[1].character_key='vera_custer'
run(r,r.damage([(1,1)],0,'shot'));assert g.players[1].hp==8
g,r=fresh();g.players[1].character_key='vera_custer'
run(r,r.damage([(1,2)],0,'shot'));assert g.players[1].hp==7
# Molly can save an ally, but cannot volunteer beyond remaining health.
g,r=fresh();g.players[2].character_key='molly_stark';g.players[2].hp=3
run(r,r.damage([(1,2)],0,'shot'),{'molly':True});assert g.players[1].hp==8 and g.players[2].hp==1
# Healing blocker consumes ability; a judge cancels the blocker and both are spent.
g,r=fresh();g.players[0].hp=3;g.players[1].special_role_key='outlaw_bad';g.players[2].special_role_key='deputy_judge'
run(r,r.heal(0,2),{'reaction':lambda q:q.owners[0],'confirm':True})
assert g.players[0].hp==5 and g.players[1].role_power_used and g.players[2].role_power_used
# Good exchanges cards and limits but never current hp.
g,r=fresh();g.current_idx=2;g.players[2].special_role_key='deputy_good';g.players[0].special_role_key='sheriff_bear';g.players[0].hp=10
run(r,r.turn_start_roles(2),{'reaction':2,'confirm':True})
assert g.players[2].role=='sheriff' and g.players[0].role=='deputy' and g.players[0].hp==10
assert g.players[0].max_hp==g.players[0].character.hp
# Ugly swaps both regular and chief arrows.
g,r=fresh();g.current_idx=1;g.players[1].special_role_key='outlaw_ugly';g.players[0].arrows=3;g.arrows_pool=6;g.chief_arrow_owner=0
run(r,r.turn_start_roles(1),{'reaction':1,'swap_first':0,'swap_second':1})
assert g.players[1].arrows==3 and g.chief_arrow_owner==1
# Left hand saves before elimination and victory, including sheriff.
g,r=fresh();g.players[3].special_role_key='renegade_left_hand';g.players[0].hp=1
run(r,r.damage([(0,2)],1,'shot'),{'reaction':3,'confirm':True})
assert g.players[0].alive and g.players[0].hp==2 and g.phase!='ended'
# Ghost conversion follows original size; not in distance; character powers off.
for n in range(5,9):
 g,r=fresh(n);g.players[3].hp=1;g.players[3].character_key='vulture_sam'
 run(r,r.damage([(3,1)],0,'shot'))
 assert g.players[3].is_ghost and not g.players[3].alive and r.char(3)==''
 assert g.players[3].role==('outlaw' if n%2 else 'deputy')
 assert distance(g,2,4)==1
# Ghost dice have no immediate effects, and identical symbols produce one double token.
g,r=fresh();g.players[1].alive=False;g.players[1].is_ghost=True;g.current_idx=1
class ArrowRng:
 def choice(self,seq):return ARROW
r.rng=ArrowRng();run(r,r.ghost_turn(1),{'roll':0,'ghost_face':ARROW,'ghost_target':0})
assert r.tokens=={0:(ARROW,2)} and g.arrows_pool==9 and len(g.dice)==2
# Token fixes only ordinary dice, even with six dice and a special die.
g,r=fresh();r.tokens={0:(DYNAMITE,2)};g.players[0].character_key='jose_delgado'
class BeerRng:
 def choice(self,seq):return 'double_bull1' if 'double_bull1' in seq else BEER
r.rng=BeerRng();run(r,r.rolling(0),{'dice':'loudmouth','roll':0})
assert g.dice[:3]==['double_bull1',DYNAMITE,DYNAMITE] and len(g.dice)==6
# Doctor changing a kept die causes its new immediate result exactly once.
g,r=fresh();g.players[2].special_role_key='deputy_doc';g.dice=[BEER]*5
from old_saloon import DieState
g.dice_types=[DieState() for _ in range(5)]
run(r,r.doctor(),{'reaction':2,'doc_die':3,'doc_face':ARROW})
assert g.dice[3]==ARROW and g.players[2].role_power_used
# Stale / wrong-player / late claims never consume ability.
g,r=fresh();g.players[2].special_role_key='deputy_doc';g.players[2].is_ai=False
r.gen=r.react(['deputy_doc']);q=r.step();r.arm(100)
for idx,now in [(1,101),(2,110)]:
 try:r.claim(q.serial,idx,now)
 except ValueError:pass
 else:raise AssertionError('invalid claim accepted')
assert not g.players[2].role_power_used
r.claim(q.serial,2,102)
assert not g.players[2].role_power_used
# Every module combination, all supported sizes, complete matches + conservation.
for n in range(3,9):
 for bits in range(1,32):
  mods={k for at,k in enumerate(MODULE_KEYS) if bits>>at&1}
  if 'ghost' in mods and n<5:continue
  for seed in range(3):
   g=Game(-n,1,ExpansionConfig('saloon',mods))
   for _ in range(n):add_ai(g)
   setup_game(g,random.Random(seed));r=SaloonRuntime(g,seed);r.step()
   for step in range(4000):
    if r.done:break
    r.step(r.ai_value(r.prompt))
    assert g.arrows_pool+sum(p.arrows for p in g.players)==9
    assert 0<=g.arrows_pool<=9
    assert all(p.hp>=0 for p in g.players)
    assert g.chief_arrow_owner is None or g.players[g.chief_arrow_owner].alive
   assert r.done,(n,mods,seed,r.prompt)
 print('PASS module combinations',n,flush=True)
print('PASS new characters, ghost, special roles, deadlines, and 462 complete matches')
