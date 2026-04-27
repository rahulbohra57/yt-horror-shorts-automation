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

    def generate(self, niche: str, recent_scripts: Iterable[str] | None = None) -> dict:
        recent = list(recent_scripts or [])
        niche_data = self._niches.get(niche, {})
        pexels_queries = niche_data.get("pexels_queries", ["dark horror scene", "night horror", "scary dark"])
        pexels_query = random.choice(pexels_queries)

        hook, script = self._generate_with_fallback(niche, recent)

        title = self._generate_title(niche, hook)
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

    def _generate_with_fallback(self, niche: str, recent: list[str]) -> tuple[str, str]:
        try:
            return self._call_gemini(niche, recent)
        except Exception as e:
            logger.error(
                "[GeminiStoryEngine] Gemini failed (%s: %s). Aborting — no template fallback.",
                type(e).__name__, str(e)[:200],
            )
            raise GeminiFailedError(f"{type(e).__name__}: {str(e)[:300]}") from e

    def _call_gemini(self, niche: str, recent_scripts: list[str]) -> tuple[str, str]:
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

        cta_options = "\n".join(f'  - "{c}"' for c in self._CTA_POOL)
        prompt = f"""You are an expert short-form storyteller for YouTube Shorts. Generate a **high-retention story** for a ~60-second video in the genres of **Horror, Mystery, Paranormal, Thriller, Urban Legend, Psychological Fear, Supernatural, or Dark Twist**.

The voiceover is read at a fast pace (+50% speed). To fill a full 60 seconds at that speed, the script body must be **150–170 words** (not counting the CTA). Do NOT write fewer words — an under-length story will leave dead air at the end.

### Requirements:

* Story body: **150–170 words** (hook + build-up + twist)
* Start with an **instant hook in the first sentence** that creates curiosity/shock.
* Maintain suspense every few lines.
* Use simple, cinematic language.
* Include 1 main character only (unless necessary).
* Use a MIX of character names — American (Jake, Emma, Ryan, Sarah, Tyler, Ashley, Michael, Jessica, Chris, Melissa), British (Oliver, Charlotte, Harry, Amelia, James, Sophie, George, Lily, Thomas, Isabelle), or Indian (Riya, Arjun, Meera, Kabir, Priya, Dev, Ananya, Vikram). Do NOT always use Indian names — vary nationality each story.
* Story should feel realistic at first, then become disturbing.
* Build tension quickly.
* End with an **unexpected twist ending** that shocks viewers.
* Final story line must be memorable and creepy.
* Avoid slow setup or unnecessary details.
* MANDATORY FINAL SENTENCE (CTA): After the twist, the very LAST sentence of "script" MUST be chosen from this list — pick one at random:
{cta_options}
  Do NOT end the script on the story. Do NOT omit this CTA. The response is rejected if the CTA is missing or if you invent a different CTA not on this list.
* DO NOT use: ellipsis (...), em dashes (—), asterisks, or markdown formatting in the script
* Write in plain prose — no bullet points, no headers, no special characters

### Structure:

1. **Hook (0-5 sec):** shocking or mysterious opening line
2. **Build-up (5-40 sec):** strange events escalate
3. **Reveal (40-55 sec):** terrifying truth appears
4. **Twist Ending (55-60 sec):** unexpected final punch
5. **CTA (final sentence):** chosen from the list above

### Tone:

Dark, suspenseful, binge-worthy, viral, cinematic.

### Example Hooks (create your OWN completely unique hook — do NOT copy or resemble these):

* Every night, someone knocks on my window from the 10th floor.
* I found a photo of myself sleeping, taken yesterday.
* The voice from my basement knew my name.
* My dead grandmother called me at 3:03 AM.
* I moved into a house where mirrors blink first.
{avoid_block}

Respond with ONLY valid JSON. No explanation, no markdown fences, just the raw JSON object:
{{"hook": "<opening hook sentence only>", "script": "<complete 160-180 word script: hook → build-up → twist → CTA as the LAST sentence>"}}"""


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
        script = parsed["script"].strip()

        # Ensure story ends with a complete sentence + CTA
        script = self._ensure_complete_story(script, niche)

        word_count = len(script.split())
        logger.info(
            "[GeminiStoryEngine] Generated niche=%s words=%d hook='%s...' ending='...%s'",
            niche, word_count, hook[:50], script[-100:],
        )

        return hook, script

    _CTA_KEYWORDS = ("subscribe", "smash like", "hit subscribe", "tap like", "drop a like", "like now", "like this video", "like if", "like before", "join the fearless")
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

    def _ensure_complete_story(self, script: str, niche: str = "") -> str:  # niche kept for call-site compat
        """Guarantee the script ends with a complete sentence and a CTA."""
        script = script.strip()

        # If the script ends mid-sentence (no terminal punctuation), decide how to recover.
        # Check if a CTA keyword already appears near the end before truncating — if so, just
        # add a period rather than wiping the CTA by cutting back to an earlier sentence.
        if script and script[-1] not in ".!?":
            tail = script[-80:].lower()
            cta_in_tail = any(kw in tail for kw in self._CTA_KEYWORDS)
            if cta_in_tail:
                # CTA is present but missing trailing period — just close it
                script = script.rstrip() + "."
                logger.warning("[GeminiStoryEngine] CTA present but no trailing period — added period")
            else:
                last_end = max(script.rfind("."), script.rfind("!"), script.rfind("?"))
                if last_end > len(script) // 2:
                    script = script[: last_end + 1].strip()
                    logger.warning("[GeminiStoryEngine] Script truncated mid-sentence — trimmed to last complete sentence")
                else:
                    script = script.rstrip() + "."

        # If no CTA near the end, append one.
        # Only check the last 120 characters so story words like "she followed him"
        # don't produce a false-positive match.
        tail = script[-120:].lower()
        if not any(kw in tail for kw in self._CTA_KEYWORDS):
            cta = random.choice(self._CTA_POOL)
            script = script + " " + cta
            logger.warning("[GeminiStoryEngine] No CTA found in script — appended: %s", cta)

        return script

    def _generate_title(self, niche: str, hook: str) -> str:
        label = GENRE_LABELS.get(niche, "Horror")
        suffix = f" #{label} #Shorts"
        max_hook_chars = 97 - len(suffix)  # YouTube title limit is 100 chars

        base = hook.rstrip(".").rstrip("?").rstrip("!")
        # Title-case without breaking apostrophes
        titled = re.sub(r"[A-Za-z]+('[A-Za-z]+)?", lambda m: m.group(0).capitalize(), base)

        # Trim to the last complete word within the character budget
        if len(titled) > max_hook_chars:
            titled = titled[:max_hook_chars].rsplit(" ", 1)[0].rstrip(",;:")

        return f"{titled}{suffix}"

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
