"""Behavioral checks: duel ownership, finite decks, wounds and all new abilities."""
import unittest, random, collections
from saloon_test_helpers import fresh
from data import *
from old_saloon import ExpansionConfig
from undead_runtime import RAGE_CARDS, WOUND_TOKENS
from saloon_runtime import SPECIAL

class Sequence(random.Random):
    def __init__(self,values):super().__init__(42);self.values=iter(values)
    def choice(self,faces):
        value=next(self.values);assert value in faces,(value,faces);return value

def new():
    g,r=fresh();g.expansion_config.modules.update({'duel_dice','rage','undead_characters'})
    return g,r

def drive(r,gen,answers=None):
    r.done=False;r.gen=gen;r.prompt=None;r.step();answers=answers or {}
    budget=1000
    while not r.done:
        budget-=1;assert budget>0
        q=r.prompt;v=answers.get(q.kind,r.ai_value(q))
        r.step(v(q) if callable(v) else v)

class UndeadTests(unittest.TestCase):
    def test_physical_decks(self):
        self.assertEqual(len(RAGE_CARDS),18);self.assertEqual(len(WOUND_TOKENS),15)
        counts=collections.Counter(RAGE_CARDS)
        for f in (BULL1,BULL2,BEER,GATLING):self.assertEqual(counts[(f,)],3)
        self.assertEqual(counts[(DUEL,)],2)
        self.assertEqual(collections.Counter(DUEL_FACES)[DUEL],2)
    def test_dependency_and_character_gate(self):
        c=ExpansionConfig('saloon',{'undead_characters'})
        self.assertEqual(set(c.eligible_new_characters()),{'belle_star','chuck_wengam'})
        c.toggle('duel_dice',5)
        self.assertTrue(c.enabled('rage'));self.assertEqual(len(c.eligible_new_characters()),8)
        c.toggle('rage',5);self.assertFalse(c.enabled('duel_dice'))
        self.assertFalse(ExpansionConfig('saloon',{'duel_dice'}).playable_status(5)[0])
    def test_duel_alternates_and_rejects_stale_click(self):
        g,r=new();r.rng=Sequence([DUEL,GATLING]);r.gen=r.resolve_duels(0,1);r.step()
        self.assertEqual(r.prompt.kind,'duel_target');r.step(1)
        q=r.prompt;self.assertEqual(q.owners,[1]);r.arm(now=0)
        with self.assertRaises(ValueError):r.answer(q.serial,0,True,now=1)
        r.answer(q.serial,1,True,now=1)
        self.assertEqual(r.prompt.owners,[0]);self.assertEqual(g.current_idx,0)
        with self.assertRaises(ValueError):r.answer(q.serial,1,True,now=1)
        r.step(True)
        self.assertTrue(r.done);self.assertEqual(g.players[0].hp,7)
        self.assertEqual(len(r.u['wounds'][0]),1)
        self.assertEqual([e['mover'] for e in r.u['duel_events']],[1,0])
        self.assertFalse(r.u['duel'])
    def test_duel_targets_are_unique_and_non_duel_face_ignored(self):
        g,r=new();r.rng=Sequence([ARROW,WHISKEY]);seen=[]
        def target(q):
            j=next(v for _,v in q.options if v not in seen);seen.append(j);return j
        drive(r,r.resolve_duels(0,2),{'duel_target':target})
        self.assertEqual(len(set(seen)),2);self.assertEqual(g.arrows_pool,9)
        self.assertEqual(g.players[seen[0]].hp,7);self.assertEqual(g.players[seen[1]].hp,7)
        self.assertFalse(any(r.u['held'].values()))
    def test_timeout_rolls_once(self):
        g,r=new();r.rng=Sequence([GATLING]);r.gen=r.resolve_duels(0,1);r.step();r.step(1)
        old=r.prompt.serial;r.timeout(old);hp=g.players[1].hp
        r.timeout(old);self.assertEqual(g.players[1].hp,hp);self.assertEqual(hp,7)
    def test_duplicate_wound_and_return(self):
        g,r=new();r.u['wound_pool']=[BULL1];r.u['wounds'][1]=[BULL1]
        r.draw_wound(1);self.assertEqual(r.u['wounds'][1],[BULL1]);self.assertEqual(r.u['wound_pool'],[BULL1])
        drive(r,r.undead_turn_end(1));self.assertFalse(r.u['wounds'][1]);self.assertEqual(r.u['wound_pool'].count(BULL1),2)
    def test_wounds_cancel_one_double_half_not_rage(self):
        g,r=new();g.dice=['double_beer','double_bull1',BULL2];r.u['wounds'][0]=[BEER,BULL1]
        r.u['active']=[0]
        self.assertEqual(collections.Counter(r.effective_final_faces(0)),collections.Counter([BEER,BULL1,BULL1,BULL2]))
    def test_dynamite_from_rage_and_wound(self):
        g,r=new();g.dice=[DYNAMITE,BEER,BEER,BEER,BEER]
        r.u['active']=[14];r.u['wounds'][0]=[DYNAMITE]
        drive(r,r.roll_effects(list(range(5))))
        self.assertEqual(g.players[0].hp,7);self.assertEqual(r.dynamite_count(),3)
    def test_rage_cumulative_damage_even_after_healing(self):
        g,r=new();drive(r,r.damage([(1,1)],0,'shot'));drive(r,r.heal(1,1,0));drive(r,r.damage([(1,1)],0,'shot'))
        drive(r,r.undead_turn_end(0));self.assertEqual(len(r.u['held'][1]),1)
        self.assertEqual(g.players[1].hp,7)
    def test_finite_rage_deck(self):
        g,r=new()
        for k in range(18):drive(r,r.draw_rage(k%5))
        self.assertFalse(r.u['deck']);self.assertEqual(len({c for cards in r.u['held'].values() for c in cards}),18)
        drive(r,r.draw_rage(0));self.assertEqual(sum(map(len,r.u['held'].values())),18)
        first=r.u['held'][0].pop();r.u['discard']=[first];drive(r,r.draw_rage(1))
        self.assertIn(first,r.u['held'][1]);self.assertFalse(r.u['discard'])
    def test_pixie_keeps_one_and_other_shuffled_back(self):
        g,r=new();g.players[0].character_key='pixie_pete'
        r.gen=r.draw_rage(0);r.step();q=r.prompt
        self.assertEqual(q.kind,'pixie');self.assertEqual(len(q.payload['secret_cards']),2)
        self.assertTrue(all('準心' not in t for t,_ in q.options))
        a,b=q.payload['secret_cards'];r.step(b)
        self.assertEqual(r.u['held'][0],[b]);self.assertIn(a,r.u['deck']);self.assertEqual(len(r.u['deck']),17)
    def test_pat_move_before_reveal(self):
        g,r=new();g.players[0].character_key='pat_brennan';r.u['held'][1]=[0]
        drive(r,r.undead_turn_begin(0),{'pat_source':1,'pat_target':0})
        self.assertFalse(r.u['held'][1]);self.assertEqual(r.u['active'],[0]);self.assertFalse(r.u['held'][0])
    def test_rage_arrows_immediate(self):
        g,r=new();r.u['held'][0]=[15]
        drive(r,r.undead_turn_begin(0),{'chief':'normal'})
        self.assertEqual(g.players[0].arrows,1);self.assertEqual(r.rage_faces(),list(RAGE_CARDS[15]))
    def test_whiskey_full_hp_and_greg_double(self):
        g,r=new();g.players[0].character_key='greg_digger'
        drive(r,r.resolve_whiskey(0,[WHISKEY]))
        self.assertEqual(g.players[0].hp,8);self.assertEqual(len(r.u['held'][0]),2)
    def test_whiskey_removes_chosen_wound(self):
        g,r=new();g.players[0].hp=4;r.u['wounds'][0]=[BEER,DYNAMITE]
        drive(r,r.resolve_whiskey(0,[WHISKEY]),{'whiskey_wound':DYNAMITE})
        self.assertEqual(g.players[0].hp,5);self.assertEqual(r.u['wounds'][0],[BEER]);self.assertFalse(r.u['held'][0])
    def test_herb_triggers_once_per_target(self):
        g,r=new();g.players[0].character_key='herb_hunter'
        drive(r,r.damage([(1,1)],0,'shot'));self.assertFalse(r.u['wounds'][1])
        drive(r,r.damage([(1,1)],0,'shot'));self.assertEqual(len(r.u['wounds'][1]),1)
        drive(r,r.damage([(1,1)],0,'shot'));self.assertEqual(len(r.u['wounds'][1]),1)
    def test_belle_changes_dynamite(self):
        g,r=new();g.players[0].character_key='belle_star';g.dice=[DYNAMITE,BEER]
        drive(r,r.after_undead_roll(0,[0,1]),{'belle':0});self.assertEqual(g.dice[0],GATLING)
        g.dice=[DYNAMITE]*3
        drive(r,r.after_undead_roll(0,[0,1,2]));self.assertEqual(g.dice,[DYNAMITE]*3)
    def test_chuck_cost_once_and_faces_of_actual_die(self):
        from old_saloon import DieState
        g,r=new();g.players[0].character_key='chuck_wengam';g.dice=[ARROW,BEER];g.dice_types=[DieState('duel'),DieState()]
        drive(r,r.after_undead_roll(0,[0,1]),{'chuck_die':0,'chuck_face':DUEL})
        self.assertEqual(g.players[0].hp,7);self.assertEqual(g.dice[0],DUEL);self.assertTrue(r.u['chuck_used'])
        drive(r,r.after_undead_roll(0,[0,1]));self.assertEqual(g.players[0].hp,7)
    def test_sam_heals_per_duel_not_return_fire(self):
        g,r=new();g.players[0].character_key='sam_the_healer';g.players[2].hp=5
        r.rng=Sequence([DUEL,GATLING])
        drive(r,r.resolve_duels(0,1),{'duel_target':1,'sam':2})
        self.assertEqual(g.players[2].hp,6);self.assertEqual(g.players[0].hp,7)
    def test_sean_retry_only_own_turn(self):
        g,r=new();g.players[0].character_key='sean_mallory';r.rng=Sequence([DUEL,GATLING,DUEL,GATLING])
        drive(r,r.resolve_duels(0,1),{'duel_target':1,'sean':True})
        self.assertTrue(r.u['sean_used']);self.assertEqual(g.players[0].hp,8);self.assertEqual(g.players[1].hp,7)
        g,r=new();g.players[1].character_key='sean_mallory';r.rng=Sequence([GATLING])
        drive(r,r.resolve_duels(0,1),{'duel_target':1})
        self.assertFalse(r.u['sean_used']);self.assertEqual(g.players[1].hp,7)
    def test_roll_setup_six_and_ghost(self):
        g,r=new();g.players[0].character_key='jose_delgado'
        r.rng=Sequence(['double_bull1',BEER,BEER,BEER,DUEL,DUEL])
        drive(r,r.rolling(0),{'dice':'loudmouth','roll':0})
        self.assertEqual(len(g.dice),6);self.assertEqual([d.kind for d in g.dice_types].count('duel'),2)
        g,r=new();g.players[1].is_ghost=True;g.players[1].alive=False;g.current_idx=1;r.rng=Sequence([BEER,BEER])
        drive(r,r.rolling(1,True),{'roll':0});self.assertEqual([d.kind for d in g.dice_types],['base','base'])
    def test_transaction_restores_all_undead_state(self):
        g,r=new();snapshot=r.snapshot();card=r.u['deck'][-1]
        drive(r,r.draw_rage(0));r.draw_wound(1);r.record_undead_loss(1,2);r.restore(snapshot)
        self.assertFalse(r.u['held'][0]);self.assertFalse(r.u['wounds'][1]);self.assertFalse(r.u['losses']);self.assertEqual(r.u['deck'][-1],card)

if __name__=='__main__':unittest.main(verbosity=2)
