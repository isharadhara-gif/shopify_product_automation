# ============================================================================
#  ISHHAARA CATALOG UPDATE  —  drop-in replacements / additions for app.py
#  ---------------------------------------------------------------------------
#  What changed & how to apply (4 steps):
#
#   1. REPLACE the whole `CATEGORIES = [...]` list with the one below.
#   2. ADD the `BAG_CATEGORIES` set right under it (new).
#   3. REPLACE the whole `TAG_PRESETS = {...}` dict with the one below
#      (every preset now uses your real Shopify pipe-delimited group format).
#   4. ADD the new keys from CATEGORY_TITLE_HINTS_NEW into your existing
#      CATEGORY_TITLE_HINTS dict, and the new keys from
#      CATEGORY_DESCRIPTIONS_NEW into your existing CATEGORY_DESCRIPTIONS dict.
#
#   5. PATCH generate_product_details() so bag categories aren't forced into
#      jewellery-only vocabulary — see the bottom of this file.
# ============================================================================


# ── 1. REPLACE CATEGORIES ────────────────────────────────────────────────────
CATEGORIES = [
    'Necklace', 'Choker', 'Pendant',
    'Earring', 'Ear Cuff',
    'Maang Tikka', 'Mathapatti', 'Nath',
    'Bangles', 'Kada / Handcuff', 'Bracelet', 'Hathphool / Hand Harness',
    'Anklet / Payal', 'Kamarband / Waist Chain', 'Bajuband / Armlet',
    'Brooch', 'Ring', 'Hair Accessories',
    # ── Bags (new product line) ──
    'Potli Bag', 'Clutch', 'Handbag / Sling',
]


# ── 2. ADD  (new) ────────────────────────────────────────────────────────────
# Categories that are NOT jewellery. generate_product_details() uses this to
# switch its copywriting rules away from "jewellery-only" for these items.
BAG_CATEGORIES = {'Potli Bag', 'Clutch', 'Handbag / Sling'}


# ── 3. REPLACE TAG_PRESETS ───────────────────────────────────────────────────
# Format mirrors the live Ishhaara store: universal flags (PPCOD, Ready_made,
# Ethinic/Western, Best Sellers) + a small number of pipe-delimited synonym
# groups. Each comma-separated entry becomes one Shopify tag.
TAG_PRESETS = {
    'Necklace':
        'PPCOD, Ready_made, Ethinic, Best Sellers, '
        'Long Necklace | Statement Necklace | Stone Necklace | Temple Necklace | Kundan Necklace Set | Polki Necklace | Layered Necklace, '
        'Party Wear Necklace, '
        'Partywear Necklace | Latest Partywear Necklace | Partywear Necklace For Women, '
        'Best Earrings | Best Rings | Best Jewellery | Best Necklace Set | Best Hairband',

    'Choker':
        'PPCOD, Ready_made, Ethinic, Best Sellers, Choker Necklaces, '
        'Choker Necklace | Pearl Choker Necklace | Traditional Choker Necklace Set | Stone Choker Necklace | Choker Necklace Set | Diamond Choker | Choker Set | Square Choker | Indian Chokers | Choker Jewellery',

    'Pendant':
        'PPCOD, Ready_made, Western, '
        'Pendant Necklace | Pendant Set | AD Pendant | Evil Eye Pendant | Dainty Pendant | Initial Pendant, '
        'New Arrivals',

    'Earring':
        'PPCOD, Ready_made, Ethinic, Western, Hoop Earrings, '
        'Gold Hoops | Hoops For Women | Silver Hoops | Hoop Earrings For Girls | Triple Hoop | Hoop Earrings | Hoop Earing | Western Hoops, '
        'Jhumka Earrings | Danglers | Studs | Chandbali | Bugadi Earrings | Statement Earrings | Pearl Earrings',

    'Ear Cuff':
        'PPCOD, Ready_made, Western, '
        'Ear Cuff | Earcuff | Ear Cuffs | Designer Earcuffs | Crawler Earrings | Ear Wrap | No Piercing Earrings, '
        'New Arrivals',

    'Maang Tikka':
        'PPCOD, Ready_made, Ethinic, Maangtikas, '
        'Maangtikas For Bride | Maangtika Women | Stylish Maangtika | Trending Mantikas | Maang Tikka | Mangtika | Maang Tika | Mangtikka | Maangtikka | Maang Teeka | Tikka, '
        'Teeka | Maangteeka | Mang Tikka | Mangtikka Set | Chandbali Teeka | Kundan Teeka | Mang Teeka | Maangtikkas | Kundan Tekka | Mang Tika | Maang Tikkas',

    'Mathapatti':
        'PPCOD, Ready_made, Ethinic, Bridal, '
        'Mathapatti | Matha Patti | Head Jewellery | Passa | Bridal Mathapatti | Rajasthani Mathapatti | Sheeshphool, '
        'New Arrivals',

    'Nath':
        'PPCOD, Ready_made, Ethinic, Bridal, '
        'Nath | Nose Ring | Nathni | Bridal Nath | Maharashtrian Nath | Nose Pin | Clip On Nath | Nathiya, '
        'New Arrivals',

    'Bangles':
        'PPCOD, Ready_made, Ethinic, '
        'Bangle | Bangles | Kada | Kangan | Bangle Set | Oxidised Bangles | Kundan Bangles | Meenakari Bangles, '
        'New Arrivals',

    'Kada / Handcuff':
        'PPCOD, Ready_made, Ethinic, '
        'Handcuff Bracelets | Kada | Hand Cuff | AD Kada | Oxidised Kada | Open Cuff Bracelet | Statement Kada, '
        'New Arrivals',

    'Bracelet':
        'PPCOD, Ready_made, Western, Bracelet, Healing Bracelets, '
        'Crystal Bracelets | Stone Bracelets | Mens Crystal Bracelet | Evil Eye | Nazar | Evil Eye Bracelet, '
        'Mens Bracelets | Bracelets For Women | Bracelets For Girls | Healing Bracelets | Beaded Bracelet | Gold Bracelet | Silver Bracelet',

    'Hathphool / Hand Harness':
        'PPCOD, Ready_made, Ethinic, Bridal, '
        'Hathphool | Hath Phool | Haathphool | Hand Harness | Hand Jewellery | Ring Bracelet | Slave Bracelet | Panja',

    'Anklet / Payal':
        'PPCOD, Ready_made, Ethinic, '
        'Anklet | Anklets | Payal | Pajeb | Anklet For Women | Silver Anklet | Oxidised Anklet | Ghungroo Anklet | Foot Jewellery | Payal Set, '
        'New Arrivals',

    'Kamarband / Waist Chain':
        'PPCOD, Ready_made, Ethinic, Bridal, '
        'Kamarband | Waist Chain | Waist Belt | Vaddanam | Kamarbandh | Belly Chain | Saree Waist Chain | Bridal Kamarband | Oddiyanam, '
        'New Arrivals',

    'Bajuband / Armlet':
        'PPCOD, Ready_made, Ethinic, Bridal, '
        'Bajuband | Baju Band | Armlet | Arm Cuff | Vanki | Bajubandh | Arm Band | Bridal Bajuband | Upper Arm Bracelet, '
        'New Arrivals',

    'Brooch':
        'PPCOD, Ready_made, '
        'Brooch | Brooch For Men | Blazer Brooch | Saree Brooch | Saree Pin | Dupatta Pin | Lapel Pin, '
        'New Arrivals',

    'Ring':
        'PPCOD, Ready_made, Ethinic, Western, Rings, '
        'Rings For Women | Rings For Girls | Stylish Women Rings | Ring In Trend For Women | Finger Rings | Simple Rings | Cocktail Ring | Finger Ring, '
        'Oxidised Ring | Adjustable Ring | Statement Ring | Kundan Ring | Polki Ring',

    'Hair Accessories':
        'PPCOD, Ready_made, Ethinic, '
        'Hair Pin | Hair Clip | Juda Pin | Hair Vine | Hair Brooch | Bun Pin | Ambada Pin | Gajra, '
        'Best Earrings | Best Rings | Best Jewellery | Best Necklace Set | Best Hairband, '
        'New Arrivals',

    # ── Bags (new) ──
    'Potli Bag':
        'PPCOD, Ready_made, Ethinic, '
        'Potli | Potli Bag | Potli Purse | Bridal Potli | Embroidered Potli | Wedding Potli | Ethnic Bags | Potli For Women, '
        'New Arrivals',

    'Clutch':
        'PPCOD, Ready_made, '
        'Clutch | Clutches | Clutch Bag | Bridal Clutch | Party Clutch | Embroidered Clutch | Box Clutch | Ethnic Clutch | Clutch Purse, '
        'New Arrivals',

    'Handbag / Sling':
        'PPCOD, Ready_made, Western, '
        'Handbag | Sling Bag | Crossbody Bag | Shoulder Bag | Mini Bag | Ladies Purse | Ethnic Sling | Hand Bag | Bags For Women, '
        'New Arrivals',
}


# ── 4a. ADD these keys into your existing CATEGORY_TITLE_HINTS dict ──────────
CATEGORY_TITLE_HINTS_NEW = {
    'Anklet / Payal':
        'This is an ANKLET / PAYAL (worn around the ankle, often with ghungroo bells). '
        'Title must include "Anklet" or "Payal" — e.g. "Oxidised Ghungroo Payal", "Silver Anklet Set".',
    'Kamarband / Waist Chain':
        'This is a KAMARBAND / WAIST CHAIN (waist jewellery worn over a saree or lehenga). '
        'Title must include "Kamarband" or "Waist Chain" — e.g. "Kundan Bridal Kamarband", "Temple Waist Chain".',
    'Bajuband / Armlet':
        'This is a BAJUBAND / ARMLET (worn on the upper arm). '
        'Title must include "Bajuband" or "Armlet" — e.g. "Kundan Bajuband", "Temple Vanki Armlet".',
    'Potli Bag':
        'This is a POTLI BAG — a drawstring ethnic pouch/purse. This is a BAG, NOT jewellery. '
        'Title must include "Potli" — e.g. "Embroidered Bridal Potli Bag", "Kundan Potli Purse".',
    'Clutch':
        'This is a CLUTCH — a small handheld party/bridal bag. This is a BAG, NOT jewellery. '
        'Title must include "Clutch" — e.g. "Embroidered Bridal Clutch Bag", "Sequin Party Clutch".',
    'Handbag / Sling':
        'This is a HANDBAG / SLING BAG — a shoulder or crossbody bag. This is a BAG, NOT jewellery. '
        'Title must include "Handbag" or "Sling Bag" — e.g. "Embroidered Sling Bag", "Mini Crossbody Handbag".',
}


# ── 4b. ADD these keys into your existing CATEGORY_DESCRIPTIONS dict ─────────
CATEGORY_DESCRIPTIONS_NEW = {
    'Anklet / Payal': """Hey gorgeous! Isn't there something magical about the soft chime of a payal with every step you take? An anklet isn't just jewellery for your feet, it's a little melody that follows you everywhere.
Ishhaara's anklets whether it be an oxidised ghungroo payal, a delicate silver anklet, or a dainty chain-style anklet offer a graceful finish for everyday wear or festive dressing. So, grab this chance and quickly check out the standout features of Ishhaara's anklet.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Signature Chime: Ishhaara's ghungroo anklets carry tiny bells that add a gentle, traditional jingle to your every movement.
2. Everyday to Festive: From minimal chain anklets for daily wear to broad oxidised payals for celebrations, there's a style for every occasion.
3. Adjustable Fit: Every anklet features an adjustable chain or hook, ensuring a secure and comfortable fit across ankle sizes.
4. Stack or Solo: Wear a single delicate anklet for understated charm, or layer multiple payals for a bold, festive foot look.
Styling Inspiration
1. Pair oxidised ghungroo payals with a lehenga or anarkali for an authentic festive vibe.
2. Wear a single dainty anklet with jeans or a dress for an everyday western touch.
3. Layer two contrasting anklets on one foot for a trend-forward, stacked look.
Care Label
1. Store the anklet in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your anklet.
4. Clean your anklet after every use with a soft brush.""",

    'Kamarband / Waist Chain': """Hey stunning bride (or festive queen)! Isn't a kamarband the most regal way to define your waist and complete a traditional look? Draped elegantly over a saree or lehenga, it turns your silhouette into a statement.
Ishhaara's kamarbands and waist chains whether it be a Kundan bridal kamarband, a temple-style vaddanam, or a delicate saree waist chain offer a grand finish for weddings and festive occasions. So, grab this chance and quickly check out the standout features of Ishhaara's kamarband.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Bridal Statement: Ishhaara's kamarbands are crafted to be the crowning waist detail of a bridal or festive ensemble.
2. Adjustable Drape: Every waist chain comes with an adjustable hook and chain so it sits securely across different waist sizes.
3. Heritage Craftsmanship: From Kundan and temple detailing to oxidised finishes, each piece reflects authentic Indian bridal traditions.
4. Saree & Lehenga Ready: Designed to drape beautifully over both saree pleats and lehenga waistbands.
Styling Inspiration
1. Drape a Kundan kamarband over a bridal lehenga for a full traditional look.
2. Style a delicate waist chain over a silk saree to accentuate the waist.
3. Pair a temple vaddanam with matching temple jewellery for a South Indian bridal ensemble.
Care Label
1. Store the kamarband in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your kamarband.
4. Clean your kamarband after every use with a soft brush.""",

    'Bajuband / Armlet': """Hey beautiful! Isn't a bajuband one of the most striking ways to add a royal touch to your upper arm? Hugging the arm with intricate detailing, it's a piece that instantly elevates a bridal or festive look.
Ishhaara's bajubands and armlets whether it be a Kundan bajuband, a temple-style vanki, or an oxidised arm cuff offer a bold, regal finish for weddings and celebrations. So, grab this chance and quickly check out the standout features of Ishhaara's bajuband.
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Regal Upper-Arm Statement: Ishhaara's bajubands are designed to sit elegantly on the upper arm as a bridal focal point.
2. Adjustable Comfort: Every armlet features an adjustable band or tie so it fits snugly and comfortably on different arm sizes.
3. Heritage Detailing: From Kundan and temple vanki designs to oxidised finishes, each piece honours traditional Indian craftsmanship.
4. Pairs Beautifully: A bajuband completes a bridal set alongside matching bangles, choker, and maang tikka.
Styling Inspiration
1. Wear a Kundan bajuband with a sleeveless bridal blouse to showcase the detailing.
2. Pair a temple vanki with a South Indian saree for an authentic regal look.
3. Style an oxidised armlet with a fusion outfit for a bold, contemporary edge.
Care Label
1. Store the bajuband in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your bajuband.
4. Clean your bajuband after every use with a soft brush.""",

    'Potli Bag': """Hey gorgeous! Isn't a potli the most charming way to carry your essentials to a wedding or festive celebration? Drawstring, dainty, and richly detailed, a potli bag is the finishing touch that ties your entire ethnic look together.
Ishhaara's potli bags whether it be an embroidered bridal potli, a Kundan-embellished potli purse, or a classic silk potli offer a graceful finish for weddings, festivals, and celebrations. So, grab this chance and quickly check out the standout features of Ishhaara's potli bag.
Product Specification
Material: Premium Fabric | Ethically Handcrafted
Closure: Secure Drawstring
Lining: Soft Inner Lining
Key Highlights
1. Handcrafted Detailing: Ishhaara's potli bags feature intricate embroidery, beadwork, or Kundan embellishment for a rich ethnic finish.
2. Drawstring Security: A snug drawstring closure keeps your essentials safe while doubling as an elegant wrist handle.
3. Just-Right Capacity: Roomy enough for a phone, cash, and touch-up essentials, without breaking the silhouette of your outfit.
4. Bridal & Festive Ready: Designed to complement lehengas, sarees, and anarkalis at weddings and celebrations.
Styling Inspiration
1. Carry an embroidered potli with a bridal lehenga to complete the traditional look.
2. Pair a Kundan potli with a silk saree for an elegant festive finish.
3. Match your potli's colour to your dupatta or blouse for a coordinated ensemble.
Care Label
1. Store the potli bag in a dust pouch when not in use.
2. Keep it away from water, perfumes, and body sprays.
3. Avoid overstuffing to preserve the shape and embroidery.
4. Spot-clean gently with a dry, soft cloth.""",

    'Clutch': """Hey stylish soul! Isn't a clutch the smallest bag with the biggest impact? Held in hand, it instantly signals polish, intention, and party-ready glamour.
Ishhaara's clutches whether it be an embroidered bridal clutch, a sequinned party clutch, or a structured box clutch offer a refined finish for weddings, receptions, and evenings out. So, grab this chance and quickly check out the standout features of Ishhaara's clutch.
Product Specification
Material: Premium Fabric | Ethically Handcrafted
Closure: Secure Clasp / Flap
Lining: Soft Inner Lining
Key Highlights
1. Statement Craftsmanship: Ishhaara's clutches feature embroidery, sequins, beadwork, or embellished detailing for an eye-catching finish.
2. Secure Closure: A dependable clasp or flap keeps your essentials safe through every function.
3. Detachable Chain Option: Many designs include a chain strap, letting you carry it handheld or over the shoulder.
4. Party & Bridal Ready: Sized to hold your phone and evening essentials while completing a festive or bridal outfit.
Styling Inspiration
1. Carry an embroidered clutch with a bridal saree or lehenga for a coordinated look.
2. Pair a sequinned clutch with a cocktail dress for a glamorous evening finish.
3. Use the chain strap to go hands-free while you dance the night away.
Care Label
1. Store the clutch in a dust pouch when not in use.
2. Keep it away from water, perfumes, and body sprays.
3. Avoid overstuffing to protect the shape and embellishments.
4. Spot-clean gently with a dry, soft cloth.""",

    'Handbag / Sling': """Hey lovely! Isn't the right bag the easiest way to pull an outfit together, whether you're running errands or heading out for the evening? A handbag or sling is the everyday hero that carries your world in style.
Ishhaara's handbags and sling bags whether it be an embroidered ethnic sling, a mini crossbody, or a structured shoulder bag offer a versatile finish for both western and ethnic looks. So, grab this chance and quickly check out the standout features of Ishhaara's handbag.
Product Specification
Material: Premium Fabric / PU | Ethically Handcrafted
Closure: Secure Zip / Flap
Strap: Adjustable Sling Strap
Key Highlights
1. Everyday Versatility: Ishhaara's handbags and slings transition effortlessly from daily errands to evening outings.
2. Hands-Free Comfort: An adjustable, detachable strap lets you wear it crossbody, over the shoulder, or handheld.
3. Smart Storage: Thoughtful compartments keep your phone, cards, and essentials organised.
4. Western-Ethnic Fusion: From embroidered ethnic slings to minimal crossbody bags, each design suits a range of outfits.
Styling Inspiration
1. Wear an embroidered sling with a kurta set for a chic ethnic-fusion look.
2. Style a mini crossbody with jeans and a top for an easy everyday outfit.
3. Match your bag's accent colour to your outfit for a coordinated finish.
Care Label
1. Store the handbag in a dust pouch when not in use.
2. Keep it away from water, perfumes, and body sprays.
3. Avoid overstuffing to preserve the shape.
4. Spot-clean gently with a dry, soft cloth.""",
}


# ============================================================================
#  5. PATCH  generate_product_details()  — make it bag-aware
#  ---------------------------------------------------------------------------
#  Inside generate_product_details(), REPLACE the block that builds `prompt`
#  (from `vendor = settings.get(...)` down to the end of the prompt f-string)
#  with the version below. It keeps jewellery behaviour identical, and only
#  switches vocabulary/rules when the seller-picked category is a bag.
# ============================================================================
PATCH_generate_product_details = r'''
        vendor = settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR', 'the brand')

        is_bag = category in BAG_CATEGORIES

        category_block = ''
        if category:
            hint = CATEGORY_TITLE_HINTS.get(category, '')
            category_block = f"""
THE SELLER HAS ALREADY IDENTIFIED THE CATEGORY AS: "{category}".
{hint}
Do NOT override this with a different product type guessed from the photo — ground the title in "{category}" above everything else. If the image looks ambiguous, still trust the seller-provided category."""

        if is_bag:
            domain_intro = f"""You are an expert accessories copywriter for {vendor}, an Indian fashion brand.
The SKU is {sku}. Study the product image carefully — it is a BAG / ethnic accessory (a potli, clutch, or handbag), NOT jewellery."""
            rules_block = """IMPORTANT RULES:
- Title must name the bag type specifically (e.g. "Embroidered Bridal Potli Bag", "Sequin Party Clutch", "Ethnic Sling Bag"). Do NOT call it jewellery.
- Use relevant Indian ethnic-wear vocabulary where it fits: Potli, Clutch, Sling, Kundan, Embroidered, Sequin, Zari, Beaded, Bridal, Festive, Party.
- Tags must be bag/accessory-only: bag type, style, occasion (wedding, festive, bridal, party, casual), material/finish (embroidered, sequin, velvet, silk, PU), and closure if visible.
- Description must focus on the bag: material and craftsmanship, embellishment, closure/strap, capacity, and occasion suitability. Do NOT describe it as jewellery."""
        else:
            domain_intro = f"""You are an expert jewellery copywriter for {vendor}, an Indian fashion jewellery brand.
The SKU is {sku}. Study the product image carefully — it is a piece of jewellery."""
            rules_block = """IMPORTANT RULES:
- Title must name the jewellery type specifically (e.g. "Kundan Choker Necklace Set", "Oxidised Jhumka Earrings", "Meenakari Bangle", "Temple Jewellery Maang Tikka"). Never use clothing terms.
- Use Indian jewellery vocabulary where relevant: Kundan, Polki, Meenakari, Jadau, Oxidised, Temple, Antique, Filigree, Jhumka, Chandbali, Maang Tikka, Matha Patti, Nath, Hathphool, Kamarband, Bajuband, Choker, Layered, Statement, etc.
- Tags must be jewellery-only: piece type, style, occasion (wedding, festive, bridal, casual, ethnic), finish (gold-plated, silver-plated, antique, oxidised), and stone if visible.
- Description must focus on jewellery: metal finish, stone/bead type, craftsmanship technique, and occasion suitability. No clothing references."""

        prompt = f"""{domain_intro}
{category_block}

{rules_block}

Respond ONLY with a valid JSON object (no markdown, no extra text):
{{
  "title": "Specific product name using the right {'bag' if is_bag else 'Indian jewellery'} terms, 4-8 words",
  "description": "2-3 sentence HTML description. Use <strong> tags on key feature labels only.",
  "handle": "url-slug-from-title-lowercase-hyphens",
  "seo_title": "Buy [Title] Online - {vendor} (max 60 chars)",
  "seo_description": "Buy [Title] from {vendor}. Shop handcrafted Indian {'accessories' if is_bag else 'jewellery'} online. (max 160 chars)",
  "alt_text": "{vendor} [Title] — handcrafted Indian {'accessory' if is_bag else 'jewellery'}",
  "tags": "comma-separated tags: type, style, occasion, finish/material"
}}"""
'''
