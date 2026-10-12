from __future__ import annotations

from io import BytesIO
from pathlib import Path
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

from data import (
    ARROW, DYNAMITE, BULL1, BULL2, BEER, GATLING,
    FACE_LABELS, CHARACTERS, ROLE_CN,
)
from game_engine import Game, valid_targets_for_face, format_hit, format_action

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

DICE_FILES = {
    BULL1: ASSETS / "dice" / "dice_bull1.png",
    BULL2: ASSETS / "dice" / "dice_bull2.png",
    BEER: ASSETS / "dice" / "dice_beer.png",
    ARROW: ASSETS / "dice" / "dice_arrow.png",
    GATLING: ASSETS / "dice" / "dice_gatling.png",
    DYNAMITE: ASSETS / "dice" / "dice_dynamite.png",
}

HEART_ICON = ASSETS / "icons" / "heart.png"
ARROW_ICON = ASSETS / "icons" / "arrow_token.png"
SHERIFF_BADGE = ASSETS / "icons" / "sheriff_badge.png"
DEAD_ICON = ASSETS / "icons" / "dead.png"
ARROW_RACK = ASSETS / "ui" / "arrow_pool.png"

# 每個人數都獨立校正。panel=(資訊牌中心 x,y)，avatar_box=(角色半身最大寬,高)
# 角色永遠以 panel.x 為水平中心，底部壓在資訊牌上緣後方。
# 這樣 3～8 人不會共用同一套座標硬縮放。
LAYOUTS = {
    # 路線 B：背景不預畫玩家框。每個人數獨立控制「半身角色 + 動態牌子」。
    # v0.5.2：僅再外擴 3~6 人；7~8 人維持剛好的版本。
    3: {
        "seats": [
            {"panel": (724, 300), "avatar_box": (320, 245)},
            {"panel": (270, 730), "avatar_box": (315, 235)},
            {"panel": (1178, 730), "avatar_box": (315, 235)},
        ],
        "panel_size": (305, 94),
        "center": (724, 360),
        "arrow_pool": (724, 505, 570, 190),
        "dice_y": 760,
        "dice_size": 88,
    },
    4: {
        "seats": [
            {"panel": (340, 270), "avatar_box": (290, 220)},
            {"panel": (1108, 270), "avatar_box": (290, 220)},
            {"panel": (320, 728), "avatar_box": (282, 212)},
            {"panel": (1128, 728), "avatar_box": (282, 212)},
        ],
        "panel_size": (292, 92),
        "center": (724, 362),
        "arrow_pool": (724, 505, 560, 186),
        "dice_y": 762,
        "dice_size": 86,
    },
    5: {
        "seats": [
            {"panel": (724, 250), "avatar_box": (265, 205)},
            {"panel": (210, 345), "avatar_box": (255, 198)},
            {"panel": (1238, 345), "avatar_box": (255, 198)},
            {"panel": (330, 735), "avatar_box": (242, 186)},
            {"panel": (1118, 735), "avatar_box": (242, 186)},
        ],
        "panel_size": (280, 88),
        "center": (724, 355),
        "arrow_pool": (724, 500, 545, 181),
        "dice_y": 766,
        "dice_size": 82,
    },
    6: {
        "seats": [
            {"panel": (345, 235), "avatar_box": (238, 186)},
            {"panel": (1103, 235), "avatar_box": (238, 186)},
            {"panel": (165, 492), "avatar_box": (230, 180)},
            {"panel": (1283, 492), "avatar_box": (230, 180)},
            {"panel": (345, 730), "avatar_box": (220, 168)},
            {"panel": (1103, 730), "avatar_box": (220, 168)},
        ],
        "panel_size": (270, 86),
        "center": (724, 352),
        "arrow_pool": (724, 498, 535, 178),
        "dice_y": 770,
        "dice_size": 80,
    },
    7: {
        "seats": [
            {"panel": (724, 182), "avatar_box": (214, 165)},
            {"panel": (320, 285), "avatar_box": (208, 160)},
            {"panel": (1128, 285), "avatar_box": (208, 160)},
            {"panel": (165, 485), "avatar_box": (200, 156)},
            {"panel": (1283, 485), "avatar_box": (200, 156)},
            {"panel": (390, 712), "avatar_box": (188, 144)},
            {"panel": (1058, 712), "avatar_box": (188, 144)},
        ],
        "panel_size": (248, 82),
        "center": (724, 350),
        "arrow_pool": (724, 492, 520, 173),
        "dice_y": 775,
        "dice_size": 77,
    },
    8: {
        "seats": [
            {"panel": (410, 205), "avatar_box": (192, 152)},
            {"panel": (1038, 205), "avatar_box": (192, 152)},
            {"panel": (150, 360), "avatar_box": (186, 147)},
            {"panel": (1298, 360), "avatar_box": (186, 147)},
            {"panel": (150, 570), "avatar_box": (180, 142)},
            {"panel": (1298, 570), "avatar_box": (180, 142)},
            {"panel": (410, 720), "avatar_box": (172, 135)},
            {"panel": (1038, 720), "avatar_box": (172, 135)},
        ],
        "panel_size": (232, 80),
        "center": (724, 345),
        "arrow_pool": (724, 487, 500, 166),
        "dice_y": 780,
        "dice_size": 74,
    },
}


# 不更動 v0.5.6 已定案的任何座位座標或大小，只把玩家順序
# 排進這些固定座位，確保座位視覺順序 = 順時針遊玩及射程順序。
# 表示第 i 位玩家實際使用 LAYOUTS[n]["seats"] 的哪個座位。
CLOCKWISE_SEATS = {
    3: (0, 2, 1),
    4: (0, 1, 3, 2),
    5: (0, 2, 4, 3, 1),
    6: (0, 1, 3, 5, 4, 2),
    7: (0, 2, 4, 6, 5, 3, 1),
    8: (0, 1, 3, 5, 7, 6, 4, 2),
}

def _aimable_indices(game: Game) -> set[int]:
    action = game.pending_action
    if game.phase not in {"resolving", "saloon_input"} or not action or action.get("type") != "shot":
        return set()
    return set(valid_targets_for_face(game, game.current_idx, action["face"]))



@lru_cache(maxsize=128)
def _find_font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        str(ASSETS / "fonts" / "NotoSansCJKtc-Regular.otf"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


FONT_SMALL = _find_font(22, False)
FONT_SMALL_BOLD = _find_font(22, True)
FONT_MED = _find_font(28, True)
FONT_BIG = _find_font(36, True)


def _text_center(draw, xy, text, font, fill=(25, 14, 8), stroke_width=0, stroke_fill=None):
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    w = box[2] - box[0]
    h = box[3] - box[1]
    draw.text(
        (xy[0] - w / 2, xy[1] - h / 2),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def _label_center(draw, xy, text, font, **kwargs):
    """Center the actual glyph bounds inside compact badges."""
    stroke = kwargs.get("stroke_width", 0)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    draw.text((xy[0] - (left + right) / 2, xy[1] - (top + bottom) / 2),
              text, font=font, **kwargs)


def _fit_font(text: str, max_w: int, start_size: int, bold: bool = True, min_size: int = 13):
    size = start_size
    while size > min_size:
        f = _find_font(size, bold)
        box = f.getbbox(text)
        if box[2] - box[0] <= max_w:
            return f
        size -= 1
    return _find_font(min_size, bold)


@lru_cache(maxsize=64)
def _load_icon(path: Path, size: tuple[int, int]):
    if not path.exists():
        return None
    im = Image.open(path).convert("RGBA")
    bbox = (im.getchannel("A").point(lambda a: 255 if a > 32 else 0).getbbox()
            if path.name in ("chief_arrow_horizontal.png", "chief_arrow_tray.png", "arrow_token.png") else im.getbbox())
    if bbox:
        im = im.crop(bbox)
    if path.name == "arrow_token.png":
        # Compact diagonal status icon; pool arrows use _arrow_asset separately.
        im = im.rotate(45, resample=Image.Resampling.BICUBIC, expand=True)
    im.thumbnail(size, Image.Resampling.LANCZOS)
    return im


@lru_cache(maxsize=32)
def _avatar_source(character_key: str, char_cn: str):
    """每個角色只從硬碟讀一次，並先縮成桌面需要的合理母圖尺寸。"""
    path = ASSETS / "characters" / f"{character_key}_avatar.png"
    saloon_avatar = not path.exists()
    if saloon_avatar:path = ASSETS / "old_saloon" / "avatars" / f"{character_key}.png"
    if not path.exists():path = ASSETS / "undead" / "avatars" / f"{character_key}.png"
    if path.exists():
        im = Image.open(path).convert("RGBA")
        bbox = im.getbbox()
        if bbox:
            im = im.crop(bbox)
        # All supplied avatars are now waist-up, including Bill Noface.
        # 桌面最大只用到約 320x245；先縮母圖可大幅降低 RAM 與後續 resize 成本。
        im.thumbnail((380, 300), Image.Resampling.LANCZOS)
        return im

    size = 280
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(
        (4, 4, size - 4, size - 4), radius=22,
        fill=(58, 38, 24, 235), outline=(223, 172, 73, 255), width=5,
    )
    ch = char_cn[:1] if char_cn else "?"
    f = _find_font(80, True)
    _text_center(d, (size / 2, size / 2), ch, f, fill=(245, 228, 190))
    return im


@lru_cache(maxsize=128)
def _avatar_asset(character_key: str, char_cn: str, max_w: int, max_h: int):
    im = _avatar_source(character_key, char_cn).copy()
    im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    alpha = im.getchannel("A").filter(ImageFilter.GaussianBlur(7))
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 88))
    shadow.putalpha(alpha.point(lambda p: int(p * 0.42)))
    return im, shadow


@lru_cache(maxsize=8)
def _table_background(n: int):
    bg_path = ASSETS / "tables" / f"table_{n}.png"
    if bg_path.exists():
        return Image.open(bg_path).convert("RGBA")
    return Image.new("RGBA", (1448, 1086), (91, 54, 28, 255))


@lru_cache(maxsize=32)
def _dice_asset(face: str, size: int):
    p = DICE_FILES.get(face)
    if p and p.exists():
        di = Image.open(p).convert("RGBA")
        return ImageOps.fit(di, (size, size), method=Image.Resampling.LANCZOS)
    di = Image.new("RGBA", (size, size), (245, 225, 180, 255))
    dd = ImageDraw.Draw(di)
    _text_center(dd, (size / 2, size / 2), FACE_LABELS.get(face, "?"), _find_font(20, True))
    return di


@lru_cache(maxsize=64)
def _saloon_die_asset(kind: str, face: str, size: int):
    path = ASSETS / ("undead" if kind=="duel" else "old_saloon") / "dice" / kind / f"{face}.png"
    if path.is_file():
        return ImageOps.fit(Image.open(path).convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
    return _dice_asset(face, size)


@lru_cache(maxsize=16)
def _rack_asset(target_w: int, target_h: int):
    rack = Image.open(ARROW_RACK).convert("RGBA")
    bbox = rack.getchannel("A").point(lambda p: 255 if p > 32 else 0).getbbox()
    if bbox:
        rack = rack.crop(bbox)
    rack = rack.resize((target_w, target_h), Image.Resampling.LANCZOS)
    rack_alpha = rack.getchannel("A").filter(ImageFilter.GaussianBlur(8))
    rack_shadow = Image.new("RGBA", rack.size, (0, 0, 0, 105))
    rack_shadow.putalpha(rack_alpha.point(lambda p: int(p * 0.50)))
    return rack, rack_shadow


@lru_cache(maxsize=32)
def _arrow_asset(arrow_w: int, arrow_h: int):
    raw = Image.open(ARROW_ICON).convert("RGBA")
    ab = raw.getchannel("A").point(lambda p: 255 if p > 32 else 0).getbbox()
    if ab:
        raw = raw.crop(ab)
    arrow = ImageOps.contain(raw, (arrow_w, arrow_h), method=Image.Resampling.LANCZOS)
    aa = arrow.getchannel("A").filter(ImageFilter.GaussianBlur(2))
    ash = Image.new("RGBA", arrow.size, (0, 0, 0, 115))
    ash.putalpha(aa.point(lambda p: int(p * 0.55)))
    return arrow, ash


def _avatar_for(player, max_w: int, max_h: int):
    """讀取快取的牌桌半身角色圖。"""
    char_cn = player.character.cn if player.character else "?"
    avatar, _ = _avatar_asset(player.character_key, char_cn, max_w, max_h)
    return avatar


def _avatar_shadow(avatar: Image.Image):
    alpha = avatar.getchannel("A").filter(ImageFilter.GaussianBlur(7))
    sh = Image.new("RGBA", avatar.size, (0, 0, 0, 88))
    sh.putalpha(alpha.point(lambda p: int(p * 0.42)))
    return sh


def _paste_icon_number(board, draw, icon_path, number_text, center_x, center_y, icon_size, font):
    icon = _load_icon(icon_path, icon_size)
    if icon:
        x = int(center_x - icon.width - 3)
        y = int(center_y - icon.height / 2)
        board.alpha_composite(icon, (x, y))
        draw.text((center_x + 2, center_y), str(number_text), font=font, fill=(68, 34, 11), anchor="lm")
    else:
        _text_center(draw, (center_x, center_y), str(number_text), font, fill=(68, 34, 11))


def _draw_arrow_pool(board: Image.Image, draw: ImageDraw.ImageDraw, game: Game, spec: tuple[int, int, int, int]):
    """中央淺托盤箭池；九支完整箭並排，保留箭身比例。"""
    cx, cy, target_w, target_h = spec
    if not ARROW_RACK.exists():
        _text_center(
            draw, (cx, cy), f"箭池 {game.arrows_pool}/9", _find_font(30, True),
            fill=(255, 233, 184), stroke_width=3, stroke_fill=(56, 28, 12)
        )
        return

    rack, rack_shadow = _rack_asset(target_w, target_h)
    rx = int(cx - rack.width / 2)
    ry = int(cy - rack.height / 2)

    # 陰影與縮放後箭架皆使用快取。
    board.alpha_composite(rack_shadow, (rx + 6, ry + 8))
    board.alpha_composite(rack, (rx, ry))

    if ARROW_ICON.exists():
        slots = 9
        inner_left = rx + int(rack.width * 0.116)
        inner_right = rx + int(rack.width * 0.884)
        step = (inner_right - inner_left) / max(1, slots - 1)
        arrow_w = max(28, int(step * 0.62))
        arrow_h = max(48, int(rack.height * 0.46))
        arrow, ash = _arrow_asset(arrow_w, arrow_h)
        ay = ry + int(rack.height * 0.485) - arrow.height // 2

        for i in range(max(0, min(9, game.arrows_pool))):
            ax = int(inner_left + i * step - arrow.width / 2)
            board.alpha_composite(ash, (ax + 2, ay + 3))
            board.alpha_composite(arrow, (ax, ay))

    if game.expansion_config.enabled("chief_arrow"):
        tray = _load_icon(ASSETS / "old_saloon" / "arrows" / "chief_arrow_tray.png", (224, 58))
        ty = int(ry - 48)
        if tray:
            board.alpha_composite(tray, (int(cx - tray.width / 2), ty))
        if game.chief_arrow_owner is None:
            chief = _load_icon(ASSETS / "old_saloon" / "arrows" / "chief_arrow_horizontal.png", (170, 24))
            if chief:
                ax = int(cx - chief.width / 2)
                ay = int(ty + (tray.height if tray else 58) / 2 - chief.height / 2)
                board.alpha_composite(_avatar_shadow(chief), (ax + 1, ay + 2))
                board.alpha_composite(chief, (ax, ay))

    count_font = _find_font(25, True)
    rage_total=len(getattr(game,'undead_state',{}).get('active',[]))
    has_rage=bool(rage_total)
    if has_rage:count_font=_find_font(22,True)
    count_center=_label_center if has_rage else _text_center
    if rage_total>3:
        _label_center(draw,(cx+306,cy-14),'普通箭',_find_font(20,True),fill=(255,237,194),stroke_width=2,stroke_fill=(54,27,11))
        _label_center(draw,(cx+306,cy+15),f'{game.arrows_pool}/9',count_font,fill=(255,237,194),stroke_width=2,stroke_fill=(54,27,11))
    else:
      count_center(
        draw,
        (cx, ry + rack.height + (14 if has_rage else 22)),
        f"普通箭 {game.arrows_pool}/9" if game.expansion_config.enabled("chief_arrow") else f"箭池剩餘 {game.arrows_pool} / 9",
        count_font,
        fill=(255, 237, 194),
        stroke_width=3,
        stroke_fill=(54, 27, 11),
    )
    if game.expansion_config.enabled("chief_arrow") and not has_rage:
        owner = (game.players[game.chief_arrow_owner].name.replace('\n', ' ')[:16]
                 if game.chief_arrow_owner is not None else '在箭池')
        _text_center(draw, (cx, ry + rack.height + 56), f"酋長箭：{owner}",
                     _fit_font(f"酋長箭：{owner}", target_w, 26, True),
                     fill=(255, 222, 125), stroke_width=3, stroke_fill=(54, 27, 11))



def preload_assets() -> dict[str, int]:
    """啟動時預熱所有牌桌繪圖素材，避免第一局邊玩邊讀檔/縮圖。"""
    counts = {"tables": 0, "avatars": 0, "dice": 0, "icons": 0, "racks": 0, "arrows": 0, "fonts": 0}

    # 常用字型尺寸先建立。
    for size, bold in [
        (13, True), (14, False), (15, False), (16, False), (17, True), (18, False),
        (18, True), (20, True), (21, True), (22, False), (22, True), (23, True),
        (24, True), (25, True), (28, True), (30, True), (36, True), (54, True),
    ]:
        _find_font(size, bold)
        counts["fonts"] += 1

    # 3～8 人背景、骰面、箭架/箭先預熱；角色先載入一次縮小母圖。
    for c in CHARACTERS:
        _avatar_source(c.key, c.cn)
        counts["avatars"] += 1

    seen_avatar_sizes = set()
    seen_dice_sizes = set()
    seen_rack_sizes = set()
    seen_arrow_sizes = set()
    for n, layout in LAYOUTS.items():
        _table_background(n)
        counts["tables"] += 1

        dice_size = layout.get("dice_size", 82)
        if dice_size not in seen_dice_sizes:
            seen_dice_sizes.add(dice_size)
            for face in DICE_FILES:
                _dice_asset(face, dice_size)
                counts["dice"] += 1

        _, _, rw, rh = layout["arrow_pool"]
        if (rw, rh) not in seen_rack_sizes:
            seen_rack_sizes.add((rw, rh))
            rack, _ = _rack_asset(rw, rh)
            counts["racks"] += 1
            slots = 9
            inner_left = int(rack.width * 0.116)
            inner_right = int(rack.width * 0.884)
            step = (inner_right - inner_left) / max(1, slots - 1)
            aw = max(28, int(step * 0.62))
            ah = max(48, int(rack.height * 0.46))
            if (aw, ah) not in seen_arrow_sizes:
                seen_arrow_sizes.add((aw, ah))
                _arrow_asset(aw, ah)
                counts["arrows"] += 1

        # avatar 的各座位尺寸在第一次用到時由 RAM 母圖快速產生，不再重讀硬碟。
        for seat in layout["seats"]:
            seen_avatar_sizes.add(tuple(seat["avatar_box"]))

    # UI 圖示的實際常用尺寸。
    for p, sizes in [
        (HEART_ICON, [(23, 23)]),
        (ARROW_ICON, [(28, 34)]),
        (SHERIFF_BADGE, [(38, 38), (44, 44)]),
        (DEAD_ICON, [(46, 46)]),
    ]:
        for size in sizes:
            _load_icon(p, size)
            counts["icons"] += 1

    return counts

def _jpeg_bytes(image: Image.Image, name: str) -> BytesIO:
    """輸出較小的 Telegram 牌桌 JPEG，減少每次 editMessageMedia 上傳量。"""
    rgb = image.convert("RGB")
    if rgb.width > 1200 or rgb.height > 900:
        rgb.thumbnail((1200, 900), Image.Resampling.LANCZOS)
    out = BytesIO()
    out.name = name
    rgb.save(out, format="JPEG", quality=84, optimize=True, progressive=True)
    out.seek(0)
    return out


def render_board(game: Game) -> BytesIO:
    n = max(3, min(8, len(game.players)))
    board = _table_background(n).copy()

    layout = LAYOUTS[n]
    panel_w, panel_h = layout["panel_size"]
    draw = ImageDraw.Draw(board)

    # 7/8人用較小字；角色名稱 > 玩家名稱 > 圖片式生命/箭數。
    if n <= 4:
        role_size, player_size, stat_size = 23, 16, 18
    elif n <= 6:
        role_size, player_size, stat_size = 21, 15, 17
    else:
        role_size, player_size, stat_size = 18, 14, 16

    circled = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"]
    targets = _aimable_indices(game)
    is_aiming = game.phase in {"resolving", "saloon_input"} and game.pending_action and game.pending_action.get("type") == "shot"

    for i, player in enumerate(game.players):
        if i >= len(layout["seats"]):
            break
        seat = layout["seats"][CLOCKWISE_SEATS[n][i]]
        nx, ny = seat["panel"]
        max_w, max_h = seat["avatar_box"]
        avatar = _avatar_for(player, max_w, max_h)
        _, cached_shadow = _avatar_asset(
            player.character_key, player.character.cn if player.character else "?", max_w, max_h
        )

        if not player.alive:
            rgb = avatar.convert("RGB")
            gray = ImageOps.grayscale(rgb).convert("RGBA")
            gray.putalpha(140)
            avatar = gray

        panel_top = int(ny - panel_h / 2)
        # 角色中心永遠等於牌子中心，人物底部稍微壓住牌子上緣。
        px = int(nx - avatar.width / 2)
        py = int(panel_top - avatar.height + 12)

        if player.alive:
            board.alpha_composite(cached_shadow, (px + 4, py + 6))
        else:
            board.alpha_composite(_avatar_shadow(avatar), (px + 4, py + 6))

        if i == game.current_idx and (player.alive or player.is_ghost) and game.phase != "ended":
            glow = Image.new("RGBA", (avatar.width + 16, avatar.height + 16), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.rounded_rectangle((2, 2, glow.width - 3, glow.height - 3), radius=22, outline=(255, 218, 72, 235), width=6)
            board.alpha_composite(glow, (px - 8, py - 8))

        board.alpha_composite(avatar, (px, py))

        # 不透明資訊牌，角色圖在後、牌子在前。
        x1 = int(nx - panel_w / 2)
        y1 = int(ny - panel_h / 2)
        x2 = x1 + panel_w
        y2 = y1 + panel_h
        is_shooter = i == game.current_idx and (player.alive or player.is_ghost) and game.phase != "ended"
        is_target = i in targets
        # 射程內的人物資訊牌直接紅框標示；目前射手仍用金框。
        border = (229, 53, 43, 255) if is_target else (
            (255, 215, 75, 255) if is_shooter else (92, 51, 22, 255)
        )
        draw.rounded_rectangle((x1, y1, x2, y2), radius=15, fill=(239, 207, 151, 252), outline=border, width=7 if is_target else 5)
        draw.rounded_rectangle((x1 + 6, y1 + 6, x2 - 6, y2 - 6), radius=10, outline=(151, 93, 43, 205), width=2)
        u=getattr(game,'undead_state',{})
        rage_count=len(u.get('held',{}).get(i,[]))
        wound_count=len(u.get('wounds',{}).get(i,[]))
        if player.alive and (rage_count or wound_count):
            # A separate badge preserves the existing HP/arrow line.
            title=f'憤怒 {rage_count}｜傷口 {wound_count}'
            by=y1-53
            draw.rounded_rectangle((nx-92,by,nx+92,by+25),radius=7,fill=(60,29,22,245),outline=(222,157,75),width=2)
            _label_center(draw,(nx,by+12),title,_find_font(16,True),fill=(255,224,169))

        # 警長徽章公開，放在資訊牌左上，不靠 Emoji。
        if player.role == "sheriff" and SHERIFF_BADGE.exists():
            badge = _load_icon(SHERIFF_BADGE, (38 if n >= 7 else 44, 38 if n >= 7 else 44))
            if badge:
                board.alpha_composite(badge, (x1 - badge.width // 3, y1 - badge.height // 3))

        char_name = player.character.cn if player.character else "未分配"
        display_name = player.name.replace("\n", " ")[:9]
        is_turn_marker = i == game.current_idx and (player.alive or player.is_ghost) and game.phase != "ended"
        display_name = f"{circled[i]} {display_name}"

        role_font = _fit_font(char_name, panel_w - 24, role_size, True)
        player_font = _fit_font(display_name, panel_w - (42 if is_turn_marker else 24), player_size, False)
        stat_font = _find_font(stat_size, True)

        _text_center(draw, (nx, y1 + 21), char_name, role_font, fill=(42, 22, 8))
        name_x = nx + (8 if is_turn_marker else 0)
        _text_center(draw, (name_x, y1 + 43), display_name, player_font, fill=(87, 49, 20))
        if is_turn_marker:
            # Draw the turn triangle directly: no font glyph or emoji required.
            box = draw.textbbox((0, 0), display_name, font=player_font)
            tx = int(name_x - (box[2] - box[0]) / 2 - 14)
            ty = int(y1 + 43 + box[1])
            draw.polygon([(tx, ty - 5), (tx, ty + 5), (tx + 9, ty)], fill=(145, 65, 14))

        # 圖片式血量與箭數：避免 Pillow 的 Emoji 變方框。
        _paste_icon_number(board, draw, HEART_ICON, f"{max(0, player.hp)}/{player.max_hp}", nx - panel_w * 0.19, y2 - 18, (23, 23), stat_font)
        has_chief_arrow = game.expansion_config.enabled("chief_arrow") and game.chief_arrow_owner == i
        arrow_count = f"{player.arrows}+2" if has_chief_arrow else str(player.arrows)
        arrow_font = _fit_font(arrow_count, panel_w * 0.27 - 10, stat_size, True)
        _paste_icon_number(board, draw, ARROW_ICON, arrow_count, nx + panel_w * 0.23, y2 - 18, (23, 22), arrow_font)
        if game.expansion_config.enabled("chief_arrow") and game.chief_arrow_owner == i:
            chief = _load_icon(ASSETS / "old_saloon" / "arrows" / "chief_arrow.png", (52, 116))
            if chief:
                board.alpha_composite(chief, (int(x1 + 8), int(y1 - chief.height - 7)))
            draw.rounded_rectangle((x1 + 3, y1 - 31, x1 + 91, y1 - 5), radius=7,
                                   fill=(87, 42, 15, 255), outline=(255, 216, 114), width=2)
            _label_center(draw, (x1 + 47, y1 - 18), '酋長箭', _find_font(19, True), fill=(255, 236, 181))

        # 最近一次傷害／補血顯示在本人名牌旁，與最近戰況牌匾同步。
        last_action = game.last_action
        if (last_action and last_action["target_idx"] == i and not is_aiming
                and player.alive and player.hp == last_action["after"]):
            is_heal = last_action.get("kind") == "heal"
            delta = last_action.get("gained", 0) if is_heal else last_action["lost"]
            value = f"+{delta}" if is_heal else (f"-{delta}" if delta else "擋下")
            if is_heal and not delta:
                value = "滿血"
            tag_width = 60 if len(value) <= 3 else 68
            tx2, ty2 = int(x2 - 6), int(y1 - 19)
            fill = ((34, 121, 72, 252) if delta else (69, 83, 72, 252)) if is_heal else (
                (163, 29, 26, 252) if delta else (69, 83, 72, 252))
            draw.rounded_rectangle((tx2 - tag_width, ty2, tx2, ty2 + 29),
                                   radius=8, fill=fill,
                                   outline=(255, 218, 137, 255), width=2)
            _label_center(draw, (tx2 - tag_width / 2, ty2 + 14), value,
                         _find_font(19 if delta else 16, True), fill=(255, 242, 213))

        if is_target:
            tag_w, tag_h = (86 if n <= 6 else 76), 27
            tx1 = x2 - tag_w - 7
            ty1 = y1 - 17
            draw.rounded_rectangle((tx1, ty1, tx1 + tag_w, ty1 + tag_h), radius=8, fill=(189, 37, 28, 255), outline=(255, 210, 111, 255), width=2)
            _text_center(draw, (tx1 + tag_w / 2, ty1 + tag_h / 2), "可射擊", _find_font(17 if n <= 6 else 15, True), fill=(255, 248, 226), stroke_width=1, stroke_fill=(111, 24, 17))

        if not player.alive:
            if DEAD_ICON.exists():
                dead = _load_icon(ASSETS / "old_saloon" / "ghost" / "ghost_icon.png" if player.is_ghost else DEAD_ICON, (46, 46))
                if dead:
                    board.alpha_composite(dead, (int(nx - dead.width / 2), int(ny - dead.height / 2)))
            else:
                _text_center(draw, (nx, ny), "淘汰", _find_font(22, True), fill=(230, 230, 230), stroke_width=3, stroke_fill=(60, 0, 0))
            # 死亡公開身份：僅在已灰階的死者肖像下緣加上小名牌，不動原座標。
            reveal = f"{'鬼魂' if player.is_ghost else '已淘汰'} · {ROLE_CN[player.role]}"
            rw = min(panel_w - 18, 165 if n <= 6 else 140)
            rh = 25 if n <= 6 else 22
            ry = y1 - rh - 4
            rx = int(nx - rw / 2)
            draw.rounded_rectangle((rx, ry, rx + rw, ry + rh), radius=7,
                                   fill=(47, 29, 24, 242), outline=(214, 168, 92, 250), width=2)
            _label_center(draw, (nx, ry + rh / 2), reveal, _find_font(16 if n <= 6 else 14, True),
                         fill=(255, 230, 179), stroke_width=1, stroke_fill=(33, 21, 17))

    # 中央公共區：目前玩家 + 圖片箭池。
    center_x, center_y = layout["center"]
    # Leave clear space above the chief-arrow cradle; the 3-player top seat
    # sits lower and retains its separately calibrated title position.
    if n >= 4:
        center_y -= 28
    if game.phase != "lobby":
        turn = game.current_player().name if game.phase != "ended" else "遊戲結束"
        center_text = "選擇紅框射擊目標" if is_aiming else f"目前：{turn}"
        if n==3:
            _label_center(draw,(center_x-255,center_y+22),center_text,_fit_font(center_text,250,24),fill=(246,224,178),stroke_width=2,stroke_fill=(56,28,12))
        else:
            _text_center(draw, (center_x, center_y), center_text, _find_font(28 if n <= 6 else 24, True), fill=(246, 224, 178), stroke_width=3, stroke_fill=(56, 28, 12))
        rage_total=len(getattr(game,'undead_state',{}).get('active',[]))
        pool_spec=(724,440,440,80) if rage_total>3 else layout["arrow_pool"]
        _draw_arrow_pool(board, draw, game, pool_spec)

        # 戰鬥牌匾顯示最近一筆攻擊或補血：誰幫誰、前後血量。
        # 不調整任何角色/座位座標，不新增持續更新的群組訊息。
        last_action = game.last_action
        if last_action:
            label = format_action(game, last_action, compact=True, for_image=True)
            bx1, by1, bx2, by2 = 310, 924, 1138, 1008
            draw.rounded_rectangle((bx1 + 3, by1 + 4, bx2 + 3, by2 + 4),
                                   radius=15, fill=(19, 12, 8, 160))
            draw.rounded_rectangle((bx1, by1, bx2, by2), radius=15,
                                   fill=(65, 32, 20, 246), outline=(222, 164, 84, 255), width=4)
            banner = "最近補血" if last_action.get("kind") == "heal" else "最近攻擊"
            _text_center(draw, (724, by1 + 19), banner, _find_font(19, True),
                         fill=(252, 217, 145), stroke_width=1, stroke_fill=(43, 18, 9))
            _text_center(draw, (724, by1 + 54), label,
                         _fit_font(label, bx2 - bx1 - 35, 28 if n <= 6 else 25, True, min_size=16),
                         fill=(255, 243, 214), stroke_width=1, stroke_fill=(29, 12, 9))

    # 骰子區：維持平面正面骰面，全部依牌桌人數單獨控制 y。
    if game.dice:
        dice_size = layout.get("dice_size", 82)
        gap = 10 if n <= 6 else 8
        total = len(game.dice) * dice_size + (len(game.dice)-1) * gap
        x0 = int(724 - total / 2)
        y0 = int(layout["dice_y"])
        for i, face in enumerate(game.dice):
            kind = game.dice_types[i].kind if i < len(game.dice_types) else "base"
            di = _saloon_die_asset(kind, face, dice_size) if kind != "base" else _dice_asset(face, dice_size)

            xx = x0 + i * (dice_size + gap)
            if i in game.selected:
                frame = Image.new("RGBA", (dice_size + 12, dice_size + 12), (0, 0, 0, 0))
                fd = ImageDraw.Draw(frame)
                fd.rounded_rectangle((0, 0, frame.width - 1, frame.height - 1), radius=14, outline=(255, 226, 72, 255), width=6)
                board.alpha_composite(frame, (xx - 6, y0 - 6))
            board.alpha_composite(di, (xx, y0))
            _text_center(draw, (xx + dice_size / 2, y0 + dice_size + 20), str(i + 1), FONT_SMALL_BOLD, fill=(242, 227, 191))

        _text_center(
            draw,
            (724, min(board.height - 115, y0 + dice_size + 58)),
            f"第 {game.roll_no} / {4 if game.current_player().character_key == 'lucky_duke' and not game.current_player().is_ghost else 3} 次擲骰",
            _find_font(24 if n <= 6 else 21, True),
            fill=(242, 227, 191),
            stroke_width=2,
            stroke_fill=(20, 10, 5),
        )

    # During a duel the central tray becomes the exchange panel.
    u=getattr(game,'undead_state',{})
    active=u.get('active',[])
    if active:
        width,height=84,112;shown=active[:6];gap=12
        top=520 if len(active)>3 else 638
        title=f'狂怒加成 {len(active)}張（不可重擲）'
        if len(active)>6:title=f'狂怒 {len(active)}張｜另{len(active)-6}張見翻牌大圖'
        _label_center(draw,(724,top-(19 if len(active)>3 else 13)),title,_find_font(18,True),fill=(251,224,170))
        for at,card in enumerate(shown):
            row,col=divmod(at,3)
            row_count=min(3,len(shown)-row*3)
            left=724-(row_count*width+(row_count-1)*gap)/2
            path=ASSETS/'undead'/'rage'/f'{card}.png'
            if path.exists():
                im=Image.open(path).convert('RGBA');im.thumbnail((width,height),Image.Resampling.LANCZOS)
                board.alpha_composite(im,(int(left+col*(width+gap)),top+row*(height+6)))
    duel=u.get('duel')
    if duel:
        compact=len(active)>3
        draw.rounded_rectangle((464,340 if compact else 420,984,490 if compact else 606),radius=20,fill=(38,23,22,250),outline=(224,167,80,255),width=4)
        names=f"{game.players[duel['challenger']].name}  vs  {game.players[duel['opponent']].name}"
        _label_center(draw,(724,363 if compact else 451),names,_fit_font(names,475,28),fill=(255,224,172))
        title=f"等待 {game.players[duel['mover']].name} 擲決鬥骰"
        _label_center(draw,(724,397 if compact else 487),title,_fit_font(title,475,24),fill=(255,244,217))
        if duel.get('face'):
            size=56 if compact else 72
            board.alpha_composite(_saloon_die_asset('duel',duel['face'],size),(724-size//2,422 if compact else 518))
        else:
            _label_center(draw,(724,450 if compact else 550),'決鬥交鋒 '+str(duel['exchange']),_find_font(26,True),fill=(237,195,120))

    # 上一動作：只留一條，不刷群組。
    if game.log:
        text = game.log[-1][:64]
        _text_center(draw, (724, board.height - 38), text, _find_font(18, False), fill=(236, 220, 184), stroke_width=2, stroke_fill=(32, 18, 8))

    return _jpeg_bytes(board, "board.jpg")


def render_rage_reveal(cards) -> BytesIO:
    """Public revealed cards only; never read a player's hidden hand."""
    columns=min(3,len(cards))
    if not columns:raise ValueError('No revealed cards')
    rows=(len(cards)+columns-1)//columns
    canvas=Image.new('RGB',(columns*300+40,rows*400+70),(55,31,19))
    draw=ImageDraw.Draw(canvas)
    _label_center(draw,(canvas.width/2,27),'狂怒卡公開',_find_font(28,True),fill=(255,225,170))
    for at,card in enumerate(cards):
        path=ASSETS/'undead'/'rage'/f'{card}.png'
        with Image.open(path) as source:
            art=source.convert('RGB');art.thumbnail((282,376),Image.Resampling.LANCZOS)
        row,col=divmod(at,columns)
        canvas.paste(art,(20+col*300+(282-art.width)//2,55+row*400))
    return _jpeg_bytes(canvas,'rage_reveal.jpg')


def render_lobby(game: Game) -> BytesIO:
    # 大廳圖片保持靜態；人數/玩家名改放 caption，按加入/加電腦時只需 edit caption。
    board = _table_background(6).copy()
    draw = ImageDraw.Draw(board)
    _text_center(draw, (724, 445), "BANG! 骰子版", _find_font(54, True), fill=(245, 225, 180), stroke_width=4, stroke_fill=(66, 27, 10))
    _text_center(draw, (724, 520), "等待玩家加入", FONT_BIG, fill=(245, 225, 180), stroke_width=3, stroke_fill=(66, 27, 10))
    return _jpeg_bytes(board, "lobby.jpg")

