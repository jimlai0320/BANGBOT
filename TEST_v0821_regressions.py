"""Boundary cases missed by the v082 saloon tests; no network required."""
from game_engine import *
from game_engine import _build_resolution_queue, _after_new_roll_other_effects
from old_saloon import ExpansionConfig
from data import *

def fresh(char='slab_the_killer'):
    g=Game(-100,1,ExpansionConfig('saloon',{'saloon_dice','chief_arrow'}))
    for _ in range(5):add_ai(g)
    setup_game(g)
    g.current_idx=0
    # Isolate the tested ability; a random El Gringo would add a retaliation arrow.
    for player in g.players:
        player.character_key="black_jack"
        player.hp=player.max_hp=8
    g.players[0].character_key=char
    g.phase='rolling'
    return g

g=fresh();g.dice=['double_beer','double_bull2',BULL1,GATLING,DYNAMITE]
_build_resolution_queue(g,True,BULL2)
assert [a['face'] for a in g.pending_actions if a['type']=='shot']==[BULL1,BULL2,BULL2]
assert [a['amount'] for a in g.pending_actions if a['type']=='shot']==[1,2,1]
assert sum(a['type']=='beer' for a in g.pending_actions)==1
assert g.slab_used

g=fresh('suzy_lafayette');g.players[0].hp=3;g.dice=['double_bull1',BEER,BEER,BEER,BEER]
end_turn(g,[]);assert g.players[0].hp==3

g=fresh();g.chief_arrow_owner=0;g.players[0].arrows=2;g.arrows_pool=7
resolve_gatling(g,[])
assert g.chief_arrow_owner is None and g.players[0].arrows==0
assert g.arrows_pool+sum(p.arrows for p in g.players)==9

g=fresh();g.dice=[DYNAMITE,BEER,BEER,BEER,BEER];g.roll_no=1;g.selected={0,100,-1}
assert reroll_selected(g)==[] and g.roll_no==1
assert g.dice[0]==DYNAMITE
# Calling initial roll twice must never replace an in-progress roll.
assert roll_initial(g)==[] and g.roll_no==1

g=fresh();g.players[0].is_ai=False;g.players[1].arrows=2;g.arrows_pool=7
# Resume from two interrupted broken-arrow choices; bullet applied once after both.
g.dice=['broken_arrow','bullet','broken_arrow',BEER,BEER];before=g.players[0].hp
_after_new_roll_other_effects(g,list(range(5)),[])
assert g.phase=='broken_arrow_choice' and g.players[0].hp==before
finish_broken_arrow_choice(g,1)
assert g.phase=='broken_arrow_choice' and g.players[1].arrows==1
finish_broken_arrow_choice(g,1)
assert g.phase=='rolling' and g.players[0].hp==before-1
assert g.players[1].arrows==0 and g.arrows_pool==9
assert finish_broken_arrow_choice(g,1) is None
print('PASS: double-symbol skills, shot order, chief return, invalid rerolls, interrupted roll continuation')
