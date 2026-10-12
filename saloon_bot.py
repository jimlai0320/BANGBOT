"""Telegram adapter for the interruptible expansion runner."""
import asyncio
import time
import hashlib
from io import BytesIO
from pathlib import Path
from saloon_dice_animation import dice_animation, TOTAL_SECONDS
from telegram.error import BadRequest
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, InputFile
from saloon_runtime import SaloonRuntime, ROLE_POWERS, SPECIAL
from data import DICE_FACES, FACE_LABELS, ROLE_CN
from undead_runtime import RAGE_CARDS, symbols_text


def runtime(g):return getattr(g,'saloon_runtime',None)
def label(v):return FACE_LABELS.get(v,{'double_bull1':'🎯1×2','double_bull2':'🎯2×2','double_beer':'🍺×2','double_gatling':'🔫×2','bullet':'🔫 自傷','broken_arrow':'🏹 斷箭'}.get(v,v))


PLAYER_CHOICES = {
    'shot': '🎯', 'heal': '🍺', 'sid': '💚',
    'swap_first': '🏹', 'swap_second': '🏹', 'elena': '🏹',
    'broken': '🏹', 'kit': '🏹', 'ghost_target': '👻',
    'duel_target': '⚔️', 'sam': '💚', 'pat_source': '🔥', 'pat_target': '🔥',
}


def player_status(g, i, name_limit=16):
    p = g.players[i]
    name = p.name if len(p.name) <= name_limit else p.name[:name_limit-1] + '…'
    if p.is_ghost:
        return f'{name} 👻 鬼魂'
    if not p.alive:
        return f'{name} 💀 已淘汰'
    return f'{name} ❤️{max(0, p.hp)}/{p.max_hp}'


def keyboard(g,common):
    r=runtime(g);q=r.prompt if r else None
    if not q:return Markup(common)
    common=[[button for button in row if not (button.callback_data or '').startswith('special:')] for row in common]
    common=[row for row in common if row]
    rows=[]
    prefix=f'x:{r.token}:{q.serial}:'
    if q.kind=='reaction':
        rows=[[Button('⚡ 我要發動技能（10秒）',callback_data=prefix+'claim')]]
    elif q.kind=='roll':
        if g.current_player().is_ghost:
            # Only two dice: direct legal masks avoid the select-then-roll step.
            for k, (text, mask) in enumerate(q.options):
                title = ('✅ 確定結果' if mask == 0 else
                         '🎲 兩顆一起重擲' if mask == 3 else
                         f'🎲 重擲第{1 if mask == 1 else 2}顆')
                rows.append([Button(title, callback_data=prefix+str(k))])
        else:
            rows=[[Button(('✅ ' if k in r.selected else '')+f'{k+1} {label(f)}',callback_data=prefix+f't{k}') for k,f in enumerate(g.dice)][a:a+3] for a in range(0,len(g.dice),3)]
            rows.append([Button('🎲 重擲選取',callback_data=prefix+'reroll'),Button('確定結果',callback_data=prefix+'stop')])
    elif q.kind in PLAYER_CHOICES:
        # Full-width targets keep current HP readable even on narrow phones.
        for k, (text, value) in enumerate(q.options):
            title = (f'{PLAYER_CHOICES[q.kind]} {player_status(g, value)}'
                     if type(value) is int and 0 <= value < len(g.players)
                     else str(label(text)))
            if q.kind in ('broken', 'kit', 'swap_first', 'swap_second', 'elena') and type(value) is int and 0 <= value < len(g.players):
                title += f'｜普通箭 {g.players[value].arrows}'
                if g.chief_arrow_owner == value:
                    title += '＋酋長箭'
            rows.append([Button(title, callback_data=prefix+str(k))])
    elif q.kind in ('bart', 'pedro', 'molly', 'slab', 'doc_die','duel_roll','sean','sean_die','belle','chuck_die','chuck_face','pixie'):
        rows = [[Button(str(label(text)), callback_data=prefix+str(k))]
                for k, (text, value) in enumerate(q.options)]
    else:
        for at in range(0,len(q.options),2):
            rows.append([Button(str(label(text))[:50],callback_data=prefix+str(k)) for k,(text,v) in enumerate(q.options[at:at+2],at)])
    # One fixed entry remains available; outside a reaction it only answers privately.
    if q.kind!='reaction' and g.expansion_config.enabled('special_roles'):
        rows.append([Button('⚡ 特殊技能',callback_data=prefix+'claim')])
    if g.expansion_config.enabled('rage') or g.expansion_config.enabled('duel_dice'):
        title='🔎 查看候選牌（只有本人可看）' if q.kind=='pixie' else '🔥 我的憤怒卡／傷口'
        rows.append([Button(title,callback_data=prefix+'peek')])
    rows += common
    return Markup(rows)


def caption(g):
    r=runtime(g);q=r.prompt if r else None
    if not q:return g.winner_text or '正在準備回合…'
    current=g.current_player()
    text=f'🤠 {current.name}'+(' 👻 鬼魂' if current.is_ghost else f'｜{current.character.cn}')
    text+='\n'+q.text
    if getattr(q,'timeout_warning',False):
        text+='\n⏰ 剩餘10秒，未操作將採用預設選項。'
    if g.dice and not current.is_ghost and q.kind in ('reaction', 'roll'):
        bombs = r.dynamite_count()
        if bombs:
            text += f'\n💣 炸藥 {bombs}/3' + ('｜已達爆炸數量，等待結算' if bombs >= 3 else '｜累積3顆會停止重擲並處理1點傷害')
    if q.kind != 'reaction' and r.selection_owner in q.owners:
        text += '\n⏳ 技能選擇共20秒，請完成下方選項。'
    if q.kind == 'roll' and current.is_ghost:
        text += f'\n👻 第 {g.roll_no}/3 次擲骰｜直接按下方重擲按鈕'
        text += '\n' + '　'.join(f'{k+1}：{label(f)}' + (' 🔒' if f == 'dynamite' else '') for k, f in enumerate(g.dice))
        text += '\n🔒 炸藥不能重擲。'
    if q.kind!='reaction':text+='\n等待：'+'、'.join(g.players[i].name for i in q.owners)
    public=[f'{p.name}：{ROLE_CN[p.role]}' for p in g.players if p.role_revealed]
    if public:text+='\n🎭 '+'｜'.join(public)
    if g.ghost_state:
        t=g.ghost_state;text+=f"\n👻 {g.players[t['target']].name} 下回合：{label(t['face'])}×{t['count']}"
    if r.u['active']:
        text+='\n🔥 本回合憤怒加成：'+symbols_text(r.rage_faces())
    if g.log:text+='\n\n'+'\n'.join(g.log[-4:])
    # Telegram's caption limit is measured in UTF-16 units (emoji use two).
    return text.encode('utf-16-le')[:2000].decode('utf-16-le', errors='ignore')


_ANIMATION_RENDER_SLOTS = asyncio.Semaphore(2)


async def animate(ctx,g,b):
    r=runtime(g)
    if not r or not g.dice or not r.last_moving:return
    signature=(r.turn,len(r.roll_history))
    if getattr(r,'animated',None)==signature:return
    kinds=tuple(d.kind for d in g.dice_types)
    faces=tuple(g.dice);moving=tuple(r.last_moving)
    try:
        async with _ANIMATION_RENDER_SLOTS:
            raw=await asyncio.to_thread(dice_animation,kinds,moving,faces)
        key=hashlib.sha256(raw).hexdigest()
        cache=ctx.bot_data.setdefault('saloon_flat_animation_ids',{})
        cached=cache.get(key)
        async def send(value):
            return await ctx.bot.send_animation(chat_id=g.chat_id,animation=value,
                caption='🎲 擲骰中…',disable_notification=True,
                read_timeout=15,write_timeout=20,connect_timeout=10,pool_timeout=10)
        try:
            msg=await send(cached or InputFile(BytesIO(raw),filename='saloon_flat_roll.gif'))
        except BadRequest:
            if not cached:raise
            cache.pop(key,None)
            msg=await send(InputFile(BytesIO(raw),filename='saloon_flat_roll.gif'))
        if getattr(msg,'animation',None):cache[key]=msg.animation.file_id
        while len(cache)>96:cache.pop(next(iter(cache)))
        r.animated=signature
        ctx.application.create_task(b._delete_message_later(ctx,g.chat_id,msg.message_id,TOTAL_SECONDS+.8))
        # Let the landing finish before a 3-second skill window starts.
        await asyncio.sleep(TOTAL_SECONDS)
    except Exception as exc:
        b.log.warning('擴充骰動畫略過：%s',exc)


async def show_rage_reveals(ctx,g,b):
    r=runtime(g)
    if not r or r.pending_roll_transaction:return
    from renderer import render_rage_reveal
    events=r.u.pop('rage_reveals',[])
    for event in events:
        try:
            msg=await ctx.bot.send_photo(chat_id=g.chat_id,
                photo=InputFile(render_rage_reveal(event['cards']),filename='rage_reveal.jpg'),
                caption=f"🔥 {g.players[event['player']].name} 翻開 {len(event['cards'])} 張狂怒卡",disable_notification=True)
            ctx.application.create_task(b._delete_message_later(ctx,g.chat_id,msg.message_id,10))
        except Exception as exc:
            b.log.warning('狂怒卡大圖略過：%s',type(exc).__name__)


async def drive(ctx,g,b):
    r=runtime(g)
    if r is None:r=SaloonRuntime(g);r.step()
    count=0
    while r.prompt and count<300:
        q=r.prompt
        # AI decisions never wait for a timer. Mixed human/AI reaction windows
        # are exposed to humans first; AI may claim after the same 3 seconds.
        if any(not g.players[i].is_ai for i in q.owners):break
        val=r.ai_value(q);r.selected.clear();r.step(val);count+=1
    await animate(ctx,g,b)
    await animate_duels(ctx,g,b)
    await show_rage_reveals(ctx,g,b)
    if r.prompt and r.prompt.kind=='pixie' and not getattr(r.prompt,'private_sent',False):
        q=r.prompt;q.private_sent=True
        text='🔥 皮克西候選牌（請回群組選A或B）\n'+ '\n'.join(
            f'{chr(65+k)}：{symbols_text(RAGE_CARDS[c])}' for k,c in enumerate(q.payload['secret_cards']))
        for i in q.owners:
            if not g.players[i].is_ai:
                try:await ctx.bot.send_message(chat_id=g.players[i].pid,text=text,disable_notification=True)
                except Exception as exc:b.log.warning('候選憤怒卡私訊略過：%s',type(exc).__name__)
    if not r.pending_roll_transaction:
        if g.indian_attacks>getattr(r,'shown_attacks',0):
            await b.show_indian_arrow_animation(ctx,g)
            r.shown_attacks=g.indian_attacks
        gatlings=sum('發動格林機槍' in line for line in r.trace)
        if gatlings>getattr(r,'shown_gatlings',0):
            await b.show_gatling_animation(ctx,g,g.current_player().name)
            r.shown_gatlings=gatlings
    await b.update_board(ctx,g)
    if count>=300 and r.prompt and all(g.players[i].is_ai for i in r.prompt.owners):
        ctx.application.create_task(resume_ai(ctx,g,b))


async def resume_ai(ctx,g,b):
    await asyncio.sleep(0.05)
    async with b.chat_lock(g.chat_id):
        if b.GAMES.get(g.chat_id) is g:await drive(ctx,g,b)


def schedule(ctx,g,b):
    r=runtime(g);q=r.prompt if r else None
    if not q or getattr(q,'scheduled',False):return
    # Called only after update_board successfully displayed the prompt.
    r.arm();q.scheduled=True
    ctx.application.create_task(expire(ctx,g,b,r,q))


async def expire(ctx,g,b,r,q):
    while True:
        warn=q.seconds>=30 and q.kind!='reaction' and not getattr(q,'timeout_warning',False)
        await asyncio.sleep(max(0,q.deadline-time.monotonic()-(10 if warn else 0)))
        async with b.chat_lock(g.chat_id):
            if b.GAMES.get(g.chat_id) is not g or runtime(g) is not r or r.prompt is not q:return
            remaining=q.deadline-time.monotonic()
            # A valid dice selection renews the idle deadline. Old wakeups
            # must re-check it under the same lock as callbacks.
            if remaining>0:
                if warn and remaining<=10:
                    q.timeout_warning=True
                    await b.update_board(ctx,g)
                continue
            if q.kind=='reaction':
                ai=[i for i in q.owners if g.players[i].is_ai]
                original=q.owners;q.owners=ai
                val=r.ai_value(q) if ai else None
                q.owners=original;r.step(val)
            else:r.timeout(q.serial)
            r.selected.clear()
            await drive(ctx,g,b)
            return


async def callback(update,ctx,g,b):
    q=update.callback_query;r=runtime(g)
    if not r:return False
    data=q.data or ''
    if data.startswith('info:') or data.startswith('browse:'):return False
    if data.startswith('special:'):
        await q.answer('請使用最新牌桌的特殊技能按鈕。',show_alert=True);return True
    if not data.startswith('x:'):
        await q.answer('請使用目前牌桌的按鈕。',show_alert=True);return True
    try:
        _,token,serial,action=data.split(':',3);serial=int(serial)
        prompt=r.prompt
        idx=next((i for i,p in enumerate(g.players) if not p.is_ai and p.pid==q.from_user.id),None)
        if token!=r.token or prompt is None or serial!=prompt.serial:raise ValueError('舊牌桌選項已過期')
        if action=='peek':
            if idx is None:raise ValueError('你不是本局玩家')
            lines=[]
            if prompt.kind=='pixie' and idx in prompt.owners:
                lines.append('候選牌：')
                lines.extend(f'{chr(65+k)}：{symbols_text(RAGE_CARDS[c])}' for k,c in enumerate(prompt.payload['secret_cards']))
            cards=r.u['held'][idx]
            lines.append('憤怒卡：'+('；'.join(symbols_text(RAGE_CARDS[c]) for c in cards) if cards else '目前沒有'))
            wounds=r.u['wounds'][idx]
            lines.append('傷口：'+('、'.join('炸藥+1' if f=='dynamite' else f'取消1個{label(f)}' for f in wounds) if wounds else '目前沒有'))
            text='\n'.join(lines)
            if len(text)>180:
                try:await ctx.bot.send_message(chat_id=g.players[idx].pid,text=text,disable_notification=True)
                except Exception:pass
                await q.answer(text[:175]+'…',show_alert=True)
            else:await q.answer(text,show_alert=True)
            return True
        if action=='claim':
            if prompt.kind!='reaction':raise ValueError('目前不是技能發動窗口；可發動時會出現「我要發動技能」按鈕，保留10秒。')
            if idx not in prompt.owners:raise ValueError('你的特殊身分不符合這次發動時機，或能力已使用。')
        if idx not in prompt.owners:raise ValueError('現在不是你的選擇')
        if prompt.deadline is None or time.monotonic()>=prompt.deadline:raise ValueError('選擇時間已結束')
        if action=='claim':r.claim(serial,idx)
        elif action.startswith('t') and prompt.kind=='roll':
            k=int(action[1:]);mask=1<<k
            if mask not in [v for _,v in prompt.options]:raise ValueError('這顆骰子不能重擲')
            if k in r.selected:r.selected.remove(k)
            else:r.selected.add(k)
            prompt.deadline=time.monotonic()+prompt.seconds
            prompt.timeout_warning=False
            await q.answer('已選擇，操作時間重新計算')
            await q.edit_message_caption(caption=caption(g),reply_markup=keyboard(g,b.common_info_rows(g)));return True
        elif action in ('stop','reroll') and prompt.kind=='roll':
            mask=sum(1<<k for k in r.selected) if action=='reroll' else 0
            if action=='reroll' and not mask:raise ValueError('請先選擇要重擲的骰子')
            r.answer(serial,idx,mask)
        else:
            option=int(action)
            if option<0 or option>=len(prompt.options):raise ValueError('選項無效')
            r.answer(serial,idx,prompt.options[option][1])
        r.selected.clear()
    except (ValueError,IndexError) as exc:
        await q.answer(str(exc)[:180],show_alert=True);return True
    await q.answer('✅ 已選擇')
    await drive(ctx,g,b)
    return True


async def animate_duels(ctx,g,b):
    r=runtime(g)
    if not r:return
    # A busy AI stretch is summarized by its last exchanges; the full rule
    # history is retained in runtime.trace. Human exchanges render one by one.
    events=list(r.u['duel_events']);r.u['duel_events'].clear()
    for event in events[-6:]:
        try:
            async with _ANIMATION_RENDER_SLOTS:
                raw=await asyncio.to_thread(dice_animation,('duel',),(0,),(event['face'],))
            who=g.players[event['mover']].name
            msg=await ctx.bot.send_animation(chat_id=g.chat_id,
                animation=InputFile(BytesIO(raw),filename='duel_roll.gif'),
                caption=f'⚔️ {who}：{label(event["face"])}'+('｜回擊成功！' if event['face']=='duel' else '｜決鬥失敗'),
                disable_notification=True,read_timeout=15,write_timeout=20)
            ctx.application.create_task(b._delete_message_later(ctx,g.chat_id,msg.message_id,TOTAL_SECONDS+1.5))
            await asyncio.sleep(TOTAL_SECONDS)
        except Exception as exc:b.log.warning('決鬥骰動畫略過：%s',type(exc).__name__)
