import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import google.generativeai as genai

from app.core.config import settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class GeminiFailedError(RuntimeError):
    """Raised when Gemini story generation fails. Pipeline should notify the user."""

NICHE_PROMPTS = {
    "horror": {
        "genre": "horror",
        "tone": "terrifying, suspenseful, and deeply unsettling",
        "elements": "ghosts, unexplained messages from the dead, dark secrets, paranormal dread",
        "ending": "a chilling twist or revelation that leaves the viewer disturbed",
    },
    "mystery": {
        "genre": "mystery/thriller",
        "tone": "tense, suspenseful, and intellectually gripping",
        "elements": "hidden clues, red herrings, unexpected betrayals, shocking revelations",
        "ending": "a plot twist that reframes everything the viewer just heard",
    },
    "paranormal": {
        "genre": "paranormal horror",
        "tone": "eerie, atmospheric, and deeply unsettling with a sense of genuine dread",
        "elements": "ghost sightings, EVP recordings, unexplained phenomena, haunted locations, apparitions",
        "ending": "an encounter with a paranormal entity or evidence that something non-human is present",
    },
    "twist_endings": {
        "genre": "psychological thriller with a devastating twist ending",
        "tone": "calm and methodical that slowly builds to a reality-shattering revelation",
        "elements": "hidden truths, fabricated realities, identity deception, unreliable narration",
        "ending": "a single twist reveal in the last 2-3 sentences that completely reframes the entire story",
    },
    "psychological": {
        "genre": "psychological horror",
        "tone": "creeping, claustrophobic, and deeply disturbing — the horror is in the mind",
        "elements": "gaslighting, memory manipulation, reality distortion, isolation, self-doubt",
        "ending": "the protagonist realizing the true nature of what has been done to their mind",
    },
    "supernatural": {
        "genre": "supernatural horror",
        "tone": "ancient, oppressive, and cosmically frightening — something beyond human comprehension",
        "elements": "demonic entities, curses, dark rituals, possessed objects, forces beyond science",
        "ending": "the protagonist confronting or being claimed by the supernatural force",
    },
    "slasher": {
        "genre": "survival slasher horror",
        "tone": "pulse-pounding, claustrophobic, and viscerally tense",
        "elements": "a stalker or hunter, an isolated location, survival decisions, cat-and-mouse tension",
        "ending": "a shocking survival moment or terrifying realization about the hunter",
    },
    "folk_horror": {
        "genre": "folk horror",
        "tone": "deeply unsettling, culturally rooted, and quietly terrifying — the community IS the threat",
        "elements": "isolated village communities, ancient rituals, old traditions with dark purposes, outsiders as sacrificial targets",
        "ending": "the protagonist realizing the true nature of the community's traditions — and their role in them",
    },
}

GENRE_LABELS = {
    "horror": "Horror",
    "mystery": "Mystery",
    "paranormal": "Paranormal",
    "twist_endings": "Twist",
    "psychological": "Psychological Horror",
    "supernatural": "Supernatural",
    "slasher": "Slasher",
    "folk_horror": "Folk Horror",
}

SEO_CONFIGS = {
    "horror": {
        "icon": "😱",
        "tagline": "One minute. One story. One nightmare.",
        "sub_tagline": "Watch till the end… the twist is waiting for you. 👀",
        "cta": "If this scared you, hit subscribe for daily horror shorts",
        "extras": "🩸 New scary stories every week\n👻 Ghosts • Mysteries • Dark Tales • Paranormal",
        "hashtags": "#shorts #horror #scary #creepy #ghoststory #thriller #haunted #paranormal #horrorshorts",
        "seo_keywords": "horror shorts, scary shorts, horror stories, ghost stories, creepy videos, short horror films, scary youtube shorts, haunted stories, paranormal shorts, dark stories, horror reels, 1 minute horror, horror twist story, spooky shorts",
        "tags": ["shorts", "horror", "scary", "creepy", "ghoststory", "thriller", "haunted", "paranormal", "horrorshorts", "horror shorts", "scary shorts", "horror stories", "ghost stories", "1 minute horror", "horror twist story"],
    },
    "mystery": {
        "icon": "🔍",
        "tagline": "One minute. One mystery. Zero answers.",
        "sub_tagline": "Watch till the end… the truth will shock you. 😱",
        "cta": "Subscribe for daily mystery shorts",
        "extras": "🎯 New mysteries every week\n🕵️ Thrillers • Twists • Dark Secrets • Unsolved Cases",
        "hashtags": "#shorts #mystery #thriller #suspense #crimestory #detective #mysterystory #crimethriller #mysteryshorts",
        "seo_keywords": "mystery shorts, thriller shorts, mystery stories, crime stories, dark secrets, short mystery films, mystery youtube shorts, unsolved mysteries, detective stories, plot twist shorts, 1 minute mystery, mystery twist story",
        "tags": ["shorts", "mystery", "thriller", "suspense", "crimestory", "detective", "mysterystory", "crimethriller", "mysteryshorts", "mystery shorts", "thriller shorts", "plot twist shorts", "1 minute mystery"],
    },
    "paranormal": {
        "icon": "👻",
        "tagline": "One minute. One encounter. One proof.",
        "sub_tagline": "Watch till the end… you will not sleep after this. 😰",
        "cta": "Subscribe for daily paranormal encounters",
        "extras": "🔮 Real paranormal stories every week\n👁 Ghosts • Apparitions • EVP • Haunted Places",
        "hashtags": "#shorts #paranormal #ghost #haunted #supernatural #spiritworld #ghoststory #paranormalactivity #horrorshorts",
        "seo_keywords": "paranormal shorts, ghost shorts, haunted stories, paranormal activity, spirit encounters, ghost sighting shorts, haunted house shorts, EVP recordings, paranormal horror, 1 minute paranormal, ghost story shorts",
        "tags": ["shorts", "paranormal", "ghost", "haunted", "supernatural", "spiritworld", "ghoststory", "paranormalactivity", "horrorshorts", "paranormal shorts", "ghost shorts", "haunted stories", "spirit encounters", "1 minute paranormal"],
    },
    "twist_endings": {
        "icon": "🌀",
        "tagline": "One minute. One story. One ending that changes everything.",
        "sub_tagline": "Watch till the very last second. The twist will break your brain. 🤯",
        "cta": "Subscribe for daily twist endings",
        "extras": "💥 New plot twists every week\n🎭 Stories • Reveals • Mind-Bending Endings",
        "hashtags": "#shorts #plottwist #twist #mindblown #shockingending #twistending #thriller #story #twiststory",
        "seo_keywords": "twist ending shorts, plot twist shorts, shocking ending stories, mind-bending shorts, twist story shorts, story with twist, youtube shorts twist, 1 minute twist story, plot twist horror, narrative twist shorts",
        "tags": ["shorts", "plottwist", "twist", "mindblown", "shockingending", "twistending", "thriller", "story", "twiststory", "twist ending shorts", "plot twist shorts", "shocking ending stories", "1 minute twist"],
    },
    "psychological": {
        "icon": "🧠",
        "tagline": "One minute. One mind. Zero certainty.",
        "sub_tagline": "Watch till the end… and then question everything you just heard. 😶",
        "cta": "Subscribe for daily psychological horror",
        "extras": "🔪 New mind horror every week\n🪞 Gaslighting • Memory • Reality • Control",
        "hashtags": "#shorts #psychologicalhorror #mindbending #gaslighting #thriller #horror #dark #psychologicalthriller #mentalhorror",
        "seo_keywords": "psychological horror shorts, mind horror shorts, gaslighting horror, psychological thriller shorts, mind bending horror, reality horror, mental manipulation story, psychological horror 1 minute, mind horror youtube shorts",
        "tags": ["shorts", "psychologicalhorror", "mindbending", "gaslighting", "thriller", "horror", "psychologicalthriller", "mentalhorror", "psychological horror shorts", "mind horror shorts", "reality horror", "1 minute psychological horror"],
    },
    "supernatural": {
        "icon": "🔱",
        "tagline": "One minute. One force. Beyond all understanding.",
        "sub_tagline": "Watch till the end… some things cannot be undone. 😨",
        "cta": "Subscribe for daily supernatural horror",
        "extras": "⚡ New supernatural stories every week\n👁 Demons • Curses • Rituals • Dark Forces",
        "hashtags": "#shorts #supernatural #demon #curse #horror #occult #darkmagic #supernaturalhorror #horrorshorts",
        "seo_keywords": "supernatural horror shorts, demon horror shorts, cursed object horror, occult horror shorts, dark ritual horror, supernatural youtube shorts, 1 minute supernatural horror, demonic horror story, curse horror shorts",
        "tags": ["shorts", "supernatural", "demon", "curse", "horror", "occult", "darkmagic", "supernaturalhorror", "horrorshorts", "supernatural horror shorts", "demon horror shorts", "cursed object horror", "1 minute supernatural"],
    },
    "slasher": {
        "icon": "🔪",
        "tagline": "One minute. One survivor. Zero guarantees.",
        "sub_tagline": "Watch till the end… if you dare. 😰",
        "cta": "Subscribe for daily survival horror",
        "extras": "🏃 New slasher stories every week\n🚪 Stalkers • Isolation • Survival • Dark Endings",
        "hashtags": "#shorts #slasher #horror #survivalhorror #stalker #scarystory #horrorshorts #thriller #horrorfan",
        "seo_keywords": "slasher horror shorts, survival horror shorts, stalker horror story, isolated horror story, slasher youtube shorts, 1 minute slasher, survival horror 1 minute, horror chase story, dark thriller shorts",
        "tags": ["shorts", "slasher", "horror", "survivalhorror", "stalker", "scarystory", "horrorshorts", "thriller", "slasher horror shorts", "survival horror shorts", "stalker horror story", "1 minute slasher"],
    },
    "folk_horror": {
        "icon": "🌾",
        "tagline": "One minute. One village. One ancient secret.",
        "sub_tagline": "Watch till the end… some traditions never die. 😱",
        "cta": "Subscribe for daily folk horror",
        "extras": "🕯 New folk horror every week\n🌑 Villages • Rituals • Ancient Dread • Dark Traditions",
        "hashtags": "#shorts #folkhorror #horror #ritual #darkfolklore #villagehorror #ancientevil #horrorshorts #scarystory",
        "seo_keywords": "folk horror shorts, village horror story, ritual horror shorts, dark folklore horror, ancient horror story, community horror shorts, folk horror youtube shorts, 1 minute folk horror, rural horror story, harvest horror",
        "tags": ["shorts", "folkhorror", "horror", "ritual", "darkfolklore", "villagehorror", "ancientevil", "horrorshorts", "folk horror shorts", "village horror story", "ritual horror shorts", "1 minute folk horror"],
    },
}

STORY_FORMATS = [
    "Real-time single-location incident where events unfold minute by minute.",
    "Recovered evidence narrative using logs, messages, or recordings as anchors.",
    "Confession format where the protagonist admits what happened after the event.",
    "Rule-based setup where breaking one specific rule triggers escalating danger.",
    "Countdown structure tied to a specific time limit before a reveal.",
    "False-safe scenario where an apparent rescue or solution becomes the final threat.",
]

VISUAL_MOTIFS = [
    "rain-soaked neon streets at night",
    "clinical fluorescent interiors with long empty corridors",
    "rural daylight unease with abandoned fields and silence",
    "grainy security-camera aesthetics in parking and hall spaces",
    "fog-heavy roads with isolated headlights and distant silhouettes",
    "decaying domestic spaces with flickering warm practical lights",
]

CONCEPT_KEYWORDS = {
    "mirror": ["mirror", "reflection", "glass"],
    "phone_call": ["phone call", "voicemail", "unknown number", "ringing phone"],
    "chat_message": ["text", "message", "chat", "notification"],
    "basement": ["basement", "cellar", "underground"],
    "door_lock": ["locked door", "deadbolt", "door chain", "jammed lock", "spare key"],
    "camera_feed": ["camera", "cctv", "security feed", "monitor"],
    "clock_time": ["3:33", "midnight", "2:17 am", "03:00 am", "countdown timer"],
    "dead_contact": ["dead", "funeral", "grave", "obituary"],
    "haunted_object": ["box", "doll", "portrait", "object", "artifact"],
    "memory_manipulation": ["memory", "remember", "forgot", "imagined", "proof"],
    "ritual_curse": ["ritual", "curse", "symbol", "demon", "entity"],
    "home_intrusion": ["footsteps", "hallway", "closet", "attic", "window"],
}

CTA_BUCKETS = {
    "engagement": [
        "Comment your theory before reading anyone else's.",
        "If this twist hit you, drop a Like and tell me why.",
        "Type the creepiest line in this story in the comments.",
    ],
    "challenge": [
        "Watch this again alone tonight and tell me if it feels different.",
        "If you can watch this with the lights off, prove it in the comments.",
        "Dare accepted? Replay this at 3 AM and tag a brave friend.",
    ],
    "community": [
        "Team ghost or team logic? Pick a side below.",
        "Vote now: coincidence or curse?",
        "Would you stay or run? Answer with one word.",
    ],
    "cliffhanger": [
        "Want part 2 of this case? Comment PART 2.",
        "If this gets enough comments, I will drop the hidden follow-up.",
        "There is a deeper layer to this story. Say NEXT for it.",
    ],
}


class GeminiStoryEngine:
    """Generates unique story scripts via Gemini API. Raises GeminiFailedError on failure."""

    def __init__(self):
        self._niches = self._load_niches()
        self._hooks = self._load_hooks()
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = genai.GenerativeModel("gemini-2.5-flash-lite")

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

    def generate(
        self,
        niche: str,
        recent_scripts: Iterable[str] | None = None,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
    ) -> dict:
        recent = list(recent_scripts or [])
        niche_data = self._niches.get(niche, {})
        motif = self._select_visual_motif()
        pexels_queries = self._build_pexels_queries(niche_data, motif)
        pexels_query = random.choice(pexels_queries)

        hook, script, cta, title_seed = self._generate_with_fallback(
            niche, recent, motif, series_context, series_episode_number, series_name
        )

        title = self._generate_title(niche, hook, title_seed)
        return {
            "niche": niche,
            "hook": hook,
            "script": script,
            "cta": cta,
            "title": title,
            "pexels_query": pexels_query,
            "pexels_queries": pexels_queries,
            "seo": self._generate_seo(title, niche),
        }

    def _generate_with_fallback(
        self,
        niche: str,
        recent: list[str],
        motif: str,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
    ) -> tuple[str, str, str, str]:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                return self._call_gemini(
                    niche=niche,
                    recent_scripts=recent,
                    motif=motif,
                    series_context=series_context,
                    series_episode_number=series_episode_number,
                    series_name=series_name,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "[GeminiStoryEngine] Attempt %d failed (%s: %s)",
                    attempt, type(e).__name__, str(e)[:180],
                )
        assert last_error is not None
        logger.error(
            "[GeminiStoryEngine] Gemini failed after retries (%s: %s). Aborting — no template fallback.",
            type(last_error).__name__, str(last_error)[:200],
        )
        raise GeminiFailedError(f"{type(last_error).__name__}: {str(last_error)[:300]}") from last_error

    def _call_gemini(
        self,
        niche: str,
        recent_scripts: list[str],
        motif: str = "",
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
    ) -> tuple[str, str, str, str]:
        # Summarize recent story openings so Gemini actively avoids them
        recent_openings = []
        for s in recent_scripts[:15]:
            first_sentence = re.split(r"[.?!]", s)[0].strip()
            if first_sentence:
                recent_openings.append(f"- {first_sentence[:100]}")
        avoid_block = ""
        if recent_openings:
            avoid_block = (
                "\n\nCRITICAL: Do NOT start the story with ANY of these opening lines or anything similar:\n"
                + "\n".join(recent_openings)
                + "\nEvery story MUST have a completely different opening situation, character, and premise."
            )
        blocked_tags = self._recent_concept_tags(recent_scripts[:30])
        if blocked_tags:
            avoid_block += (
                "\n\nCONCEPT FRESHNESS: Avoid these recently used concepts: "
                + ", ".join(sorted(blocked_tags))
                + ". Use a different core mechanism and reveal."
            )
        format_instruction = random.choice(STORY_FORMATS)
        continuity_block = ""
        if series_context.strip():
            continuity_block = (
                "\n\nSERIES CONTINUITY MODE:\n"
                f"- Series name: {series_name or 'Unnamed Series'}\n"
                f"- Current episode: {series_episode_number or 'unknown'}\n"
                "- This episode MUST continue directly from prior events.\n"
                "- Reuse key entities, unresolved threat, and consequences from previous episodes.\n"
                "- Do NOT reset premise as a fresh standalone story.\n"
                "- Advance the arc with new revelations while preserving internal logic.\n"
                "- Prior context:\n"
                f"{series_context}\n"
            )

        prompt = f"""You are an expert short-form storyteller for YouTube Shorts. Generate a **high-retention story** for a ~60-second video in the genres of **Horror, Mystery, Paranormal, Thriller, Urban Legend, Psychological Fear, Supernatural, or Dark Twist**.

The voiceover is read at a fast pace (+50% speed). To fill a full 60 seconds at that speed the story must be **150–170 words**. Do NOT write fewer words — an under-length story leaves dead air at the end.

### Requirements:

* Length: **150–170 words** (story only — no CTA, no sign-off)
* Start the script with the exact hook sentence. The first 10 seconds must be impossible to ignore.
* In the first 35 words, include one disturbing question, impossible discovery, or immediate danger.
* Maintain suspense every few lines.
* Use simple, cinematic language.
* Include 1 main character only (unless necessary).
* Use a MIX of character names — American (Jake, Emma, Ryan, Sarah, Tyler, Ashley, Michael, Jessica, Chris, Melissa), British (Oliver, Charlotte, Harry, Amelia, James, Sophie, George, Lily, Thomas, Isabelle), or Indian (Riya, Arjun, Meera, Kabir, Priya, Dev, Ananya, Vikram). Do NOT always use Indian names — vary nationality each story.
* Story should feel realistic at first, then become disturbing.
* Build tension quickly.
* End with an **unexpected twist ending** that shocks viewers.
* Final line must be memorable and creepy.
* Story format for this generation: {format_instruction}
* Keep the visual atmosphere compatible with this motif: {motif}
* Avoid slow setup, backstory, or unnecessary details.
* Create a clickable YouTube Shorts title under 58 characters. It must feel complete, specific, and curiosity-driven.
* The title must NOT include hashtags, markdown, quotes, ellipsis, or trailing incomplete phrases.
* DO NOT include any CTA, subscribe line, or sign-off — the story ends on the twist.
* DO NOT use: ellipsis (...), em dashes (—), asterisks, or markdown formatting in the script.
* Write in plain prose — no bullet points, no headers, no special characters.

### Structure:

1. **Hook (0-5 sec):** shocking or mysterious opening line
2. **Build-up (5-40 sec):** strange events escalate
3. **Reveal (40-55 sec):** terrifying truth appears
4. **Twist Ending (55-60 sec):** unexpected final punch

### Tone:

Dark, suspenseful, binge-worthy, viral, cinematic.

### Example Hooks (create your OWN completely unique hook — do NOT copy or resemble these):

* Every night, someone knocks on my window from the 10th floor.
* I found a photo of myself sleeping, taken yesterday.
* The voice from my basement knew my name.
* My dead grandmother called me at 3:03 AM.
* I moved into a house where mirrors blink first.
{avoid_block}
{continuity_block}

Respond with ONLY valid JSON. No explanation, no markdown fences, just the raw JSON object:
{{"hook": "<opening hook sentence only>", "title": "<catchy complete title under 58 characters, no hashtags>", "script": "<150-170 word story starting with the exact hook and ending on the twist — no CTA>"}}"""


        response = self._model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=1.0,
                top_p=0.95,
                max_output_tokens=2048,
            ),
        )
        text = response.text.strip()

        # Strip markdown code fences if Gemini wraps in them
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        text = text.strip()

        parsed = json.loads(text)
        hook = parsed["hook"].strip()
        title_seed = parsed.get("title", "").strip()
        script = parsed["script"].strip()
        script = self._ensure_hook_starts_script(script, hook)
        self._enforce_concept_freshness(script, blocked_tags)

        # Ensure story body ends with a complete sentence.
        script = self._close_incomplete_sentence(script)

        # Always stitch a CTA from our controlled pool. Prefer niche-specific
        # template CTAs so production can be tuned without changing code.
        cta = self._choose_cta(niche)
        script = self._append_cta(script, cta)

        word_count = len(script.split())
        logger.info(
            "[GeminiStoryEngine] Generated niche=%s words=%d cta='%s' hook='%s...'",
            niche, word_count, cta, hook[:50],
        )

        return hook, script, cta, title_seed

    _CTA_POOL = [
        "If this scared you, smash Like before it finds you.",
        "Subscribe now, or tonight's story becomes yours.",
        "Like this video if your heart skipped a beat.",
        "Dare to watch more? Hit Subscribe.",
        "If you're still watching, you're brave enough to subscribe.",
        "Like now before the lights go out.",
        "Subscribe for daily nightmares in 60 seconds.",
        "If this gave you chills, drop a Like.",
        "Subscribe, the next horror story is already waiting.",
        "Like if you'd never enter that house.",
        "Only the fearless subscribe to Horror Shorts.",
        "Tap Like if you got goosebumps.",
        "Subscribe now, we know you'll come back anyway.",
        "Like this video to survive the next story.",
        "If you love twist endings, subscribe now.",
        "Hit Subscribe before midnight.",
        "Like if that ending shocked you.",
        "Subscribe for horror that ends too late to sleep.",
        "If you heard something behind you, Like now.",
        "Join the fearless. Subscribe to Horror Shorts.",
    ]

    def _cta_pool_for(self, niche: str) -> list[str]:
        niche_ctas = self._niches.get(niche, {}).get("ctas", [])
        clean_ctas = [cta.strip() for cta in niche_ctas if isinstance(cta, str) and cta.strip()]
        return clean_ctas or self._CTA_POOL

    def _choose_cta(self, niche: str) -> str:
        niche_ctas = self._niches.get(niche, {}).get("ctas", [])
        clean_niche_ctas = [cta.strip() for cta in niche_ctas if isinstance(cta, str) and cta.strip()]
        if clean_niche_ctas:
            return random.choice(clean_niche_ctas)
        pool = self._cta_pool_for(niche)
        bucket = random.choice(list(CTA_BUCKETS.values()))
        return random.choice(pool + bucket)

    def _select_visual_motif(self) -> str:
        iso_week = datetime.now().isocalendar().week
        return VISUAL_MOTIFS[iso_week % len(VISUAL_MOTIFS)]

    def _build_pexels_queries(self, niche_data: dict, motif: str) -> list[str]:
        base_queries = niche_data.get("pexels_queries", ["dark horror scene", "night horror", "scary dark"])
        motif_queries = [f"{q} {motif}" for q in base_queries[:4]]
        return list(dict.fromkeys(motif_queries + base_queries))

    def _concept_tags(self, text: str) -> set[str]:
        normalized = re.sub(r"\s+", " ", (text or "").lower())
        tags: set[str] = set()
        for tag, markers in CONCEPT_KEYWORDS.items():
            if any(marker in normalized for marker in markers):
                tags.add(tag)
        return tags

    def _recent_concept_tags(self, recent_scripts: list[str]) -> set[str]:
        tags: set[str] = set()
        for script in recent_scripts:
            tags.update(self._concept_tags(script))
        return tags

    def _enforce_concept_freshness(self, script: str, blocked_tags: set[str]) -> None:
        if not blocked_tags:
            return
        overlap = self._concept_tags(script) & blocked_tags
        if len(overlap) >= 2:
            raise ValueError(f"Concept overlap too high: {sorted(overlap)}")

    def _append_cta(self, script: str, cta: str) -> str:
        script = script.strip()
        cta = cta.strip()
        if not cta:
            return script
        if cta in script:
            return script
        return f"{script} {cta}".strip()

    def _ensure_hook_starts_script(self, script: str, hook: str) -> str:
        script = script.strip()
        hook = hook.strip()
        if not hook:
            return script

        def normalize(text: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

        hook_words = normalize(hook).split()
        script_opening = " ".join(normalize(script).split()[:len(hook_words)])
        if hook_words and script_opening == " ".join(hook_words):
            return script
        return f"{hook} {script}".strip()

    def _close_incomplete_sentence(self, script: str) -> str:
        """Trim or close a mid-sentence tail so the story body ends cleanly."""
        script = script.strip()
        if script and script[-1] not in ".!?":
            last_end = max(script.rfind("."), script.rfind("!"), script.rfind("?"))
            if last_end > len(script) // 2:
                script = script[: last_end + 1].strip()
                logger.warning("[GeminiStoryEngine] Story trimmed to last complete sentence")
            else:
                script = script.rstrip() + "."
        return script

    def _generate_title(self, niche: str, hook: str, title_seed: str = "") -> str:
        title = self._clean_title(title_seed) or self._clean_title(hook)
        if not title:
            title = "This Ending Will Haunt You"

        suffix = " #Shorts"
        max_title_chars = 100 - len(suffix)
        if len(title) > max_title_chars:
            title = title[:max_title_chars].rsplit(" ", 1)[0].rstrip(",;:!?")
        if len(title) > 62:
            title = title[:62].rsplit(" ", 1)[0].rstrip(",;:!?")
        return f"{title}{suffix}"

    def _clean_title(self, title: str) -> str:
        title = re.sub(r"#\w+", "", title or "")
        title = re.sub(r"[\"'`*_]+", "", title)
        title = title.replace("...", " ")
        title = title.replace("—", " ").replace("–", " ")
        title = re.sub(r"\s+", " ", title).strip(" .,:;-")
        if not title:
            return ""
        # Keep titles punchy without turning hashtags into broken multi-word tags.
        title = re.sub(r"[A-Za-z]+('[A-Za-z]+)?", lambda m: m.group(0).capitalize(), title)
        return title

    def _generate_seo(self, title: str, niche: str) -> dict:
        ch = settings.CHANNEL_NAME
        cfg = SEO_CONFIGS.get(niche, SEO_CONFIGS["horror"])
        description = (
            f"{title}\n\n"
            f"{cfg['icon']} {cfg['tagline']}\n\n"
            f"{cfg['sub_tagline']}\n"
            f"{cfg['cta']} → @{ch}\n\n"
            f"{cfg['extras']}\n\n"
            f"{cfg['hashtags']}\n\n"
            f"{cfg['seo_keywords']}"
        )
        return {
            "title": title,
            "description": description,
            "tags": cfg["tags"],
        }
