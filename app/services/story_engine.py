import json
import logging
import random
import re
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
MAX_RECENT_STORIES = 40
MIN_WORDS = 160
MAX_WORDS = 210
MIN_NOVELTY_SCORE = 0.70
MAX_SIMILARITY_ALLOWED = 0.30

STOPWORDS = {
    "the", "and", "that", "with", "from", "this", "they", "their", "there", "were", "have",
    "been", "into", "your", "about", "after", "before", "because", "while", "when", "what",
    "where", "which", "could", "would", "should", "just", "then", "them", "over", "under",
    "inside", "outside", "someone", "every", "never", "still", "very", "only", "more", "less",
}

HORROR_ESCALATIONS = [
    "Then the smell of wet earth crept in, like a grave had just been opened nearby.",
    "A thin trail of muddy footprints appeared across the floor, each one filling with dark water.",
    "The walls began to pulse softly, as if something alive was breathing behind them.",
    "From the ceiling, a drop of cold liquid landed on their hand, thick and unmistakably red.",
]

MYSTERY_ESCALATIONS = [
    "One detail refused to fit, and that was the detail that broke the whole case open.",
    "The evidence did not just point to a suspect, it pointed to someone inside the investigation.",
    "That final clue proved this was never one crime, but a cover for something much older and darker.",
]


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

    def generate(self, niche: str, recent_scripts: Iterable[str] | None = None) -> dict:
        if niche not in self._niches:
            raise ValueError(f"Unknown niche: '{niche}'. Available: {list(self._niches.keys())}")

        data = self._niches[niche]
        pexels_query = random.choice(data["pexels_queries"])
        recent = [s for s in (recent_scripts or []) if isinstance(s, str) and s.strip()][:MAX_RECENT_STORIES]
        recent_fingerprints = {self._script_fingerprint(s) for s in recent}
        recent_openings = {self._opening_fingerprint(s) for s in recent}
        history_count = len(recent)

        # Build multiple candidates and score for novelty against recent stories.
        best_candidate = None
        for attempt in range(120):
            hook = random.choice(self._hooks)
            template = random.choice(data["script_templates"])
            cta = self._pick(data.get("ctas", ["Subscribe for daily stories."]))
            script = self._fill_template(template, hook, data, cta)
            escalation = self._pick_escalation(niche, history_count)
            if escalation:
                script = self._inject_before_cta(script, cta, escalation)

            word_count = len(script.split())
            if not (MIN_WORDS <= word_count <= MAX_WORDS):
                logger.debug(f"Script attempt {attempt+1}: {word_count} words, retrying")
                continue

            fingerprint = self._script_fingerprint(script)
            if fingerprint in recent_fingerprints:
                logger.debug(f"Script attempt {attempt+1}: skipped exact-match fingerprint")
                continue
            opening_fp = self._opening_fingerprint(script)
            opening_repeat = bool(opening_fp and opening_fp in recent_openings)

            novelty = self._novelty_score(script, recent)
            max_similarity = self._max_similarity(script, recent)
            score = novelty + random.random() * 0.02
            if max_similarity > MAX_SIMILARITY_ALLOWED:
                # Soft penalty so we still keep a best candidate even if all templates are close.
                score -= (max_similarity - MAX_SIMILARITY_ALLOWED) * 1.5
            if opening_repeat:
                score -= 0.20
            candidate = {
                "hook": hook,
                "script": script,
                "cta": cta,
                "score": score,
                "novelty": novelty,
                "similarity": max_similarity,
                "opening_repeat": opening_repeat,
            }
            if best_candidate is None or candidate["score"] > best_candidate["score"]:
                best_candidate = candidate
            if (
                novelty >= MIN_NOVELTY_SCORE
                and max_similarity <= MAX_SIMILARITY_ALLOWED
                and not opening_repeat
            ):
                break

        # Fallback if all attempts were filtered out by length or duplicate checks.
        if best_candidate is None:
            hook = random.choice(self._hooks)
            template = random.choice(data["script_templates"])
            cta = self._pick(data.get("ctas", ["Subscribe for daily stories."]))
            script = self._fill_template(template, hook, data, cta)
            escalation = self._pick_escalation(niche, history_count)
            if escalation:
                script = self._inject_before_cta(script, cta, escalation)
            best_candidate = {"hook": hook, "script": script, "cta": cta, "novelty": 0.0}

        title = self._generate_title(best_candidate["hook"])
        logger.info(
            "Generated script for niche=%s, words=%s, novelty=%.2f",
            niche,
            len(best_candidate["script"].split()),
            best_candidate["novelty"],
        )
        return {
            "niche": niche,
            "hook": best_candidate["hook"],
            "script": best_candidate["script"],
            "title": title,
            "pexels_query": pexels_query,
            "pexels_queries": data["pexels_queries"],
            "cta": best_candidate["cta"],
            "seo": self._generate_seo(title, niche),
        }

    def _fill_template(self, template: str, hook: str, data: dict, cta: str) -> str:
        replacements = {"hook": hook, "cta": cta}

        # All single-value arrays in the niche data become template placeholders
        field_map = {
            # legacy keys
            "action": "actions",
            "conflict": "conflicts",
            "moral_lesson": "lessons",
            "clue": "clues",
            "red_herring": "red_herrings",
            "setup": "setups",
            "escalation": "escalations",
            "reveal": "reveals",
            "low_point": "low_points",
            "result": "results",
            "partner": "partners",
            "realization": "realizations",
            # new keys
            "character": "characters",
            "dead_person": "dead_persons",
            "time": "times",
            "timeframe": "timeframes",
            "secret_message": "secret_messages",
            "tense_action": "tense_actions",
            "discovery": "discoveries",
            "discovery_detail": "discovery_details",
            "final_message": "final_messages",
            "horror_detail": "horror_details",
            "closing_line": "closing_lines",
            "turning_point": "turning_points",
            "lesson": "lessons",
            "twist": "twists",
            "victim": "victims",
            "betrayal": "betrayals",
            "low_points": "low_points",
            "decisions": "decisions",
            "results": "results",
            "year": "years",
            "name": "names",
            "partner_name": "partner_names",
        }
        for placeholder, key in field_map.items():
            if key in data:
                replacements[placeholder] = self._pick(data[key])

        result = template
        if "{hook}" not in template:
            result = f"{hook} {result}"
        for k, v in replacements.items():
            result = result.replace("{" + k + "}", v)

        return self._clean_script(result)

    def _clean_script(self, text: str) -> str:
        text = re.sub(r'\.{2,}(?!\.)|\.\s+\.', '.', text)
        # Capitalize first letter after any sentence-ending punctuation
        text = re.sub(r'([.?!])\s+([a-z])', lambda m: m.group(1) + ' ' + m.group(2).upper(), text)
        text = text[0].upper() + text[1:] if text else text
        return text.strip()

    def _pick(self, lst: list) -> str:
        return random.choice(lst) if lst else ""

    def _pick_escalation(self, niche: str, history_count: int) -> str:
        if niche == "horror":
            tier = min(history_count // 4, len(HORROR_ESCALATIONS) - 1)
            return HORROR_ESCALATIONS[tier]
        if niche == "mystery":
            tier = min(history_count // 5, len(MYSTERY_ESCALATIONS) - 1)
            return MYSTERY_ESCALATIONS[tier]
        return ""

    def _inject_before_cta(self, script: str, cta: str, extra_line: str) -> str:
        idx = script.rfind(cta)
        if idx == -1:
            return self._clean_script(f"{script} {extra_line}")
        prefix = script[:idx].rstrip()
        suffix = script[idx:].lstrip()
        return self._clean_script(f"{prefix} {extra_line} {suffix}")

    def _script_fingerprint(self, script: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", script.lower()).strip()

    def _opening_fingerprint(self, script: str) -> str:
        parts = [s.strip() for s in re.split(r"[.?!]", script) if s.strip()]
        if not parts:
            return ""
        opening = " ".join(parts[0].lower().split()[:12])
        return re.sub(r"[^a-z0-9]+", " ", opening).strip()

    def _tokenize(self, script: str) -> set[str]:
        words = re.findall(r"[a-zA-Z']+", script.lower())
        return {w for w in words if len(w) > 3 and w not in STOPWORDS}

    def _max_similarity(self, script: str, recent_scripts: list[str]) -> float:
        if not recent_scripts:
            return 0.0
        tokens = self._tokenize(script)
        if not tokens:
            return 0.0
        max_similarity = 0.0
        for old in recent_scripts:
            other = self._tokenize(old)
            if not other:
                continue
            union = tokens | other
            if not union:
                continue
            similarity = len(tokens & other) / len(union)
            if similarity > max_similarity:
                max_similarity = similarity
        return max_similarity

    def _novelty_score(self, script: str, recent_scripts: list[str]) -> float:
        if not recent_scripts:
            return 1.0
        max_similarity = self._max_similarity(script, recent_scripts)
        return 1.0 - max_similarity

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
