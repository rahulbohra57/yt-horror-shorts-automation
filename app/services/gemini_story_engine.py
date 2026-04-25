import json
import logging
import random
import re
from pathlib import Path
from typing import Iterable

import google.generativeai as genai

from app.core.config import settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

NICHE_PROMPTS = {
    "horror": {
        "genre": "horror",
        "tone": "terrifying, suspenseful, and deeply unsettling",
        "elements": "ghosts, unexplained phenomena, dark secrets, paranormal events, psychological dread",
        "ending": "a chilling twist or revelation that leaves the viewer disturbed",
    },
    "mystery": {
        "genre": "mystery/thriller",
        "tone": "tense, suspenseful, and intellectually gripping",
        "elements": "hidden clues, red herrings, unexpected betrayals, shocking revelations",
        "ending": "a plot twist that reframes everything the viewer just heard",
    },
}

SEO_TEMPLATES = {
    "horror": {
        "description_fmt": (
            "{title}\n\n"
            "😱 One minute. One story. One nightmare.\n\n"
            "Watch till the end… the twist is waiting for you. 👀\n"
            "If this scared you, hit subscribe for daily horror shorts → @{channel}\n\n"
            "🩸 New scary stories every week\n"
            "👻 Ghosts • Mysteries • Dark Tales • Paranormal\n\n"
            "#shorts #horror #scary #creepy #ghoststory #thriller "
            "#haunted #paranormal #horrorshorts\n\n"
            "horror shorts, scary shorts, horror stories, ghost stories, creepy videos, "
            "short horror films, scary youtube shorts, haunted stories, paranormal shorts, "
            "dark stories, horror reels, creepy tales, horror channel, scary endings, "
            "1 minute horror, jumpscare shorts, horror india, scary stories hindi, "
            "horror twist story, spooky shorts"
        ),
        "tags": [
            "shorts", "horror", "scary", "creepy", "ghoststory", "thriller",
            "haunted", "paranormal", "horrorshorts", "horror shorts", "scary shorts",
            "horror stories", "ghost stories", "creepy videos", "haunted stories",
            "paranormal shorts", "dark stories", "horror reels", "1 minute horror",
            "jumpscare shorts", "horror twist story", "spooky shorts",
        ],
    },
    "mystery": {
        "description_fmt": (
            "{title}\n\n"
            "🔍 One minute. One mystery. Zero answers.\n\n"
            "Watch till the end… the truth will shock you. 😱\n"
            "Subscribe for daily mystery shorts → @{channel}\n\n"
            "🎯 New mysteries every week\n"
            "🕵️ Thrillers • Twists • Dark Secrets • Unsolved Cases\n\n"
            "#shorts #mystery #thriller #suspense #crimestory "
            "#detective #mysterystory #crimethriller #mysteryshorts\n\n"
            "mystery shorts, thriller shorts, mystery stories, crime stories, dark secrets, "
            "short mystery films, mystery youtube shorts, unsolved mysteries, detective stories, "
            "plot twist shorts, mystery channel, shocking endings, 1 minute mystery, "
            "crime thriller shorts, mystery india, crime stories hindi, mystery twist story"
        ),
        "tags": [
            "shorts", "mystery", "thriller", "suspense", "crimestory", "detective",
            "mysterystory", "crimethriller", "mysteryshorts", "mystery shorts",
            "thriller shorts", "mystery stories", "crime stories", "dark secrets",
            "plot twist shorts", "detective stories", "1 minute mystery",
            "mystery twist story", "crime thriller shorts",
        ],
    },
}


class GeminiStoryEngine:
    """Generates unique story scripts via Gemini API with template fallback."""

    def __init__(self, fallback_engine=None):
        self._fallback = fallback_engine
        self._niches = self._load_niches()
        self._hooks = self._load_hooks()
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = genai.GenerativeModel("gemini-1.5-flash")

    def _load_niches(self) -> dict:
        try:
            with open(TEMPLATES_DIR / "niches.json") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _load_hooks(self) -> list:
        try:
            with open(TEMPLATES_DIR / "hooks.json") as f:
                return json.load(f)["hooks"]
        except (FileNotFoundError, KeyError):
            return []

    def generate(self, niche: str, recent_scripts: Iterable[str] | None = None) -> dict:
        recent = list(recent_scripts or [])
        niche_data = self._niches.get(niche, {})
        pexels_queries = niche_data.get("pexels_queries", ["dark horror scene"])
        pexels_query = random.choice(pexels_queries)

        try:
            hook, script = self._call_gemini(niche, recent)
        except Exception as e:
            logger.warning(f"[GeminiStoryEngine] Gemini call failed: {e}. Using fallback.")
            if self._fallback:
                return self._fallback.generate(niche, recent_scripts=recent)
            raise

        title = self._generate_title(hook)
        return {
            "niche": niche,
            "hook": hook,
            "script": script,
            "title": title,
            "pexels_query": pexels_query,
            "pexels_queries": pexels_queries,
            "cta": "Subscribe for more stories like this.",
            "seo": self._generate_seo(title, niche),
        }

    def _call_gemini(self, niche: str, recent_scripts: list[str]) -> tuple[str, str]:
        config = NICHE_PROMPTS.get(niche, NICHE_PROMPTS["horror"])
        hook_examples = "\n".join(f"- {h}" for h in self._hooks[:5])

        # Build a summary of recent story openings so Gemini avoids them
        recent_openings = []
        for s in recent_scripts[:10]:
            first_sentence = re.split(r"[.?!]", s)[0].strip()
            if first_sentence:
                recent_openings.append(f"- {first_sentence[:80]}")
        avoid_block = ""
        if recent_openings:
            avoid_block = (
                "\n\nIMPORTANT - Do NOT reuse or closely resemble these recent story openings:\n"
                + "\n".join(recent_openings)
            )

        prompt = f"""You are a viral YouTube Shorts scriptwriter specializing in {config['genre']} stories.

Write a BRAND NEW, completely original {config['genre']} story script for a YouTube Short.

Requirements:
- Total length: 160–210 words (strict — count carefully)
- Tone: {config['tone']}
- Must include: {config['elements']}
- Opening hook: A gripping single sentence that instantly hooks viewers (first 2 seconds)
- Story pacing: One sentence every 1–2 seconds, pattern interrupt every 5 seconds
- Ending: {config['ending']}
- Last sentence must be a CTA like: "Subscribe for more stories like this." or "Follow for your daily horror fix."
- Use Indian names (Riya, Arjun, Meera, Kabir, Priya, Dev, etc.)
- Do NOT use: ellipsis (…), em dashes (—), or any special formatting

Hook examples (pick a style, create your own unique hook — do NOT copy these):
{hook_examples}
{avoid_block}

Respond with ONLY valid JSON in this exact format:
{{
  "hook": "<opening hook sentence only>",
  "script": "<complete script including hook, story, and CTA — 160-210 words>"
}}"""

        response = self._model.generate_content(prompt)
        text = response.text.strip()

        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        parsed = json.loads(text)
        hook = parsed["hook"].strip()
        script = parsed["script"].strip()

        word_count = len(script.split())
        logger.info(f"[GeminiStoryEngine] Generated {word_count} word script for niche={niche}")

        return hook, script

    def _generate_title(self, hook: str) -> str:
        base = hook.rstrip(".")
        return f"{base.title()} #Shorts"

    def _generate_seo(self, title: str, niche: str) -> dict:
        ch = settings.CHANNEL_NAME
        template = SEO_TEMPLATES.get(niche, SEO_TEMPLATES["horror"])
        description = template["description_fmt"].format(title=title, channel=ch)
        return {
            "title": title,
            "description": description,
            "tags": template["tags"],
        }
