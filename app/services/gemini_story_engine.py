import json
import logging
import random
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import google.generativeai as genai

from app.core.config import settings
from app.services.premise_bank import describe_premise, pick_premise

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
    "social_media": ["social media", "instagram", "livestream", "followers", "comment section"],
    "photograph_letter": ["photograph", "photo", "polaroid", "handwritten letter", "old note"],
    "power_outage": ["power went out", "power outage", "lights flickered off", "blackout"],
    "static_noise": ["static", "white noise", "radio static", "buzzing on the line"],
    "hospital": ["hospital", "er room", "hospital bed", "nurse station"],
    "car_breakdown": ["car broke down", "engine stalled", "flat tire", "stranded on the road"],
    "hotel_room": ["hotel room", "motel", "hotel hallway", "front desk clerk", "hotel"],
    "webcam_stream": ["webcam", "laptop camera", "video call", "screen recording"],
    "tape_recording": ["tape recording", "cassette", "recorder", "voice memo"],
    "doppelganger": ["doppelganger", "exact copy", "looked exactly like", "impostor"],
    "missing_time": ["missing time", "lost hours", "gap in memory", "hours had passed"],
    "family_secret": ["family secret", "adopted", "biological father", "hidden sibling"],
    "forest_isolation": ["forest", "woods", "hiking trail", "cabin in the woods"],
    "wedding_object": ["wedding ring", "engagement ring", "wedding dress", "bridal"],
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
}


SERIES_CTA_TEMPLATES = [
    "Part {next} drops tomorrow. Follow so you don't miss it.",
    "Part {next} is tomorrow. Follow to see what happens next.",
    "This is not over. Follow for part {next} tomorrow.",
]

QUALITY_NONE = "none"
QUALITY_STRICT = "strict"
QUALITY_RELAXED = "relaxed"
QUALITY_ERROR_PREFIX = "Story failed quality check"
MODE_STANDALONE = "standalone"
MODE_CLIFFHANGER = "cliffhanger"
MODE_FINALE = "finale"
# The prompt targets 130-140 story words; these are the enforced limits.
STRICT_WORD_RANGE = (120, 155)
RELAXED_WORD_RANGE = (100, 175)
MAX_SCENES = 8
# The SDK has no default timeout, and a hung call would stall the whole scheduled job.
REQUEST_OPTIONS = {"timeout": 120}
RECENT_HOOK_OPENINGS = 6
DANGLING_LAST_WORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "with", "my", "your", "his", "her",
    "their", "in", "on", "at", "for", "from", "that",
}


@dataclass
class StoryDraft:
    hook: str
    script: str
    cta: str
    title_seed: str
    scene_queries: list = field(default_factory=list)
    scenes: list = field(default_factory=list)
    hook_card: str = ""
    on_screen_text: str = ""
    plan: dict = field(default_factory=dict)
    key_visual: dict | None = None


class GeminiStoryEngine:
    """Generates unique story scripts via Gemini API. Raises GeminiFailedError on failure."""

    def __init__(self):
        self._niches = self._load_niches()
        self._hooks = self._load_hooks()
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = genai.GenerativeModel(settings.GEMINI_STORY_MODEL)
        self._check_model = genai.GenerativeModel(settings.GEMINI_CHECK_MODEL)
        self._fallback_model = self._check_model

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

    def pick_premise(self, niche: str, recent_premises: list[dict] | None = None) -> dict:
        return pick_premise(niche, recent_premises)

    def generate(
        self,
        niche: str,
        recent_scripts: Iterable[str] | None = None,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        is_final_episode: bool = True,
        recent_titles: Iterable[str] | None = None,
        recent_hooks: Iterable[str] | None = None,
        recent_premises: list[dict] | None = None,
        premise: dict | None = None,
    ) -> dict:
        recent = list(recent_scripts or [])
        niche_data = self._niches.get(niche, {})
        premise = premise or pick_premise(niche, recent_premises)
        pexels_queries = self._build_pexels_queries(niche_data)

        draft = self._generate_with_fallback(
            niche, recent, premise, series_context, series_episode_number, series_name,
            is_final_episode, list(recent_titles or []), list(recent_hooks or []),
        )

        # Prepend story-specific scene queries so the pipeline fetches visually matched footage.
        if draft.scene_queries:
            pexels_queries = list(dict.fromkeys(draft.scene_queries + pexels_queries))
        pexels_query = pexels_queries[0] if pexels_queries else "dark horror scene"

        title = self._generate_title(niche, draft.hook, draft.title_seed)
        story_hashtags = self._extract_story_hashtags(draft.hook, title, niche)
        return {
            "niche": niche,
            "hook": draft.hook,
            "script": draft.script,
            "cta": draft.cta,
            "title": title,
            "pexels_query": pexels_query,
            "pexels_queries": pexels_queries,
            "scenes": draft.scenes,
            "hook_card": draft.hook_card,
            "on_screen_text": draft.on_screen_text,
            "key_visual": draft.key_visual,
            "story_format": premise["format"],
            "premise": {**premise, "plan": draft.plan},
            "seo": self._generate_seo(title, niche, story_hashtags),
        }

    def generate_series_title(self, niche: str, hook: str, script: str) -> str:
        prompt = (
            "You are naming a new horror/mystery YouTube Shorts story series based on its "
            "first episode.\n"
            f"Genre: {niche}\n"
            f"Episode 1 hook: {hook}\n"
            f"Episode 1 story: {script}\n\n"
            "Create ONE short, catchy series title (2-5 words) that sounds like a real "
            "streaming show name, grounded in this episode's premise, setting, or central "
            "object/threat. Do NOT use generic words like 'Horror Series' or 'Episode'. "
            "No quotes, no markdown, no trailing punctuation.\n\n"
            "Respond with ONLY the title text, nothing else."
        )
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = self._generate_story_content(
                    prompt,
                    # Thinking models spend output tokens before writing, so 32 is not enough.
                    genai.types.GenerationConfig(temperature=0.9, max_output_tokens=2048),
                )
                title = (response.text or "").strip()
                title = re.sub(r'["\'`*_]+', "", title)
                title = re.sub(r"\s+", " ", title).strip(" .,:;-")
                if len(title.split()) < 2 or len(title) > 60:
                    raise ValueError(f"Invalid series title generated: '{title}'")
                return title
            except Exception as e:
                last_error = e
        raise ValueError(f"Could not name series: {last_error}")

    def _generate_with_fallback(
        self,
        niche: str,
        recent: list[str],
        premise: dict,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        is_final_episode: bool = True,
        recent_titles: list[str] | None = None,
        recent_hooks: list[str] | None = None,
    ) -> StoryDraft:
        last_error: Exception | None = None
        blocked_tags = self._recent_concept_tags(recent[:30])
        common = dict(
            niche=niche,
            recent_scripts=recent,
            premise=premise,
            series_context=series_context,
            series_episode_number=series_episode_number,
            series_name=series_name,
            is_final_episode=is_final_episode,
            recent_titles=recent_titles,
            recent_hooks=recent_hooks,
        )

        # Tier 1: strict novelty and story-quality enforcement.
        for attempt in range(1, 6):
            try:
                return self._call_gemini(
                    **common,
                    blocked_tags_override=blocked_tags,
                    overlap_fail_count=2,
                    quality=QUALITY_STRICT,
                    rejection_note=str(last_error) if self._is_quality_error(last_error) else "",
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "[GeminiStoryEngine] Attempt %d failed (%s: %s)",
                    attempt, type(e).__name__, str(e)[:180],
                )

        # Tier 2: relaxed retries when the failures were about the story, not the API.
        if self._is_concept_overlap_error(last_error) or self._is_quality_error(last_error):
            relaxed_blocked_tags = self._drop_most_common_blocked_tag(recent[:30], blocked_tags)
            for attempt in range(1, 4):
                try:
                    result = self._call_gemini(
                        **common,
                        blocked_tags_override=relaxed_blocked_tags,
                        overlap_fail_count=3,
                        quality=QUALITY_RELAXED,
                    )
                    logger.warning(
                        "[GeminiStoryEngine] Recovered via relaxed fallback on attempt %d",
                        attempt,
                    )
                    return result
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "[GeminiStoryEngine] Relaxed fallback attempt %d failed (%s: %s)",
                        attempt, type(e).__name__, str(e)[:180],
                    )

        # Tier 3: deterministic local template so schedules can still ship. A template
        # cannot continue an arc, so series episodes fail loudly instead.
        if series_episode_number is None:
            try:
                template_story = self._build_template_story(niche)
                hook = template_story["hook"]
                script = template_story["script"]
                script = self._ensure_hook_starts_script(script, hook)
                cta = self._choose_cta(niche)
                script = self._append_cta(script, cta)
                script = self._close_incomplete_sentence(script)
                title_seed = template_story["title"]
                logger.warning("[GeminiStoryEngine] Using deterministic template fallback for niche=%s", niche)
                return StoryDraft(hook=hook, script=script, cta=cta, title_seed=title_seed)
            except Exception as template_error:
                logger.error(
                    "[GeminiStoryEngine] Deterministic template fallback failed (%s: %s)",
                    type(template_error).__name__, str(template_error)[:200],
                )

        assert last_error is not None
        logger.error(
            "[GeminiStoryEngine] Gemini failed after all fallbacks (%s: %s). Aborting.",
            type(last_error).__name__, str(last_error)[:200],
        )
        raise GeminiFailedError(f"{type(last_error).__name__}: {str(last_error)[:300]}") from last_error

    def _call_gemini(
        self,
        niche: str,
        recent_scripts: list[str],
        premise: dict | None = None,
        series_context: str = "",
        series_episode_number: int | None = None,
        series_name: str = "",
        blocked_tags_override: set[str] | None = None,
        overlap_fail_count: int = 2,
        is_final_episode: bool = True,
        recent_titles: list[str] | None = None,
        recent_hooks: list[str] | None = None,
        quality: str = QUALITY_NONE,
        rejection_note: str = "",
    ) -> StoryDraft:
        premise = premise or pick_premise(niche)
        is_series = series_episode_number is not None
        is_cliffhanger_episode = is_series and not is_final_episode
        mode = MODE_CLIFFHANGER if is_cliffhanger_episode else (MODE_FINALE if is_series else MODE_STANDALONE)

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
            )
        # A series must reuse its own threat and objects, so novelty rules only apply to one-offs.
        blocked_tags: set[str] = set()
        if not is_series:
            blocked_tags = blocked_tags_override if blocked_tags_override is not None else self._recent_concept_tags(recent_scripts[:30])
            blocked_tags = blocked_tags - self._concept_tags(f"{premise['setting']} {premise['threat']}")
        if blocked_tags:
            avoid_block += (
                "\n\nCONCEPT FRESHNESS: Avoid these recently used concepts: "
                + ", ".join(sorted(blocked_tags))
                + ". Use a different core mechanism and reveal."
            )
        recent_titles = recent_titles or []
        recent_hooks = recent_hooks or []
        if recent_titles:
            avoid_block += (
                "\n\nTITLE FRESHNESS: Do NOT reuse or closely resemble any of these previously "
                "used titles: " + "; ".join(t[:70] for t in recent_titles[:20])
            )
        if recent_hooks:
            avoid_block += (
                "\n\nHOOK FRESHNESS: Do NOT reuse or closely resemble any of these previously "
                "used hook sentences: " + "; ".join(h[:100] for h in recent_hooks[:20])
            )
        if rejection_note:
            avoid_block += f"\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix this: {rejection_note[:300]}"

        if mode == MODE_CLIFFHANGER:
            ending_requirement = (
                "* End on a CLIFFHANGER: this episode reveals something real, then cuts away at "
                "the moment of maximum tension. The last line must be a concrete event that leads "
                "straight into the next episode, never vague dread."
            )
            final_beat = (
                "4. **Cliffhanger cut (last 15%):** Escalate to the most tense moment, then stop. "
                "Do not resolve the series' main question."
            )
            plan_note = (
                '"central_question": what this episode asks, "answer": what this episode reveals, '
                '"protagonist_fate": where the episode leaves them, "planted_clue": the detail that '
                "points at the next episode"
            )
        else:
            ending_requirement = (
                "* The story must be COMPLETE. Answer the central question out loud in the script, "
                "and make the protagonist's fate unmistakable. The viewer must never wonder what "
                "happened. Do not imply a sequel, or that it is only the beginning."
            )
            final_beat = (
                "4. **Payoff (last 15%):** Answer the central question using the planted clue. "
                "Finish on one short, memorable sentence that closes the story."
            )
            plan_note = (
                '"central_question": the one question the story raises, "answer": its specific '
                'answer, "protagonist_fate": exactly what happens to them, "planted_clue": an early '
                "detail that the ending pays off"
            )
        continuity_block = ""
        if is_series:
            continuity_block = (
                "\n\nSERIES MODE (one continuous story across episodes):\n"
                f"- Series name: {series_name or 'Unnamed Series'}\n"
                f"- Current episode: {series_episode_number}\n"
                "- Follow the series plan exactly. Keep the same protagonist, setting and threat.\n"
                "- From episode 2 onward, the hook picks up the instant the previous episode ended, "
                "and the first two sentences briefly restate what just happened so a new viewer "
                "can follow along.\n"
                "- Plant what the next episode needs. Never contradict earlier episodes.\n"
                f"{series_context}\n"
            )

        prompt = f"""You are an expert short-form storyteller for YouTube Shorts. Write one high-retention {niche.replace('_', ' ')} story for narration.

### Assigned premise (mandatory, do not swap any of these):
{describe_premise(premise, include_ending=mode != MODE_CLIFFHANGER)}

### Requirements:

* Length: **130 to 140 words** (story only, no CTA, no sign-off). Count them.
* Start the script with the exact hook sentence.
* Open directly on the impossible or dangerous detail. Do NOT open with stock actions like "You find", "You open", "You wake", "You receive", "I woke", or "It started".
* In the first 30 words, include one disturbing question, impossible discovery, or immediate danger.
* Vary sentence length: short punchy sentences at the hook and the ending, longer ones in the build-up.
* Use simple, visceral, cinematic language. One main character unless the premise needs more.
* Vary character names and nationality across American, British and Indian names.
* The story should feel realistic at first, then become deeply disturbing.
{ending_requirement}
* DO NOT include any CTA, subscribe line, or sign-off.
* DO NOT use ellipsis, em dashes, asterisks, quotation marks, or markdown in the script. Report speech without quotation marks.

### Structure (strict):

1. **Hook (first 5%):** One or two short sentences. Immediate dread.
2. **Build-up (to 65%):** Events escalate and the planted clue appears.
3. **Reveal (to 85%):** The truth surfaces. Short sharp sentences.
{final_beat}
{avoid_block}
{continuity_block}

### Plan first:
Before writing, fill in "plan" with: {plan_note}, "central_object": the one thing this story is about.

### On-screen fields:
* "hook_card": 3 to 5 words for a title card, adding intrigue without repeating the hook.
* "on_screen_text": up to 6 words matching the format, such as the rule being broken. Empty if not needed.

### Titles:
Give 3 distinct clickable title options under 58 characters. Complete, specific, curiosity-driven. No hashtags, markdown, quotes, or ellipsis.

### Scenes:
Give 6 to 8 "scenes" in story order, each matching the narration at that moment. "first_words" is the exact first four words of the sentence where the shot begins; the first scene begins at the very start. "query" is a 2 to 5 word Pexels stock video search for something common that actually exists on video, dark or at night where it fits (such as "empty motel corridor night" or "hand on door handle"). Each must be a different shot. Never search for impossible objects.

### Key visual:
"key_visual" is the single most striking moment: "first_words" as above and "image_prompt", a one-sentence vertical cinematic description of it with no text and no recognizable real people.

Respond with ONLY valid JSON in exactly this shape:
{{"plan": {{"central_question": "", "answer": "", "protagonist_fate": "", "planted_clue": "", "central_object": ""}}, "hook": "<opening hook sentence only>", "hook_card": "", "on_screen_text": "", "title": "", "title_alt_1": "", "title_alt_2": "", "scenes": [{{"first_words": "", "query": ""}}], "key_visual": {{"first_words": "", "image_prompt": ""}}, "script": "<story starting with the exact hook>"}}"""

        response = self._generate_story_content(
            prompt,
            genai.types.GenerationConfig(
                temperature=1.0,
                top_p=0.95,
                # Generous because thinking models spend output tokens before the JSON.
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )
        parsed = self._parse_json(response.text)
        hook = parsed["hook"].strip()
        script = parsed["script"].strip()
        script = self._ensure_hook_starts_script(script, hook)
        if quality != QUALITY_NONE:
            self._enforce_concept_freshness(script, blocked_tags, fail_overlap_count=overlap_fail_count)
            if quality == QUALITY_STRICT:
                self._enforce_opening_variety(hook, recent_hooks, is_series)

        script = self._close_incomplete_sentence(script)
        plan = parsed.get("plan") if isinstance(parsed.get("plan"), dict) else {}
        self._enforce_quality(script, plan, mode, quality, series_context)

        story_body = script
        cta = self._series_cta(series_episode_number) if is_cliffhanger_episode else self._choose_cta(niche)
        script = self._append_cta(script, cta)

        # Pick the best title from up to 3 variants Gemini returned.
        title_candidates = [
            parsed.get("title", "").strip(),
            parsed.get("title_alt_1", "").strip(),
            parsed.get("title_alt_2", "").strip(),
        ]
        valid_titles = [t for t in title_candidates if t and len(t) <= 58]
        title_seed = random.choice(valid_titles) if valid_titles else (title_candidates[0] or "")

        self._enforce_title_hook_freshness(hook, title_seed, recent_hooks, recent_titles)

        scenes = self._locate_scenes(story_body, parsed.get("scenes"))
        scene_queries = [s["query"] for s in scenes] or [
            q.strip() for q in parsed.get("scene_queries", []) if isinstance(q, str) and q.strip()
        ]
        key_visual = self._locate_key_visual(story_body, parsed.get("key_visual"))

        logger.info(
            "[GeminiStoryEngine] Generated niche=%s words=%d mode=%s cta='%s' hook='%s...' scene_queries=%s",
            niche, len(story_body.split()), mode, cta, hook[:50], scene_queries,
        )
        return StoryDraft(
            hook=hook,
            script=script,
            cta=cta,
            title_seed=title_seed,
            scene_queries=scene_queries,
            scenes=scenes,
            hook_card=self._clean_hook_card(parsed.get("hook_card", "")),
            on_screen_text=self._clean_on_screen_text(parsed.get("on_screen_text", "")),
            plan=plan,
            key_visual=key_visual,
        )

    def _generate_story_content(self, prompt: str, config):
        """Use the writing model, dropping to the fallback if it is retired or out of quota."""
        try:
            return self._model.generate_content(prompt, generation_config=config, request_options=REQUEST_OPTIONS)
        except Exception as e:
            fallback = getattr(self, "_fallback_model", None)
            if fallback is None or not re.search(r"404|not found|429|quota", str(e), re.IGNORECASE):
                raise
            logger.warning("[GeminiStoryEngine] Story model unavailable (%s), using fallback", str(e)[:120])
            return fallback.generate_content(prompt, generation_config=config, request_options=REQUEST_OPTIONS)

    @staticmethod
    def _parse_json(text: str):
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        return json.loads(text.strip())

    def _enforce_opening_variety(self, hook: str, recent_hooks: list[str], is_series: bool) -> None:
        """Reject hooks that open with the same two words as one of the last few."""
        if is_series:
            return
        opening = self._normalize_for_dedup(hook).split()[:2]
        for prior in recent_hooks[:RECENT_HOOK_OPENINGS]:
            if opening and opening == self._normalize_for_dedup(prior).split()[:2]:
                raise ValueError(f"{QUALITY_ERROR_PREFIX}: hook opens like a recent one ({' '.join(opening)})")

    def _enforce_quality(self, story: str, plan: dict, mode: str, quality: str, series_context: str) -> None:
        if quality == QUALITY_NONE:
            return
        low, high = STRICT_WORD_RANGE if quality == QUALITY_STRICT else RELAXED_WORD_RANGE
        words = len(story.split())
        if not low <= words <= high:
            raise ValueError(f"{QUALITY_ERROR_PREFIX}: story is {words} words, needs {low}-{high}")
        last_word = self._normalize_for_dedup(story).split()[-1]
        if last_word in DANGLING_LAST_WORDS:
            raise ValueError(f"{QUALITY_ERROR_PREFIX}: story ends mid-thought on '{last_word}'")

        passed, reason = self._review_story(story, plan, mode, series_context)
        if passed:
            return
        if quality == QUALITY_STRICT:
            raise ValueError(f"{QUALITY_ERROR_PREFIX}: {reason}")
        logger.warning("[GeminiStoryEngine] Shipping despite review on relaxed pass: %s", reason)

    def _review_story(self, story: str, plan: dict, mode: str, series_context: str) -> tuple[bool, str]:
        """Independent pass/fail read. A broken reviewer must never block publishing."""
        criteria = {
            MODE_STANDALONE: (
                "The central question is answered explicitly in the story. The protagonist's fate "
                "is clear. Nothing important is left dangling. It feels finished and does not "
                "imply a sequel."
            ),
            MODE_CLIFFHANGER: (
                "It continues directly from any earlier episodes and contradicts none of them. It "
                "reveals something new. It ends unresolved on a concrete event that leads into "
                "the next episode in the plan."
            ),
            MODE_FINALE: (
                "It continues directly from the earlier episodes. It answers the series' main "
                "question with the planned final truth. The protagonist's fate is clear and it "
                "feels like a finished ending."
            ),
        }[mode]
        prompt = (
            "You are a strict story editor. Decide whether this short story meets every criterion.\n"
            f"Criteria: {criteria}\n"
            f"Writer's plan: {json.dumps(plan)}\n"
            f"{series_context}\n\n"
            f"Story to judge:\n{story}\n\n"
            'Respond with ONLY JSON: {"passes": true or false, "reason": "one sentence on what to fix"}'
        )
        try:
            model = getattr(self, "_check_model", None) or self._model
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1, max_output_tokens=4096, response_mime_type="application/json",
                ),
                request_options=REQUEST_OPTIONS,
            )
            verdict = self._parse_json(response.text)
            return bool(verdict["passes"]), str(verdict.get("reason", ""))[:300]
        except Exception as e:
            logger.warning("[GeminiStoryEngine] Story review unavailable (%s), not blocking", str(e)[:160])
            return True, ""

    @classmethod
    def _word_tokens(cls, text: str) -> list[str]:
        return re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).split()

    @classmethod
    def _find_word_index(cls, tokens: list[str], first_words: str, start: int = 0) -> int | None:
        target = cls._word_tokens(first_words)[:5]
        if not target:
            return None
        for i in range(start, len(tokens) - len(target) + 1):
            if tokens[i:i + len(target)] == target:
                return i
        return None

    @classmethod
    def _locate_scenes(cls, story: str, raw_scenes) -> list[dict]:
        """Anchor each scene to a word position in the narration, in story order."""
        if not isinstance(raw_scenes, list):
            return []
        cleaned = [
            s for s in raw_scenes
            if isinstance(s, dict) and isinstance(s.get("query"), str) and s["query"].strip()
        ][:MAX_SCENES]
        if not cleaned:
            return []
        tokens = cls._word_tokens(story)
        indices: list[int | None] = []
        cursor = 0
        for s in cleaned:
            found = cls._find_word_index(tokens, str(s.get("first_words", "")), cursor)
            indices.append(found)
            if found is not None:
                cursor = found + 1
        indices[0] = 0
        # Unmatched scenes are spread evenly between their matched neighbours.
        i = 0
        while i < len(indices):
            if indices[i] is not None:
                i += 1
                continue
            j = i
            while j < len(indices) and indices[j] is None:
                j += 1
            left = indices[i - 1]
            right = indices[j] if j < len(indices) else len(tokens)
            step = (right - left) / (j - i + 1)
            for k in range(i, j):
                indices[k] = int(left + step * (k - i + 1))
            i = j
        scenes, last = [], -1
        for s, index in zip(cleaned, indices):
            if index > last:
                scenes.append({"query": s["query"].strip(), "word_index": index})
                last = index
        return scenes

    @classmethod
    def _locate_key_visual(cls, story: str, raw) -> dict | None:
        if not isinstance(raw, dict) or not str(raw.get("image_prompt", "")).strip():
            return None
        index = cls._find_word_index(cls._word_tokens(story), str(raw.get("first_words", "")))
        if index is None:
            return None
        return {"image_prompt": str(raw["image_prompt"]).strip(), "word_index": index}

    @staticmethod
    def _clean_hook_card(text) -> str:
        words = re.sub(r"[^\w\s'?!-]", "", str(text or "")).split()
        return " ".join(words) if 2 <= len(words) <= 6 else ""

    @staticmethod
    def _clean_on_screen_text(text) -> str:
        words = re.sub(r"[^\w\s':#-]", "", str(text or "")).split()
        return " ".join(words[:6])

    def generate_series_bible(self, niche: str, premise: dict, planned_episodes: int, published_episodes: str = "") -> dict:
        """Plan the whole arc up front so every episode knows the past and the next one."""
        honor = (
            f"\n\nThese episodes are ALREADY PUBLISHED. Keep them exactly and plan around them:\n{published_episodes}\n"
            if published_episodes.strip() else ""
        )
        prompt = f"""Plan a {planned_episodes}-episode YouTube Shorts {niche.replace('_', ' ')} serial with one continuous story. Each episode is about 135 narrated words.

Assigned premise (mandatory):
{describe_premise(premise)}{honor}

Rules:
* One protagonist, one setting, one threat for the whole series.
* Every episode except the last reveals something new and ends on a specific cliffhanger.
* Each episode must begin from the previous episode's exact cliffhanger.
* The last episode answers the central question with the final truth and states the protagonist's fate.

Respond with ONLY JSON in exactly this shape, with one "episodes" entry per episode:
{{"protagonist": "<name and one defining detail>", "central_question": "", "final_truth": "<the answer, decided now>", "rules": "<how the threat works>", "episodes": [{{"number": 1, "events": "<what happens>", "reveal": "<what is learned>", "ending": "<exact cliffhanger, or the resolution for the last episode>"}}]}}"""
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._generate_story_content(
                    prompt,
                    genai.types.GenerationConfig(
                        temperature=0.9, max_output_tokens=8192, response_mime_type="application/json",
                    ),
                )
                bible = self._parse_json(response.text)
                episodes = bible.get("episodes")
                if not isinstance(episodes, list) or len(episodes) != planned_episodes:
                    raise ValueError("Series plan has the wrong number of episodes")
                for field in ("protagonist", "central_question", "final_truth"):
                    if not str(bible.get(field, "")).strip():
                        raise ValueError(f"Series plan is missing {field}")
                for number, episode in enumerate(episodes, start=1):
                    episode["number"] = number
                bible["premise"] = premise
                return bible
            except Exception as e:
                last_error = e
                logger.warning("[GeminiStoryEngine] Series plan attempt %d failed: %s", attempt, str(e)[:180])
        raise ValueError(f"Could not plan series: {last_error}")

    @staticmethod
    def format_series_plan(bible: dict, episode_number: int) -> str:
        """The writer's view of the arc: what came before, this episode, and what follows."""
        episodes = {e.get("number"): e for e in bible.get("episodes", [])}

        def describe(number: int) -> str:
            e = episodes.get(number, {})
            return f"events: {e.get('events', '')} | reveal: {e.get('reveal', '')} | ending: {e.get('ending', '')}"

        lines = [
            "SERIES PLAN (private to the writer):",
            f"- Protagonist: {bible.get('protagonist', '')}",
            f"- Central question: {bible.get('central_question', '')}",
            f"- How the threat works: {bible.get('rules', '')}",
            f"- Final truth (only state this outright in the last episode): {bible.get('final_truth', '')}",
        ]
        lines += [f"- Episode {n} (already told): {describe(n)}" for n in sorted(episodes) if n < episode_number]
        lines.append(f"- THIS EPISODE ({episode_number}): {describe(episode_number)}")
        if episode_number + 1 in episodes:
            lines.append(f"- NEXT EPISODE ({episode_number + 1}), set this up: {describe(episode_number + 1)}")
        return "\n".join(lines)

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

    @staticmethod
    def _series_cta(episode_number: int) -> str:
        """Point at the actual next episode; only used on cliffhanger episodes."""
        return random.choice(SERIES_CTA_TEMPLATES).format(next=episode_number + 1)

    def _build_pexels_queries(self, niche_data: dict) -> list[str]:
        base_queries = niche_data.get("pexels_queries", ["dark horror scene", "night horror", "scary dark"])
        return list(dict.fromkeys(base_queries))

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

    def _enforce_concept_freshness(
        self,
        script: str,
        blocked_tags: set[str],
        fail_overlap_count: int = 2,
    ) -> None:
        if not blocked_tags:
            return
        overlap = self._concept_tags(script) & blocked_tags
        if len(overlap) >= fail_overlap_count:
            raise ValueError(f"Concept overlap too high: {sorted(overlap)}")

    def _normalize_for_dedup(self, text: str) -> str:
        normalized = re.sub(r"[^a-z0-9\s]", "", (text or "").lower())
        return re.sub(r"\s+", " ", normalized).strip()

    def _is_near_duplicate(self, a: str, b: str, threshold: float = 0.9) -> bool:
        tokens_a = set(self._normalize_for_dedup(a).split())
        tokens_b = set(self._normalize_for_dedup(b).split())
        if not tokens_a or not tokens_b:
            return False
        overlap = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
        return overlap >= threshold

    def _enforce_title_hook_freshness(
        self, hook: str, title: str, recent_hooks: list[str], recent_titles: list[str]
    ) -> None:
        normalized_hook = self._normalize_for_dedup(hook)
        for prior_hook in recent_hooks:
            if normalized_hook and (
                normalized_hook == self._normalize_for_dedup(prior_hook)
                or self._is_near_duplicate(hook, prior_hook)
            ):
                raise ValueError(f"Hook too similar to a recently used hook: '{prior_hook[:80]}'")

        normalized_title = self._normalize_for_dedup(title)
        for prior_title in recent_titles:
            if normalized_title and (
                normalized_title == self._normalize_for_dedup(prior_title)
                or self._is_near_duplicate(title, prior_title)
            ):
                raise ValueError(f"Title too similar to a recently used title: '{prior_title[:80]}'")

    @staticmethod
    def _is_quality_error(err: Exception | None) -> bool:
        return err is not None and QUALITY_ERROR_PREFIX in str(err)

    def _is_concept_overlap_error(self, err: Exception | None) -> bool:
        if err is None:
            return False
        return "Concept overlap too high" in str(err)

    def _drop_most_common_blocked_tag(self, recent_scripts: list[str], blocked_tags: set[str]) -> set[str]:
        if not blocked_tags:
            return set()
        counts: dict[str, int] = {tag: 0 for tag in blocked_tags}
        for script in recent_scripts:
            tags = self._concept_tags(script)
            for tag in blocked_tags:
                if tag in tags:
                    counts[tag] += 1
        tag_to_drop = max(sorted(counts), key=lambda t: counts[t])
        relaxed = set(blocked_tags)
        relaxed.discard(tag_to_drop)
        logger.warning(
            "[GeminiStoryEngine] Relaxing novelty guard by dropping common tag '%s' (count=%d)",
            tag_to_drop,
            counts.get(tag_to_drop, 0),
        )
        return relaxed

    def _build_template_story(self, niche: str) -> dict:
        niche_data = self._niches.get(niche, {})
        templates = niche_data.get("script_templates") or []
        if not templates:
            raise ValueError(f"No script_templates found for niche '{niche}'")

        # Deterministic selection for stable fallback behavior across retries/runs.
        day_key = datetime.utcnow().strftime("%Y-%m-%d")
        seed = zlib.crc32(f"{niche}:{day_key}".encode("utf-8"))
        rng = random.Random(seed)

        template = templates[seed % len(templates)]
        hook = self._deterministic_hook(seed)
        values = self._template_placeholder_values(niche_data, rng)
        script = self._render_template(template, values)
        title = self._build_fallback_title(hook, niche)
        return {"hook": hook, "script": script, "title": title}

    def _deterministic_hook(self, seed: int) -> str:
        if not self._hooks:
            return "At 3:12 AM, the lock clicked open by itself."
        return self._hooks[seed % len(self._hooks)]

    def _template_placeholder_values(self, niche_data: dict, rng: random.Random) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, raw in niche_data.items():
            if isinstance(raw, list) and raw:
                values[key] = str(rng.choice(raw))

        defaults = {
            "character": "Riya",
            "dead_person": "their best friend",
            "time": "3:12 AM",
            "timeframe": "three days",
            "secret_message": "\"I never left.\"",
            "tense_action": "they froze in place",
            "discovery": "A photo was placed face-down on the bed",
            "discovery_detail": "It was a note written in their handwriting",
            "final_message": "\"Turn around slowly.\"",
            "horror_detail": "No shadow. No sound.",
            "closing_line": "\"I was always here.\"",
            "cta": "Follow for the next story.",
        }
        for key, value in defaults.items():
            values.setdefault(key, value)
        return values

    def _render_template(self, template: str, values: dict[str, str]) -> str:
        def repl(match: re.Match) -> str:
            key = match.group(1)
            return str(values.get(key, f"something {key.replace('_', ' ')}"))

        return re.sub(r"\{([a-zA-Z0-9_]+)\}", repl, template).strip()

    def _build_fallback_title(self, hook: str, niche: str) -> str:
        cleaned = re.sub(r"[\"'`*_]+", "", hook or "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned.endswith("."):
            cleaned = cleaned[:-1].strip()
        if not cleaned:
            base = GENRE_LABELS.get(niche, "Horror")
            return f"{base} Story You Won't Forget"
        return cleaned[:57].rstrip(" ,;:!?")

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
        title = re.sub(r"#\w+", "", title or "").replace("’", "'")
        # Apostrophes inside words stay ("Aarav's"); quote marks around phrases go.
        title = re.sub(r"(?<![A-Za-z])'|'(?![A-Za-z])", "", title)
        title = re.sub(r"[\"“”`*_]+", "", title)
        title = title.replace("...", " ")
        title = title.replace("—", " ").replace("–", " ")
        title = re.sub(r"\s+", " ", title).strip(" .,:;-")
        if not title:
            return ""
        # Keep titles punchy without turning hashtags into broken multi-word tags.
        title = re.sub(r"[A-Za-z]+('[A-Za-z]+)?", lambda m: m.group(0).capitalize(), title)
        return title

    _HASHTAG_STOPWORDS = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "of", "for",
        "with", "was", "is", "were", "are", "this", "that", "had", "has", "have",
        "you", "your", "she", "her", "hers", "him", "his", "they", "their", "them",
        "it", "its", "one", "two", "from", "into", "under", "over", "after",
        "before", "when", "while", "then", "than", "not", "no", "never", "found",
        "heard", "saw", "said", "there", "here", "who", "what", "why", "how",
    }

    def _extract_story_hashtags(self, hook: str, title: str, niche: str, max_count: int = 3) -> list[str]:
        """Pull 2-3 story-specific hashtag tokens from the hook/title so every
        upload's description isn't just the same static niche hashtag set."""
        existing = set(SEO_CONFIGS.get(niche, SEO_CONFIGS["horror"])["tags"])
        words = re.findall(r"[A-Za-z]+", f"{title} {hook}".lower())
        picked: list[str] = []
        for w in words:
            if len(w) < 4 or w in self._HASHTAG_STOPWORDS or w in existing or w in picked:
                continue
            picked.append(w)
            if len(picked) >= max_count:
                break
        return picked

    def _generate_seo(self, title: str, niche: str, story_hashtags: list[str] | None = None) -> dict:
        ch = settings.CHANNEL_NAME
        cfg = SEO_CONFIGS.get(niche, SEO_CONFIGS["horror"])
        story_hashtags = story_hashtags or []
        story_hashtag_line = " ".join(f"#{tag}" for tag in story_hashtags)
        hashtags_line = f"{cfg['hashtags']} {story_hashtag_line}".strip() if story_hashtag_line else cfg["hashtags"]
        description = (
            f"{title}\n\n"
            f"{cfg['icon']} {cfg['tagline']}\n\n"
            f"{cfg['sub_tagline']}\n"
            f"{cfg['cta']} → @{ch}\n\n"
            f"{cfg['extras']}\n\n"
            f"{hashtags_line}\n\n"
            f"{cfg['seo_keywords']}"
        )
        return {
            "title": title,
            "description": description,
            "tags": cfg["tags"] + story_hashtags,
        }
