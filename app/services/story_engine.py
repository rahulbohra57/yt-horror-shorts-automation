import json
import random
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class StoryEngine:
    def __init__(self):
        with open(TEMPLATES_DIR / "hooks.json") as f:
            self._hooks = json.load(f)["hooks"]
        with open(TEMPLATES_DIR / "niches.json") as f:
            self._niches = json.load(f)

    def generate(self, niche: str) -> dict:
        if niche not in self._niches:
            raise ValueError(f"Unknown niche: '{niche}'. Available: {list(self._niches.keys())}")

        data = self._niches[niche]
        hook = random.choice(self._hooks)
        template = random.choice(data["script_templates"])
        pexels_query = random.choice(data["pexels_queries"])

        script = self._fill_template(template, hook, niche, data)
        title = self._generate_title(hook, niche)
        cta = self._pick(data.get("ctas", ["Subscribe for more stories."]))

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

    def _fill_template(self, template: str, hook: str, niche: str, data: dict) -> str:
        replacements = {"hook": hook}
        field_map = {
            "character": "characters",
            "action": "actions",
            "conflict": "conflicts",
            "moral_lesson": "lessons",
            "cta": "ctas",
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
        return result

    def _pick(self, lst: list) -> str:
        return random.choice(lst) if lst else ""

    def _generate_title(self, hook: str, niche: str) -> str:
        base = hook.replace("...", "").strip().rstrip(".")
        return f"{base} #shorts"

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
