from data import BULL1, BULL2, BEER, GATLING
from game_engine import (
    Game, Player, start_damage_session, current_damage_choice, choose_damage_option,
    resolve_gatling, apply_slab_choice, _build_resolution_queue,
    roll_initial, _after_new_roll, check_win,
)

def game(keys, roles=None, ais=None):
    roles=roles or ['sheriff','outlaw','outlaw','renegade'][:len(keys)]
    ais=ais or [False] * len(keys)
    g=Game(chat_id=-1,host_id=1,phase='resolving')
    g.players=[Player(i+1, f'P{i}', is_ai=ais[i], role=roles[i], character_key=k, hp=7, max_hp=9) for i,k in enumerate(keys)]
    g.current_idx=0
    return g

# 1. Bart human: can choose 0 or 1 arrow, cannot take pool last arrow.
g=game(['willy_the_kid','bart_cassidy','black_jack','jesse_jones'])
g.players[1].hp=1
assert start_damage_session(g,[(1,1)],0,'shot',[]) and g.phase=='damage_choice'
assert current_damage_choice(g)=={'kind':'bart','idx':1,'max':1}
assert choose_damage_option(g,1,1)
assert g.phase=='resolving' and g.players[1].hp==1 and g.players[1].arrows==1 and g.arrows_pool==8
assert g.completed_damage_events and '擋' in str(g.completed_damage_events)

g=game(['willy_the_kid','bart_cassidy','black_jack','jesse_jones']);g.players[1].hp=1
assert start_damage_session(g,[(1,1)],0,'shot',[])
assert choose_damage_option(g,1,0)
assert not g.players[1].alive and g.players[1].hp==0

g=game(['willy_the_kid','bart_cassidy','black_jack','jesse_jones']);g.arrows_pool=1
assert not start_damage_session(g,[(1,1)],0,'shot',[])
assert g.players[1].hp==6

# 2. Pedro optional discard 0..damage and fatal loss doesn't need pointless button.
g=game(['willy_the_kid','pedro_ramirez','black_jack','jesse_jones']);g.players[1].arrows=2;g.arrows_pool=7
assert start_damage_session(g,[(1,2)],0,'shot',[])
assert current_damage_choice(g)['max']==2
assert choose_damage_option(g,1,1)
assert (g.players[1].hp,g.players[1].arrows,g.arrows_pool)==(5,1,8)

g=game(['willy_the_kid','pedro_ramirez','black_jack','jesse_jones']);g.players[1].arrows=2;g.arrows_pool=7
assert start_damage_session(g,[(1,1)],0,'shot',[])
assert choose_damage_option(g,1,0)
assert (g.players[1].hp,g.players[1].arrows,g.arrows_pool)==(6,2,7)

# 3. Slab can choose BULL2 even if BULL1 first, beer exactly one consumed.
g=game(['slab_the_killer','black_jack','calamity_janet','el_gringo']);g.phase='slab_choice'
g.dice=[BULL1,BULL2,BEER,BEER,GATLING]
apply_slab_choice(g,BULL2)
assert [(a['face'],a['amount']) for a in g.pending_actions if a['type']=='shot']==[(BULL1,1),(BULL2,2)]
assert sum(a['type']=='beer' for a in g.pending_actions)==1

g.phase='slab_choice';apply_slab_choice(g,False)
assert all(a['amount']==1 for a in g.pending_actions if a['type']=='shot')
assert sum(a['type']=='beer' for a in g.pending_actions)==2

# 4. simultaneous Gatling: both 1hp including Vulture die before healing.
g=game(['willy_the_kid','vulture_sam','black_jack','jesse_jones']);g.players[1].hp=1;g.players[2].hp=1
resolve_gatling(g,[])
assert not g.players[1].alive and not g.players[2].alive, (g.players[1],g.players[2])

g=game(['willy_the_kid','vulture_sam','black_jack','jesse_jones']);g.players[1].hp=2;g.players[2].hp=1
resolve_gatling(g,[])
assert g.players[1].alive and g.players[1].hp==3 and not g.players[2].alive

# interactive Gatling and separate human decisions
g=game(['willy_the_kid','bart_cassidy','pedro_ramirez','jesse_jones']);g.players[2].arrows=2;g.arrows_pool=7
assert start_damage_session(g,[(1,1),(2,1),(3,1)],0,'gatling',[])
assert current_damage_choice(g)['kind']=='bart'
assert not choose_damage_option(g,1,1)
assert current_damage_choice(g)['kind']=='pedro'
assert choose_damage_option(g,2,0)
assert g.players[1].hp==7 and g.players[1].arrows==1
assert g.players[2].hp==6 and g.players[2].arrows==2

# simulate dynamite on Pedro - prompts not mandatory auto discard
from data import DYNAMITE
g=game(['pedro_ramirez','black_jack','calamity_janet','willy_the_kid']);g.phase='rolling';g.roll_no=1;g.players[0].arrows=2;g.arrows_pool=7
g.dice=[DYNAMITE]*3+[BEER,BEER]
e=[];_after_new_roll(g,[0,1,2,3,4],e)
assert g.phase=='damage_choice' and current_damage_choice(g)['kind']=='pedro'
assert choose_damage_option(g,0,0)
assert g.players[0].arrows==2 and g.phase=='resolving'
print('PASS: Bart select shield / direct damage; arrow pool last arrow restriction')
print('PASS: Pedro select discard 0..N after shot and dynamite')
print('PASS: Slab choose BULL1 or BULL2 and consume exactly one beer')
print('PASS: simultaneous Gatling / Vulture death order')
print('PASS: multi-human damage prompts')
# AI Bartlett auto defensively takes 1 arrow; no UI prompt.
g=game(['willy_the_kid','bart_cassidy','black_jack','jesse_jones'], ais=[False,True,False,False]);g.players[1].hp=1
assert not start_damage_session(g,[(1,1)],0,'shot',[])
assert g.players[1].hp==1 and g.players[1].arrows==1

# Safety: no other player can decide the human's ability (engine validates target index).
g=game(['willy_the_kid','bart_cassidy','black_jack','jesse_jones']);g.players[1].hp=2
start_damage_session(g,[(1,1)],0,'shot',[])
try:
    choose_damage_option(g,2,1)
    raise AssertionError('cross-player choice should fail')
except ValueError:
    pass
assert current_damage_choice(g)['idx']==1
print('PASS: AI Bart still defends; invalid target responses rejected')
