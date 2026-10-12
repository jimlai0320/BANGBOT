"""Old Saloon visual assets API (v0.8.1).

The images are packaged and individually addressable, but the gameplay logic
is intentionally not active until the separate modules are implemented/tested.
"""
from __future__ import annotations
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'assets' / 'old_saloon'
MANIFEST_FILE = ROOT / 'SALOON_ASSETS_MANIFEST.json'


def asset_manifest() -> dict:
    return json.loads(MANIFEST_FILE.read_text(encoding='utf-8'))


def face_file(die_kind: str, face: str) -> Path:
    """Strict allowlist of faces; never silently show a base die for unknown symbols."""
    data = asset_manifest().get('saloon_dice', {}).get(die_kind)
    if data is None:
        raise ValueError(f'未知的老酒館骰子：{die_kind}')
    match = next((f for f in data['faces'] if f['face'] == face), None)
    if match is None:
        raise ValueError(f'骰子 {die_kind} 沒有 {face} 骰面')
    p = ROOT / match['path']
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def character_asset(character_key: str, part: str = 'card') -> Path:
    """Return approved card or avatar of one of the 8 new characters."""
    if part not in {'card', 'avatar'}:
        raise ValueError('part 只能是 card / avatar')
    data = asset_manifest().get('characters', {}).get(character_key)
    if data is None:
        raise ValueError(f'未知的老酒館角色：{character_key}')
    p = ROOT / data[part]
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def special_role_card(role_key: str) -> Path:
    item = asset_manifest()['special_roles'].get(role_key)
    if item is None:
        raise ValueError(f'未知特殊身分：{role_key}')
    path = ROOT / item['card']
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def ghost_token(face: str) -> Path:
    path_str = asset_manifest()['ghost_tokens'].get(face)
    if path_str is None:
        raise ValueError(f'未知鬼魂標記：{face}')
    path = ROOT / path_str
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def chief_arrow() -> Path:
    path = ROOT / asset_manifest()['other']['chief_arrow']
    if not path.is_file():
        raise FileNotFoundError(path)
    return path
