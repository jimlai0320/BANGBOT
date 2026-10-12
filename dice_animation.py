from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ANIM_DIR = ASSETS / "animations"


def mask_from_indices(moving_indices) -> int:
    if moving_indices is None:
        return 31
    mask = 0
    for i in moving_indices:
        i = int(i)
        if 0 <= i < 5:
            mask |= 1 << i
    return mask or 31


def animation_path(moving_indices=None) -> Path:
    mask = mask_from_indices(moving_indices)
    return ANIM_DIR / f"dice_mask_{mask:02d}.mp4"


def preload_dice_animation_assets() -> dict[str, int]:
    files = list(ANIM_DIR.glob("dice_mask_*.mp4"))
    total = sum(p.stat().st_size for p in files if p.exists())
    return {"animations": len(files), "bytes": total}
