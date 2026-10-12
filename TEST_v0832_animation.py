"""Animation fidelity and Telegram fallback checks; no network."""
from io import BytesIO
from PIL import Image,ImageChops
from saloon_dice_animation import frames,dice_animation,TOTAL_SECONDS
import asyncio,types,hashlib
import saloon_bot as sb
from telegram.error import BadRequest

for kinds,faces in [
 (('base','base'),('arrow','dynamite')),
 (('loudmouth',)+('base',)*4,('double_gatling','beer','arrow','bull1','bull2')),
 (('coward',)+('base',)*5,('double_beer','beer','arrow','bull1','bull2','gatling')),
]:
 moving=(0,);seq=list(frames(kinds,moving,faces));still=list(frames(kinds,(),faces))[-1]
 assert ImageChops.difference(seq[-1],still).getbbox() is None,'Final result differs from actual dice'
 spacing={2:144,5:144,6:130}[len(kinds)]
 for i in range(1,len(kinds)):
  cx=450+(i-(len(kinds)-1)/2)*spacing
  box=(int(cx-33),159,int(cx+33),226)
  reference=seq[-1].crop(box)
  assert all(ImageChops.difference(im.crop(box),reference).getbbox() is None for im in seq),'Unselected die moved'
 raw=dice_animation(kinds,moving,faces);im=Image.open(BytesIO(raw));duration=0
 for i in range(im.n_frames):im.seek(i);duration+=im.info['duration']
 assert duration==int(TOTAL_SECONDS*1000)
 assert len(raw)<3_000_000
print('PASS 2/5/6 dice, fixed unselected dice, true final results, duration and upload size')

async def check():
 original=sb.dice_animation;original_sleep=sb.asyncio.sleep
 sb.dice_animation=lambda *args:b'GIF89a-test'
 async def nosleep(n):pass
 sb.asyncio.sleep=nosleep
 calls=[]
 class Bot:
  async def send_animation(self,**kwargs):
   calls.append(kwargs['animation'])
   if isinstance(kwargs['animation'],str):raise BadRequest('wrong file identifier')
   return types.SimpleNamespace(message_id=7,animation=types.SimpleNamespace(file_id='fresh-id'))
 class App:
  def create_task(self,coro):coro.close()
 async def delete(*args):pass
 runner=types.SimpleNamespace(last_moving=(0,),turn=1,roll_history=[('arrow',)])
 game=types.SimpleNamespace(saloon_runtime=runner,dice=['arrow','beer'],dice_types=[types.SimpleNamespace(kind='base')]*2,chat_id=1)
 key=hashlib.sha256(b'GIF89a-test').hexdigest()
 ctx=types.SimpleNamespace(bot=Bot(),bot_data={'saloon_flat_animation_ids':{key:'expired-id'}},application=App())
 b=types.SimpleNamespace(_delete_message_later=delete,log=types.SimpleNamespace(warning=lambda *a:None))
 try:
  await sb.animate(ctx,game,b)
  assert len(calls)==2 and ctx.bot_data['saloon_flat_animation_ids'][key]=='fresh-id'
  await sb.animate(ctx,game,b)
  assert len(calls)==2,'same roll uploaded twice'
 finally:sb.dice_animation=original;sb.asyncio.sleep=original_sleep
 print('PASS expired Telegram file_id fallback and duplicate-roll suppression')
asyncio.run(check())
