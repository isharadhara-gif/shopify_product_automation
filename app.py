import os, json, time, base64, re, io, csv, random, threading
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, Response
from flask_socketio import SocketIO
from PIL import Image, ImageOps

# ── Default catalog values ────────────────────────────────────────────────────
DEFAULT_HS_CODE = '7117.90'
DEFAULT_WEIGHT_G = 1
DEFAULT_COUNTRY_OF_ORIGIN = 'IN'
DEFAULT_INVENTORY_QTY = 10
DEFAULT_BANGLE_SIZES = ['2.4', '2.6', '2.8']

TARGET_W, TARGET_H = 1080, 1440

# ── Brand color palette (54 colors) ──────────────────────────────────────────
BRAND_COLORS = [
    ("Red",              (220,  50,  50)),
    ("Orange",           (230, 120,  40)),
    ("Yellow",           (230, 200,  50)),
    ("Green",            ( 50, 160,  70)),
    ("Blue",             ( 50,  90, 200)),
    ("Purple",           (130,  50, 180)),
    ("Pink",             (230, 120, 160)),
    ("Brown",            (130,  80,  40)),
    ("Black",            ( 30,  30,  30)),
    ("White",            (245, 245, 245)),
    ("Grey",             (150, 150, 150)),
    ("Magenta",          (200,  50, 160)),
    ("Maroon",           (120,  20,  30)),
    ("Indigo",           ( 60,  50, 160)),
    ("Turquoise",        ( 50, 185, 175)),
    ("Beige",            (220, 200, 165)),
    ("Teal",             ( 30, 130, 130)),
    ("Violet",           (150,  80, 220)),
    ("Gold",             (210, 165,  50)),
    ("Silver",           (185, 190, 200)),
    ("Rose Gold",        (210, 145, 130)),
    ("Dark Red",         (140,  20,  20)),
    ("Dark Orange",      (180,  85,  15)),
    ("Dark Yellow",      (180, 150,  20)),
    ("Dark Green",       ( 25, 100,  35)),
    ("Dark Blue",        ( 20,  40, 140)),
    ("Dark Purple",      ( 85,  20, 130)),
    ("Dark Pink",        (185,  70, 110)),
    ("Dark Brown",       ( 80,  45,  15)),
    ("Dark Grey",        ( 80,  80,  80)),
    ("Dark Magenta",     (150,  20, 115)),
    ("Dark Maroon",      ( 75,  10,  15)),
    ("Dark Indigo",      ( 35,  25, 110)),
    ("Dark Turquoise",   ( 20, 130, 120)),
    ("Dark Beige",       (175, 155, 115)),
    ("Dark Teal",        ( 15,  85,  85)),
    ("Dark Violet",      (105,  45, 170)),
    ("Light Red",        (255, 120, 120)),
    ("Light Orange",     (255, 185, 120)),
    ("Light Yellow",     (255, 240, 140)),
    ("Light Green",      (140, 225, 140)),
    ("Light Blue",       (130, 175, 255)),
    ("Light Purple",     (195, 150, 240)),
    ("Light Pink",       (255, 185, 210)),
    ("Light Brown",      (190, 145, 100)),
    ("Off White",        (235, 230, 215)),
    ("Light Grey",       (210, 210, 210)),
    ("Light Magenta",    (255, 150, 230)),
    ("Light Maroon",     (185,  90, 100)),
    ("Light Indigo",     (130, 125, 220)),
    ("Light Turquoise",  (140, 230, 225)),
    ("Light Beige",      (240, 225, 200)),
    ("Light Teal",       (100, 200, 195)),
    ("Light Violet",     (210, 165, 255)),
    ("Multicolor",       (128, 128, 128)),   # fallback only — not used in nearest-neighbour
]

def _nearest_brand_color(r: int, g: int, b: int) -> str:
    """Return the closest brand color name using squared-Euclidean distance in RGB."""
    best_name, best_d = "Multicolor", float('inf')
    for name, (cr, cg, cb) in BRAND_COLORS[:-1]:   # skip Multicolor entry
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_d:
            best_d, best_name = d, name
    return best_name


def _sample_foreground(img: Image.Image, size: int = 120) -> list[tuple[int,int,int]]:
    """Resize to *size*×*size*, convert to RGB, and return only non-background pixels.

    "Background" = luma > 230 (near-white studio backdrop).
    Falls back to all pixels when fewer than 50 foreground pixels survive.
    """
    thumb = img.convert("RGB").resize((size, size), Image.LANCZOS)
    pixels = list(thumb.getdata())                       # list of (R,G,B) tuples
    fg = [(r, g, b) for r, g, b in pixels
          if (0.299 * r + 0.587 * g + 0.114 * b) < 230]
    return fg if len(fg) >= 50 else pixels


def _kmeans_dominant(pixels: list[tuple[int,int,int]],
                     k: int = 5, iterations: int = 5,
                     seed: int = 42) -> tuple[tuple[int,int,int], float]:
    """Pure-Python mini k-means.

    Returns (dominant_centroid_rgb, dominant_cluster_share).
    dominant_cluster_share is the fraction of pixels in the largest cluster —
    used by the caller to decide whether the image is multicolor.
    """
    # Deterministic seed: pick k evenly-spaced pixels as initial centers
    step = max(1, len(pixels) // k)
    centers = [pixels[i * step] for i in range(k)]

    labels = [0] * len(pixels)
    for _ in range(iterations):
        # Assignment step
        for i, (r, g, b) in enumerate(pixels):
            best_c, best_d = 0, float('inf')
            for ci, (cr, cg, cb) in enumerate(centers):
                d = (r-cr)**2 + (g-cg)**2 + (b-cb)**2
                if d < best_d:
                    best_d, best_c = d, ci
            labels[i] = best_c

        # Update step — recompute centroids
        sums   = [[0, 0, 0] for _ in range(k)]
        counts = [0] * k
        for i, (r, g, b) in enumerate(pixels):
            c = labels[i]
            sums[c][0] += r; sums[c][1] += g; sums[c][2] += b
            counts[c] += 1
        for c in range(k):
            if counts[c]:
                centers[c] = (sums[c][0] // counts[c],
                               sums[c][1] // counts[c],
                               sums[c][2] // counts[c])

    dominant_c = max(range(k), key=lambda c: (labels.count(c) if c < len(centers) else 0))
    dominant_share = labels.count(dominant_c) / len(pixels) if pixels else 1.0
    return centers[dominant_c], dominant_share


def detect_color_from_image(image_path: Path) -> str:
    """Detect the dominant brand color of the jewellery in *image_path*.

    Algorithm:
      1. Strip near-white background pixels (studio backdrops).
      2. Run 5-cluster k-means on a 120×120 thumbnail (pure Pillow, no numpy).
      3. If the largest cluster holds < 78 % of foreground pixels → "Multicolor".
      4. Otherwise map the dominant centroid to the nearest brand color by
         squared RGB distance.

    Returns one of the 54 BRAND_COLORS names.  Never raises — falls back to
    "Multicolor" on any error.
    """
    try:
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)

        pixels = _sample_foreground(img)
        centroid, share = _kmeans_dominant(pixels)

        if share < 0.78:          # no single colour dominates → multicolor product
            return "Multicolor"

        return _nearest_brand_color(*centroid)

    except Exception:
        return "Multicolor"


def process_image(path: Path) -> Path:
    """Crop-to-fit to TARGET_W × TARGET_H, save as high-quality JPEG."""
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)

        if img.mode in ('RGBA', 'P', 'LA'):
            rgba = img.convert('RGBA')
            background = Image.new('RGB', rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = img.convert('RGB')

        target_ratio = TARGET_W / TARGET_H
        w, h = img.size
        ratio = w / h
        if ratio > target_ratio:
            new_w = max(1, int(h * target_ratio))
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        else:
            new_h = max(1, int(w / target_ratio))
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))

        img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)

        new_path = path.with_suffix('.jpg')
        img.save(new_path, 'JPEG', quality=95, optimize=True, progressive=True)

        if new_path != path:
            try:
                path.unlink()
            except Exception:
                pass
        return new_path
    except Exception:
        return path

# ── Category list, tag presets & description templates ───────────────────────
# Single source of truth for every jewellery category the studio understands.
# Used to populate the dropdown selects on the frontend (via /tag_presets),
# to select the static SEO description template, and to ground the Groq
# title-generation prompt so it can't mistitle a piece as the wrong type.
CATEGORIES = [
    'Necklace', 'Choker', 'Pendant',
    'Earring', 'Ear Cuff',
    'Maang Tikka', 'Mathapatti', 'Nath',
    'Bangles', 'Kada / Handcuff', 'Bracelet', 'Hathphool / Hand Harness',
    'Brooch', 'Ring', 'Hair Accessories',
]

# Tag presets sourced directly from the brand's generalized group-tag sheet.
# Keyed by the same category names used above so the frontend can pull a
# ready-made tag string the moment a seller picks a category.
TAG_PRESETS = {
    'Necklace':                 'PPCOD, Long Necklace, Statement Necklace, Stone Necklace, Temple Necklace, Ethnic, Sabyasachi',
    'Choker':                   'PPCOD, Choker Necklaces, Choker Set, Choker Bridal Necklace, Ethnic, New Arrivals',
    'Pendant':                  'PPCOD, Pendant Necklace, AD Jewellery, Western, New Arrivals',
    'Earring':                  'PPCOD, COD, Dangler Earrings, Pearl Earrings, Bugadi Earrings, Statement Earrings, Ethnic, Western',
    'Ear Cuff':                 'PPCOD, Earcuff Earrings, Designer Earcuffs, Ethnic, Sabyasachi, New Arrivals',
    'Maang Tikka':              'PPCOD, Maangtikas, Tikka, Teeka, Mang Tikka, Ethnic, New Arrivals',
    'Mathapatti':               'PPCOD, Mathapatti, Matha Patti, Head Jewellery, Passa, Bridal, Ethnic, New Arrivals',
    'Nath':                     'PPCOD, Nath, Nose Ring, Nathni, Bridal Nath, Ethnic, New Arrivals',
    'Bangles':                  'PPCOD, Bangle, Bangles, Kada, Kangan, Ethnic, New Arrivals',
    'Kada / Handcuff':          'PPCOD, Handcuff Bracelets, Kada, AD Jewellery, Ethnic, New Arrivals',
    'Bracelet':                 'PPCOD, Bracelet, Crystal Bracelets, Stone Bracelets, Western, Ethnic, New Arrivals',
    'Hathphool / Hand Harness': 'PPCOD, Hand Harness, Hath Phool, Haathphool, Hand Jewellery, Ethnic',
    'Brooch':                   'PPCOD, Brooch, Brooch for Men, Blazer Brooch, Ethnic, New Arrivals',
    'Ring':                     'PPCOD, Ring, Rings, Statement Ring, Adjustable Ring, Ethnic, Western, New Arrivals',
    'Hair Accessories':         'PPCOD, Hair Pin, Hair Clip, Juda Pin, Hair Vine, Ethnic, New Arrivals',
}

# Hints fed straight into the Groq prompt so the model grounds the title in
# the seller-picked category instead of guessing the piece type from the
# photo alone (which is what was causing mistitled listings).
CATEGORY_TITLE_HINTS = {
    'Necklace':                 'This is a NECKLACE (worn around the full neck, longer chain/strand). Use terms like Long Necklace, Statement Necklace, Temple Necklace, Kundan Necklace Set.',
    'Choker':                   'This is a CHOKER (short necklace sitting snugly at the base of the throat). Title must include "Choker" — e.g. "Kundan Choker Necklace Set", "Bridal Choker Set".',
    'Pendant':                  'This is a PENDANT NECKLACE (a single drop/charm on a slim chain). Title should read like "[Stone/Style] Pendant Necklace".',
    'Earring':                  'This is a pair of EARRINGS. Identify the exact earring style shown — studs, jhumkas, danglers, hoops, chandbalis, or bugadi — and name it precisely in the title.',
    'Ear Cuff':                 'This is an EAR CUFF (clip-on cartilage/ear-wrap piece worn without a piercing). Title must include "Ear Cuff" or "Earcuff".',
    'Maang Tikka':              'This is a MAANG TIKKA / TEEKA (a chain with a pendant that sits on the centre parting, hanging onto the forehead). Title must include "Maang Tikka" or "Teeka".',
    'Mathapatti':               'This is a MATHAPATTI / MATHA PATTI (an elaborate head jewellery piece with chains that spread across the forehead and into the hairline, often with a side passa). Title must include "Mathapatti" or "Matha Patti".',
    'Nath':                     'This is a NATH (a nose ring or nose pin, sometimes chain-linked to the hair). Title must include "Nath" or "Nose Ring".',
    'Bangles':                  'This is a set of BANGLES (closed-circle wrist jewellery, worn stacked). Title must include "Bangle" or "Bangles" or "Kangan".',
    'Kada / Handcuff':          'This is a KADA / HANDCUFF BRACELET (a broad, often open-cuff, statement wrist piece). Title must include "Kada" or "Handcuff Bracelet".',
    'Bracelet':                 'This is a BRACELET (a delicate chain-link or beaded wrist piece, not a broad cuff). Title must include "Bracelet".',
    'Hathphool / Hand Harness': 'This is a HATHPHOOL (a ring-to-wrist piece connected by chains across the back of the hand). Title must include "Hathphool" only — do NOT use the words "Hand Harness" anywhere in the title, even though that is the category name.',
    'Brooch':                   'This is a BROOCH (a pin-back accessory for blazers, sarees, or dupattas). Title must include "Brooch".',
    'Ring':                     'This is a RING (finger jewellery). Title must include "Ring".',
    'Hair Accessories':         'This is a HAIR ACCESSORY (hairpin, clip, juda pin, or hair vine). Title must include the specific accessory type, e.g. "Hair Pin", "Juda Pin", "Hair Vine".',
}

CATEGORY_DESCRIPTIONS = {
    'Necklace': """Hello lovely souls! Don\u2019t you agree that your look is never complete without a breathtaking necklace? A necklace set isn\u2019t just an accessory. It is the star of the show, ensuring you make a lasting impression every time you step out of your house.
Ishhaara's necklaces for women whether it be a gold choker necklace set, pearl necklace, silver necklace set, or long necklace offer a phenomenal look. Pair these necklace sets and instantly make a wonderful appeal wherever you go. So, grab this chance and quickly check out the standout features of Ishhaara's necklace.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Premium Materials: From shimmering gold to lustrous pearls, Ishhaara's every piece of necklace sets such as pendant necklaces or statement necklaces are crafted using premium materials only, ensuring durability and long-lasting beauty.
2. Perfect for Layering: Whether it be an evil eye necklace, stone necklace, Kundan necklace, or ruby necklace, Ishhaara's every necklace design is ideal for mixing and matching. Ensuring you create a personalised look with multiple layers.
3. Statement Appeal: From semi-precious and precious bridal necklace sets to western necklace sets, Ishhaara's each piece is designed to be the focal point of your ensemble, ensuring all eyes are on you. Letting you take the centre of the stage.
4. Versatile Styling: Ishhaara's each piece of artificial necklaces for girls like Polki, Meenakari or temple are ideal for making a transition on a range of outfits from casual outings to grand celebrations. These neckpieces can compliment any occasion and mood effortlessly.
Styling Inspiration
1. Pair these necklaces with a traditional silk saree or lehenga. It will give a classic and regal vibe.
2. Opt for stacking these necklaces with statement bangles, a pair of bold earrings or statement rings. It will add an extra sparkle and twist to your look.
3. Style these necklaces with a chic pantsuit or tailored blazer. It will give a power-packed, professional look.
Care Label
1. Store the necklaces in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your necklace.
4. Clean your necklace after every use with a soft brush.""",

    'Choker': """Hey stunner! Isn\u2019t there something irresistibly bold about a choker sitting right at the base of your throat? Snug, striking, and impossible to ignore, a choker set instantly becomes the focal point of your entire look.
Ishhaara's chokers for women whether it be a Kundan choker set, bridal choker necklace, or a sleek velvet-base choker offer a dramatic finish to any outfit. Pair these chokers and instantly command attention wherever you go. So, grab this chance and quickly check out the standout features of Ishhaara's choker.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Snug, Flattering Fit: Ishhaara's chokers are designed to sit perfectly at the collarbone, framing the neckline and drawing the eye upward for an instantly elegant silhouette.
2. Bridal-Ready Grandeur: From Kundan choker sets to Polki bridal chokers, each piece is crafted to be the centrepiece of a bridal or festive ensemble.
3. Layer-Friendly Design: Ishhaara's chokers pair beautifully with a longer necklace underneath, letting you build a dramatic layered look in seconds.
4. Versatile Styling: Whether it's a traditional choker set or a western-inspired velvet choker, each design transitions easily from daytime events to evening celebrations.
Styling Inspiration
1. Pair a Kundan choker with a deep-neck blouse and silk saree for a regal bridal look.
2. Layer a delicate pendant necklace beneath a statement choker for added depth.
3. Style a sleek choker with an off-shoulder western outfit for a chic, modern edge.
Care Label
1. Store the choker in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your choker.
4. Clean your choker after every use with a soft brush.""",

    'Pendant': """Hello lovely! Isn\u2019t it wonderful how one delicate pendant can effortlessly complete an entire outfit? A pendant necklace isn\u2019t about doing the most, it\u2019s about doing the right amount, subtle, meaningful, and endlessly wearable.
Ishhaara's pendant necklaces whether it be a stone-studded pendant, an evil eye pendant, or a dainty AD pendant offer a refined finish for everyday wear or evening dressing. So, grab this chance and quickly check out the standout features of Ishhaara's pendant necklace.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Everyday Elegance: Ishhaara's pendant necklaces are lightweight and designed for daily wear, adding a subtle sparkle without ever feeling like too much.
2. Symbolic Charm: Many of our pendants carry meaningful motifs like the evil eye, heart, or initial, making them a thoughtful gift as much as a style statement.
3. Easy Layering: A single pendant necklace pairs effortlessly with chokers or longer chains, letting you build a personalised layered look.
4. Day-to-Night Versatility: From office wear to evening dinners, Ishhaara's pendant necklaces make the transition without missing a beat.
Styling Inspiration
1. Wear a single pendant close to the collarbone with a simple crew-neck top for understated elegance.
2. Layer a pendant necklace with a choker for a multi-dimensional look.
3. Pick a gemstone pendant to complement your outfit's colour palette for a coordinated finish.
Care Label
1. Store the pendant in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your pendant.
4. Clean your pendant after every use with a soft brush.""",

    'Earring': """Hey gorgeous! Don\u2019t you think your face glows differently the moment the right pair of earrings catches the light? Earrings aren\u2019t just an accessory, they\u2019re the easiest way to switch up an entire look in seconds.
Ishhaara's earrings for women whether it be gold studs, jhumkas, hoops, danglers, or chandbalis offer a stunning finish to any outfit. Pair these earrings and instantly elevate your everyday or festive look. So, grab this chance and quickly check out the standout features of Ishhaara's earrings.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Lightweight Comfort: Ishhaara's earrings whether it be jhumkas, studs, or chandbalis are crafted to be lightweight, ensuring comfortable wear through long days and longer celebrations.
2. Premium Finish: From shimmering kundan to lustrous pearls, every pair of earrings is crafted using premium materials only, ensuring durability and long-lasting shine.
3. Face-Framing Appeal: Whether it be danglers, hoops, or studs, Ishhaara's earrings are designed to frame the face beautifully, drawing attention upward and ensuring all eyes are on you.
4. Versatile Styling: Each pair of earrings like Polki, Meenakari, or temple is ideal for making a transition across a range of outfits from casual outings to grand celebrations.
Styling Inspiration
1. Pair statement jhumkas or chandbalis with a traditional silk saree or lehenga for a classic, regal vibe.
2. Opt for delicate studs or small hoops with western wear for an everyday chic look.
3. Style oversized hoops or danglers with an updo hairstyle to let the earrings take centre stage.
Care Label
1. Store the earrings in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your earrings.
4. Clean your earrings after every use with a soft brush.""",

    'Ear Cuff': """Hey edgy soul! Who says you need a piercing to make a statement on your ear? An ear cuff clips on, wraps around, and instantly gives your look a contemporary, no-fuss edge.
Ishhaara's ear cuffs whether it be a delicate crawler-style cuff or a bold statement earcuff offer a striking finish without committing to another piercing. So, grab this chance and quickly check out the standout features of Ishhaara's ear cuffs.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. No Piercing Needed: Ishhaara's ear cuffs clip comfortably onto the ear, giving you the look of multiple piercings without any commitment.
2. Contemporary Edge: Designed for the modern, fashion-forward wearer, our earcuffs add an unexpected, edgy detail to any outfit.
3. Layer with Studs: Pair an ear cuff with a classic stud on the lobe for a stacked, multi-piercing illusion.
4. Adjustable Comfort: Every earcuff is designed with a flexible fit that comfortably hugs the ear's curve without pinching.
Styling Inspiration
1. Stack an ear cuff above a simple stud for an effortlessly edgy everyday look.
2. Pair a statement earcuff solo on one ear for an asymmetric, fashion-forward finish.
3. Style with sleek, pulled-back hair to let the earcuff's detailing take centre stage.
Care Label
1. Store the ear cuff in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your ear cuff.
4. Clean your ear cuff after every use with a soft brush.""",

    'Maang Tikka': """Hey bride-to-be (or just in the mood to glow)! Isn\u2019t a maang tikka the single most striking way to frame your face for a festive occasion? Resting right on the centre parting, it draws every eye straight to you.
Ishhaara's maang tikkas whether it be a Kundan teeka, a Polki mang tikka, or a delicate everyday tikka offer a stunning finish for weddings, festivals, and celebrations. So, grab this chance and quickly check out the standout features of Ishhaara's maang tikka.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Bridal Centrepiece: Ishhaara's maang tikkas are crafted to be the crowning detail of a bridal or festive look, sitting elegantly along the centre parting.
2. Adjustable Fit: Every tikka comes with an adjustable chain or hook, ensuring a comfortable, secure fit across different hairstyles.
3. Premium Craftsmanship: From Kundan to Polki to Meenakari, our tikkas are handcrafted using premium materials for long-lasting shine.
4. Versatile Pairing: A maang tikka pairs beautifully with matching earrings and a choker for a complete bridal jewellery set.
Styling Inspiration
1. Wear a Kundan maang tikka with a centre-parted bridal hairstyle for a timeless regal look.
2. Pair with a matching choker and jhumkas for a coordinated festive ensemble.
3. Opt for a delicate tikka with a sleek bun for an elegant, understated finish at smaller celebrations.
Care Label
1. Store the maang tikka in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your maang tikka.
4. Clean your maang tikka after every use with a soft brush.""",

    'Mathapatti': """Hey gorgeous bride! Isn\u2019t a mathapatti the most breathtaking way to crown your bridal look? Spreading gracefully across the forehead and into the hairline, it turns your entire hairstyle into a jewel in itself.
Ishhaara's mathapattis whether it be a Kundan matha patti, a Polki bridal set with side passa, or a Meenakari head piece offer full bridal grandeur for weddings and grand celebrations. So, grab this chance and quickly check out the standout features of Ishhaara's mathapatti.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Full Bridal Coverage: Ishhaara's mathapattis are designed with multiple connected chains that elegantly cover the forehead and hairline for maximum bridal impact.
2. Adjustable Framework: Every mathapatti comes with adjustable hooks and chains so it sits securely and comfortably across different hairstyles.
3. Heritage Craftsmanship: Inspired by Rajasthani and Maharashtrian bridal traditions, our mathapattis are handcrafted with Kundan, Polki, or Meenakari detailing.
4. Statement Centrepiece: Designed to be the crowning glory of a bridal look, pairing beautifully with a matching maang tikka, choker, and jhumkas.
Styling Inspiration
1. Pair a mathapatti with a centre-parted bridal hairstyle and a matching maang tikka for a regal look.
2. Style with a heavy lehenga or bridal saree to balance the intricate headpiece detailing.
3. Complete the ensemble with matching jhumkas and a choker for a full bridal jewellery set.
Care Label
1. Store the mathapatti in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your mathapatti.
4. Clean your mathapatti after every use with a soft brush.""",

    'Nath': """Hey beautiful! Isn\u2019t a nath one of the most timeless symbols of bridal and festive jewellery? Whether clipped on or chain-linked to the hair, a nath instantly elevates a traditional look with quiet grandeur.
Ishhaara's naths whether it be a Maharashtrian nath, a Kashmiri-style nose ring, or a delicate everyday nath pin offer an authentic finish for weddings, festivals, and cultural celebrations. So, grab this chance and quickly check out the standout features of Ishhaara's nath.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. No-Piercing Option: Many of Ishhaara's naths come as clip-on styles, so you can wear the look without a nose piercing.
2. Cultural Authenticity: From Maharashtrian nauvari-style naths to Kashmiri and Rajasthani designs, each piece stays true to traditional craftsmanship.
3. Lightweight Comfort: Designed to sit comfortably for hours, even through long wedding functions and celebrations.
4. Chain-Linked Elegance: Several designs connect via a fine chain to the hair, adding a graceful, secure drape alongside the nose ring.
Styling Inspiration
1. Pair a Maharashtrian nath with a nauvari saree and matching bangles for an authentic traditional look.
2. Style a delicate nath pin for everyday festive wear without an elaborate hair chain.
3. Coordinate your nath with a matching maang tikka and jhumkas for a complete bridal ensemble.
Care Label
1. Store the nath in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your nath.
4. Clean your nath after every use with a soft brush.""",

    'Bangles': """Hey gorgeous! Isn\u2019t there something so satisfying about the gentle jingle of a stack of bangles on your wrist? Bangles aren\u2019t just jewellery, they're rhythm, tradition, and effortless glamour rolled into one.
Ishhaara's bangles whether it be a classic gold-finish bangle, an oxidised kada, or a Kundan kangan offer a timeless finish for everyday wear or festive dressing. So, grab this chance and quickly check out the standout features of Ishhaara's bangles.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Perfectly Stackable: Ishhaara's bangles are designed to be mixed, matched, and stacked, letting you build your own signature wrist stack.
2. Broad Statement Kadas: For a bolder look, our kada-style bangles make a striking standalone statement.
3. Festive & Everyday Fit: Available in a range of sizes and finishes, our bangles transition easily from daily wear to wedding season.
4. Cultural Craftsmanship: Whether Kundan, Meenakari, or oxidised, every bangle is handcrafted to reflect authentic Indian jewellery traditions.
Styling Inspiration
1. Stack multiple bangles of varying widths and finishes for a rich, layered wrist look.
2. Pair a single broad kada with a solid-coloured outfit for a striking minimalist statement.
3. Match your bangle finish to your other jewellery pieces for a cohesive festive look.
Care Label
1. Store the bangles in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your bangles.
4. Clean your bangles after every use with a soft brush.""",

    'Kada / Handcuff': """Hey bold soul! Isn\u2019t a kada or handcuff bracelet the ultimate way to make a wrist statement that can\u2019t be ignored? Broad, sculptural, and unapologetically striking, it's the piece that finishes the look.
Ishhaara's kadas and handcuff bracelets whether it be an oxidised handcuff, an AD-studded kada, or a sleek open-cuff design offer a bold finish for festive dressing or fusion styling. So, grab this chance and quickly check out the standout features of Ishhaara's kada / handcuff.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Adjustable Open Cuff: Ishhaara's handcuff bracelets and kadas feature an open-cuff design that adjusts comfortably to most wrist sizes.
2. Bold Statement Wrist Piece: Designed to be worn solo, each kada or handcuff makes a striking impact without needing any other wrist jewellery.
3. Oxidised & AD Detailing: From oxidised silver finishes to AD stonework, our designs suit both ethnic and fusion styling.
4. Bollywood-Inspired Glamour: Reflecting the iconic statement jewellery seen on the red carpet, our kadas and handcuffs bring instant drama to any outfit.
Styling Inspiration
1. Wear a single oxidised handcuff with a solid-coloured kurta for an eye-catching fusion look.
2. Pair an AD kada with a lehenga for a bold bridal-adjacent statement.
3. Style with rolled-up sleeves so the sculptural detailing of the cuff stays visible.
Care Label
1. Store the kada / handcuff in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your kada / handcuff.
4. Clean your kada / handcuff after every use with a soft brush.""",

    'Bracelet': """Hey lovely! Isn\u2019t a delicate bracelet the easiest way to add a touch of sparkle to your everyday wrist? Light, dainty, and endlessly stackable, it's the accessory that quietly does the most.
Ishhaara's bracelets whether it be a crystal-studded bracelet, a stone bracelet, or a fine chain-link design offer a versatile finish for both western and ethnic styling. So, grab this chance and quickly check out the standout features of Ishhaara's bracelet.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Delicate, Everyday Wear: Ishhaara's bracelets are lightweight and comfortable enough for all-day wear, whether at work or a night out.
2. Crystal & Stone Detailing: Featuring crystal and stone embellishments, each bracelet adds a subtle sparkle without overwhelming the look.
3. Stackable with Bangles: Our bracelets pair beautifully alongside bangles and kadas for a rich, layered wrist stack.
4. Western-Ethnic Fusion: Versatile enough to style with both western outfits and ethnic wear, making it a year-round staple.
Styling Inspiration
1. Stack a delicate bracelet alongside your bangles for a fusion wrist look.
2. Wear a crystal bracelet solo with a western dress for understated evening glam.
3. Match a stone bracelet to your outfit's accent colour for a coordinated finish.
Care Label
1. Store the bracelet in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your bracelet.
4. Clean your bracelet after every use with a soft brush.""",

    'Hathphool / Hand Harness': """Hey gorgeous! Are you ready to add a whimsical statement to your \u2018Solah Shringar\u2019? A hathphool, connecting a ring to a wrist chain across the back of the hand, is one of the most graceful pieces in bridal jewellery.
Ishhaara's hathphools and hand harnesses whether it be a Kundan hathphool, a delicate chain-link hand harness, or a statement bridal piece offer a stunning finish for weddings and festive occasions. So, grab this chance and quickly check out the standout features of Ishhaara's hathphool / hand harness.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Graceful Hand Coverage: Ishhaara's hathphools connect a ring to the wrist via delicate chains, elegantly covering the back of the hand.
2. Bridal Signature Piece: A must-have for the complete Solah Shringar bridal look, adding an extra layer of intricate detailing.
3. Adjustable, Comfortable Fit: Designed with adjustable rings and chain lengths to comfortably fit most hand sizes.
4. Cultural Connection: Rooted in Indian bridal tradition, our hathphools carry deep cultural significance while looking effortlessly elegant.
Styling Inspiration
1. Pair a Kundan hathphool with your bridal Chooda for a complete traditional hand look.
2. Wear a delicate hand harness with a fitted sleeve outfit to let the detailing stand out.
3. Match your hathphool's finish to your other bridal jewellery for a coordinated ensemble.
Care Label
1. Store the hathphool / hand harness in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your hathphool / hand harness.
4. Clean your hathphool / hand harness after every use with a soft brush.""",

    'Brooch': """Hey stylish soul! Isn\u2019t a brooch the smallest accessory with the biggest impact? Pinned onto a blazer, saree, or dupatta, it instantly signals intention and polish.
Ishhaara's brooches whether it be a classic blazer brooch, a statement saree pin, or a brooch for men offer a refined finishing touch to any outfit. So, grab this chance and quickly check out the standout features of Ishhaara's brooch.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Pins Onto Any Fabric: Ishhaara's brooches feature a secure pin-back that attaches easily to blazers, sarees, dupattas, or lapels.
2. Unisex Styling: From blazer brooches for men to statement pieces for sarees, our designs suit every wardrobe.
3. Instant Finishing Touch: A single brooch can elevate a plain outfit into a polished, intentional look in seconds.
4. Versatile Placement: Wear it on a lapel, a saree pallu, a dupatta, or even as a hairpin alternative.
Styling Inspiration
1. Pin a classic brooch onto a blazer lapel for a sharp, professional finish.
2. Use a statement brooch to secure a saree pallu for an elegant, functional detail.
3. Style a brooch on a dupatta corner for a subtle festive touch.
Care Label
1. Store the brooch in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your brooch.
4. Clean your brooch after every use with a soft brush.""",

    'Ring': """Howdy, partners! Are you passionate about elevating your style with stunning rings? Isn\u2019t it incredible how these glamorous accessories can add elegance, flair, and trendiness to any outfit? Whether you love adding gold rings, traditional rings, statement rings, or oxidised rings, Ishhaara's treasure trove uncovers a wide variety of choices.
These rings are perfect for transforming any look into something extraordinary and are essential additions to your jewellery box. Ready to find the perfect piece? Dive in and explore the details now!
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Timeless Finish: Ishhaara's artificial rings come in various finishes from polished, matte, brushed or hammered texture. Allowing you to bring a glittery shine to your overall look.
2. Meaningful Piece: Ishhaara's every piece of ring is crafted from precious or semi-precious stones that hold symbolic meanings like love, commitment, friendship, or personal achievements. Making a perfect gift or passing it down to heirlooms.
3. Full Versatility: Ishhaara\u2019s every piece of ring whether it be silver rings, gold rings, Kundan rings, or Polki rings gives you full flexibility of wearing it alone or stacking with other rings. Perfect for adding a layered chic style that defines your personality.
4. Free Size: Ishhaara\u2019s every type of artificial ring for women whether it be engagement rings or stainless steel rings is curated to fit every finger size. Ensuring you create a perfect look with a fully comfortable accessory.
5. Gemstone Setting: Ishhaara\u2019s artificial rings for girls are made in various styles and settings such as prongs, bezels, or channel settings. This ensures you make a vibrantly visual appeal wherever you go.""",

    'Hair Accessories': """Hey beautiful! Isn\u2019t it amazing how the right hair accessory can transform your entire look in seconds? A hairpin, clip, or hair band isn\u2019t just functional. It is a styling statement that ties your whole appearance together effortlessly.
Ishhaara's hair accessories for women whether it be a pearl hairpin, kundan maang tikka, juda pin, or floral hair vine offer a stunning finish to any hairstyle. Pair these pieces and instantly elevate your everyday or festive look. So, grab this chance and quickly check out the standout features of Ishhaara's hair accessories.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Premium Materials: From shimmering kundan to delicate pearls, Ishhaara's every hair accessory such as hairpins or maang tikkas is crafted using premium materials only, ensuring durability and long-lasting beauty.
2. Secure Hold: Whether it be a juda pin, clutcher, or hair vine, Ishhaara's every design is built to hold your hairstyle in place comfortably through long functions and celebrations.
3. Statement Appeal: From bridal maang tikkas to everyday hair clips, Ishhaara's each piece is designed to be a focal point of your hairstyle, ensuring all eyes are on you.
4. Versatile Styling: Ishhaara's each piece of hair accessory like Polki, Meenakari, or floral designs is ideal for making a transition across a range of hairstyles from casual buns to grand bridal updos.
Styling Inspiration
1. Pair these hair accessories with a traditional bun or braided hairstyle. It will give a classic and regal vibe.
2. Opt for stacking multiple hairpins or clips along a side parting. It will add an extra sparkle and twist to your look.
3. Style a single statement hair vine or tikka with an open hairstyle for special occasions for an instant glam finish.
Care Label
1. Store the hair accessories in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your hair accessories.
4. Clean your hair accessories after every use with a soft brush.""",
}

_SECTION_HEADERS = {'Product Specification', 'Key Highlights', 'Styling Inspiration', 'Care Label'}
_LABEL_LINE_RE = re.compile(r'^([A-Za-z][A-Za-z \u2019\']{1,30}):\s*(.*)$')
_NUMBERED_RE = re.compile(r'^(\d+\.\s*[^:]+:)\s*(.*)$')

def template_description_html(category):
    text = CATEGORY_DESCRIPTIONS.get(category)
    if not text:
        return None
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    html_parts = []
    for p in paragraphs:
        if p in _SECTION_HEADERS:
            html_parts.append(f'<p><strong>{p}</strong></p>'); continue
        m = _NUMBERED_RE.match(p)
        if m:
            html_parts.append(f'<p><strong>{m.group(1)}</strong> {m.group(2)}'); continue
        m = _LABEL_LINE_RE.match(p)
        if m:
            html_parts.append(f'<p><strong>{m.group(1)}:</strong> {m.group(2)}</p>'); continue
        html_parts.append(f'<p>{p}</p>')
    return ''.join(html_parts)

def random_digits(n=10):
    return ''.join(str(random.randint(0, 9)) for _ in range(n))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

UPLOAD_DIR = Path('uploads'); UPLOAD_DIR.mkdir(exist_ok=True)
HISTORY_FILE = Path('history.json')
SETTINGS_FILE = Path('settings.json')

MAX_CONCURRENT = 3
upload_semaphore = threading.Semaphore(MAX_CONCURRENT)

import requests

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_settings():
    if SETTINGS_FILE.exists():
        try: return json.loads(SETTINGS_FILE.read_text())
        except Exception: return {}
    return {}

def load_history():
    if HISTORY_FILE.exists():
        try: return json.loads(HISTORY_FILE.read_text())
        except Exception: return []
    return []

def append_history(row):
    h = load_history(); h.insert(0, row); h = h[:500]
    HISTORY_FILE.write_text(json.dumps(h, indent=2))

def log(sid, msg, level='info'):
    socketio.emit('log', {'msg': msg, 'level': level}, to=sid)

def slugify(text):
    text = (text or '').lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-') or f'product-{int(time.time())}'

def _strip_phrase(text, phrase):
    """Remove *phrase* (case-insensitive, whole-word) from *text* and tidy up
    any leftover double spaces or stray connector words/punctuation left behind
    (e.g. "Kundan Hathphool Hand Harness with Pearls" -> "Kundan Hathphool with Pearls")."""
    if not text:
        return text
    cleaned = re.sub(re.escape(phrase), '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)          # collapse double spaces
    cleaned = re.sub(r'\s+([,\-])', r'\1', cleaned)    # trailing space before , or -
    cleaned = re.sub(r'^[\s,\-]+|[\s,\-]+$', '', cleaned)  # trim stray leading/trailing junk
    return cleaned.strip() or text

def calc_sp(cp: float, markup: float = 4.0) -> int:
    raw = cp * markup
    tiers = []
    for base in range(1, 100):
        for exp in (1, 2, 3, 4, 5):
            tiers.append(base * (10 ** exp) - 1)
    tiers = sorted(set(tiers))
    for t in tiers:
        if t >= raw:
            return t
    base = int(raw)
    remainder = base % 1000
    return base - remainder + 999 if remainder < 999 else base + 999

# ── Groq rate limiting / retry ────────────────────────────────────────────────
GROQ_CALL_LOCK = threading.Lock()
GROQ_LAST_CALL_AT = [0.0]
GROQ_MIN_INTERVAL = 2.2
GROQ_MAX_RETRIES = 4

def call_groq_with_backoff(payload, headers, sid):
    last_exc = None
    for attempt in range(GROQ_MAX_RETRIES):
        with GROQ_CALL_LOCK:
            wait = GROQ_MIN_INTERVAL - (time.time() - GROQ_LAST_CALL_AT[0])
            if wait > 0:
                time.sleep(wait)
            GROQ_LAST_CALL_AT[0] = time.time()
        try:
            resp = requests.post('https://api.groq.com/openai/v1/chat/completions',
                                  headers=headers, json=payload, timeout=30)
            if resp.status_code == 429:
                retry_after = resp.headers.get('Retry-After')
                try:    delay = float(retry_after) if retry_after else 2 ** (attempt + 1)
                except: delay = 2 ** (attempt + 1)
                log(sid, f'⏳ Groq rate limit — retrying in {delay:.0f}s (attempt {attempt+1}/{GROQ_MAX_RETRIES})', 'muted')
                time.sleep(delay); last_exc = requests.exceptions.HTTPError('429'); continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < GROQ_MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            continue
    raise last_exc or RuntimeError('Groq request failed after retries')

# ── Groq: generate product fields ─────────────────────────────────────────────
def generate_product_details(image_paths, sku, sid, category=None):
    settings = load_settings()
    groq_key = settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY', '')

    if not groq_key:
        log(sid, 'Groq key not set — using SKU as title', 'muted')
        slug = slugify(sku)
        return {'title': sku, 'description': '', 'handle': slug,
                'seo_title': sku, 'seo_description': '', 'alt_text': sku, 'tags': ''}

    log(sid, f'🤖 Generating product content via Groq for {sku}…')
    try:
        image_path = image_paths[0]
        img_bytes = image_path.read_bytes()
        b64 = base64.b64encode(img_bytes).decode()
        ext = image_path.suffix.lower().lstrip('.')
        mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp'}.get(ext,'image/jpeg')
        vendor = settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR', 'the brand')

        category_block = ''
        if category:
            hint = CATEGORY_TITLE_HINTS.get(category, '')
            category_block = f"""
THE SELLER HAS ALREADY IDENTIFIED THE CATEGORY AS: "{category}".
{hint}
Do NOT override this with a different jewellery type guessed from the photo — ground the title in "{category}" above everything else. If the image looks ambiguous, still trust the seller-provided category."""

        prompt = f"""You are an expert jewellery copywriter for {vendor}, an Indian fashion jewellery brand.
The SKU is {sku}. Study the product image carefully — it is a piece of jewellery.
{category_block}

IMPORTANT RULES:
- Title must name the jewellery type specifically (e.g. "Kundan Choker Necklace Set", "Oxidised Jhumka Earrings", "Meenakari Bangle", "Temple Jewellery Maang Tikka"). Never use clothing terms.
- Use Indian jewellery vocabulary where relevant: Kundan, Polki, Meenakari, Jadau, Oxidised, Temple, Antique, Filigree, Jhumka, Chandbali, Maang Tikka, Matha Patti, Nath, Hathphool, Kamarband, Bajuband, Choker, Layered, Statement, etc.
- Tags must be jewellery-only: piece type, style, occasion (wedding, festive, bridal, casual, ethnic), finish (gold-plated, silver-plated, antique, oxidised), and stone if visible.
- Description must focus on jewellery: metal finish, stone/bead type, craftsmanship technique, and occasion suitability. No clothing references.

Respond ONLY with a valid JSON object (no markdown, no extra text):
{{
  "title": "Specific jewellery name using Indian jewellery terms, 4-8 words",
  "description": "2-3 sentence HTML description covering: jewellery type and style, metal finish and stones/beads, craftsmanship and occasion. Use <strong> tags on key feature labels only.",
  "handle": "url-slug-from-title-lowercase-hyphens",
  "seo_title": "Buy [Title] Online - {vendor} (max 60 chars)",
  "seo_description": "Buy [Title] from {vendor}. Shop handcrafted Indian jewellery online. (max 160 chars)",
  "alt_text": "{vendor} [Title] — handcrafted Indian jewellery",
  "tags": "comma-separated jewellery tags: piece type, style, occasion, finish, stone/material"
}}"""

        headers = {'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'}
        payload = {
            'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
            'messages': [{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{b64}'}},
                {'type': 'text', 'text': prompt}
            ]}],
            'max_tokens': 500,
        }
        resp = call_groq_with_backoff(payload, headers, sid)
        content = resp.json()['choices'][0]['message']['content'].strip()
        content = content.replace('```json','').replace('```','').strip()
        result = json.loads(content)
        if category == 'Hathphool / Hand Harness' and result.get('title'):
            result['title'] = _strip_phrase(result['title'], 'Hand Harness')
        result['handle'] = slugify(result.get('handle', result.get('title', sku)))
        log(sid, f'✅ Title: {result.get("title")}', 'success')
        return result
    except Exception as e:
        log(sid, f'⚠️ Groq error: {e} — using SKU fallback', 'error')
        slug = slugify(sku)
        return {'title': sku, 'description': '', 'handle': slug,
                'seo_title': sku, 'seo_description': '', 'alt_text': sku, 'tags': ''}

# ── Shopify: publish to all sales channels ────────────────────────────────────
def publish_to_all_channels(base_url, headers, product_id, sid):
    store_host = base_url.split('/admin/api/')[0].replace('https://','')
    api_version = base_url.split('/admin/api/')[1]
    gql_url = f'https://{store_host}/admin/api/{api_version}/graphql.json'
    gql_headers = {k: v for k, v in headers.items()}
    try:
        pub_query = '{ publications(first: 25) { edges { node { id name } } } }'
        r = requests.post(gql_url, headers=gql_headers, json={'query': pub_query}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if 'errors' in data:
            log(sid, f'⚠️ Could not list sales channels: {data["errors"]}', 'error'); return
        pubs = data.get('data', {}).get('publications', {}).get('edges', [])
        if not pubs:
            log(sid, 'ℹ️ No sales channels found', 'muted'); return
        gid = f'gid://shopify/Product/{product_id}'
        mutation = """
        mutation publishablePublish($id: ID!, $input: [PublicationInput!]!) {
          publishablePublish(id: $id, input: $input) {
            userErrors { field message }
          }
        }"""
        variables = {'id': gid, 'input': [{'publicationId': p['node']['id']} for p in pubs]}
        r2 = requests.post(gql_url, headers=gql_headers,
                            json={'query': mutation, 'variables': variables}, timeout=30)
        r2.raise_for_status()
        result = r2.json()
        errs = result.get('data',{}).get('publishablePublish',{}).get('userErrors',[])
        if errs: log(sid, f'⚠️ Channel publish errors: {errs}', 'error')
        else:
            names = ', '.join(p['node']['name'] for p in pubs)
            log(sid, f'✅ Published to all sales channels ({names})', 'success')
    except Exception as e:
        log(sid, f'⚠️ Could not publish to all sales channels: {e}', 'error')

def set_inventory_item_details(base_url, headers, inventory_item_id, hs_code_clean,
                                country_of_origin, cost_price, sid, label=''):
    cost_payload = {}
    if cost_price not in (None, '', 0):
        cost_payload['cost'] = str(cost_price)
    for attempt in range(2):
        try:
            resp = requests.put(
                f'{base_url}/inventory_items/{inventory_item_id}.json',
                headers=headers,
                json={'inventory_item': {
                    'id': inventory_item_id,
                    'harmonized_system_code': hs_code_clean,
                    'country_code_of_origin': country_of_origin,
                    **cost_payload,
                }}, timeout=30)
            if resp.ok:
                saved = resp.json().get('inventory_item', {})
                ok = (saved.get('harmonized_system_code') == hs_code_clean and
                      saved.get('country_code_of_origin') == country_of_origin)
                if cost_payload:
                    ok = ok and saved.get('cost') is not None
                if ok:
                    log(sid, f'✅ {label}HS {hs_code_clean} · Origin {country_of_origin} confirmed', 'success')
                    return
                log(sid, f'⚠️ {label}HS/origin saved but mismatched, retrying…', 'error')
            else:
                log(sid, f'⚠️ {label}HS/origin update failed (HTTP {resp.status_code}): {resp.text[:200]}', 'error')
        except Exception as e:
            log(sid, f'⚠️ {label}Could not set HS/origin: {e}', 'error')
        time.sleep(1)

# ── Shopify: create product ───────────────────────────────────────────────────
def create_shopify_product(image_paths, sku, selling_price, details, sid,
                            manual_title=None, category=None, manual_tags=None,
                            weight_g=None, hs_code=None, country_of_origin=None,
                            inventory_qty=None, cost_price=None,
                            colors=None, sizes=None):
    settings = load_settings()
    store = (settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE','')).replace('https://','').replace('http://','').rstrip('/')
    token = settings.get('shopify_token') or os.environ.get('SHOPIFY_TOKEN','')
    vendor = settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR','')
    p_type = settings.get('product_type') or os.environ.get('PRODUCT_TYPE','')

    if not store or not token:
        raise ValueError('Shopify store or token not configured')

    base_url = f'https://{store}/admin/api/2024-01'
    headers  = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}

    title        = manual_title or details.get('title', sku)
    template_desc = template_description_html(category)
    description  = template_desc if template_desc else details.get('description', '')
    handle       = details.get('handle', slugify(title))
    seo_title    = details.get('seo_title', f'Buy {title} Online - {vendor}')
    seo_desc     = details.get('seo_description', '')
    tags         = (manual_tags or '').strip() or details.get('tags', '')

    weight_g = weight_g if weight_g not in (None,'',0) else settings.get('default_weight_g', DEFAULT_WEIGHT_G)
    try:    weight_g = float(weight_g)
    except: weight_g = DEFAULT_WEIGHT_G

    hs_code_raw   = (hs_code or '').strip() or settings.get('default_hs_code', DEFAULT_HS_CODE)
    hs_code_clean = re.sub(r'[^0-9]','',hs_code_raw) or re.sub(r'[^0-9]','',DEFAULT_HS_CODE)

    country_of_origin = (country_of_origin or '').strip().upper() or \
        (settings.get('default_country_of_origin') or DEFAULT_COUNTRY_OF_ORIGIN).upper()

    inventory_qty = inventory_qty if inventory_qty not in (None,'') else settings.get('default_inventory_qty', DEFAULT_INVENTORY_QTY)
    try:    inventory_qty = int(inventory_qty)
    except: inventory_qty = DEFAULT_INVENTORY_QTY

    compare_at_price = int(round(selling_price * 2))
    title_slug       = slugify(title)
    base_image_name  = f'ishhaara-{title_slug}-{random_digits(10)}'
    alt_text         = details.get('alt_text') or f'Ishhaara {title}'

    colors = [c.strip() for c in (colors or []) if c.strip()]
    sizes  = [s.strip() for s in (sizes  or []) if s.strip()]

    log(sid, f'📦 Creating Shopify product: {title}…')

    base_variant = {
        'price': str(selling_price),
        'compare_at_price': str(compare_at_price),
        'inventory_management': 'shopify',
        'inventory_policy': 'deny',
        'fulfillment_service': 'manual',
        'requires_shipping': True,
        'taxable': True,
        'weight': weight_g,
        'weight_unit': 'g',
        'inventory_quantity': inventory_qty,
    }

    options = []
    variants = []

    if colors and sizes:
        options = [{'name':'Color','values':colors},{'name':'Size','values':sizes}]
        idx = 1
        for c in colors:
            for s in sizes:
                variants.append({**base_variant,'option1':c,'option2':s,'sku':f'{sku}.{idx}'}); idx+=1
    elif colors:
        options = [{'name':'Color','values':colors}]
        for idx, c in enumerate(colors, 1):
            variants.append({**base_variant,'option1':c,'sku':f'{sku}.{idx}'})
    elif sizes:
        options = [{'name':'Size','values':sizes}]
        for idx, s in enumerate(sizes, 1):
            variants.append({**base_variant,'option1':s,'sku':f'{sku}.{idx}'})
    else:
        variants = [{**base_variant,'sku':sku}]

    product_payload = {
        'title': title, 'body_html': description, 'vendor': vendor,
        'product_type': p_type, 'handle': handle, 'tags': tags,
        'metafields_global_title_tag': seo_title,
        'metafields_global_description_tag': seo_desc,
        'variants': variants, 'status': 'active', 'published': True, 'gift_card': False,
    }
    if options:
        product_payload['options'] = options

    resp = requests.post(f'{base_url}/products.json', headers=headers,
                          json={'product': product_payload}, timeout=30)
    if not resp.ok:
        try:    shopify_errors = resp.json().get('errors')
        except: shopify_errors = resp.text[:500]
        log(sid, f'❌ Shopify rejected product (HTTP {resp.status_code}): {shopify_errors}', 'error')
        raise ValueError(f'Shopify {resp.status_code}: {shopify_errors}')

    product    = resp.json()['product']
    product_id = product['id']
    variant_note = f' | {len(product["variants"])} variants ({", ".join(o["name"] for o in options)})' if options else ''
    log(sid, f'✅ Product created — ID {product_id} | MRP ₹{compare_at_price} → SP ₹{selling_price} | Qty {inventory_qty}{variant_note}', 'success')

    for v in product['variants']:
        label = f'[{v.get("title",v.get("sku",""))}] ' if options else ''
        set_inventory_item_details(base_url, headers, v['inventory_item_id'],
                                    hs_code_clean, country_of_origin, cost_price, sid, label=label)

    publish_to_all_channels(base_url, headers, product_id, sid)

    total = len(image_paths)
    for i, img_path in enumerate(image_paths, 1):
        log(sid, f'🖼️ Uploading image {i}/{total}…')
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        ext = img_path.suffix.lower() or '.jpg'
        img_filename = f'{base_image_name}{("-"+str(i)) if total>1 else ""}{ext}'
        img_alt = alt_text if i==1 else f'{alt_text} - view {i}'
        img_resp = requests.post(
            f'{base_url}/products/{product_id}/images.json', headers=headers,
            json={'image':{'attachment':img_b64,'filename':img_filename,'alt':img_alt}}, timeout=60)
        if img_resp.ok: log(sid, f'✅ Image {i}/{total} uploaded', 'success')
        else:           log(sid, f'⚠️ Image {i}/{total} failed: {img_resp.text}', 'error')

    shopify_url = f'https://{store}/admin/products/{product_id}'
    return {'product_id':product_id,'shopify_url':shopify_url,'handle':handle,
            'title':title,'compare_at_price':compare_at_price,
            'hs_code':hs_code_clean,'country_of_origin':country_of_origin,
            'variant_count':len(variants),'detected_color':colors[0] if colors else None}

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    settings = load_settings()
    has_groq    = bool(settings.get('groq_api_key')    or os.environ.get('GROQ_API_KEY'))
    has_shopify = bool(settings.get('shopify_store')   or os.environ.get('SHOPIFY_STORE'))
    shopify_store = settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE','')
    with open('index.html','r') as f:
        html = f.read()
    html = (html
        .replace('{% if has_groq %}ok{% else %}warn{% endif %}',    'ok' if has_groq else 'warn')
        .replace('{% if not has_groq %}— not set{% endif %}',       '' if has_groq else '— not set')
        .replace('{% if has_shopify %}ok{% else %}warn{% endif %}', 'ok' if has_shopify else 'warn')
        .replace('{% if not has_shopify %}— not set{% endif %}',    '' if has_shopify else '— not set')
        .replace('{{ shopify_store }}', shopify_store))
    return html

# ── NEW: return the full color list so the frontend can show it ───────────────
@app.route('/colors')
def get_colors():
    return jsonify([c[0] for c in BRAND_COLORS])

# ── NEW: return the jewellery category list + tag presets ─────────────────────
@app.route('/tag_presets')
def get_tag_presets():
    return jsonify({'categories': CATEGORIES, 'presets': TAG_PRESETS})

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('images')
    if not files:
        if 'image' in request.files: files = [request.files['image']]
        else: return jsonify({'error':'No image file(s)'}), 400

    sku = request.form.get('sku','').strip().upper()
    if not sku: return jsonify({'error':'SKU required'}), 400

    saved = []
    ts = int(time.time() * 1000)
    for idx, file in enumerate(files):
        ext = Path(file.filename).suffix.lower() or '.jpg'
        filename = f'{sku}_{ts}_{idx}{ext}'
        save_path = UPLOAD_DIR / filename
        file.save(save_path)
        processed_path = process_image(save_path)
        saved.append(processed_path.name)

    return jsonify({'filenames':saved,'sku':sku})

@app.route('/history')
def history():
    return jsonify(load_history())

@app.route('/history/csv')
def history_csv():
    rows = load_history()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Timestamp','SKU','Title','Images','Variants','Cost Price','Selling Price',
                      'Compare At (MRP)','HS Code','Country of Origin','Detected Color','Status','Shopify URL','Error'])
    for r in rows:
        writer.writerow([r.get('timestamp'),r.get('sku'),r.get('title'),r.get('image_count',1),
                          r.get('variant_count',1),r.get('cost_price'),r.get('selling_price'),
                          r.get('compare_at_price'),r.get('hs_code'),r.get('country_of_origin'),
                          r.get('detected_color',''),r.get('status'),r.get('shopify_url'),r.get('error')])
    return Response(buf.getvalue(), mimetype='text/csv',
                     headers={'Content-Disposition':'attachment; filename=upload_history.csv'})

@app.route('/get_settings')
def get_settings_route():
    settings = load_settings()
    out = {
        'shopify_store':  settings.get('shopify_store')  or os.environ.get('SHOPIFY_STORE',''),
        'shopify_token':  settings.get('shopify_token')  or os.environ.get('SHOPIFY_TOKEN',''),
        'groq_api_key':   settings.get('groq_api_key')   or os.environ.get('GROQ_API_KEY',''),
        'product_vendor': settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR',''),
        'product_type':   settings.get('product_type')   or os.environ.get('PRODUCT_TYPE',''),
        'default_markup': settings.get('default_markup', 4),
        'default_hs_code':  settings.get('default_hs_code', DEFAULT_HS_CODE),
        'default_weight_g': settings.get('default_weight_g', DEFAULT_WEIGHT_G),
        'default_country_of_origin': settings.get('default_country_of_origin', DEFAULT_COUNTRY_OF_ORIGIN),
        'default_inventory_qty':  settings.get('default_inventory_qty', DEFAULT_INVENTORY_QTY),
        'default_bangle_sizes':   settings.get('default_bangle_sizes', DEFAULT_BANGLE_SIZES),
    }
    return jsonify(out)

@app.route('/save_settings', methods=['POST'])
def save_settings_route():
    data = request.get_json()
    current = load_settings(); current.update(data)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2))
    return jsonify({'ok':True})

@app.route('/test_shopify', methods=['POST'])
def test_shopify():
    settings = load_settings()
    store = (settings.get('shopify_store') or '').replace('https://','').replace('http://','').rstrip('/')
    token = settings.get('shopify_token') or ''
    if not store or not token:
        return jsonify({'ok':False,'error':'Store URL and token both required'}), 400
    try:
        r = requests.get(f'https://{store}/admin/api/2024-01/shop.json',
                          headers={'X-Shopify-Access-Token':token}, timeout=15)
        if r.ok:
            shop = r.json().get('shop',{})
            return jsonify({'ok':True,'shop_name':shop.get('name'),'domain':shop.get('myshopify_domain')})
        return jsonify({'ok':False,'error':f'HTTP {r.status_code}: {r.text[:200]}'}), 400
    except Exception as e:
        return jsonify({'ok':False,'error':str(e)}), 400

@app.route('/test_groq', methods=['POST'])
def test_groq():
    settings = load_settings()
    key = settings.get('groq_api_key') or ''
    if not key: return jsonify({'ok':False,'error':'Groq key required'}), 400
    try:
        r = requests.post('https://api.groq.com/openai/v1/chat/completions',
                           headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},
                           json={'model':'meta-llama/llama-4-scout-17b-16e-instruct',
                                 'messages':[{'role':'user','content':'Say OK'}],'max_tokens':5},
                           timeout=20)
        if r.ok: return jsonify({'ok':True})
        return jsonify({'ok':False,'error':f'HTTP {r.status_code}: {r.text[:200]}'}), 400
    except Exception as e:
        return jsonify({'ok':False,'error':str(e)}), 400

@app.route('/history/<int:idx>', methods=['DELETE'])
def delete_history_row(idx):
    rows = load_history()
    if 0 <= idx < len(rows):
        rows.pop(idx)
        HISTORY_FILE.write_text(json.dumps(rows, indent=2))
        return jsonify({'ok':True})
    return jsonify({'ok':False}), 404

# ── Socket.IO pipeline ────────────────────────────────────────────────────────
@socketio.on('start_upload')
def handle_start_upload(data):
    sid = request.sid
    filenames       = data.get('filenames') or ([data['filename']] if data.get('filename') else [])
    sku             = (data.get('sku') or '').upper()
    cost_price      = float(data.get('cost_price', 0) or 0)
    markup          = float(data.get('markup', 4) or 4)
    manual_title    = (data.get('title') or '').strip() or None
    category        = (data.get('category') or '').strip() or None
    manual_tags     = (data.get('tags') or '').strip() or None
    weight_g        = data.get('weight_g')
    hs_code         = (data.get('hs_code') or '').strip() or None
    country_of_origin = (data.get('country_of_origin') or '').strip() or None
    inventory_qty   = data.get('inventory_qty')
    colors          = data.get('colors') or []
    sizes           = data.get('sizes') or []
    if isinstance(colors, str): colors = [c.strip() for c in colors.split(',') if c.strip()]
    if isinstance(sizes,  str): sizes  = [s.strip() for s in sizes.split(',')  if s.strip()]

    selling_price    = calc_sp(cost_price, markup)
    compare_at_price = int(round(selling_price * 2))
    image_paths      = [UPLOAD_DIR / fn for fn in filenames]
    timestamp        = datetime.now().isoformat()

    log(sid, f'▶ {sku} | {len(filenames)} image(s) | CP: ₹{cost_price} → SP: ₹{selling_price} (MRP ₹{compare_at_price})')

    def run():
        with upload_semaphore:
            try:
                missing = [p for p in image_paths if not p.exists()]
                if missing:
                    raise FileNotFoundError(f'Image(s) not found: {[p.name for p in missing]}')

                details = generate_product_details(image_paths, sku, sid, category=category)
                result  = create_shopify_product(
                    image_paths, sku, selling_price, details, sid,
                    manual_title=manual_title, category=category,
                    manual_tags=manual_tags, weight_g=weight_g, hs_code=hs_code,
                    country_of_origin=country_of_origin, inventory_qty=inventory_qty,
                    cost_price=cost_price, colors=colors, sizes=sizes)

                row = {'timestamp':timestamp,'sku':sku,'title':result.get('title'),
                       'handle':result.get('handle'),'cost_price':cost_price,
                       'selling_price':selling_price,'compare_at_price':result.get('compare_at_price'),
                       'hs_code':result.get('hs_code'),'country_of_origin':result.get('country_of_origin'),
                       'detected_color':result.get('detected_color'),
                       'variant_count':result.get('variant_count',1),
                       'status':'success','shopify_url':result['shopify_url'],'error':None,
                       'image_count':len(filenames)}
                append_history(row)
                log(sid, f'🎉 Done! {result["shopify_url"]}', 'success')
                socketio.emit('product_done', {
                    'sku':sku,'title':result.get('title'),
                    'selling_price':selling_price,'compare_at_price':result.get('compare_at_price'),
                    'shopify_url':result['shopify_url'],'detected_color':result.get('detected_color'),
                    'status':'success'
                }, to=sid)
            except Exception as e:
                log(sid, f'❌ Failed for {sku}: {e}', 'error')
                append_history({'timestamp':timestamp,'sku':sku,'title':manual_title,
                                'cost_price':cost_price,'selling_price':selling_price,
                                'compare_at_price':compare_at_price,
                                'status':'failed','shopify_url':None,'error':str(e),
                                'image_count':len(filenames)})
                socketio.emit('product_done',{'sku':sku,'status':'failed','error':str(e)}, to=sid)
            finally:
                for p in image_paths:
                    try: p.unlink()
                    except Exception: pass

    threading.Thread(target=run, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
