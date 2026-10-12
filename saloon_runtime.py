"""Complete Old Saloon turn runner.

A suspended generator owns each in-flight operation. A validated answer resumes
that exact stack once; no replay of damage, randomness or irreversible effects.
Telegram and offline simulations drive the same prompts.
"""
from __future__ import annotations
import random
import copy
import secrets
import time
from dataclasses import dataclass, field
from data import *
from old_saloon import DieState
from undead_runtime import UndeadMixin

ROLE_POWERS = {
 'sheriff_bear': ('熊警長', '開局額外3血，取代原本2血。'),
 'deputy_good': ('好人', '自己回合開始，與警長交換身分，雙方保留目前生命。'),
 'deputy_doc': ('醫生', '任何一次擲骰後，將一顆骰子改成該骰任一面。'),
 'deputy_judge': ('法官', '另一位玩家公開特殊身分時，取消其能力，該能力仍消耗。'),
 'outlaw_gambler': ('賭徒', '另一位玩家最後一擲後，忽略該擲結果，全部骰子重擲並接受結果。'),
 'outlaw_bad': ('壞人', '其他玩家即將回血時，取消這次回血。'),
 'outlaw_ugly': ('醜人', '自己回合開始，交換任意兩名玩家的全部箭。'),
 'renegade_right_hand': ('惡魔右手', '自己回合結束後，立即再進行一個完整回合。'),
 'renegade_left_hand': ('惡魔左手', '玩家即將淘汰時，保留2血，該玩家可丟棄全部箭。'),
}
ROLE_DECKS = {r: [k for k in ROLE_POWERS if k.startswith(r+'_')] for r in ROLE_CN}
SPECIAL = {'loudmouth': ['arrow','bullet','double_bull1','double_bull2','dynamite','double_gatling'],
           'coward': ['arrow','broken_arrow','bull1','bull2','beer','double_beer'],
           'duel': list(DUEL_FACES)}
CHOICE_FACE_LABELS = {**FACE_LABELS, 'double_bull1':'🎯1×2',
    'double_bull2':'🎯2×2', 'double_beer':'🍺×2',
    'double_gatling':'🔫×2', 'bullet':'🔫 自傷', 'broken_arrow':'🏹 斷箭'}


def enabled(g):
    return bool(g.expansion_config.active_modules())


def assign_special_roles(g, rng=random):
    decks = {k: list(v) for k,v in ROLE_DECKS.items()}
    for d in decks.values(): rng.shuffle(d)
    for p in g.players:
        p.is_ghost=False; p.ghost_target=None; p.special_role_key=''; p.role_power_used=False
        p.role_revealed=p.role=='sheriff' or len(g.players)==3
        if g.expansion_config.enabled('special_roles'):
            p.special_role_key=decks[p.role].pop()
            if p.role=='sheriff':
                p.max_hp=p.character.hp+3; p.hp=p.max_hp; p.role_power_used=True


@dataclass
class Prompt:
    serial: int
    kind: str
    text: str
    owners: list[int]
    options: list[tuple[str, object]]
    default: object = None
    seconds: float = 50.0
    deadline: float | None = None
    claimant: int | None = None
    payload: dict = field(default_factory=dict)


class SaloonRuntime(UndeadMixin):
    def __init__(self,g,seed=None):
        self.g=g; self.rng=random.Random(seed); self.token=secrets.token_hex(4)
        self.serial=0; self.prompt=None; self.gen=None; self.done=False
        self.turn=0; self.first_elimination=False; self.tokens={}; self.shots_used=0
        self.suppress_end=0; self.selected=set(); self.extra=False
        self.trace=[]; self.roll_history=[]
        self.selection_owner=None; self.selection_deadline=None
        self.pending_roll_transaction=False;self.last_moving=()
        g.saloon_runtime=self
        self.init_undead()

    def char(self,i):
        p=self.g.players[i]
        return '' if p.is_ghost else p.character_key

    def log(self,line):
        self.g.add_log(line);self.trace.append(line)

    def ask(self,kind,text,owner,options,default=None,seconds=50,payload=None):
        self.serial+=1
        owners=owner if isinstance(owner,list) else [owner]
        q=Prompt(self.serial,kind,text,owners,list(options),default,seconds,payload=payload or {})
        result=yield q
        return result

    def arm(self,now=None):
        if self.prompt and self.prompt.deadline is None:
            now=time.monotonic() if now is None else now
            if self.prompt.kind!='reaction' and self.selection_owner in self.prompt.owners:
                if self.selection_deadline is None:self.selection_deadline=now+20
                self.prompt.deadline=self.selection_deadline
            else:self.prompt.deadline=now+self.prompt.seconds

    def step(self,value=None):
        if self.done:return None
        if self.gen is None:self.gen=self.match()
        try:
            self.prompt=self.gen.send(value)
            self.g.phase='saloon_input'
        except StopIteration:
            self.done=True;self.prompt=None
        return self.prompt

    def answer(self,serial,idx,value,now=None):
        q=self.prompt
        if not q or q.serial!=serial:raise ValueError('選項已過期')
        if q.deadline is not None and (time.monotonic() if now is None else now)>=q.deadline:
            raise ValueError('已超過選擇時間')
        if idx not in q.owners:raise ValueError('現在不是你的選擇')
        if q.kind=='reaction':raise ValueError('請先按特殊技能')
        if value not in [v for _,v in q.options]:raise ValueError('選項無效')
        return self.step(value)

    def claim(self,serial,idx,now=None):
        q=self.prompt
        now=time.monotonic() if now is None else now
        if not q or q.serial!=serial or q.kind!='reaction' or idx not in q.owners or q.claimant is not None:
            raise ValueError('此刻沒有可發動的特殊技能')
        if q.deadline is None or now>=q.deadline:raise ValueError('反應窗口已結束')
        p=self.g.players[idx]
        if not p.alive or p.is_ghost or p.role_power_used:raise ValueError('能力已使用或不能發動')
        q.claimant=idx
        self.selection_owner=idx;self.selection_deadline=None
        return self.step(idx)

    def timeout(self,serial):
        if not self.prompt or self.prompt.serial!=serial:return self.prompt
        q=self.prompt
        choice=next((text for text,value in q.options if value==q.default),'略過')
        if q.kind != 'reaction':
            names='、'.join(self.g.players[i].name for i in q.owners)
            self.log(f'⏰ {names} 選擇逾時，自動採用：{choice}。')
        self.selection_owner=None;self.selection_deadline=None
        return self.step(self.prompt.default)

    def allied(self,a,b):
        ra=self.g.players[a].role;rb=self.g.players[b].role
        return a==b or (ra in ('sheriff','deputy') and rb in ('sheriff','deputy')) or ra==rb=='outlaw'

    def ai_value(self,q):
        i=q.owners[0];g=self.g
        vals=[v for _,v in q.options]
        if q.kind=='reaction':
            for j in q.owners:
                p=g.players[j];key=p.special_role_key;ctx=q.payload
                target=ctx.get('target',g.current_idx)
                good=(key in ('outlaw_ugly','renegade_right_hand') or
                      key=='deputy_good' and g.players[g.current_idx].hp>next((p.hp for p in g.players if p.role=='sheriff'),0) or
                      key=='renegade_left_hand' and (target==j or self.allied(j,target)) or
                      key=='outlaw_bad' and not self.allied(j,target) or
                      key=='outlaw_gambler' and not self.allied(j,g.current_idx) or
                      key=='deputy_doc' or
                      key=='deputy_judge' and not self.allied(j,target))
                if good:return j
            return None
        if q.kind=='dice':
            if self.char(i)=='jose_delgado':return 'loudmouth'
            if self.char(i)=='tequila_joe':return 'coward'
            return 'coward' if 'coward' in vals and g.players[i].hp<4 else vals[-1]
        if q.kind=='roll':
            # Keep useful attacks/healing, reroll arrows/bullets/isolated gatlings.
            mask=0;gat=sum(2 if f=='double_gatling' else f==GATLING for f in g.dice)
            for k,f in enumerate(g.dice):
                if f==DYNAMITE and self.char(i)!='black_jack':continue
                if f in (ARROW,'bullet','broken_arrow') or (f in (GATLING,'double_gatling') and gat<2):mask|=1<<k
            return mask if mask in vals else 0
        if q.kind in ('shot','elena','ghost_target','duel_target'):
            return max(vals,key=lambda j:(not self.allied(i,j),g.players[j].role=='sheriff',-g.players[j].hp))
        if q.kind in ('heal','sid','sam'):
            return max(vals,key=lambda j:(self.allied(i,j),g.players[j].max_hp-g.players[j].hp,j==i))
        if q.kind=='molly':return True if self.allied(i,q.payload['target']) and g.players[i].hp>q.payload['amount'] else False
        if q.kind=='doc_die':return next((v for v in vals if g.dice[v]==DYNAMITE),vals[0])
        if q.kind=='doc_face':return BEER if self.allied(i,g.current_idx) and BEER in vals else (ARROW if ARROW in vals else vals[0])
        if q.kind=='swap_first':return max(vals,key=lambda j:g.players[j].arrows+(2 if g.chief_arrow_owner==j else 0))
        if q.kind=='swap_second':return max(vals,key=lambda j:(not self.allied(i,j),g.players[j].role=='sheriff'))
        if q.kind=='chief':return 'chief' if 'chief' in vals else vals[0]
        if q.kind=='broken':return i if i in vals else vals[0]
        if q.kind=='ghost_face':return ARROW if ARROW in vals else vals[0]
        if q.kind=='kit':return i if i in vals else None
        if q.kind=='slab':return vals[-1]
        if q.kind=='confirm':return True
        if q.kind in ('bart','pedro'):return vals[-1]
        if q.kind=='belle':return vals[-1]
        if q.kind=='chuck_die':return vals[-1] if g.players[i].hp>3 else None
        if q.kind=='chuck_face':return BEER if BEER in vals else GATLING if GATLING in vals else DUEL if DUEL in vals else vals[-1]
        if q.kind=='sean':return True
        if q.kind=='sean_die':return next((k for k in vals if k is not None and g.dice[k] in (ARROW,)),None)
        if q.kind=='pixie':
            from undead_runtime import RAGE_CARDS
            return max(vals,key=lambda c:sum(2 if f in (BEER,DUEL) else -1 if f in (ARROW,DYNAMITE) else 1 for f in RAGE_CARDS[c]))
        return q.default if q.default in vals else vals[0]

    def alive(self):return [i for i,p in enumerate(self.g.players) if p.alive]
    def available(self,key):
        return [i for i,p in enumerate(self.g.players) if p.alive and not p.is_ghost and p.special_role_key==key and not p.role_power_used]

    def react(self,keys,ctx=None,only=None):
        owners=[i for key in keys for i in self.available(key) if only is None or i in only]
        if not owners:return None
        # The public prompt never names eligible players or their unrevealed roles.
        return (yield from self.ask('reaction','⚡ 特殊技能反應窗口（10秒）\n要使用能力，請按下方「我要發動技能」。',owners,[],None,10,ctx))

    def reveal(self,i,judge=True):
        self.selection_owner=None;self.selection_deadline=None
        p=self.g.players[i];p.role_revealed=True;p.role_power_used=True
        self.log(f'🎭 {p.name} 公開「{ROLE_POWERS[p.special_role_key][0]}」並發動能力。')
        if judge:
            j=yield from self.react(['deputy_judge'],{'target':i},only=[k for k in self.alive() if k!=i])
            if j is not None:
                yield from self.reveal(j,False)
                self.log('⚖️ 法官取消這次特殊能力；雙方能力均已消耗。')
                return False
        return True

    def confirm(self,i,text):
        answer=yield from self.ask('confirm',text,i,[('發動',True),('放棄',False)],False,10)
        if not answer:self.selection_owner=None;self.selection_deadline=None
        return answer

    def heal(self,i,n,source=None):
        p=self.g.players[i]
        if not p.alive or p.hp>=p.max_hp:return
        j=yield from self.react(['outlaw_bad'],{'target':i},only=[k for k in self.alive() if k!=i])
        if j is not None and (yield from self.confirm(j,'阻止這次回血？')):
            if (yield from self.reveal(j)):
                self.log(f'🚫 {p.name} 的回血被取消。');return
        before=p.hp;p.hp=min(p.max_hp,p.hp+n)
        from game_engine import _record_hit
        action={'kind':'heal','source_idx':source,'target_idx':i,'cause':'beer','before':before,'after':p.hp,'gained':p.hp-before}
        self.g.last_action=action;self.g.recent_actions.append(action)
        actor = self.g.players[source].name if source is not None else '角色能力'
        who = f'{actor} → 自己' if source == i else f'{actor} → {p.name}'
        self.log(f'🍺 {who}：回復 {p.hp-before} 血（{before}→{p.hp}/{p.max_hp}）。')

    def discard_all(self,i):
        g=self.g;p=g.players[i];g.arrows_pool+=p.arrows;p.arrows=0
        if g.chief_arrow_owner==i:g.chief_arrow_owner=None

    def log_arrow_removed(self,source,target,kind,reason):
        g=self.g
        who = '自己' if source == target else g.players[target].name
        arrow = '1 支普通箭' if kind == 'normal' else '酋長箭'
        remaining = f'剩 {g.players[target].arrows} 支普通箭'
        if g.chief_arrow_owner == target:remaining += '，另持有酋長箭'
        self.log(f'🏹 {g.players[source].name}〔{reason}〕移除{who}的{arrow}（{remaining}）。')

    def discard_one(self,i):
        g=self.g;p=g.players[i];opts=[]
        if p.arrows:opts.append(('丟普通箭','normal'))
        if g.chief_arrow_owner==i:opts.append(('丟酋長箭','chief'))
        if not opts:return
        val=yield from self.ask('pedro',f'{p.name}：受傷後可丟棄一支箭\n目前普通箭 {p.arrows} 支'+('，另持有酋長箭' if g.chief_arrow_owner==i else ''),i,[('保留箭，不使用能力',None)]+opts,None,10)
        if val=='normal':p.arrows-=1;g.arrows_pool+=1
        if val=='chief':g.chief_arrow_owner=None
        if val in ('normal','chief'):self.log_arrow_removed(i,i,val,'佩德羅能力')

    def take_arrow(self,i,allow_steal=False):
        g=self.g;p=g.players[i]
        if not p.alive:return
        opts=[]
        if g.arrows_pool:opts.append(('普通箭','normal'))
        if g.expansion_config.enabled('chief_arrow') and (g.chief_arrow_owner is None or (allow_steal and g.chief_arrow_owner!=i)):
            opts.append(('酋長箭','chief'))
        if not opts:
            yield from self.arrow_attack();return
        choice=opts[0][1] if len(opts)==1 else (yield from self.ask('chief',f'{p.name}：選擇箭矢',i,opts,opts[0][1],10))
        if choice=='chief':g.chief_arrow_owner=i;self.log(f'👑🏹 {p.name} 取得酋長箭。')
        else:p.arrows+=1;g.arrows_pool-=1;self.log(f'🏹 {p.name} 拿一支箭。')
        if g.arrows_pool==0 and (not g.expansion_config.enabled('chief_arrow') or g.chief_arrow_owner is not None):
            yield from self.arrow_attack()

    def arrow_attack(self):
        g=self.g;g.indian_attacks+=1;self.log('🏹 印第安人來襲！全場同時結算。')
        w={i:g.players[i].arrows+(2 if g.chief_arrow_owner==i else 0) for i in self.alive()}
        most=max(w.values(),default=0);chief=g.chief_arrow_owner
        safe=chief is not None and w.get(chief)==most and list(w.values()).count(most)==1
        hits=[]
        for i,n in w.items():
            if safe and i==chief:n=0;self.log(f'👑 {g.players[i].name} 酋長箭獨自最多，免傷。')
            if self.char(i)=='jourdonnais':n=min(1,n)
            if n:hits.append((i,n))
        for i in range(len(g.players)):self.discard_all(i)
        yield from self.damage(hits,None,'indians')

    def damage(self,hits,source,cause):
        """Collect defenses, apply the batch, rescue, eliminate, then check victory."""
        g=self.g;prepared=[];reserved={}
        for i,n in hits:
            p=g.players[i]
            if not p.alive:continue
            if cause=='shot' and self.char(i)=='vera_custer':n=max(0,n-1)
            if cause=='gatling' and self.char(i)=='paul_regret':n=0
            if n<=0:continue
            if self.char(i)=='bart_cassidy' and cause in ('shot','gatling'):
                cap=min(n,max(0,g.arrows_pool-1))
                if cap:
                    opts=[(f'❤️ 不拿箭，承受 {n} 點傷害',0)]
                    opts += [(f'🏹 拿 {x} 支普通箭，抵擋 {x} 點（剩 {n-x} 點傷害）',x) for x in range(1,cap+1)]
                    block=yield from self.ask('bart',f'{p.name}：即將受到 {n} 點傷害\n卡西迪：每拿1支普通箭，可抵擋1點傷害。',i,opts,0,10)
                    g.arrows_pool-=block;p.arrows+=block;n-=block
            if not n:continue
            for m in self.alive():
                if m!=i and self.char(m)=='molly_stark' and g.players[m].hp-reserved.get(m,0)>=n:
                    accept=yield from self.ask('molly',f'{g.players[m].name}：代替 {p.name} 承受 {n} 傷害？',m,[(f'🛡 我承受 {n} 點傷害',True),('不代擋',False)],False,10,{'target':i,'amount':n})
                    if accept:i=m;p=g.players[m];self.log(f'🛡 {p.name} 代為承受 {n} 傷害。');break
            prepared.append((i,n));reserved[i]=reserved.get(i,0)+n
        totals={}
        for i,n in prepared:totals[i]=totals.get(i,0)+n
        losts={}
        for i,n in totals.items():
            p=g.players[i];lost=min(p.hp,n);p.hp-=lost;losts[i]=lost
            self.record_undead_loss(i,lost)
            from game_engine import _record_hit
            _record_hit(g,source,i,cause,p.hp+lost,lost,[],0)
            actor = g.players[source].name if source is not None else {'indians':'印第安人', 'dynamite':'炸藥', 'bullet':'子彈骰面','chuck':'查克能力'}.get(cause, '環境傷害')
            icon = {'shot':'🎯', 'gatling':'🔫','duel':'⚔️'}.get(cause, '💥')
            if cause == 'gatling':actor += '〔格林機槍〕'
            self.log(f'{icon} {actor} → {p.name}：失去 {lost} 血（{p.hp+lost}→{p.hp}/{p.max_hp}）。')
        dying=[]
        for i,lost in losts.items():
            p=g.players[i]
            if p.hp<=0:
                j=yield from self.react(['renegade_left_hand'],{'target':i})
                rescued=False
                if j is not None and (yield from self.confirm(j,f'讓 {p.name} 保留2血？')):
                    rescued=yield from self.reveal(j)
                if rescued:
                    p.hp=2
                    discard=yield from self.ask('confirm',f'{p.name}：丟棄全部箭？',i,[('全部丟棄',True),('保留',False)],False,10)
                    if discard:self.discard_all(i)
                else:dying.append(i)
            elif self.char(i)=='pedro_ramirez':
                for _ in range(lost):yield from self.discard_one(i)
        # All deaths in the same batch are committed before Vulture healing.
        for i in dying:
            p=g.players[i];p.alive=False;p.role_revealed=True;self.discard_all(i)
            self.clear_undead_player(i)
            self.log(f'💀 {p.name} 淘汰，身分：{ROLE_CN[p.role]}。')
            if not self.first_elimination:
                self.first_elimination=True
                if g.expansion_config.enabled('ghost') and p.role!='sheriff':
                    p.ghost_original_role=p.role
                    p.is_ghost=True
                    if p.role=='renegade':p.role='outlaw' if len(g.players)%2 else 'deputy'
                    self.log(f'👻 {p.name} 成為鬼魂，陣營：{ROLE_CN[p.role]}。')
            self.tokens.pop(i,None)
        if dying:
            for i in self.alive():
                if self.char(i)=='vulture_sam':yield from self.heal(i,2*len(dying),i)
            if len(g.players)==3:
                if source is not None and g.players[source].alive and not g.three_player_duel and any(THREE_PLAYER_TARGET[g.players[source].role]==g.players[i].role for i in dying):
                    g.phase='ended';g.winner_indices=[source];g.winner_text=f'🏆 {g.players[source].name} 獲勝！';return
                g.three_player_duel=True
        from game_engine import check_win
        if check_win(g):return
        if self.char(g.current_idx)=='herb_hunter' and g.current_player().alive:
            for target in self.alive():
                if target!=g.current_idx and self.u['losses'].get(target,0)>=2 and target not in self.u['herb_given']:
                    self.u['herb_given'].append(target);self.draw_wound(target)
        if cause in ('shot','gatling','duel') and source is not None and g.players[source].alive:
            for i,lost in losts.items():
                if lost and i!=source and self.char(i)=='el_gringo':yield from self.take_arrow(source)

    def turn_start_roles(self,i):
        g=self.g
        j=yield from self.react(['deputy_good','outlaw_ugly'],only=[i])
        if j is None:return
        key=g.players[j].special_role_key
        if key=='deputy_good':
            sheriff=next((k for k,p in enumerate(g.players) if p.role=='sheriff' and p.alive),None)
            if sheriff is None:return
            if not (yield from self.confirm(j,'與警長交換身分？')):return
            if not (yield from self.reveal(j)):return
            a=g.players[j];b=g.players[sheriff]
            a.role,b.role=b.role,a.role;a.special_role_key,b.special_role_key=b.special_role_key,a.special_role_key
            a.role_power_used=b.role_power_used=True;a.role_revealed=b.role_revealed=True
            a.max_hp=a.character.hp;b.max_hp=b.character.hp
            self.log(f'⭐ {a.name} 成為新警長；雙方目前生命不變。')
        else:
            opts=[(g.players[k].name,k) for k in self.alive()]
            a=yield from self.ask('swap_first','交換箭：選第一位',j,opts,None,10)
            if a is None:return
            b=yield from self.ask('swap_second','交換箭：選第二位',j,[(n,k) for n,k in opts if k!=a],None,10)
            if b is None:return
            if not (yield from self.reveal(j)):return
            g.players[a].arrows,g.players[b].arrows=g.players[b].arrows,g.players[a].arrows
            if g.chief_arrow_owner==a:g.chief_arrow_owner=b
            elif g.chief_arrow_owner==b:g.chief_arrow_owner=a
            self.log(f'🏹 {g.players[a].name} 與 {g.players[b].name} 交換全部箭。')

    def doctor(self):
        g=self.g;j=yield from self.react(['deputy_doc'])
        if j is None:return
        die=yield from self.ask('doc_die','選擇要修改的骰子',j,[(f'第{k+1}顆：{CHOICE_FACE_LABELS.get(f, f)}',k) for k,f in enumerate(g.dice)],None,10)
        if die is None:return
        faces=SPECIAL.get(g.dice_types[die].kind,DICE_FACES)
        face=yield from self.ask('doc_face','選擇該骰的骰面',j,[(CHOICE_FACE_LABELS.get(f,f),f) for f in dict.fromkeys(faces)],None,10)
        if face is None:return
        if (yield from self.reveal(j)):
            g.dice[die]=face;self.log(f'🎲 醫生改變第 {die+1} 顆骰子。');return die

    def roll_effects(self,indices,final=False):
        g=self.g;i=g.current_idx
        arrows=[k for k in indices if g.dice[k]==ARROW]
        if self.char(i)=='bill_noface':arrows=[k for k,f in enumerate(g.dice) if f==ARROW] if final else []
        receiver=i
        if arrows and self.char(i)=='elena_fuente':
            receiver=yield from self.ask('elena','其中一支箭交給誰？',i,[(g.players[k].name,k) for k in self.alive()],i,10)
        for at,_ in enumerate(arrows):
            yield from self.take_arrow(receiver if at==0 else i,self.char(i)=='apache_kid')
            if g.phase=='ended' or not g.players[i].alive:return
        for k in indices:
            if g.dice[k]=='broken_arrow':
                opts=[(p.name,j) for j,p in enumerate(g.players) if p.alive and p.arrows]
                if opts:
                    j=yield from self.ask('broken','斷箭：移除誰的普通箭？',i,opts,opts[0][1],10)
                    g.players[j].arrows-=1;g.arrows_pool+=1
                    self.log_arrow_removed(i,j,'normal','斷箭')
        for k in indices:
            if g.dice[k]=='bullet':
                yield from self.damage([(i,1)],None,'bullet')
                if g.phase=='ended' or not g.players[i].alive:return
        if self.dynamite_count(i)>=3:
            if not g.players[i].is_ai:
                yield from self.ask('dynamite_notice',
                    '💥 已累積3顆以上炸藥，停止重擲！\n接下來處理1點炸藥傷害，再結算其餘骰面。\n按「繼續結算」，或5秒後自動繼續。',
                    i,[('💥 繼續結算',True)],True,5)
            yield from self.damage([(i,1)],None,'dynamite')

    def snapshot(self):
        state=copy.deepcopy({k:v for k,v in self.g.__dict__.items() if k!='saloon_runtime'})
        return state,copy.deepcopy(self.tokens),self.first_elimination,list(self.trace)

    def restore(self,snapshot):
        state,tokens,first,trace=snapshot
        ui={k:getattr(self.g,k) for k in ('board_message_id','announced_deaths','final_announcement_sent')}
        self.g.__dict__.clear();self.g.__dict__.update(copy.deepcopy(state));self.g.__dict__.update(ui);self.g.saloon_runtime=self
        self.tokens=copy.deepcopy(tokens);self.first_elimination=first;self.trace=list(trace)

    def rolling(self,i,ghost=False):
        g=self.g;p=g.players[i]
        if ghost:kind='base';count=2
        else:
            opts=[('普通骰','base')]
            if g.expansion_config.enabled('saloon_dice'):opts += [('大嘴巴','loudmouth'),('膽小鬼','coward')]
            kind=yield from self.ask('dice','選擇本回合骰子',i,opts,'base')
            count=6 if (self.char(i),kind) in [('jose_delgado','loudmouth'),('tequila_joe','coward')] else 5
        g.dice_types=[DieState(kind=kind)]+[DieState() for _ in range(count-1)]
        if not ghost and g.expansion_config.enabled('duel_dice'):
            # Replace exactly two base dice, including a sixth-die character.
            bases=[k for k,d in enumerate(g.dice_types) if d.kind=='base']
            for k in bases[-2:]:g.dice_types[k].kind='duel'
        g.dice=['']*count;indices=list(range(count));limit=3 if ghost else (4 if self.char(i)=='lucky_duke' else 3)
        token=self.tokens.get(i);frozen={}
        if token and not ghost:
            face,n=token
            slots=[k for k,d in enumerate(g.dice_types) if d.kind=='base'][:n]
            frozen={k:face for k in slots}
        force=False
        for roll in range(1,limit+1):
            g.roll_no=roll
            for k in indices:g.dice[k]=frozen[k] if roll==1 and k in frozen else self.rng.choice(SPECIAL.get(g.dice_types[k].kind,DICE_FACES))
            self.last_moving=tuple(k for k in indices if roll!=1 or k not in frozen)
            self.roll_history.append(tuple(g.dice));self.log(f'🎲 {p.name} 第 {roll} 次擲骰。')
            if not ghost:
                changed=yield from self.doctor()
                if changed is not None and changed not in indices:indices.append(changed)
                yield from self.after_undead_roll(i,indices)
            # Keep a transaction snapshot of this roll's immediate effects.
            # Earlier rolls remain committed. A Gambler may replace only this roll.
            self.pending_roll_transaction=bool(self.available('outlaw_gambler')) and not ghost
            before=self.snapshot()
            if not ghost:
                yield from self.roll_effects(indices,False)
                if g.players[i].alive and g.phase!='ended' and self.dynamite_count(i)<3:
                    extra_before=yield from self.sean_extra_roll(i)
                    if extra_before is not None:before=extra_before
            p=g.players[i]
            locked=self.dynamite_count(i)>=3 and not ghost
            final=roll==limit or locked or (not ghost and not p.alive) or g.phase=='ended'
            mask=0
            if not final:
                legal=[k for k,f in enumerate(g.dice) if f!=DYNAMITE or (not ghost and self.char(i)=='black_jack')]
                masks=[m for m in range(1,1<<count) if all(not(m>>k&1) or k in legal for k in range(count))]
                opts=[('確定結果',0)]+[('重擲 '+','.join(str(k+1) for k in range(count) if m>>k&1),m) for m in masks]
                mask=yield from self.ask('roll','選擇重擲骰子，或確定結果',i,opts,0)
                final=mask==0
            replaced=False
            if final and not ghost:
                after=self.snapshot()
                # Eligibility and final-roll results are evaluated before committing
                # elimination, allowing a lethal final roll to be replaced too.
                self.restore(before)
                owners=[k for k in self.available('outlaw_gambler') if k!=i]
                if owners:
                    j=yield from self.react(['outlaw_gambler'],only=owners)
                    confirmed=j is not None and (yield from self.confirm(j,'強迫全部骰子重擲並接受？'))
                    if confirmed:
                        replaced=yield from self.reveal(j)
                    # A judge may cancel the Gambler, but both cards stay spent.
                    powers={k:(q.role_power_used,q.role_revealed) for k,q in enumerate(g.players)
                            if q.role_power_used and not before[0]['players'][k].role_power_used}
                    reveal_lines=list(g.log[len(before[0]['log']):])
                    if not replaced:
                        self.restore(after)
                        for k,(used,revealed) in powers.items():
                            g.players[k].role_power_used=used;g.players[k].role_revealed=revealed
                        for line in reveal_lines:self.log(line)
                else:self.restore(after)
                if replaced:
                    g.dice=[self.rng.choice(SPECIAL.get(d.kind,DICE_FACES)) for d in g.dice_types]
                    indices=list(range(count));self.last_moving=tuple(indices);self.roll_history.append(tuple(g.dice));self.log('🎲 賭徒：忽略本次原結果，全部骰子重擲。')
                    yield from self.doctor()
                    yield from self.after_undead_roll(i,indices)
                    yield from self.roll_effects(indices,True)
                elif self.char(i)=='bill_noface' and g.players[i].alive and g.phase!='ended':
                    # Bill has not taken any arrow from this roll yet.
                    for _ in range(g.dice.count(ARROW)):
                        yield from self.take_arrow(i)
                        if g.phase=='ended' or not g.players[i].alive:break
            self.pending_roll_transaction=False
            if not ghost and (g.phase=='ended' or not g.players[i].alive):return False
            if final:return True
            indices=[k for k in range(count) if mask>>k&1]
        return True

    def resolve(self,i):
        g=self.g;p=g.players[i]
        faces=self.effective_final_faces(i)
        yield from self.resolve_whiskey(i,faces)
        if g.phase=='ended' or not p.alive:return
        shots=sorted(f for f in faces if f in (BULL1,BULL2));beers=faces.count(BEER)
        slab=None
        if self.char(i)=='slab_the_killer' and beers and shots:
            slab=yield from self.ask('slab','消耗一個啤酒，加倍一次射擊？',i,[('🍺 保留啤酒，不加倍',None)]+[(f'消耗1啤酒：一次{CHOICE_FACE_LABELS[f]}射擊改為2傷害',f) for f in sorted(set(shots))],None,10)
            if slab:beers-=1
        used=0
        from game_engine import valid_targets_for_face
        for face in shots:
            valid=valid_targets_for_face(g,i,face)
            if not valid:continue
            amount=2 if slab==face else 1
            if slab==face:slab=None
            g.pending_action={'type':'shot','face':face,'amount':amount}
            target=yield from self.ask('shot',f'{p.name}：{FACE_LABELS[face]} 選射擊目標',i,[(g.players[k].name,k) for k in valid],valid[0])
            used+=1;yield from self.damage([(target,amount)],i,'shot')
            if g.phase=='ended' or not p.alive:return
        g.pending_action=None
        if used>=3 and self.char(i)=='doc_holyday':yield from self.heal(i,2,i)
        for _ in range(beers):
            target=yield from self.ask('heal','啤酒：選補血目標',i,[(g.players[k].name,k) for k in self.alive()],i)
            n=2 if self.char(i)=='jesse_jones' and target==i and p.hp<=4 else 1
            yield from self.heal(target,n,i)
        gat=faces.count(GATLING)
        if gat>=(2 if self.char(i)=='willy_the_kid' else 3):
            self.discard_all(i);self.log(f'🔫 {p.name} 發動格林機槍！')
            yield from self.damage([(k,1) for k in self.alive() if k!=i],i,'gatling')
            if g.phase=='ended' or not p.alive:return
        if self.char(i)=='kit_carlson':
            for _ in range(gat):
                opts=[(q.name,k) for k,q in enumerate(g.players) if q.alive and (q.arrows or g.chief_arrow_owner==k)]
                if not opts:break
                target=yield from self.ask('kit','基特：選擇移除誰的一支箭（可選酋長箭）',i,[('略過這次移除',None)]+opts,None,10)
                if target is not None:
                    if g.players[target].arrows and g.chief_arrow_owner==target:
                        arrow=yield from self.ask('chief','基特：選擇移除的箭',i,[('普通箭','normal'),('酋長箭','chief')],'normal',10)
                    else:arrow='normal' if g.players[target].arrows else 'chief'
                    if arrow=='chief':g.chief_arrow_owner=None
                    else:g.players[target].arrows-=1;g.arrows_pool+=1
                    self.log_arrow_removed(i,target,arrow,'基特能力')
        if not shots and self.char(i)=='suzy_lafayette':yield from self.heal(i,2,i)
        yield from self.resolve_duels(i,faces.count(DUEL))

    def ghost_turn(self,i):
        g=self.g
        yield from self.rolling(i,True)
        faces=list(dict.fromkeys(g.dice))
        face=yield from self.ask('ghost_face','鬼魂：選擇要給出的符號',i,[(f,f) for f in faces],faces[0])
        targets=self.alive()
        if not targets:return
        target=yield from self.ask('ghost_target','鬼魂：標記交給誰？',i,[(g.players[k].name,k) for k in targets],targets[0])
        self.tokens.clear();self.tokens[target]=(face,2 if len(faces)==1 else 1)
        g.ghost_state={'target':target,'face':face,'count':self.tokens[target][1]}
        self.log(f'👻 {g.players[i].name} 給 {g.players[target].name} {FACE_LABELS[face]} ×{self.tokens[target][1]}。')

    def match(self):
        g=self.g
        from game_engine import check_win
        while not check_win(g):
            i=g.current_idx;p=g.players[i];self.turn+=1
            g.dice=[];g.dice_types=[];g.roll_no=0;g.pending_action=None
            self.u['losses']={};self.u['duel']=None
            self.log(f'▶ 輪到 {p.name}' + ('（鬼魂）' if p.is_ghost else f'（{p.character.cn}）'))
            if p.is_ghost:yield from self.ghost_turn(i)
            elif p.alive:
                yield from self.turn_start_roles(i)
                yield from self.undead_turn_begin(i)
                if self.char(i)=='sid_ketchum':
                    target=yield from self.ask('sid','席德：回合開始補血',i,[(g.players[k].name,k) for k in self.alive()],i)
                    yield from self.heal(target,1,i)
                ok=(yield from self.rolling(i)) if g.players[i].alive and g.phase!='ended' else False
                p=g.players[i]
                if ok and p.alive and g.phase!='ended':yield from self.resolve(i)
            if g.phase!='ended':yield from self.undead_turn_end(i)
            self.tokens.pop(i,None)
            if g.ghost_state.get('target')==i:g.ghost_state={}
            if check_win(g):break
            self.log(f'✅ {g.players[i].name} 本回合骰面已結算完畢。')
            j=yield from self.react(['renegade_right_hand'],only=[i])
            if j is not None and (yield from self.confirm(j,'立即進行額外回合？')):
                if (yield from self.reveal(j)):continue
            for step in range(1,len(g.players)+1):
                k=(i+step)%len(g.players)
                if g.players[k].alive or g.players[k].is_ghost:g.current_idx=k;break
        g.phase='ended'
