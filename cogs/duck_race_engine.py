"""Seeded automatic simulation and pixel renderer; no Discord dependency."""
from functools import lru_cache
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COLORS = ['#ffe066','#ff91af','#73cfff','#96e08b','#c7a0ff','#ffac63','#ffffff','#7ce2d2','#c3cf63','#b2b8d9']
NAMES = ['노랑꽥','딸기꽥','하늘꽥','풀잎꽥','보라꽥','귤꽥','눈꽃꽥','민트꽥','올리브꽥','먹구름꽥']
FPS = 12

def simulate(ducks, seed=None):
    if not 2 <= len(ducks) <= 10 or len(set(ducks)) != len(ducks):
        raise ValueError('서로 다른 오리 2~10마리가 필요합니다.')
    rng = random.Random(seed)
    pos = {d: 0.0 for d in ducks}
    finish = {}
    frames = []
    for tick in range(720):
        events = {}
        for d in ducks:
            if d in finish:
                continue
            speed = rng.uniform(0.22, 0.34)
            roll = rng.random()
            if roll < .018:
                speed *= 5
                events[d] = 'BOOST!'
            elif roll < .038:
                speed = 0
                events[d] = 'NAP...'
            old = pos[d]
            pos[d] = min(100, old + speed)
            if pos[d] >= 100:
                finish[d] = tick + (100-old)/speed
        frames.append((pos.copy(), events))
        if len(finish) == len(ducks):
            break
    if len(finish) != len(ducks):
        raise RuntimeError('경주 시간 초과')
    return frames, sorted(ducks, key=lambda d: (finish[d], d))

SPRITE = ['       XXXX   ','      XCCCCX  ','      XCCECXBB','   XXXCCCCXXBB','  XCCCCCCCX   ',' XCCCCCCCCX   ',' XCCCCCCCX    ','  XXXXXXX     ','   F   F      ']

@lru_cache(maxsize=16)
def font(size):
    path = Path(__file__).resolve().parent / 'duck_race_assets/fonts/NanumGothic-Regular.ttf'
    return ImageFont.truetype(str(path), size)

def fit_name(name, max_width, size):
    name = ' '.join(str(name).split()) or '이름 없음'
    f = font(size)
    if f.getlength(name) <= max_width:
        return name
    while name and f.getlength(name + '…') > max_width:
        name = name[:-1]
    return name + '…'

def draw_frame(ducks, positions, events, tick, labels=None, native=False):
    labels = labels or {}
    im = Image.new('RGB', (480, 300), '#19352e')
    dr = ImageDraw.Draw(im)
    dr.text((12, 8), 'QUACK GRAND PRIX  /  AUTO RACE', fill='#ffe066')
    dr.text((12, 24), f'{tick/FPS:04.1f}s    BOOST / NAP', fill='white')
    lane = 23
    for i, d in enumerate(ducks):
        y = 48+i*lane
        dr.rectangle((5,y,474,y+lane-2), fill=('#4b9e58' if i%2==0 else '#448f50'))
        dr.rectangle((5,y,105,y+lane-2), fill='#244a40')
        dr.text((8,y+5), fit_name(labels.get(d, f'오리 {d+1:02}'), 94, 12), fill='white', font=font(12))
        for xx in range(442,454,6):
            for yy in range(y,y+lane-2,6):
                dr.rectangle((xx,yy,xx+5,yy+5), fill='white' if (xx//6+yy//6)%2 else '#152326')
        x = 110+int(positions[d]*3.16)
        bob = (tick//3+i)%2 if positions[d]<100 else 0
        palette={'X':'#172834','C':COLORS[d],'E':'#111111','B':'#ff8c33','F':'#ff8c33'}
        for sy,row in enumerate(SPRITE):
            for sx,c in enumerate(row):
                if c in palette:
                    dr.rectangle((x+sx,y+5+sy-bob,x+sx,y+5+sy-bob),fill=palette[c])
        if d in events:
            dr.text((min(x,380),y),events[d],fill='#ffe066')
    return im if native else im.resize((960,600), Image.Resampling.NEAREST)

def render(ducks, frames, order, output, labels=None):
    """Low-memory GIF: fixed palette, 480x300, 8 fps, no FFmpeg process."""
    labels = labels or {}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # A fixed palette avoids buffering full RGB frames in FFmpeg's palette filter.
    colors = COLORS + ['#19352e','#ffe066','#ffffff','#4b9e58','#448f50',
                       '#244a40','#152326','#172834','#111111','#ff8c33']
    rgb = []
    for color in colors:
        rgb.extend(bytes.fromhex(color[1:]))
    palette = Image.new('P',(1,1))
    palette.putpalette(rgb + [0]*(768-len(rgb)))
    images = []
    started = time.monotonic()
    try:
        count = 27 * 8
        for i in range(count):
            if time.monotonic()-started > 90:
                raise TimeoutError('GIF 생성이 90초를 초과했습니다.')
            positions, events = frames[round(i*(len(frames)-1)/(count-1))]
            image = draw_frame(ducks, positions, events, round(i*FPS/8), labels, native=True)
            images.append(image.quantize(palette=palette,dither=Image.Dither.NONE))
            image.close()
        final = draw_frame(ducks,frames[-1][0],{},27*FPS,labels,native=True)
        dr = ImageDraw.Draw(final)
        dr.rectangle((95,32,385,283),fill='#172834',outline='#ffe066',width=2)
        winner = fit_name(labels.get(order[0],f'오리 {order[0]+1:02}'),215,14)
        dr.text((110,44),f'우승 · {winner}',fill='#ffe066',font=font(14))
        for rank,duck in enumerate(order,1):
            label=fit_name(labels.get(duck,f'오리 {duck+1:02}'),220,12)
            dr.text((112,72+(rank-1)*19),f'{rank}위 · {label}',fill=COLORS[duck],font=font(12))
        images.append(final.quantize(palette=palette,dither=Image.Dither.NONE))
        final.close()
        # GIF delay uses 10ms units: alternating 120/130ms = 8fps exactly.
        durations = [120 if i%2==0 else 130 for i in range(count)] + [3000]
        images[0].save(output,save_all=True,append_images=images[1:],
                       duration=durations,loop=0,optimize=False,disposal=1)
        return output
    finally:
        for image in images:
            image.close()
        palette.close()
