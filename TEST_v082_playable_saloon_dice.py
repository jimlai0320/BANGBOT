"""Offline tests for the first playable Old Saloon module (no Telegram connection)."""
from game_engine import (Game, add_ai, setup_game, roll_initial, reroll_selected,
                         pick_saloon_die, start_turn, finalize_dice, count_symbols,
                         _build_resolution_queue)
from old_saloon import ExpansionConfig, IMPLEMENTED_MODULES
from data import BULL1,BULL2,BEER,GATLING
class Rng:
    def __init__(self, results): self.results=iter(results)
    def choice(self, faces):
        v=next(self.results)
        assert v in faces, (v,faces)
        return v

assert {'saloon_dice', 'chief_arrow'} <= IMPLEMENTED_MODULES
for size in range(3,9):
 g=Game(-size,1,ExpansionConfig('saloon', {'saloon_dice'}))
 for _ in range(size):add_ai(g)
 setup_game(g)
 assert pick_saloon_die(g,'loudmouth')
 res=roll_initial(g,Rng(['double_bull1','beer','gatling','arrow','bull2']))
 assert g.dice[0]=='double_bull1' and g.dice_types[0].kind=='loudmouth'
 assert count_symbols(g,BULL1)==2
 assert g.phase in ('rolling','turn_start','ended')
 if g.phase=='rolling':
  g.selected={0}
  reroll_selected(g,Rng(['double_gatling']))
  assert g.dice[0]=='double_gatling'
  assert count_symbols(g,GATLING)==3
  _build_resolution_queue(g,False)
  assert sum(a['type']=='gatling' for a in g.pending_actions)==1
  assert sum(a['type']=='shot' for a in g.pending_actions)==1

 # Coward double beer splits into two independent heals.
 h=Game(-size-20,1,ExpansionConfig('saloon', {'saloon_dice'}))
 for _ in range(size):add_ai(h)
 setup_game(h)
 assert pick_saloon_die(h,'coward')
 roll_initial(h,Rng(['double_beer','beer','bull1','bull2','arrow']))
 if h.phase=='rolling':
  _build_resolution_queue(h,False)
  assert sum(a['type']=='beer' for a in h.pending_actions)==3

 blocked=Game(-size-40,1,ExpansionConfig('saloon', {'ghost'}))
 for _ in range(size):add_ai(blocked)
 assert blocked.expansion_config.playable_status(size)[0] == (size >= 5)
print('PASS: 3-8 players saloon dice, double shots, double gatling, double beer, unimplemented gates')
