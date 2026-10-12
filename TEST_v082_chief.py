from game_engine import (Game, Player, add_ai, setup_game, arrow_tokens_remaining,
                         take_chief_arrow,take_arrow, indian_attack, roll_initial,choose_chief_arrow)
from old_saloon import ExpansionConfig
from data import ARROW,BEER
import random

def game(n=4):
 g=Game(-9,1,ExpansionConfig('saloon', {'chief_arrow'}))
 for _ in range(n):add_ai(g)
 setup_game(g,random.Random(82))
 # Keep unrelated random character immunities out of arrow accounting tests.
 for player in g.players:
  player.character_key="black_jack";player.hp=player.max_hp=8
 return g

g=game();event=[]
assert arrow_tokens_remaining(g)==10
assert take_chief_arrow(g,0,event)
assert arrow_tokens_remaining(g)==9 and g.chief_arrow_owner==0
assert not take_chief_arrow(g,1,event)
for _ in range(8):take_arrow(g,1,1,event)
assert g.arrows_pool==1
# holder with 2 vs opponent with 9, holder loses 2
hp=g.players[0].hp
indian_attack(g,event)
assert g.players[0].hp == hp-2
assert g.chief_arrow_owner is None and g.arrows_pool==9

g=game();event=[]
assert take_chief_arrow(g,0,event)
for _ in range(3):take_arrow(g,0,1,event)
for _ in range(2):take_arrow(g,1,1,event)
hp=g.players[0].hp
indian_attack(g,event)
assert g.players[0].hp==hp, event

g=game();event=[]
take_chief_arrow(g,0,event)
for _ in range(2):take_arrow(g,1,1,event)
hp=g.players[0].hp
indian_attack(g,event)
assert g.players[0].hp == hp-2, 'tied top arrows must not be immune'

# Human gets real choice, and die result need not be rolled again after choice.
g=game();g.players[g.current_idx].pid=123;g.players[g.current_idx].is_ai=False
class Rng:
 def __init__(self): self.n=0
 def choice(self,fs):
  self.n+=1;return ARROW if self.n==1 else BEER
r=Rng();roll_initial(g,r)
assert g.phase=='chief_arrow_choice' and g.pending_action['cursor']==1
idx=g.current_idx
assert choose_chief_arrow(g,True) is not None
assert g.chief_arrow_owner==idx and g.phase=='rolling' and r.n==5
print('PASS: chief 10 tokens, solo leader immunity, tied-top normal damage, human target picker')
