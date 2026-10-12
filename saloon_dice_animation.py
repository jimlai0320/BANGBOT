"""Flat dice wobble on the original wooden tray, using existing face artwork."""
from functools import lru_cache
from pathlib import Path
from io import BytesIO
import math
from PIL import Image
from data import DICE_FACES, DUEL_FACES

ROOT = Path(__file__).resolve().parent / 'assets'
FACES = {
    'base': tuple(DICE_FACES),
    'loudmouth': ('arrow','bullet','double_bull1','double_bull2','dynamite','double_gatling'),
    'coward': ('arrow','broken_arrow','bull1','bull2','beer','double_beer'),
    'duel': tuple(DUEL_FACES),
}
WIDTH, HEIGHT = 900, 318
FRAME_COUNT, FRAME_MS, HOLD_MS = 18, 40, 200
TOTAL_SECONDS = ((FRAME_COUNT - 1) * FRAME_MS + HOLD_MS) / 1000

@lru_cache(maxsize=24)
def texture(kind, face):
    path = (ROOT/'dice'/f'dice_{face}.png' if kind == 'base' else
            ROOT/'undead'/'dice'/kind/f'{face}.png' if kind == 'duel' else
            ROOT/'old_saloon'/'dice'/kind/f'{face}.png')
    im = Image.open(path).convert('RGBA')
    bbox = im.getbbox()
    im = im.crop(bbox) if bbox else im
    im.thumbnail((160,160), Image.Resampling.LANCZOS)
    return im

@lru_cache(maxsize=1)
def tray():
    return Image.open(ROOT/'animations'/'dice_tray_bg.png').convert('RGBA').resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)

def frames(kinds, moving, faces):
    if len(kinds) not in (1,2,5,6) or len(kinds) != len(faces):raise ValueError('Expected 1, 2, 5 or 6 dice')
    if any(k not in FACES or f not in FACES[k] for k,f in zip(kinds,faces)):raise ValueError('Invalid die face')
    if any(i < 0 or i >= len(kinds) for i in moving):raise ValueError('Invalid moving die')
    size = 112 if len(kinds) == 6 else 126
    gap = 18
    left = (WIDTH - (len(kinds)*size + (len(kinds)-1)*gap)) / 2
    for at in range(FRAME_COUNT):
        im = tray().copy()
        for i, kind in enumerate(kinds):
            active = i in moving and at < FRAME_COUNT - 1
            face = FACES[kind][(at//2+i*2)%6] if active else faces[i]
            die = texture(kind,face).copy()
            die.thumbnail((size,size), Image.Resampling.LANCZOS)
            angle = math.sin(at*1.35+i)*16*(1-at/FRAME_COUNT) if active else 0
            die = die.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
            dx = math.sin(at*1.8+i)*3 if active else 0
            dy = math.cos(at*1.5+i)*4 if active else 0
            x = round(left+i*(size+gap)+size/2-die.width/2+dx)
            y = round(HEIGHT/2-die.height/2+dy)
            im.alpha_composite(die,(x,y))
        yield im.convert('RGB')

@lru_cache(maxsize=8)
def dice_animation(kinds, moving, faces):
    images = list(frames(kinds,moving,faces))
    palette = images[-1].quantize(colors=192)
    images = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    out = BytesIO()
    images[0].save(out,format='GIF',save_all=True,append_images=images[1:],
                   duration=[FRAME_MS]*(FRAME_COUNT-1)+[HOLD_MS],loop=0,disposal=1)
    return out.getvalue()
