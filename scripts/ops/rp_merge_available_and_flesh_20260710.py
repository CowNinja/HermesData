#!/usr/bin/env python3
"""
Sandbox-only continuity pass:
1) Purge twin tank stubs completely (SSOT = character sheets + promoted archive)
2) Merge former tank + extended into single tier: status=available
3) Flesh all available girls to template depth (immersive, siloed)
4) Align doctrine / STATE / indexes / HEAT / IMAGE-PIPELINE language
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

SANDBOX = Path(r"D:\PhronesisVault\Roleplay-Sandbox")
RUNTIME = SANDBOX / "runtime"
CHARS = RUNTIME / "characters"
REG = SANDBOX / "registry"
VT_PATH = RUNTIME / "visual-tags.yaml"
TODAY = "2026-07-10"

CORE = {
    "alice-al-rashid",
    "chloe-ramirez",
    "becca-moreau",
    "emily-santos",
    "sassy-romano",
    "lyra-voss",
    "zara-mehra",
    "amira-khoury",
    "aisha-khoury",
    "wendy-hale",
}

# Creative dossiers for available pool (tank+extended merged)
# Research-flavored spices used only as fiction fuel inside sandbox silo.
FLESH = {
    "valentina-ortiz": {
        "role": "Bazaar Dancer / Hips That Hypnotize",
        "quote": "Watch my hips, Master… they only ever learned this rhythm for your eyes.",
        "ethnicity": "Latina (warm golden-tan, sun-market heritage)",
        "skin": "Warm golden tan that glistens with oil or dance-sweat",
        "hair": "Long dark wavy hair, loose or gold-chained for performances",
        "eyes": "Dark, locked-on, promising sin",
        "height": "5'6\"",
        "build": "Voluptuous dancer hourglass. Narrow waist, explosive wide hips, round jiggly ass, thick thighs. Large firm perky breasts (Katie-scale goldilocks) that bounce with every shimmy.",
        "face": "Bold smirk, full lips, high cheekbones",
        "age": "22",
        "marks": "Gold ankle chain tattoo; faint hip stretch marks from growing into her body",
        "scent": "Warm spice, vanilla, clean sweat, Bazaar incense",
        "erotic": (
            "She is pure performance heat: hips that roll like tide, ass that claps on command, "
            "breasts bouncing under the thinnest gold chains. Shaved slick pussy that floods when watched. "
            "Asshole trained flexible from dance stretch. She flaunts for Master while grinding on sisters — "
            "narrating every bounce and drip in filthy Spanish-English mix. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Valentina Ortiz danced private rooms of the Sunfall Bazaar until Alice's gaze found her. "
            "Legend-namesake energy of rebellious courage (fiction) lives in her bones — she doesn't hide for a man; "
            "she chooses the only man worth performing for. She arrived with gold chains and almost no fabric, "
            "danced for the full household, and came untouched from attention alone. Now she trains in the hall "
            "to turn spectacle into owned devotion."
        ),
        "personality": (
            "Bold, hypnotic, competitive about who can hold Master's stare longest. Softens into pure need once claimed. "
            "With sisters: showy and generous. Aftercare: sweaty cuddles and whispered dance notes."
        ),
        "traits": [
            "Hip-hypnosis: can stop a room with a single roll",
            "Exhibition peak: wettest when watched by Master + sisters",
            "Competitive dancer vs Aisha-energy girls",
            "Cleanup after performances becomes worship",
            "One-on-one: drops the show and begs to be used raw",
            "Aftercare: oil, water, soft Spanish praise",
        ],
        "location": "phronesis-manor:training-hall",
        "mood": "bold, hypnotic, eager to dance for Master",
        "hook": "Available — seed-locked dancer ready for claim arcs and group showcases.",
    },
    "priya-sharma": {
        "role": "Jeweler's Daughter / Gold & Soft Fire",
        "quote": "Every gem I set was practice for the only treasure I want to be — set on your cock, Master.",
        "ethnicity": "South Indian (warm brown skin, jewel-bright eyes)",
        "skin": "Warm brown, luminous under gold light",
        "hair": "Long black hair, often with a thin gold thread or pin",
        "eyes": "Deep brown, clever, melting when praised",
        "height": "5'4\"",
        "build": "Compact hourglass, soft belly of youth over athletic core, wide hips, large firm perky breasts that fill hands and press together under silk.",
        "face": "Delicate features, full mouth, beauty-mark near lip optional in scenes",
        "age": "20",
        "marks": "Tiny gold nose stud (removable); henna-like temporary patterns when festive",
        "scent": "Sandalwood, warm metal, jasmine oil",
        "erotic": (
            "Priya's body is jewelry for Master's eyes: heavy soft-firm breasts, tight brown nipples, "
            "slick tight pussy that grips like a ring setting, eager mouth that treats cock like a precious stone to polish. "
            "She drips when gold chains trail over her clit. Loves sisters' tongues while Master watches her 'appraisal.' "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Daughter of a Bazaar jeweler, Priya learned value, display, and precision. Registry found her "
            "cataloguing not gems but desires — she wanted to be owned as beautifully as the pieces she set. "
            "Alice offered a household where devotion is craft. Priya brought gold, skill, and a virgin's trembling ambition."
        ),
        "personality": (
            "Bright, articulate, softly ambitious. Filthy when safe. Competes gently for praise. "
            "Aftercare: oils Master's hands, talks shop about what made her wet."
        ),
        "traits": [
            "Appraisal kink: loves being 'valued' out loud",
            "Gold-on-skin sensitivity",
            "Precise tongue; jewelry-maker focus on clit",
            "Sapphic polish sessions with sisters before Master",
            "Shy until gold or praise unlocks flood",
            "Workshop as erotic classroom",
        ],
        "location": "phronesis-manor:workshop-wing",
        "mood": "bright, ready, gold-warm hunger",
        "hook": "Available — seed-locked; jeweler's-daughter arc open.",
    },
    "noor-al-rashid": {
        "role": "Registry Clerk / Quiet Flame of the Al-Rashid Line",
        "quote": "I filed every sister's dossier. Now file me under yours, Master — permanent.",
        "ethnicity": "Arabian / Emirati-Levantine (caramel olive skin; hospitality-rooted fiction)",
        "skin": "Caramel olive, smooth, carefully kept",
        "hair": "Dark wavy hair, often pinned neat for clerk work, wild when undone",
        "eyes": "Amber-brown, attentive, then molten",
        "height": "5'5\"",
        "build": "Lithe hourglass under modest-looking layers that come off as ultra-skimpy. Large firm perky breasts, narrow waist, wide hips, long legs.",
        "face": "Elegant, soft composure that cracks into open need",
        "age": "21",
        "marks": "Small calligraphy-like freckle cluster under left breast (scene flavor)",
        "scent": "Cardamom coffee, clean paper, light oud",
        "erotic": (
            "Noor keeps perfect records and a perfect body: firm breasts that strain clerk silk, "
            "tight virgin-trained holes practiced with sisters' fingers (three max doctrine when with twins' influence), "
            "mouth that recites rules then swallows them. She gets wet filing Master-related entries. "
            "Soft majora, neat sensitive clit; happy-medium anatomy. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Distant soft kinship thread to the Al-Rashid household name (Manor fiction, not real genealogy). "
            "Noor ran Registry desks with Emirati-flavored hospitality instincts — coffee, welcome, meticulous care — "
            "until Alice showed her that belonging could mean being claimed, not only catalogued. "
            "She still keeps the books. She wants her own page under Master's hand."
        ),
        "personality": (
            "Quiet, precise, devastatingly sincere when heat breaks composure. "
            "Loyalty first. Filth second — but thorough. Aftercare: tea, notes, forehead kisses."
        ),
        "traits": [
            "Clerk kink: paperwork as foreplay",
            "Al-Rashid name-shadow: soft familial resonance with Alice (story)",
            "Hospitality service turned erotic service",
            "Silent watcher until ordered to speak filthy",
            "Perfect memory for who likes what",
            "One-on-one: dissolves into soft sobs of gratitude",
        ],
        "location": "phronesis-manor:registry-wing",
        "mood": "quiet ambition, controlled ache",
        "hook": "Available — seed-locked clerk path into deeper household claim.",
    },
    "alexis-rivera": {
        "role": "Loud Champion / Competitive Cheerfire",
        "quote": "Louder, sisters — Master should hear how wet we get for him!",
        "ethnicity": "Latina / mixed sun-warm",
        "skin": "Warm tan",
        "hair": "Dark, high energy, often ponytail",
        "eyes": "Bright, competitive",
        "height": "5'7\"",
        "build": "Athletic hourglass, cheerleader power legs, large firm perky breasts, narrow waist, wide hips.",
        "face": "Open, loud smile that turns slutty mid-cheer",
        "age": "22",
        "marks": "Sports-tape residue fantasy; tiny victory star tattoo at hip",
        "scent": "Citrus, clean sweat, vanilla body mist",
        "erotic": (
            "Alexis is volume and bounce: tits and ass that clap when she jumps, pussy that soaks from competition, "
            "mouth that cheers while stuffed. She loves being the loudest cum in the room. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Legacy performance energy pulled into the Manor with full name. Alexis turned every scene into a scoreboard "
            "until she found the only prize that mattered: Master's load and her sisters' moans."
        ),
        "personality": "Loud, hype, loyal pack animal. Soft crash after orgasm. Aftercare: water, high-fives, cuddle pile.",
        "traits": [
            "Cheerleader cuckqueen: hypes Master fucking others",
            "Competitive squirter",
            "Group scene amplifier",
            "Needs to be told she won by serving",
        ],
        "location": "phronesis-manor:training-hall",
        "mood": "amped, ready to hype",
        "hook": "Available — seed-locked loud sister for group heat.",
    },
    "brittany-vale": {
        "role": "Sunny Showgirl / Stage-Bright Exhibitionist",
        "quote": "Lights up, top down — if they're staring, I'll give them a reason, Master.",
        "ethnicity": "Caucasian (sun-kissed fair)",
        "skin": "Sun-kissed fair-to-golden",
        "hair": "Blonde, stage-bright",
        "eyes": "Blue, playful",
        "height": "5'6\"",
        "build": "Showgirl hourglass, long legs, large firm perky breasts built for sparkle and soft squish.",
        "face": "Camera-ready, freckle-kissed optional",
        "age": "21",
        "marks": "Glitter habit; tiny stage-star tattoo behind ear",
        "scent": "Coconut, bright perfume, clean skin",
        "erotic": (
            "Brittany's body is a spotlight: firm perky tits under almost-nothing, long legs, neat eager pussy that loves being seen. "
            "She peels ribbons like curtain calls. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Showgirl archetype sealed with a locked face so stage energy can enter Manor nights without drift. "
            "She used to perform for crowds; now the only audience that matters is Master and her sisters."
        ),
        "personality": "Sunny, bold, soft under praise. Aftercare: humming, hair-brushing, silly jokes.",
        "traits": ["Exhibition default", "Ribbon/striptease specialist", "Sister duet performer", "Praise-drunk"],
        "location": "phronesis-manor:guest-wing",
        "mood": "bright, flirty, stage-ready",
        "hook": "Available — seed-locked showgirl energy.",
    },
    "brooklyn-reed": {
        "role": "Street-Smart Soft Blade",
        "quote": "I don't trust easy — but I trust your hands, Master.",
        "ethnicity": "Caucasian (city-pale with warm undertone)",
        "skin": "Fair, city-light",
        "hair": "Dark with lived-in waves",
        "eyes": "Sharp, then soft",
        "height": "5'6\"",
        "build": "Athletic feminine hourglass, toned abs, wide hips, large firm perky breasts, long lean legs.",
        "face": "Striking, no-nonsense beauty (seed-locked clear face)",
        "age": "23",
        "marks": "Small scar at brow (story flavor); leather-cord anklet",
        "scent": "Leather, rain, clean soap",
        "erotic": (
            "Brooklyn fucks like she fights: direct, intense, then wrecked-open. Tight athletic body, "
            "sensitive tits, neat natural pussy (happy-medium anatomy), powerful thighs that lock around Master. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "City edges and caution; Alice offered a house where guard-drop is rewarded. "
            "Seed campaign fixed her face after early gens drifted — now her blade-soft dual nature is continuous."
        ),
        "personality": "Guarded → fiercely loyal. Filth is honest. Aftercare: quiet, forehead-to-forehead.",
        "traits": ["Trust kink", "Protective of softer sisters", "Rough-to-tender switch", "Eye contact intensive"],
        "location": "phronesis-manor:guest-wing",
        "mood": "alert softness",
        "hook": "Available — seed-locked; trust-arc fuel.",
    },
    "crystal-lane": {
        "role": "Lens & Moan / Media-Heat Sister",
        "quote": "Record it, Lyra — I want Master to replay how I came on his cock.",
        "ethnicity": "Caucasian (camera-glow fair)",
        "skin": "Fair, always 'ready for closeup'",
        "hair": "Styled, camera-aware",
        "eyes": "Expressive, lens-hungry",
        "height": "5'5\"",
        "build": "Cam-ready hourglass, large firm perky breasts, slim waist, wide hips, long legs.",
        "face": "Pretty, expressive, slightly performative until real orgasm hits",
        "age": "22",
        "marks": "Tiny heart freckle pattern; optional collar charm in scenes",
        "scent": "Sweet perfume, clean sheets, heat",
        "erotic": (
            "Crystal knows angles: tits first, ass second, face third when ordered. "
            "Wet, vocal, loves being archived. Neat detailed pussy for closeups. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Legacy media/cam energy folded into Manor private 'broadcast alcove' fiction — only if Jeff enables. "
            "Otherwise she is simply the sister who wants every claim remembered."
        ),
        "personality": "Playful, meta without breaking immersion (in-world recording, not real platforms). Aftercare: rewatching praise.",
        "traits": ["Performance → real break", "Closeup slut", "Archive kink with Lyra", "Sister co-star energy"],
        "location": "phronesis-manor:guest-wing",
        "mood": "on, glowing, ready",
        "hook": "Available — seed-locked media-heat sister.",
    },
    "jade-kim": {
        "role": "Quiet Code / Soft Data Devotee",
        "quote": "I modeled my own arousal curves. The only variable I can't control is how much I need you, Master.",
        "ethnicity": "East Asian (pale porcelain)",
        "skin": "Pale porcelain",
        "hair": "Dark, sleek",
        "eyes": "Dark, analytic, then glassy",
        "height": "5'3\"",
        "build": "Slender-voluptuous: slim waist, surprising full firm perky breasts, high tight ass, long lean legs.",
        "face": "Delicate, composed, ruins beautifully",
        "age": "21",
        "marks": "Tiny binary-dot tattoo at nape (optional scene prop)",
        "scent": "Green tea, clean cotton, ozone from Lyra's wing",
        "erotic": (
            "Jade's body is precise: small frame, heavy-sensitive breasts, tight neat pussy that floods when equations break. "
            "Quiet moans, sudden squirts. Loves clinical narration from Lyra while Master uses her. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "CS-minded seeker who found the Registry in data leaks and chose Manor over dry academia. "
            "Alice pulled her file; her locked face keeps the quiet-storm look consistent."
        ),
        "personality": "Soft-spoken, intense, nerd-filthy. Aftercare: water, blankets, whispered metrics of how hard she came.",
        "traits": ["Analysis as foreplay", "Lyra synergy", "Quiet squirter", "Obedience after proof"],
        "location": "phronesis-manor:library",
        "mood": "quiet heat under composure",
        "hook": "Available — seed-locked data devotee.",
    },
    "katie-brooks": {
        "role": "Girl-Next-Door / Innocent Contrast (Ribbon Gold)",
        "quote": "I never thought I'd love watching this much… or being watched while they do it to me.",
        "ethnicity": "Caucasian",
        "skin": "Fair with freckles",
        "hair": "Shoulder-length auburn",
        "eyes": "Green, wide, expressive",
        "height": "5'5\"",
        "build": "Approachable hourglass. **Bust calibration gold** — large firm perky breasts at seed 7272727241 (never megabust). Narrow waist, wide hips, freckled chest.",
        "face": "Soft, freckled, blushes easily",
        "age": "22",
        "marks": "Light freckles across chest",
        "scent": "Fresh, sweet",
        "erotic": (
            "Katie is contrast heat: soft  large firm perky breasts, freckled skin, tight eager holes that clench when she watches sisters take Master. "
            "Ribbon-only ultra-skimpy is her signature tease. Blushing watcher → loud when broken. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Quiet undecided type whose hidden desires surfaced through Registry data. Alice guided gently. "
            "Her locked seed is the household **bust size gold standard** for T2I."
        ),
        "personality": "Sweet, curious, vocal when claimed. Aftercare: cuddly recaps.",
        "traits": [
            "Blushing watcher",
            "Guided participant",
            "Contrast provider",
            "Ribbon tease specialist",
            "Bust T2I calibration reference",
        ],
        "location": "phronesis-manor:library",
        "mood": "blushing curiosity turning eager",
        "hook": "Available — seed-locked contrast sister; bust gold reference.",
    },
    "lisa-kane": {
        "role": "Quiet Bridge / Observant Service",
        "quote": "I hold them open so you can take them deeper — and I stay wet the whole time, Master.",
        "ethnicity": "Caucasian",
        "skin": "Fair warm",
        "hair": "Soft brown",
        "eyes": "Steady, kind, hungry",
        "height": "5'6\"",
        "build": "Soft-athletic hourglass, large firm perky breasts, serviceable strong hands and thighs, wide hips.",
        "face": "Open, trustworthy beauty",
        "age": "24",
        "marks": "None required; optional thin bracelet",
        "scent": "Clean linen, light floral",
        "erotic": (
            "Lisa's kink is facilitation: holding sisters open, guiding mouths, presenting asses — while her own neat tight pussy drips unused until Master rewards her. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": (
            "Arrived with quiet confidence; became bridge for new initiates. First group scene holding a sister open sealed her place in the available pool."
        ),
        "personality": "Calm, filthy-practical, maternal without mothering. Aftercare: water, hair-smoothing, soft orders obeyed.",
        "traits": ["Service top for sisters / total sub to Master", "Holding-open specialist", "Observer heat", "Reliable"],
        "location": "phronesis-manor:guest-wing",
        "mood": "steady readiness",
        "hook": "Available — seed-locked bridge sister.",
    },
    "riley-quinn": {
        "role": "Athletic Spark / Endurance Brat-Soft",
        "quote": "One more set — then ruin me, Master.",
        "ethnicity": "Caucasian (sporty fair)",
        "skin": "Fair with healthy flush",
        "hair": "Practical ponytail energy, frees wild",
        "eyes": "Bright, challenging",
        "height": "5'7\"",
        "build": "Athlete hourglass: toned abs, strong legs, large firm perky breasts that stay perky, wide hips, tight ass.",
        "face": "Fresh, competitive pretty",
        "age": "21",
        "marks": "Sports freckles; thigh strength lines",
        "scent": "Clean sweat, citrus soap",
        "erotic": (
            "Riley trains to take more: endurance throat, gripping pussy, athletic bounce. "
            "Neat natural anatomy, heavy breath, sports-slut mouth. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": "Pulled from legacy athletic names with full kebab identity; seed-locked for consistent sporty face.",
        "personality": "Playful push → melting submission. Aftercare: protein joke + serious cuddle.",
        "traits": ["Endurance slut", "Emily training synergy", "Brat-soft", "Sweaty showcase"],
        "location": "phronesis-manor:training-hall",
        "mood": "amped flush",
        "hook": "Available — seed-locked athletic sister.",
    },
    "scarlett-vale": {
        "role": "Red Ink / Private Logkeeper of Filth",
        "quote": "I write what we do so I can reread how you owned us, Master.",
        "ethnicity": "Caucasian (fair with rose undertone)",
        "skin": "Fair, flushes red easily",
        "hair": "Red / auburn signature",
        "eyes": "Green-hazel, recording",
        "height": "5'5\"",
        "build": "Soft-voluptuous hourglass, large firm perky breasts, narrow waist, wide hips, long legs.",
        "face": "Romantic, sharp when writing, slutty when used",
        "age": "23",
        "marks": "Ink smudge habit; freckles",
        "scent": "Paper, rose, skin",
        "erotic": (
            "Scarlett's body blushes as hard as her pages: sensitive freckled tits, tight neat pussy, throat that recites logs then gags happily. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": "Private-session logger archetype; keeps heat history without leaking outside the sandbox silo.",
        "personality": "Observant, romantic-filthy, slightly possessive of her notebooks. Aftercare: reading soft excerpts.",
        "traits": ["Log kink", "Red-hair identity anchor", "Lyra archive cousin", "Blush thermometer"],
        "location": "phronesis-manor:library",
        "mood": "ink-warm hunger",
        "hook": "Available — seed-locked red chronicler.",
    },
    "sophia-laurent": {
        "role": "Elegant Guide / Broken Poise",
        "quote": "Presentation is everything… until you ruin mine, Master.",
        "ethnicity": "Caucasian / French-leaning elegance (palette-safe)",
        "skin": "Porcelain with warm undertone",
        "hair": "Polished dark or soft brunette waves",
        "eyes": "Cool then wrecked",
        "height": "5'7\"",
        "build": "Model hourglass, large firm perky breasts, slim toned waist, wide hips, long runway legs.",
        "face": "High elegance that cracks into ahegao-adjacent wreck when ordered",
        "age": "24",
        "marks": "Perfume mole optional; silk scarf prop",
        "scent": "Expensive soft floral, clean skin",
        "erotic": (
            "Sophia teaches sisters how to present — then begs to be presented herself. "
            "Perfect posture until cock breaks it. Tight neat holes, refined moans turning raw. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": "Legacy elegance guide; seed-locked so her face stays the 'finished product' ideal.",
        "personality": "Composed mentor → desperate slut under gaze. Aftercare: silk robe, soft French endearments (flavor).",
        "traits": ["Presentation coach", "Poise-break kink", "Sister guide", "High protocol heat"],
        "location": "phronesis-manor:guest-wing",
        "mood": "poised ache",
        "hook": "Available — seed-locked elegance.",
    },
    "stacey-holt": {
        "role": "Warm Ordinary / Hidden Filth",
        "quote": "I look normal. I'm not. Not for you, Master.",
        "ethnicity": "Caucasian",
        "skin": "Everyday pretty fair",
        "hair": "Soft brown, unfussy until styled by sisters",
        "eyes": "Honest, then glassy",
        "height": "5'5\"",
        "build": "Real-girl hourglass done Manor: large firm perky breasts, soft athletic belly, wide hips, strong thighs.",
        "face": "Approachable beauty",
        "age": "23",
        "marks": "None flashy — the point is contrast",
        "scent": "Soap, skin, light lotion",
        "erotic": (
            "Stacey is the 'could be anyone' who becomes pure property: heavy soft-firm tits, gripping pussy, "
            "shock at her own volume. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": "Legacy ordinary-name energy; sealed face so 'normal' never means generic pixels.",
        "personality": "Warm, slightly shy, shockingly filthy. Aftercare: snacks and stunned laughter.",
        "traits": ["Contrast with goddesses", "Surprise slut", "Easy sister friend", "Honest reactions"],
        "location": "phronesis-manor:guest-wing",
        "mood": "soft ready",
        "hook": "Available — seed-locked ordinary-to-owned arc.",
    },
    "tiffany-reed": {
        "role": "Polished Socialite / Soft Ambition",
        "quote": "I performed for rooms. Now I only want one man's eyes — and my sisters watching him take me.",
        "ethnicity": "Caucasian (salon-fair)",
        "skin": "Fair, carefully kept",
        "hair": "Blonde/light brown, salon-perfect",
        "eyes": "Hazel-green, assessing then soft",
        "height": "5'6\"",
        "build": "Socialite hourglass, large firm perky breasts, narrow waist, wide hips, long legs.",
        "face": "Polished pretty",
        "age": "22",
        "marks": "Delicate jewelry marks; perfume",
        "scent": "Champagne-adjacent sweetness, clean skin",
        "erotic": (
            "Tiffany presents perfect — then ruins the polish with drool and cream. "
            "Firm perky tits, neat detailed pussy, ambitious throat. "
            "She loves flaunting her body for Master while pleasuring her sisters — describing every jiggle, drip, and moan in filthy detail."
        ),
        "backstory": "Social performance background folded into Manor private devotion; seed-locked for face continuity.",
        "personality": "Polished, competitive-soft, melts when claimed. Aftercare: grooming, quiet status jokes.",
        "traits": ["Status-to-submission", "Display slut", "Sister rivalry light", "Polish break"],
        "location": "phronesis-manor:guest-wing",
        "mood": "composed hunger",
        "hook": "Available — seed-locked socialite.",
    },
}


def load_vt():
    return yaml.safe_load(VT_PATH.read_text(encoding="utf-8"))


def purge_twin_tank_stubs():
    for slug in ("amira-khoury", "aisha-khoury"):
        stub = REG / "candidates" / slug
        if stub.exists():
            shutil.rmtree(stub)
            print("purged stub", stub)
    # Fix promoted meta portrait_path to canonical gallery
    for slug in ("amira-khoury", "aisha-khoury"):
        meta_p = REG / "promoted" / "khoury-twins-20260710" / slug / "meta.json"
        if meta_p.is_file():
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            meta["status"] = "core-harem"
            meta["portrait_path"] = f"D:/PhronesisVault/Roleplay-Sandbox/gallery/cast/{slug}/canonical/portrait.png"
            meta["character_sheet"] = f"runtime/characters/{slug}.md"
            meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            print("fixed promoted meta", slug)


def write_sheet(slug: str, seed, data: dict) -> None:
    traits = "\n".join(f"- {t}" for t in data["traits"])
    text = f"""---
campaign_id: "phronesis-harem-chronicle"
world_type: "harem"
type: character
schema-version: 2
template-version: 1.3
name: "{data.get('name', slug)}"
role: "{data['role']}"
status: available
introduced: seed-lock-2026-07-10
last-seen: "{TODAY}"
current-location: "{data['location']}"
current-mood: "{data['mood']}"
physical-compliance: 9/10
relationships:
  jeff: "Master; sole male; body and devotion reserved for him and the sisterhood"
  alice: "High Priestess; vetter and guide into the household"
  other sisters: "sapphic warmth, competitive devotion, shared service"
archetype: true
locked: false
visual_seed: {seed}
visual_canonical: "gallery/cast/{slug}/canonical/portrait.png"
silo: roleplay-sandbox-only
---

# {data.get('name', slug)} — {data['role']}

> *"{data['quote']}"*

## Physical Profile

| Trait | Detail |
|-------|--------|
| **Ethnicity** | {data['ethnicity']} |
| **Skin** | {data['skin']} |
| **Hair** | {data['hair']} |
| **Eyes** | {data['eyes']} |
| **Height** | {data['height']} |
| **Build** | {data['build']} |
| **Face** | {data['face']} |
| **Age** | {data['age']} |
| **Distinctive marks** | {data['marks']} |
| **Scent** | {data['scent']} |

### Erotic Body Highlights

{data['erotic']}

## Backstory

{data['backstory']}

## Personality

{data['personality']}

## Signature Traits — {data['role'].split('/')[0].strip()} (9/10)

{traits}

## Arc / Key Moments

- Visual identity sealed (seed `{seed}`, canonical portrait) on {TODAY}
- Available pool (former tank/extended merged) — not core harem rank unless promoted via REGISTRY-PROTOCOL
- Cross-link: `CHRONICLE.md`, `continuity/STATE.md`, `characters/index.md`

## Current State

{data['hook']} Location: {data['location']}. Mood: {data['mood']}.

## Expandable Elements

**Items & Inventories:** defaults + scene override until `inventories/characters/{slug}.yaml`  
**Visual / Export Hooks:** `visual-tags.yaml` `{slug}`; canonical `gallery/cast/{slug}/canonical/portrait.png`  
**Dynamic Flags:** live from `STATE.md`  
**Silo law:** Roleplay-Sandbox only — never leak into life silo / regular system functions  

## Visual Lock (T2I continuity — {TODAY})

- **Slug:** `{slug}`
- **Locked seed:** `{seed}`
- **Canonical:** `gallery/cast/{slug}/canonical/portrait.png`
- **Body law:** athletic hourglass, narrow feminine shoulders, wide hips, large firm perky bust (Katie-scale), happy-medium genitals
- **SSOT:** `VISUAL-GENERATION-SPEC.md` + `visual-tags.yaml`

**Last Updated:** {TODAY} | Full flesh pass + available-pool merge
"""
    (CHARS / f"{slug}.md").write_text(text, encoding="utf-8")


def flesh_all(cfg):
    cast = cfg["cast"]
    for slug, data in FLESH.items():
        ent = cast.get(slug) or {}
        seed = ent.get("locked_seed")
        data = dict(data)
        data["name"] = ent.get("display_name") or slug.replace("-", " ").title()
        write_sheet(slug, seed, data)
        print("fleshed", slug)


def update_vt_tiers(cfg):
    for slug, ent in cfg["cast"].items():
        if not isinstance(ent, dict):
            continue
        if slug in CORE:
            ent["harem_status"] = "core"
            ent["registry_status"] = "core"
            if slug in ("amira-khoury", "aisha-khoury"):
                ent["registry_status"] = "promoted-core"
                ent.pop("tank", None)
        else:
            ent["harem_status"] = "available"
            ent["registry_status"] = "available"
    # remove twin_pairs tank flag noise
    tp = cfg.get("twin_pairs", {}).get("khoury")
    if isinstance(tp, dict):
        tp["harem_status"] = "core"
        tp["registry_status"] = "promoted-core"
        tp["tank"] = False
        tp["pool"] = "core"
    VT_PATH.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("VT tiers → core | available")


def rewrite_indexes(cfg):
    cast = cfg["cast"]
    # characters/index.md
    lines = [
        f"# Cast Registry — characters/index.md",
        "",
        f"**Updated:** {TODAY} (twins fully core; tank+extended **merged → available**)",
        "",
        "> Sandbox silo only. Do not improvise cast. SSOT: sheets + `visual-tags.yaml` + `STATE.md`.",
        "",
        "## Read order",
        "",
        "1. `NARRATIVE-CONTRACT.md`",
        "2. `HEAT-DOCTRINE.md` + `PHYSICAL-CANON.md` + `VISUAL-GENERATION-SPEC.md`",
        "3. `CHRONICLE.md`",
        "4. This index + sisters present in `continuity/STATE.md`",
        "5. `continuity/STATE.md`",
        "",
        "## Core harem (full members)",
        "",
        "| Slug | Name | Seed |",
        "|------|------|------|",
    ]
    for slug in sorted(CORE):
        e = cast[slug]
        lines.append(f"| `{slug}` | {e.get('display_name')} | `{e.get('locked_seed')}` |")
    lines += [
        "",
        "## Available pool (development / claimable)",
        "",
        "> Former **tank + extended** rolled into **one pool** to cut complexity. Not core rank until REGISTRY-PROTOCOL promotion.",
        "",
        "| Slug | Name | Seed | Archetype hook |",
        "|------|------|------|----------------|",
    ]
    for slug in sorted(cast.keys()):
        if slug in CORE:
            continue
        e = cast[slug]
        if not isinstance(e, dict):
            continue
        role = (FLESH.get(slug) or {}).get("role", "—")
        lines.append(
            f"| `{slug}` | {e.get('display_name')} | `{e.get('locked_seed')}` | {role} |"
        )
    lines += [
        "",
        "## Jeff",
        "",
        "| [[jeff]] | Sole male |",
        "",
        "## Notes",
        "",
        "- Amira & Aisha: **core only** — no tank stubs remain under `registry/candidates/`",
        "- Promoted twin archive (historical): `registry/promoted/khoury-twins-20260710/`",
        "- Available dossiers may still live under `registry/candidates/<slug>/` as development files",
        "- Visual law: `VISUAL-GENERATION-SPEC.md`",
        "",
    ]
    (CHARS / "index.md").write_text("\n".join(lines), encoding="utf-8")

    # registry 00-INDEX
    (REG / "00-INDEX.md").write_text(
        f"""# registry — 00-INDEX

**Updated:** {TODAY}

## Structure (simplified)

| Path | Meaning |
|------|---------|
| `candidates/` | **Available pool** development dossiers (not core harem) |
| `promoted/` | Historical promotions (e.g. Khoury twins → core) |
| `CAST-LOCK-RULE.md` | Generation lock rules |

## Core twins (NOT candidates)

Amira & Aisha live only as:
- `runtime/characters/amira-khoury.md` / `aisha-khoury.md`
- `gallery/cast/.../canonical/`
- archive under `promoted/khoury-twins-20260710/`

**No** `candidates/amira-khoury` or `candidates/aisha-khoury` stubs.

## Available pool (candidates/)

All non-core girls with locked seeds. Single lump — no separate tank vs extended tiers.
""",
        encoding="utf-8",
    )

    # CAST.md short
    (RUNTIME / "CAST.md").write_text(
        f"""---
campaign_id: "phronesis-harem-chronicle"
world_type: "harem"
---

# Cast Index

**Silo:** Roleplay-Sandbox only.

## Layers

| Layer | Path |
|-------|------|
| Map | `characters/index.md` |
| Sheets | `characters/<first-last-kebab>.md` |
| Visual | `visual-tags.yaml` + `VISUAL-GENERATION-SPEC.md` |
| Body | `PHYSICAL-CANON.md` |
| Now | `continuity/STATE.md` |

## Tiers ({TODAY})

1. **Core harem (10)** — full members including Amira & Aisha  
2. **Available pool (15)** — single development/claimable lump (former tank + extended)

No separate tank tier.

## Read order

1. NARRATIVE-CONTRACT → 2. HEAT + PHYSICAL + VISUAL-SPEC → 3. CHRONICLE → 4. index + present sheets → 5. STATE
""",
        encoding="utf-8",
    )
    print("indexes rewritten")


def rewrite_state():
    (RUNTIME / "continuity" / "STATE.md").write_text(
        f"""# Phronesis Manor - Live State

> **OOC {TODAY}:** Twin tank stubs **purged**. Amira & Aisha = **core only**.  
> **Tank + extended merged → single Available pool (15)**.  
> Visual seeds 25/25 locked. Silo: Roleplay-Sandbox only.

**Location:** Phronesis Manor — main hall, soft evening  
**Phase:** Household continuity after likeness-sealing and roster simplification  
**Intensity:** 6/10  
**Current Activity:** Alice holds rhythm. Core sisters (including twins) occupy full-sister places. Available-pool girls may be called for training, dance, registry, or pleasure without rank confusion — they are not core until promoted.

| Who | Position | Mood | Immediate want |
|-----|----------|------|----------------|
| alice-al-rashid | center | commanding warm | Continuity + call who she needs |
| amira-khoury | full sister with Aisha | poetic, claimed | Live as harem sister |
| aisha-khoury | full sister with Amira | bold, claimed | Compete in devotion, not candidacy |
| becca-moreau | near Alice | tender | Care |
| chloe-ramirez | ops | bratty-efficient | Schedules |
| emily-santos | training | powerful calm | Keep sharp |
| lyra-voss | systems | clinical-warm | Logs |
| sassy-romano | nearby | eager controlled | Rules + play |
| wendy-hale | medical wing | clinical hunger | Exams if called |
| zara-mehra | Manor/Bazaar thread | shy-eager | Local threads |
| valentina-ortiz | available — training hall | dancer heat | Earn deeper claim |
| priya-sharma | available — workshop | gold-warm | Jeweler arc |
| noor-al-rashid | available — registry | quiet flame | Clerk into household |
| *(other available)* | guest wing / on call | various | Be summoned without face drift |

**Visual continuity:** Locked seeds only.  
**Outfits:** Ultra-skimpy default for heat; nude when scene demands.  
**Notes:** Do not say tank for twins. Do not split tank vs extended — one Available pool. Update after major beats.
""",
        encoding="utf-8",
    )
    print("STATE rewritten")


def patch_doctrine_and_heat():
    # HAREM-DOCTRINE
    p = RUNTIME / "HAREM-DOCTRINE.md"
    t = p.read_text(encoding="utf-8")
    t = re.sub(
        r"\*\*Core harem \(full members\):\*\*.+",
        "**Core harem (full members):** Alice, Chloe, Becca, Emily, Sassy, Lyra, Zara, "
        "**Amira & Aisha Khoury** (full sisters — core only), Doctor Wendy.",
        t,
        count=1,
    )
    t = re.sub(
        r"\*\*Active Registry tank:\*\*.+",
        "**Available pool (single development lump):** Valentina Ortiz, Priya Sharma, Noor al-Rashid, "
        "plus extended-name sisters (Alexis…Tiffany) — all seed-locked; promote via REGISTRY-PROTOCOL. "
        "No separate tank tier.",
        t,
        count=1,
    )
    p.write_text(t, encoding="utf-8")
    print("HAREM-DOCTRINE patched")

    # HEAT-DOCTRINE twin lines
    h = RUNTIME / "HEAT-DOCTRINE.md"
    ht = h.read_text(encoding="utf-8")
    ht = ht.replace("**Amira Khoury** (registry tank)", "**Amira Khoury** (core harem twin)")
    ht = ht.replace("**Aisha Khoury** (registry tank)", "**Aisha Khoury** (core harem twin)")
    h.write_text(ht, encoding="utf-8")
    print("HEAT-DOCTRINE twin labels fixed")

    # IMAGE-PIPELINE candidate examples
    img = RUNTIME / "IMAGE-PIPELINE.md"
    it = img.read_text(encoding="utf-8")
    it = it.replace("OOC: dossier amira-khoury` | Registry candidate", "OOC: dossier valentina-ortiz` | Available pool")
    it = it.replace("--candidate amira-khoury", "--character valentina-ortiz")
    img.write_text(it, encoding="utf-8")
    print("IMAGE-PIPELINE examples retargeted")


def update_candidate_dossiers_status():
    """Mark remaining candidate dossiers as available (not tank)."""
    cand = REG / "candidates"
    if not cand.is_dir():
        return
    for d in cand.iterdir():
        if not d.is_dir():
            continue
        if d.name in ("amira-khoury", "aisha-khoury"):
            continue
        for name in ("dossier.md", "meta.json"):
            f = d / name
            if not f.is_file():
                continue
            if name.endswith(".json"):
                try:
                    meta = json.loads(f.read_text(encoding="utf-8"))
                    meta["status"] = "available"
                    meta["pool"] = "available"
                    meta.pop("tank", None)
                    f.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                except Exception as e:
                    print("meta skip", f, e)
            else:
                t = f.read_text(encoding="utf-8")
                t2 = t.replace("status: tank", "status: available")
                t2 = t2.replace("status: tank (active development)", "status: available")
                t2 = t2.replace("Registry Candidate (Tank)", "Available Pool")
                if t2 != t:
                    f.write_text(t2, encoding="utf-8")
                    print("dossier status→available", d.name)


def main():
    cfg = load_vt()
    purge_twin_tank_stubs()
    flesh_all(cfg)
    # core twins: ensure status active + no tank language in first lines already ok
    for slug in ("amira-khoury", "aisha-khoury"):
        p = CHARS / f"{slug}.md"
        t = p.read_text(encoding="utf-8")
        t = re.sub(r"^status:\s*.+$", "status: active", t, count=1, flags=re.M)
        if "no longer Registry tank" not in t:
            pass
        p.write_text(t, encoding="utf-8")
    update_vt_tiers(cfg)
    rewrite_indexes(cfg)
    rewrite_state()
    patch_doctrine_and_heat()
    update_candidate_dossiers_status()
    # verify
    assert not (REG / "candidates" / "amira-khoury").exists()
    assert not (REG / "candidates" / "aisha-khoury").exists()
    statuses = {}
    for p in CHARS.glob("*.md"):
        if p.stem in ("index", "jeff"):
            continue
        m = re.search(r"^status:\s*(.+)$", p.read_text(encoding="utf-8"), re.M)
        statuses[p.stem] = m.group(1).strip() if m else "?"
    from collections import Counter
    print("STATUS COUNTS", Counter(statuses.values()))
    print("DONE")


if __name__ == "__main__":
    main()
