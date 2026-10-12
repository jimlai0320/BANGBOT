"""Full offline test of approved Old Saloon image integration, no Telegram token needed."""
from pathlib import Path
from hashlib import sha256
from PIL import Image
import json
from old_saloon import ExpansionConfig, MODULE_KEYS, IMPLEMENTED_MODULES
from saloon_assets import ASSETS, ROOT, MANIFEST_FILE, asset_manifest, face_file, character_asset, special_role_card, ghost_token, chief_arrow

manifest = asset_manifest()
assert manifest['base_version'].startswith('0.8.0')
assert len(manifest['characters']) == 8
assert len(manifest['special_roles']) == 9
assert len(manifest['ghost_tokens']) == 7
assert len(manifest['saloon_dice']) == 2
assert len(manifest['other']) == 5
assert IMPLEMENTED_MODULES == set(MODULE_KEYS)

for idx, (key, entry) in enumerate(manifest['characters'].items(), 17):
    assert entry['number'] == idx
    assert entry['hp'] in (7,8,9)
    for part in ('card','avatar'):
        with Image.open(character_asset(key, part)) as im:
            assert im.width > 650 and im.height > 850
for key in manifest['special_roles']:
    with Image.open(special_role_card(key)) as im:
        assert im.width > 750 and im.height > 1000

expected = {
    'loudmouth':['arrow','bullet','double_bull1','double_bull2','dynamite','double_gatling'],
    'coward':['arrow','broken_arrow','bull1','bull2','beer','double_beer'],
}
for kind, faces in expected.items():
    assert [e['face'] for e in manifest['saloon_dice'][kind]['faces']] == faces
    for face in faces:
        with Image.open(face_file(kind,face)) as im:
            assert im.mode == 'RGBA' and im.size == (900,900)
            assert im.getpixel((0,0))[3] == 0, (kind,face,'transparent corner missing')
for face in ('arrow','beer','bull1','bull2','dynamite','gatling','double'):
    with Image.open(ghost_token(face)) as im:
        assert im.size == (950,950) and im.mode=='RGBA'
with Image.open(chief_arrow()) as im:
    assert im.mode=='RGBA' and im.height > im.width
    assert im.getpixel((0,0))[3] == 0

for path, expected_digest in manifest['checksums'].items():
    p=ROOT/path
    assert p.is_file(), p
    assert sha256(p.read_bytes()).hexdigest() == expected_digest, p

original_assets = json.loads((ROOT/'BASE_V079_ASSET_SHA256.json').read_text('utf8'))
assert len(original_assets) >= 80
for rel,digest in original_assets.items():
    p=ROOT/rel
    assert p.is_file(), p
    assert sha256(p.read_bytes()).hexdigest()==digest, f'已覆蓋 v0.7.9 原始素材：{rel}'

for n in range(3,9):
    for module in MODULE_KEYS:
        c=ExpansionConfig('saloon',{module})
        assert c.playable_status(n)[0] == (module != 'ghost' or n >= 5), f'模組狀態錯誤：{module}'

print('PASS: 8 cards + 8 matching-key avatars, 9 special role art assets')
print('PASS: 12 individually indexed 900px transparent Saloon dice faces')
print('PASS: 7 ghost tokens, chief arrow, ghost cards/banner/icon')
print(f'PASS: all {len(manifest["checksums"])} imported artwork SHA256 checksums verified')
print(f'PASS: all {len(original_assets)} original v0.7.9 assets unchanged')
print('PASS: 五個模組開局驗證，鬼魂維持五人門檻')
