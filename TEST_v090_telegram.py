"""Actual adapter callbacks and caption/keyboard secrecy, without Telegram I/O."""
import asyncio,time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from TEST_v090_undead import new,Sequence
from data import DUEL,GATLING
import saloon_bot as sb

async def main():
 g,r=new()
 for i,p in enumerate(g.players):p.is_ai=False;p.pid=100+i
 r.rng=Sequence([DUEL,GATLING]);r.gen=r.resolve_duels(0,1);r.step();r.step(1);r.arm()
 q=r.prompt
 rows=sb.keyboard(g,[]).inline_keyboard
 assert rows[0][0].text=='🎲 擲決鬥骰'
 assert '等待：'+g.players[1].name in sb.caption(g)
 b=SimpleNamespace(common_info_rows=lambda g:[])
 old_drive=sb.drive;sb.drive=AsyncMock()
 def click(idx,serial):
  return SimpleNamespace(callback_query=SimpleNamespace(data=f'x:{r.token}:{serial}:0',from_user=SimpleNamespace(id=100+idx),answer=AsyncMock()))
 upd=click(0,q.serial);await sb.callback(upd,SimpleNamespace(),g,b)
 assert '現在不是你的選擇' in upd.callback_query.answer.call_args.args[0]
 assert r.prompt is q
 upd=click(1,q.serial);await sb.callback(upd,SimpleNamespace(),g,b)
 assert r.prompt.owners==[0] and g.players[0].hp==8
 upd=click(1,q.serial);await sb.callback(upd,SimpleNamespace(),g,b)
 assert '舊牌桌選項已過期' in upd.callback_query.answer.call_args.args[0]
 r.arm();upd=click(0,r.prompt.serial);await sb.callback(upd,SimpleNamespace(),g,b)
 assert g.players[0].hp==7 and r.done
 # Pixie's card faces stay out of public captions and button text.
 g,r=new();g.players[0].character_key='pixie_pete';g.players[0].pid=100;g.players[0].is_ai=False
 r.gen=r.draw_rage(0);r.step();r.arm()
 assert '準心' not in sb.caption(g)
 assert all('準心' not in b.text for row in sb.keyboard(g,[]).inline_keyboard for b in row)
 upd=SimpleNamespace(callback_query=SimpleNamespace(data=f'x:{r.token}:{r.prompt.serial}:peek',from_user=SimpleNamespace(id=100),answer=AsyncMock()))
 await sb.callback(upd,SimpleNamespace(),g,b)
 assert '候選牌' in upd.callback_query.answer.call_args.args[0]
 assert r.prompt.kind=='pixie'
 sb.drive=old_drive
 print('PASS real callbacks: alternating owners, wrong player, stale/double click, private Rage inspection and public secrecy')

asyncio.run(main())
