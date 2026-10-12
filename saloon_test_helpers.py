"""Rule and suspension tests for all expansion modules; no Telegram connection."""
import random
from game_engine import Game,add_ai,setup_game,distance,winning_player_indices
from old_saloon import ExpansionConfig,MODULE_KEYS
from saloon_runtime import SaloonRuntime,ROLE_POWERS
from data import *

def fresh(n=5,seed=1):
    g=Game(-123,1,ExpansionConfig('saloon',(set(MODULE_KEYS)-{'duel_dice','rage','undead_characters'})-({'ghost'} if n<5 else set())))
    for _ in range(n):add_ai(g)
    setup_game(g,random.Random(seed))
    for i,p in enumerate(g.players):
        p.role=['sheriff','outlaw','deputy','renegade','outlaw','outlaw','deputy','renegade'][i]
        p.character_key='black_jack';p.hp=p.max_hp=8;p.special_role_key='';p.role_power_used=False
    g.current_idx=0
    return g,SaloonRuntime(g,seed)

def run(r,gen,answers=None):
    r.gen=gen;r.step();answers=answers or {}
    while not r.done:
        q=r.prompt;v=answers.get(q.kind, r.ai_value(q))
        if callable(v):v=v(q)
        r.step(v)

