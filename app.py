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
# Matches the consistent pattern seen across the existing Shopify catalog export:
# Inventory Tracker=shopify, Inventory Policy=deny, Fulfillment Service=manual,
# Requires Shipping=true, Taxable=true, Inventory Qty=10, Status=active.
DEFAULT_INVENTORY_QTY = 10

# Target product photo canvas — portrait 3:4, Shopify-friendly
TARGET_W, TARGET_H = 1080, 1440

def process_image(path: Path) -> Path:
    """Crop-to-fit (never stretch/squeeze) to TARGET_W x TARGET_H, then save as a
    high-quality compressed JPEG. Returns the path of the processed file
    (always .jpg — original is replaced)."""
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

# ── Category description templates ────────────────────────────────────────────
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

    'Earrings': """Hey gorgeous! Don\u2019t you think your face glows differently the moment the right pair of earrings catches the light? Earrings aren\u2019t just an accessory, they\u2019re the easiest way to switch up an entire look in seconds.
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

    'Hand accessories': """Hey gorgeous! Are you ready to add a whimsical statement to your \u2018Solah Shringar\u2019? Powerful and graceful a charm it can add, isn't it? From statement handcuffs, delicate bracelets, and traditional bangles to stunning Chooda and Kaleera, Ishhaara\u2019s studio has everything you need to add that \u2018wow\u2019 factor.
So, if you\u2019re someone who loves making a grand entrance wherever you go, you need to explore these premium pieces. Let\u2019s dive in and discover what makes these hand accessories a must-have!
Product Specification
Material: Skin Friendly | Hypoallergenic
Craftsmanship: Ethically Handmade
Waterproof: Retains Colour and Brilliance
Key Highlights
1. Subtle Yet Impactful Piece: For those who love subtle elegance, Ishhaara's hand accessories from oxidised handcuffs to sleek bangles can instantly add the right amount of sparkle. Letting you bring a refined and eye-catching appeal.
2. Boosts Confidence: Ishhaara\u2019s premium handcrafted hand accessories whether it be a bridal Chooda or gold bangles will not only complete your whole look. But, also boosts confidence and lets you bring a poised appeal wherever you go.
3. Cultural Connection: Ishhaara\u2019s hand accessories from bridal Chooda to bridal Kaleera will not only complete your traditional look but also carry cultural significance, letting you feel connected to your roots.
4. Personalised Touch: Ishhaara\u2019s customisable option on hand accessories like oxidised handcuffs, layered silver bracelets, etc. will beautifully reflect your unique style and add unexpected flair to your accessory collection.
5. Bollywood Glamour: Ishhaara\u2019s every piece of hand accessories from bangles, and bracelets to gold handcuffs reflects Bollywood\u2019s iconic style. Perfect for adding a touch of luxury and sophistication to even the simplest outfits.
6. Perfect for Every Occasion: Ishhaara\u2019s every piece of artificial bangles, artificial handcuffs, artificial bracelets, etc are suitable for wide festivities from weddings to casual get-togethers. Making it a favourite choice in your jewellery box.
Styling Inspiration
1. Opt for mixing different textures and widths of different bangles and bracelets. This will create a perfect layered look.
2. Look for complementing your handcuffs with your outfit style. For instance, if you are wearing a solid-coloured dress, opt for silver or gold bangles.
3. Consider wearing a striking accessory on your favourite hand. For instance, if you work mostly with your right hand, pair a stunning oxidised bracelet with your dominant hand for a bolder look.
Care Label
1. Store the hand accessories in an air-tight jewellery box or sealed pouch.
2. Keep it away from body sprays, body lotions, or perfumes.
3. Avoid using detergents, soaps, or toothpaste to clean your hand accessories.
4. Clean your hand accessories after every use with a soft brush.""",

    'Rings': """Howdy, partners! Are you passionate about elevating your style with stunning rings? Isn\u2019t it incredible how these glamorous accessories can add elegance, flair, and trendiness to any outfit? Whether you love adding gold rings, traditional rings, statement rings, or oxidised rings, Ishhaara's treasure trove uncovers a wide variety of choices.
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

    'Hair accessories': """Hey beautiful! Isn\u2019t it amazing how the right hair accessory can transform your entire look in seconds? A hairpin, clip, or hair band isn\u2019t just functional. It is a styling statement that ties your whole appearance together effortlessly.
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

# Section headers that should render as bold standalone lines
_SECTION_HEADERS = {'Product Specification', 'Key Highlights', 'Styling Inspiration', 'Care Label'}
# Lines like "Material: Skin Friendly" — bold the label before the colon
_LABEL_LINE_RE = re.compile(r'^([A-Za-z][A-Za-z \u2019\']{1,30}):\s*(.*)$')
# Numbered list lines like "1. Premium Materials: blah blah" — bold "1. Premium Materials:"
_NUMBERED_RE = re.compile(r'^(\d+\.\s*[^:]+:)\s*(.*)$')

def template_description_html(category):
    """Convert a plain-text category template into HTML for body_html, with
    section headers and the lead-in of each bullet/spec line bolded."""
    text = CATEGORY_DESCRIPTIONS.get(category)
    if not text:
        return None
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    html_parts = []
    for p in paragraphs:
        if p in _SECTION_HEADERS:
            html_parts.append(f'<p><strong>{p}</strong></p>')
            continue
        m = _NUMBERED_RE.match(p)
        if m:
            html_parts.append(f'<p><strong>{m.group(1)}</strong> {m.group(2)}</p>')
            continue
        m = _LABEL_LINE_RE.match(p)
        if m:
            html_parts.append(f'<p><strong>{m.group(1)}:</strong> {m.group(2)}</p>')
            continue
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
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            return {}
    return {}

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return []
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

# ── Groq: generate ALL product fields ────────────────────────────────────────
def generate_product_details(image_paths, sku, sid):
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
        mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}.get(ext, 'image/jpeg')

        vendor = settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR', 'the brand')

        prompt = f"""You are a Shopify product copywriter for a brand called {vendor}.
The SKU is {sku}. Look at the product image carefully.

Respond ONLY with a valid JSON object (no markdown, no extra text):
{{
  "title": "Short product name 4-7 words",
  "description": "2-3 sentence HTML product description highlighting material, craftsmanship, occasion suitability. Wrap any key feature label in <strong></strong> tags.",
  "handle": "url-slug-from-title-lowercase-hyphens",
  "seo_title": "Buy [Title] Online - {vendor} (max 60 chars)",
  "seo_description": "Shop [Title] from {vendor}. Brief benefit. Best offers at our online store. (max 160 chars)",
  "alt_text": "{vendor} [Title] - descriptive alt text for image",
  "tags": "comma separated relevant tags"
}}"""

        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
                'messages': [{'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{b64}'}},
                    {'type': 'text', 'text': prompt}
                ]}],
                'max_tokens': 500,
            }, timeout=30
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        content = content.replace('```json', '').replace('```', '').strip()
        result = json.loads(content)
        result['handle'] = slugify(result.get('handle', result.get('title', sku)))
        log(sid, f'✅ Title: {result.get("title")}', 'success')
        return result
    except Exception as e:
        log(sid, f'⚠️ Groq error: {e} — using SKU fallback', 'error')
        slug = slugify(sku)
        return {'title': sku, 'description': '', 'handle': slug,
                'seo_title': sku, 'seo_description': '', 'alt_text': sku, 'tags': ''}

# ── Shopify: publish a product to every active sales channel ─────────────────
def publish_to_all_channels(base_url, headers, product_id, sid):
    """Uses the GraphQL Admin API to publish the product onto every channel
    the store has available (Online Store, POS, Shop, Google, Facebook, etc).
    REST product creation only auto-publishes to the Online Store channel, so
    this is required if the product should be sellable everywhere."""
    graphql_url = base_url.replace('/admin/api/', '/admin/api/') .rsplit('/admin/api/', 1)
    store_host = graphql_url[0].replace('https://', '')
    api_version = graphql_url[1]
    gql_url = f'https://{store_host}/admin/api/{api_version}/graphql.json'
    gql_headers = {k: v for k, v in headers.items()}

    try:
        pub_query = '{ publications(first: 25) { edges { node { id name } } } }'
        r = requests.post(gql_url, headers=gql_headers, json={'query': pub_query}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if 'errors' in data:
            log(sid, f'⚠️ Could not list sales channels: {data["errors"]}', 'error')
            return
        pubs = data.get('data', {}).get('publications', {}).get('edges', [])
        if not pubs:
            log(sid, 'ℹ️ No sales channels found to publish to', 'muted')
            return

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
        errs = result.get('data', {}).get('publishablePublish', {}).get('userErrors', [])
        if errs:
            log(sid, f'⚠️ Sales channel publish reported errors: {errs}', 'error')
        else:
            names = ', '.join(p['node']['name'] for p in pubs)
            log(sid, f'✅ Published to all sales channels ({names})', 'success')
    except Exception as e:
        log(sid, f'⚠️ Could not publish to all sales channels: {e}', 'error')

# ── Shopify: create product with MULTIPLE images ─────────────────────────────
def create_shopify_product(image_paths, sku, selling_price, details, sid, manual_title=None,
                            category=None, manual_tags=None, weight_g=None, hs_code=None,
                            country_of_origin=None, inventory_qty=None, cost_price=None):
    settings = load_settings()
    store = (settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE', '')).replace('https://', '').replace('http://', '').rstrip('/')
    token = settings.get('shopify_token') or os.environ.get('SHOPIFY_TOKEN', '')
    vendor = settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR', '')
    p_type = settings.get('product_type') or os.environ.get('PRODUCT_TYPE', '')

    if not store or not token:
        raise ValueError('Shopify store or token not configured')

    base_url = f'https://{store}/admin/api/2024-01'
    headers = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}

    title = manual_title or details.get('title', sku)

    template_desc = template_description_html(category)
    description = template_desc if template_desc else details.get('description', '')

    handle = details.get('handle', slugify(title))
    seo_title = details.get('seo_title', f'Buy {title} Online - {vendor}')
    seo_desc = details.get('seo_description', '')
    tags = (manual_tags or '').strip() or details.get('tags', '')

    weight_g = weight_g if weight_g not in (None, '', 0) else settings.get('default_weight_g', DEFAULT_WEIGHT_G)
    try:
        weight_g = float(weight_g)
    except (TypeError, ValueError):
        weight_g = DEFAULT_WEIGHT_G

    hs_code_raw = (hs_code or '').strip() or settings.get('default_hs_code', DEFAULT_HS_CODE)
    # Shopify's harmonized_system_code field rejects punctuation (e.g. "7117.90") —
    # it must be digits only. Strip everything else before sending.
    hs_code_clean = re.sub(r'[^0-9]', '', hs_code_raw) or re.sub(r'[^0-9]', '', DEFAULT_HS_CODE)

    country_of_origin = (country_of_origin or '').strip().upper() or \
        (settings.get('default_country_of_origin') or DEFAULT_COUNTRY_OF_ORIGIN).upper()

    inventory_qty = inventory_qty if inventory_qty not in (None, '') else settings.get('default_inventory_qty', DEFAULT_INVENTORY_QTY)
    try:
        inventory_qty = int(inventory_qty)
    except (TypeError, ValueError):
        inventory_qty = DEFAULT_INVENTORY_QTY
    compare_at_price = int(round(selling_price * 2))

    title_slug = slugify(title)
    base_image_name = f'ishhaara-{title_slug}-{random_digits(10)}'
    alt_text = details.get('alt_text') or f'Ishhaara {title}'

    log(sid, f'📦 Creating Shopify product: {title}…')

    payload = {'product': {
        'title': title,
        'body_html': description,
        'vendor': vendor,
        'product_type': p_type,
        'handle': handle,
        'tags': tags,
        'metafields_global_title_tag': seo_title,
        'metafields_global_description_tag': seo_desc,
        'variants': [{
            'sku': sku,
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
            # Setting HS code / country of origin / cost inline at creation
            # time, in addition to the follow-up PUT below — some store API
            # versions only persist this when it's sent on creation.
            'inventory_item': {
                'harmonized_system_code': hs_code_clean,
                'country_code_of_origin': country_of_origin,
                **({'cost': str(cost_price)} if cost_price not in (None, '', 0) else {}),
            },
        }],
        'status': 'active',
        'published': True,
        'gift_card': False,
    }}

    resp = requests.post(f'{base_url}/products.json', headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    product = resp.json()['product']
    product_id = product['id']
    log(sid, f'✅ Product created — ID {product_id} | MRP ₹{compare_at_price} → SP ₹{selling_price} | Qty {inventory_qty}', 'success')

    # Confirm / set HS code + country of origin on the inventory item.
    # Always re-PUT explicitly and verify with a GET, since the inline
    # creation field above is not honoured by every store/API version.
    try:
        inventory_item_id = product['variants'][0]['inventory_item_id']
        cost_payload = {}
        if cost_price not in (None, '', 0):
            cost_payload['cost'] = str(cost_price)
        for attempt in range(2):
            hs_resp = requests.put(
                f'{base_url}/inventory_items/{inventory_item_id}.json',
                headers=headers,
                json={'inventory_item': {
                    'id': inventory_item_id,
                    'harmonized_system_code': hs_code_clean,
                    'country_code_of_origin': country_of_origin,
                    **cost_payload,
                }},
                timeout=30
            )
            if hs_resp.ok:
                saved = hs_resp.json().get('inventory_item', {})
                saved_hs = saved.get('harmonized_system_code')
                saved_origin = saved.get('country_code_of_origin')
                saved_cost = saved.get('cost')
                ok = saved_hs == hs_code_clean and saved_origin == country_of_origin
                if cost_payload:
                    ok = ok and saved_cost is not None
                if ok:
                    cost_note = f' · Cost ₹{saved_cost}' if cost_payload else ''
                    log(sid, f'✅ HS code {hs_code_clean} · Origin {country_of_origin}{cost_note} confirmed', 'success')
                    break
                else:
                    log(sid, f'⚠️ HS/origin/cost saved but mismatched (got hs={saved_hs}, origin={saved_origin}, cost={saved_cost}), retrying…', 'error')
            else:
                log(sid, f'⚠️ HS code/origin/cost update failed (HTTP {hs_resp.status_code}): {hs_resp.text[:300]}', 'error')
            time.sleep(1)
    except Exception as e:
        log(sid, f'⚠️ Could not set HS code/origin/cost: {e}', 'error')

    # Publish to every sales channel the store has enabled (Online Store,
    # POS, Shop app, Google & YouTube, Facebook & Instagram, etc.)
    publish_to_all_channels(base_url, headers, product_id, sid)

    # Upload ALL images, in order, first one becomes the featured image
    total = len(image_paths)
    for i, img_path in enumerate(image_paths, start=1):
        log(sid, f'🖼️ Uploading image {i}/{total}…')
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        ext = img_path.suffix.lower() or '.jpg'
        img_filename = f'{base_image_name}{("-" + str(i)) if total > 1 else ""}{ext}'
        img_alt = alt_text if i == 1 else f'{alt_text} - view {i}'
        img_resp = requests.post(
            f'{base_url}/products/{product_id}/images.json',
            headers=headers,
            json={'image': {'attachment': img_b64, 'filename': img_filename, 'alt': img_alt}},
            timeout=60
        )
        if img_resp.ok:
            log(sid, f'✅ Image {i}/{total} uploaded ({img_filename})', 'success')
        else:
            log(sid, f'⚠️ Image {i}/{total} failed: {img_resp.text}', 'error')

    shopify_url = f'https://{store}/admin/products/{product_id}'
    return {'product_id': product_id, 'shopify_url': shopify_url, 'handle': handle,
            'title': title, 'compare_at_price': compare_at_price,
            'hs_code': hs_code_clean, 'country_of_origin': country_of_origin}

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    settings = load_settings()
    has_groq = bool(settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY'))
    has_shopify = bool(settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE'))
    shopify_store = settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE', '')

    with open('index.html', 'r') as f:
        html = f.read()
    html = (html
            .replace('{% if has_groq %}ok{% else %}warn{% endif %}', 'ok' if has_groq else 'warn')
            .replace('{% if not has_groq %}— not set{% endif %}', '' if has_groq else '— not set')
            .replace('{% if has_shopify %}ok{% else %}warn{% endif %}', 'ok' if has_shopify else 'warn')
            .replace('{% if not has_shopify %}— not set{% endif %}', '' if has_shopify else '— not set')
            .replace('{{ shopify_store }}', shopify_store)
            )
    return html

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('images')
    if not files:
        if 'image' in request.files:
            files = [request.files['image']]
        else:
            return jsonify({'error': 'No image file(s)'}), 400

    sku = request.form.get('sku', '').strip().upper()
    if not sku:
        return jsonify({'error': 'SKU required'}), 400

    saved = []
    ts = int(time.time() * 1000)
    for idx, file in enumerate(files):
        ext = Path(file.filename).suffix.lower() or '.jpg'
        filename = f'{sku}_{ts}_{idx}{ext}'
        save_path = UPLOAD_DIR / filename
        file.save(save_path)
        processed_path = process_image(save_path)
        saved.append(processed_path.name)

    return jsonify({'filenames': saved, 'sku': sku})

@app.route('/history')
def history():
    return jsonify(load_history())

@app.route('/history/csv')
def history_csv():
    rows = load_history()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Timestamp', 'SKU', 'Title', 'Cost Price', 'Selling Price', 'Compare At (MRP)',
                      'HS Code', 'Country of Origin', 'Status', 'Shopify URL', 'Error'])
    for r in rows:
        writer.writerow([r.get('timestamp'), r.get('sku'), r.get('title'), r.get('cost_price'),
                          r.get('selling_price'), r.get('compare_at_price'), r.get('hs_code'),
                          r.get('country_of_origin'), r.get('status'), r.get('shopify_url'), r.get('error')])
    return Response(buf.getvalue(), mimetype='text/csv',
                     headers={'Content-Disposition': 'attachment; filename=upload_history.csv'})

@app.route('/get_settings')
def get_settings_route():
    settings = load_settings()
    out = {
        'shopify_store': settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE', ''),
        'shopify_token': settings.get('shopify_token') or os.environ.get('SHOPIFY_TOKEN', ''),
        'groq_api_key': settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY', ''),
        'product_vendor': settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR', ''),
        'product_type': settings.get('product_type') or os.environ.get('PRODUCT_TYPE', ''),
        'default_markup': settings.get('default_markup', 4),
        'default_hs_code': settings.get('default_hs_code', DEFAULT_HS_CODE),
        'default_weight_g': settings.get('default_weight_g', DEFAULT_WEIGHT_G),
        'default_country_of_origin': settings.get('default_country_of_origin', DEFAULT_COUNTRY_OF_ORIGIN),
        'default_inventory_qty': settings.get('default_inventory_qty', DEFAULT_INVENTORY_QTY),
    }
    return jsonify(out)

@app.route('/save_settings', methods=['POST'])
def save_settings_route():
    data = request.get_json()
    current = load_settings(); current.update(data)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2))
    return jsonify({'ok': True})

@app.route('/test_shopify', methods=['POST'])
def test_shopify():
    settings = load_settings()
    store = (settings.get('shopify_store') or '').replace('https://', '').replace('http://', '').rstrip('/')
    token = settings.get('shopify_token') or ''
    if not store or not token:
        return jsonify({'ok': False, 'error': 'Store URL and token both required'}), 400
    try:
        r = requests.get(f'https://{store}/admin/api/2024-01/shop.json',
                          headers={'X-Shopify-Access-Token': token}, timeout=15)
        if r.ok:
            shop = r.json().get('shop', {})
            return jsonify({'ok': True, 'shop_name': shop.get('name'), 'domain': shop.get('myshopify_domain')})
        return jsonify({'ok': False, 'error': f'HTTP {r.status_code}: {r.text[:200]}'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/test_groq', methods=['POST'])
def test_groq():
    settings = load_settings()
    key = settings.get('groq_api_key') or ''
    if not key:
        return jsonify({'ok': False, 'error': 'Groq key required'}), 400
    try:
        r = requests.post('https://api.groq.com/openai/v1/chat/completions',
                           headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                           json={'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
                                 'messages': [{'role': 'user', 'content': 'Say OK'}], 'max_tokens': 5},
                           timeout=20)
        if r.ok:
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': f'HTTP {r.status_code}: {r.text[:200]}'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/history/<int:idx>', methods=['DELETE'])
def delete_history_row(idx):
    rows = load_history()
    if 0 <= idx < len(rows):
        rows.pop(idx)
        HISTORY_FILE.write_text(json.dumps(rows, indent=2))
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 404

# ── Socket.IO pipeline ────────────────────────────────────────────────────────
@socketio.on('start_upload')
def handle_start_upload(data):
    sid = request.sid
    filenames = data.get('filenames') or ([data['filename']] if data.get('filename') else [])
    sku = (data.get('sku') or '').upper()
    cost_price = float(data.get('cost_price', 0) or 0)
    markup = float(data.get('markup', 4) or 4)
    manual_title = (data.get('title') or '').strip() or None
    category = (data.get('category') or '').strip() or None
    manual_tags = (data.get('tags') or '').strip() or None
    weight_g = data.get('weight_g')
    hs_code = (data.get('hs_code') or '').strip() or None
    country_of_origin = (data.get('country_of_origin') or '').strip() or None
    inventory_qty = data.get('inventory_qty')
    selling_price = calc_sp(cost_price, markup)
    compare_at_price = int(round(selling_price * 2))
    image_paths = [UPLOAD_DIR / fn for fn in filenames]
    timestamp = datetime.now().isoformat()

    log(sid, f'▶ {sku} | {len(filenames)} image(s) | CP: ₹{cost_price} → SP: ₹{selling_price} (MRP ₹{compare_at_price})')

    def run():
        with upload_semaphore:
            try:
                missing = [p for p in image_paths if not p.exists()]
                if missing:
                    raise FileNotFoundError(f'Image(s) not found: {[p.name for p in missing]}')

                details = generate_product_details(image_paths, sku, sid)
                result = create_shopify_product(image_paths, sku, selling_price, details, sid, manual_title,
                                                 category=category, manual_tags=manual_tags,
                                                 weight_g=weight_g, hs_code=hs_code,
                                                 country_of_origin=country_of_origin,
                                                 inventory_qty=inventory_qty,
                                                 cost_price=cost_price)

                row = {'timestamp': timestamp, 'sku': sku, 'title': result.get('title'),
                       'handle': result.get('handle'), 'cost_price': cost_price,
                       'selling_price': selling_price, 'compare_at_price': result.get('compare_at_price'),
                       'hs_code': result.get('hs_code'), 'country_of_origin': result.get('country_of_origin'),
                       'status': 'success', 'shopify_url': result['shopify_url'], 'error': None,
                       'image_count': len(filenames)}
                append_history(row)
                log(sid, f'🎉 Done! {result["shopify_url"]}', 'success')
                socketio.emit('product_done', {
                    'sku': sku, 'title': result.get('title'),
                    'selling_price': selling_price, 'compare_at_price': result.get('compare_at_price'),
                    'shopify_url': result['shopify_url'],
                    'status': 'success'
                }, to=sid)
            except Exception as e:
                log(sid, f'❌ Failed for {sku}: {e}', 'error')
                append_history({'timestamp': timestamp, 'sku': sku, 'title': manual_title,
                                'cost_price': cost_price, 'selling_price': selling_price,
                                'compare_at_price': compare_at_price,
                                'status': 'failed', 'shopify_url': None, 'error': str(e),
                                'image_count': len(filenames)})
                socketio.emit('product_done', {'sku': sku, 'status': 'failed', 'error': str(e)}, to=sid)
            finally:
                for p in image_paths:
                    try:
                        p.unlink()
                    except Exception:
                        pass

    threading.Thread(target=run, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
