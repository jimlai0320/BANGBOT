from game_engine import Game, add_ai, setup_game
from old_saloon import ExpansionConfig
from ai import run_ai_turn, run_ai_resolution
import random
random.seed(842)
for n in range(3,9):
 for trial in range(15):
  g=Game(chat_id=-(n*100+trial),host_id=1,expansion_config=ExpansionConfig('saloon',{'saloon_dice','chief_arrow'}))
  for _ in range(n): add_ai(g)
  setup_game(g)
  for step in range(120):
   if g.phase=='ended':break
   if g.phase=='turn_start': run_ai_turn(g)
   elif g.phase=='resolving':run_ai_resolution(g)
   else: raise AssertionError((n,trial,step,g.phase))
  assert g.phase=='ended',(n,trial,g.phase,g.current_idx)
  assert all(0 <= p.arrows <=9 for p in g.players)
  assert 0 <= g.arrows_pool <=9
 print('PASS',n,'players x15 matches')
