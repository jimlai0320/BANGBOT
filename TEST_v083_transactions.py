from saloon_test_helpers import fresh,run
from data import *
# Ignore only the final roll's immediate damage, including death/win state.
g,r=fresh();g.players[0].hp=1;g.players[1].special_role_key='outlaw_gambler'
class Sequence:
 def __init__(self,values):self.values=iter(values)
 def choice(self,faces):
  value=next(self.values);assert value in faces,(value,faces);return value
r.rng=Sequence(['bullet',BEER,BEER,BEER,BEER,'double_bull1',BEER,BEER,BEER,BEER])
run(r,r.rolling(0),{'dice':'loudmouth','roll':0,'reaction':1,'confirm':True})
assert g.players[0].hp==1 and g.players[0].alive and g.phase!='ended'
assert g.players[1].role_power_used and g.dice[0]=='double_bull1'
assert not any('淘汰' in line for line in g.log)
# A prior committed roll's arrow stays; last roll arrow is rolled back.
g,r=fresh();g.players[1].special_role_key='outlaw_gambler'
r.rng=Sequence([ARROW,BEER,BEER,BEER,BEER, ARROW, BEER,BEER,BEER,BEER,BEER])
rolls=iter([1,0])
run(r,r.rolling(0),{'dice':'base','roll':lambda q:next(rolls),'chief':'normal','reaction':1,'confirm':True})
assert g.players[0].arrows==1 and g.arrows_pool==8
# Judge blocks gambler; the original lethal result stands and both powers spent.
g,r=fresh();g.players[0].hp=1;g.players[1].special_role_key='outlaw_gambler';g.players[2].special_role_key='deputy_judge'
r.rng=Sequence(['bullet',BEER,BEER,BEER,BEER])
run(r,r.rolling(0),{'dice':'loudmouth','roll':0,'reaction':lambda q:q.owners[0],'confirm':True})
assert not g.players[0].alive and g.phase=='ended'
assert g.players[1].role_power_used and g.players[2].role_power_used
# Doc Holyday counts symbols used, including the halves of a double.
g,r=fresh();g.players[0].character_key='doc_holyday';g.players[0].hp=3
g.dice=['double_bull1',BULL1,DYNAMITE,DYNAMITE,DYNAMITE]
run(r,r.resolve(0),{'shot':1});assert g.players[0].hp==5
# Right hand grants a fresh full turn before advancing the seat.
g,r=fresh();g.players[0].special_role_key='renegade_right_hand'
class Beers:
 def choice(self,faces):return BEER
r.rng=Beers();r.step();turn_dice=0
for _ in range(100):
 q=r.prompt
 if q.kind=='dice':
  turn_dice+=1
  if turn_dice==2:break
 val=0 if q.kind=='roll' else (0 if q.kind=='reaction' else (True if q.kind=='confirm' else r.ai_value(q)))
 r.step(val)
assert turn_dice==2 and g.current_idx==0 and g.players[0].role_power_used and g.roll_no==0
print('PASS gambler rollback, prior roll retention, judge cancellation, Holyday and extra turn')

# A ghost is eliminated but still gets all three rolls; dynamite remains locked.
g,r=fresh();g.players[1].alive=False;g.players[1].is_ghost=True;g.current_idx=1
r.rng=Sequence([DYNAMITE,ARROW,ARROW,ARROW]);choices=iter([2,2])
run(r,r.rolling(1,True),{'roll':lambda q:next(choices)})
assert g.roll_no==3 and g.dice==[DYNAMITE,ARROW] and g.arrows_pool==9
print('PASS ghost three rolls and locked dynamite')
