"""Picks each story's premise in code, so variety never depends on the model."""
import json
import random
from pathlib import Path

_PREMISES_PATH = Path(__file__).parent.parent / "templates" / "premises.json"
_BANK = json.loads(_PREMISES_PATH.read_text())


def _fresh(pool: list[str], recent_values: list[str], rng: random.Random) -> str:
    """Choose from pool, excluding as many recent values as possible (newest first wins)."""
    remaining = list(pool)
    for value in recent_values:
        if value in remaining and len(remaining) > 1:
            remaining.remove(value)
    return rng.choice(remaining)


def pick_premise(niche: str, recent: list[dict] | None = None, rng: random.Random | None = None) -> dict:
    """Return a premise whose setting + threat pair is unused in `recent` (newest first)."""
    rng = rng or random
    recent = [p for p in (recent or []) if isinstance(p, dict)]
    niche_bank = _BANK["niches"].get(niche) or _BANK["niches"]["horror"]
    same_niche = [p for p in recent if p.get("niche") == niche]

    used_pairs = {(p.get("setting"), p.get("threat")) for p in same_niche}
    setting = _fresh(niche_bank["settings"], [p.get("setting") for p in same_niche], rng)
    threat = _fresh(niche_bank["threats"], [p.get("threat") for p in same_niche], rng)
    if (setting, threat) in used_pairs:
        unused = [
            (s, t) for s in niche_bank["settings"] for t in niche_bank["threats"]
            if (s, t) not in used_pairs
        ]
        if unused:
            setting, threat = rng.choice(unused)

    pov = _fresh(list(_BANK["pov"]), [p.get("pov") for p in recent[:2]], rng)
    story_format = _fresh(list(_BANK["formats"]), [p.get("format") for p in recent[:2]], rng)
    ending = _fresh(list(_BANK["endings"]), [p.get("ending") for p in recent[:3]], rng)
    protagonist = _fresh(_BANK["protagonists"], [p.get("protagonist") for p in recent[:6]], rng)
    return {
        "niche": niche,
        "setting": setting,
        "threat": threat,
        "protagonist": protagonist,
        "pov": pov,
        "format": story_format,
        "ending": ending,
    }


def describe_premise(premise: dict, include_ending: bool = True) -> str:
    """Render a premise as the mandatory prompt block."""
    lines = [
        f"* Setting: {premise['setting']}",
        f"* Central threat: {premise['threat']}",
        f"* Protagonist: {premise['protagonist']}",
        f"* Narration: {_BANK['pov'][premise['pov']]}",
        f"* Story format: {_BANK['formats'][premise['format']]}",
    ]
    if include_ending:
        lines.append(f"* Ending type: {_BANK['endings'][premise['ending']]}")
    return "\n".join(lines)
