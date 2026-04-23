import json
import logging
import random
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class StoryEngine:
    def __init__(self):
        try:
            with open(TEMPLATES_DIR / "hooks.json") as f:
                self._hooks = json.load(f)["hooks"]
        except (FileNotFoundError, KeyError) as e:
            raise RuntimeError(f"Failed to load hooks.json from {TEMPLATES_DIR}: {e}") from e
        try:
            with open(TEMPLATES_DIR / "niches.json") as f:
                self._niches = json.load(f)
        except FileNotFoundError as e:
            raise RuntimeError(f"Failed to load niches.json from {TEMPLATES_DIR}: {e}") from e

    def generate(self, niche: str) -> dict:
        if niche not in self._niches:
            raise ValueError(f"Unknown niche: '{niche}'. Available: {list(self._niches.keys())}")

        data = self._niches[niche]
        hook = random.choice(self._hooks)
        template = random.choice(data["script_templates"])
        pexels_query = random.choice(data["pexels_queries"])
        # Pick CTA once — used in both the inline {cta} placeholder and the returned dict
        cta = self._pick(data.get("ctas", ["Subscribe for daily stories."]))

        script = self._fill_template(template, hook, data, cta)
        title = self._generate_title(hook)

        logger.info(f"Generated script for niche={niche}, words={len(script.split())}")
        return {
            "niche": niche,
            "hook": hook,
            "script": script,
            "title": title,
            "pexels_query": pexels_query,
            "cta": cta,
            "seo": self._generate_seo(title, niche),
        }

    def _fill_template(self, template: str, hook: str, data: dict, cta: str) -> str:
        replacements = {"hook": hook, "cta": cta}
        field_map = {
            "character": "characters",
            "action": "actions",
            "conflict": "conflicts",
            "moral_lesson": "lessons",
            "clue": "clues",
            "red_herring": "red_herrings",
            "twist": "twists",
            "setup": "setups",
            "escalation": "escalations",
            "reveal": "reveals",
            "low_point": "low_points",
            "result": "results",
            "partner": "partners",
            "realization": "realizations",
        }
        for placeholder, key in field_map.items():
            if key in data:
                replacements[placeholder] = self._pick(data[key])

        result = template
        for k, v in replacements.items():
            result = result.replace("{" + k + "}", v)

        return self._clean_script(result)

    def _clean_script(self, text: str) -> str:
        text = re.sub(r'\.{2,}(?!\.)|\.\s+\.', '.', text)
        text = re.sub(r'\.\s+([a-z])', lambda m: '. ' + m.group(1).upper(), text)
        text = text[0].upper() + text[1:] if text else text
        return text.strip()

    def _pick(self, lst: list) -> str:
        return random.choice(lst) if lst else ""

    def _generate_title(self, hook: str) -> str:
        # Preserve ellipsis for cliffhanger effect; apply Title Case (YouTube standard)
        base = hook.rstrip(".")
        return f"{base.title()} #Shorts"

    def _generate_seo(self, title: str, niche: str) -> dict:
        base_tags = ["#shorts", "#story", "#viral", "#ytshorts"]
        niche_tags = {
            "moral": ["#moralstory", "#lifelesson", "#motivation"],
            "mystery": ["#mystery", "#thriller", "#suspense"],
            "horror": ["#horror", "#scarystory", "#creepy"],
            "motivation": ["#motivation", "#success", "#mindset"],
            "relationship": ["#love", "#relationship", "#drama"],
        }
        tags = base_tags + niche_tags.get(niche, [])
        description = (
            f"{title}\n\n"
            f"A powerful {niche} story that will stay with you.\n"
            f"Watch till the end — the twist will surprise you.\n\n"
            f"Subscribe for daily stories → @{niche}shorts\n\n"
            + " ".join(tags)
        )
        return {"title": title, "description": description, "tags": tags}
