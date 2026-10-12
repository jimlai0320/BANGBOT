"""Undead or Alive modules 1–3, shared by Telegram and offline games.

The finite Rage deck is transcribed from the owner's photograph of all 18
cards. Game-owned state is included in the Saloon Gambler's transaction.
"""
from data import ARROW, DYNAMITE, GATLING, BEER, BULL1, BULL2, DUEL, WHISKEY, DUEL_FACES, FACE_LABELS

RAGE_CARDS = (
    *((BULL1,),) * 3, *((BULL2,),) * 3,
    *((BEER,),) * 3, *((GATLING,),) * 3, *((DUEL,),) * 2,
    (BULL1, BEER, DYNAMITE), (BULL1, DUEL, ARROW),
    (BULL2, DUEL, DYNAMITE), (BULL2, GATLING, ARROW),
)
WOUND_TOKENS = (BEER,) * 3 + (BULL1,) * 5 + (BULL2,) * 5 + (DYNAMITE,) * 2


def symbols_text(faces):
    return ' ＋ '.join(FACE_LABELS.get(f, f) for f in faces)


class UndeadMixin:
    def init_undead(self):
        g = self.g
        if g.undead_state:return
        deck = list(range(len(RAGE_CARDS))); wounds = list(WOUND_TOKENS)
        self.rng.shuffle(deck); self.rng.shuffle(wounds)
        g.undead_state = dict(deck=deck, discard=[], wound_pool=wounds,
            held={i: [] for i in range(len(g.players))},
            wounds={i: [] for i in range(len(g.players))}, active=[],
            losses={}, herb_given=[], chuck_used=False, sean_used=False,
            duel_events=[], duel=None)

    @property
    def u(self):return self.g.undead_state

    def rage_faces(self):
        return [f for card in self.u['active'] for f in RAGE_CARDS[card]]

    def dynamite_count(self, i=None):
        i = self.g.current_idx if i is None else i
        return (self.g.dice.count(DYNAMITE) + self.rage_faces().count(DYNAMITE)
                + self.u['wounds'][i].count(DYNAMITE))

    def draw_rage_raw(self):
        u = self.u
        if not u['deck']:
            u['deck'], u['discard'] = u['discard'], []
            self.rng.shuffle(u['deck'])
        return u['deck'].pop() if u['deck'] else None

    def draw_rage(self, i):
        if not self.g.expansion_config.enabled('rage') or not self.g.players[i].alive:return
        first = self.draw_rage_raw()
        if first is None:
            self.log('🔥 憤怒牌庫暫時全在玩家手上，沒有可抽的牌。');return
        selected = first
        if self.char(i) == 'pixie_pete':
            second = self.draw_rage_raw()
            if second is not None:
                selected = yield from self.ask('pixie',
                    '皮克西：抽2張選1張。牌面只在你的私訊／「查看候選牌」中顯示。', i,
                    [('保留A牌', first), ('保留B牌', second)], first,
                    payload={'secret_cards': [first, second]})
                other = second if selected == first else first
                self.u['deck'].append(other);self.rng.shuffle(self.u['deck'])
        self.u['held'][i].append(selected)
        self.log(f'🔥 {self.g.players[i].name} 取得1張憤怒卡（保留到自己下回合）。')

    def draw_wound(self, i):
        if not (self.g.expansion_config.enabled('duel_dice') or self.g.expansion_config.enabled('rage')) or not self.g.players[i].alive:return
        pool = self.u['wound_pool']
        if not pool:
            self.log('🩹 決鬥傷口池暫時沒有標記。');return
        face = pool.pop()
        if face in self.u['wounds'][i]:
            pool.append(face);self.rng.shuffle(pool)
            self.log(f'🩹 {self.g.players[i].name} 抽到重複的{FACE_LABELS[face]}傷口，洗回、不重抽。')
        else:
            self.u['wounds'][i].append(face)
            label = '多算1個炸藥' if face == DYNAMITE else f'抵消1個{FACE_LABELS[face]}骰面'
            self.log(f'🩹 {self.g.players[i].name} 取得傷口：{label}。')

    def clear_undead_player(self, i):
        if self.u['wounds'][i]:
            self.u['wound_pool'].extend(self.u['wounds'][i]);self.u['wounds'][i].clear()
            self.rng.shuffle(self.u['wound_pool'])
        self.u['discard'].extend(self.u['held'][i]);self.u['held'][i].clear()
        if i == self.g.current_idx:
            self.u['discard'].extend(self.u['active']);self.u['active'].clear()

    def record_undead_loss(self, i, lost):
        self.u['losses'][i] = self.u['losses'].get(i, 0) + lost

    def undead_turn_begin(self, i):
        u = self.u;g = self.g
        u['losses'] = {};u['herb_given'] = []
        u['chuck_used'] = u['sean_used'] = False;u['duel'] = None
        u['active'] = []
        if self.char(i) == 'pat_brennan':
            candidates = [k for k in self.alive() if u['held'][k]]
            if candidates:
                a = yield from self.ask('pat_source','帕特：移動誰的1張憤怒卡？',i,
                    [('不移動',None)] + [(g.players[k].name,k) for k in candidates],None)
                if a is not None:
                    at = 0
                    if len(u['held'][a]) > 1:
                        at = yield from self.ask('pat_card','選擇要移動的蓋牌（不公開牌面）',i,
                            [(f'第{k+1}張蓋牌',k) for k in range(len(u['held'][a]))],0)
                    targets = [k for k in self.alive() if k != a]
                    if targets:
                        b = yield from self.ask('pat_target','帕特：把憤怒卡移給誰？',i,
                            [(g.players[k].name,k) for k in targets],targets[0])
                        card = u['held'][a].pop(at);u['held'][b].append(card)
                        self.log(f'🔥 {g.players[i].name}〔帕特能力〕將{g.players[a].name}的1張憤怒卡移給{g.players[b].name}。')
        if g.players[i].is_ghost or not g.players[i].alive:return
        u['active'],u['held'][i] = u['held'][i],[]
        if u['active']:
            u.setdefault('rage_reveals',[]).append({'player':i,'cards':list(u['active'])})
            self.log(f'🔥 {g.players[i].name} 翻開憤怒卡：{symbols_text(self.rage_faces())}。')
        for f in list(self.rage_faces()):
            if f == ARROW:
                yield from self.take_arrow(i)
                if g.phase == 'ended' or not g.players[i].alive:return

    def undead_turn_end(self, i):
        g = self.g
        self.u['discard'].extend(self.u['active']);self.u['active'].clear()
        if self.u['wounds'][i]:
            self.u['wound_pool'].extend(self.u['wounds'][i]);self.u['wounds'][i].clear()
            self.rng.shuffle(self.u['wound_pool'])
        for k in self.alive():
            if self.u['losses'].get(k,0) >= 2:
                yield from self.draw_rage(k)
        self.u['duel'] = None

    def after_undead_roll(self, i, indices):
        g = self.g
        if self.char(i) == 'belle_star' and g.dice.count(DYNAMITE) and self.dynamite_count(i) < 3:
            bombs = [k for k,f in enumerate(g.dice) if f == DYNAMITE]
            k = yield from self.ask('belle','貝爾：把1顆炸藥改成格林機槍？',i,
                [('保留炸藥',None)] + [(f'第{k+1}顆炸藥 → 格林機槍',k) for k in bombs],None)
            if k is not None:
                g.dice[k] = GATLING
                self.log(f'🤠 {g.players[i].name}〔貝爾能力〕第{k+1}顆炸藥改為格林機槍。')
                if k not in indices:indices.append(k)
        if self.char(i) == 'chuck_wengam' and not self.u['chuck_used'] and g.players[i].hp > 0:
            valid = [k for k,f in enumerate(g.dice) if not(f == DYNAMITE and self.dynamite_count(i) >= 3)]
            if valid:
                k = yield from self.ask('chuck_die','查克：失去1血，修改1顆骰子？（每回合1次）',i,
                    [('暫不使用',None)] + [(f'第{k+1}顆：{FACE_LABELS.get(g.dice[k],g.dice[k])}',k) for k in valid],None)
                if k is not None:
                    from saloon_runtime import SPECIAL, CHOICE_FACE_LABELS
                    from data import DICE_FACES
                    faces = list(dict.fromkeys(SPECIAL.get(g.dice_types[k].kind,DICE_FACES)))
                    face = yield from self.ask('chuck_face','查克：選擇骰面，確定後支付1血',i,
                        [('取消，不支付',None)] + [(CHOICE_FACE_LABELS.get(f,f),f) for f in faces],None)
                    if face is not None:
                        self.u['chuck_used'] = True
                        yield from self.damage([(i,1)],None,'chuck')
                        if g.players[i].alive and g.phase != 'ended':
                            g.dice[k] = face
                            self.log(f'🤠 {g.players[i].name}〔查克能力〕第{k+1}顆改為{CHOICE_FACE_LABELS.get(face,face)}。')
                            if k not in indices:indices.append(k)

    def sean_extra_roll(self, i):
        g=self.g
        if self.char(i)!='sean_mallory' or self.u['sean_used']:return
        indices=[k for k,d in enumerate(g.dice_types) if d.kind=='duel']
        if not indices:return
        k=yield from self.ask('sean_die','尚恩：使用額外1次決鬥骰重擲？也可保留能力用於決鬥回擊。',i,
            [('暫不使用',None)]+[(f'重擲第{k+1}顆：{FACE_LABELS[g.dice[k]]}',k) for k in indices],None)
        if k is None:return
        self.u['sean_used']=True
        before=self.snapshot()
        g.dice[k]=self.rng.choice(DUEL_FACES)
        self.last_moving=(k,);self.roll_history.append(tuple(g.dice))
        self.log(f'🤠 {g.players[i].name}〔尚恩能力〕額外重擲第{k+1}顆決鬥骰。')
        changed=yield from self.doctor()
        affected=[k] + ([changed] if changed is not None and changed!=k else [])
        yield from self.roll_effects(affected,False)
        return before

    def effective_final_faces(self, i):
        # Wounds cancel dice, not the extra symbols printed on Rage cards.
        faces = [f.removeprefix('double_') for f in self.g.dice
                 for _ in range(2 if f.startswith('double_') else 1)]
        for f in self.u['wounds'][i]:
            if f != DYNAMITE and f in faces:
                faces.remove(f)
                self.log(f'🩹 {self.g.players[i].name} 的傷口抵消1個{FACE_LABELS[f]}骰面。')
        return faces + self.rage_faces()

    def resolve_whiskey(self, i, faces):
        g = self.g
        for _ in range(faces.count(WHISKEY) * (2 if self.char(i) == 'greg_digger' else 1)):
            self.log(f'🥃 {g.players[i].name} 使用威士忌。')
            yield from self.heal(i,1,i)
            wounds = self.u['wounds'][i]
            if wounds:
                if len(wounds) == 1:face = wounds[0]
                else:
                    face = yield from self.ask('whiskey_wound','威士忌：移除哪一枚傷口？',i,
                        [(('💣 炸藥傷口' if f == DYNAMITE else f'取消{FACE_LABELS[f]}的傷口'),f) for f in wounds],wounds[0])
                wounds.remove(face);self.u['wound_pool'].append(face);self.rng.shuffle(self.u['wound_pool'])
                self.log(f'🩹 {g.players[i].name} 的{FACE_LABELS[face]}傷口已移除。')
            else:yield from self.draw_rage(i)

    def resolve_duels(self, i, count):
        g = self.g;used = set()
        for _ in range(count):
            targets = [k for k in self.alive() if k != i and k not in used]
            if not targets:
                self.log('⚔️ 本回合所有可挑戰的對手都已決鬥，剩餘決鬥符號無目標。');break
            j = yield from self.ask('duel_target','決鬥：挑戰誰？同回合不能重複挑戰同一人。',i,
                [(g.players[k].name,k) for k in targets],targets[0])
            used.add(j)
            if self.char(i) == 'sam_the_healer':
                k = yield from self.ask('sam','山姆：使用決鬥符號，讓誰回復1血？',i,
                    [(g.players[k].name,k) for k in self.alive()],i)
                yield from self.heal(k,1,i)
            self.log(f'⚔️ {g.players[i].name} 挑戰 {g.players[j].name}！')
            mover = j;exchange = 0
            while g.players[i].alive and g.players[j].alive and g.phase != 'ended':
                exchange += 1
                self.u['duel'] = dict(challenger=i,opponent=j,mover=mover,exchange=exchange,face=None)
                yield from self.ask('duel_roll',
                    f'⚔️ {g.players[i].name} ↔ {g.players[j].name}\n第{exchange}次交鋒｜輪到{g.players[mover].name}擲決鬥骰',
                    mover,[('🎲 擲決鬥骰',True)],True)
                face = self.rng.choice(DUEL_FACES)
                shown=False
                if face != DUEL and mover == i and self.char(i) == 'sean_mallory' and not self.u['sean_used']:
                    self.u['duel']['face'] = face
                    self.u['duel_events'].append(dict(self.u['duel']));shown=True
                    retry = yield from self.ask('sean',f'尚恩：擲出{FACE_LABELS[face]}，要使用本回合1次重擲？',i,
                        [('🎲 使用能力，重擲決鬥骰',True),('接受失敗',False)],False)
                    if retry:
                        self.u['sean_used'] = True
                        self.log(f'🤠 {g.players[i].name}〔尚恩能力〕重擲決鬥骰。')
                        face = self.rng.choice(DUEL_FACES)
                        shown=False
                self.u['duel']['face'] = face
                if not shown:self.u['duel_events'].append(dict(self.u['duel']))
                if face == DUEL:
                    self.log(f'⚔️ {g.players[mover].name} 擲出決鬥，回擊成功！換{g.players[i if mover == j else j].name}。')
                    mover = i if mover == j else j
                else:
                    winner = i if mover == j else j
                    self.log(f'⚔️ {g.players[mover].name} 擲出{FACE_LABELS[face]}，決鬥失敗；其他骰面效果不生效。')
                    yield from self.damage([(mover,1)],winner,'duel')
                    if g.players[mover].alive and g.phase != 'ended':self.draw_wound(mover)
                    break
            self.u['duel'] = None
            if g.phase == 'ended' or not g.players[i].alive:return
