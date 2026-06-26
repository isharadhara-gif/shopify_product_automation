import os, json, time, base64, re, requests, threading
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

UPLOAD_DIR = Path('uploads'); UPLOAD_DIR.mkdir(exist_ok=True)
HISTORY_FILE = Path('history.json')
SETTINGS_FILE = Path('settings.json')

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_settings():
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {}

def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []

def append_history(row):
    h = load_history(); h.insert(0, row); h = h[:200]
    HISTORY_FILE.write_text(json.dumps(h, indent=2))

def log(sid, msg, level='info'):
    socketio.emit('log', {'msg': msg, 'level': level}, to=sid)

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')

def calc_sp(cp: float) -> int:
    """Round up cost*4 to nearest price ending in 999/9999 pattern."""
    raw = cp * 4
    # Find the right tier: 999, 1999, 2999, 4999, 9999, 19999...
    tiers = []
    for base in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
        for exp in range(2, 6):
            tiers.append(base * (10**exp) - 1)
    tiers.sort()
    for t in tiers:
        if t >= raw:
            return t
    # fallback: round up to nearest 999 ending
    base = int(raw)
    remainder = base % 1000
    return base - remainder + 999 if remainder < 999 else base + 999

# ── Groq: generate ALL product fields ────────────────────────────────────────
def generate_product_details(image_path: Path, sku: str, sid: str) -> dict:
    settings = load_settings()
    groq_key = settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY', '')

    if not groq_key:
        log(sid, 'Groq key not set — using SKU as title', 'muted')
        slug = slugify(sku)
        return {
            'title': sku, 'description': '', 'handle': slug,
            'seo_title': sku, 'seo_description': '',
            'alt_text': sku, 'tags': ''
        }

    log(sid, f'🤖 Generating product content via Groq for {sku}…')
    try:
        img_bytes = image_path.read_bytes()
        b64 = base64.b64encode(img_bytes).decode()
        ext = image_path.suffix.lower().lstrip('.')
        mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp'}.get(ext,'image/jpeg')

        prompt = f"""You are a Shopify product copywriter for an Indian jewellery brand called Ishhaara.
The SKU is {sku}. Look at the product image carefully.

Respond ONLY with a valid JSON object (no markdown, no extra text):
{{
  "title": "Short product name 4-7 words, e.g. 'Green Onyx Stone Bracelet'",
  "description": "2-3 sentence HTML product description highlighting material, craftsmanship, occasion suitability",
  "handle": "url-slug-from-title-lowercase-hyphens",
  "seo_title": "Buy [Title] Online - Ishhaara (max 60 chars)",
  "seo_description": "Shop [Title] from Ishhaara. [brief benefit]. Best offers at our online store. (max 160 chars)",
  "alt_text": "Ishhaara [Title] - descriptive alt text for image",
  "tags": "comma separated relevant tags like: Bracelet, Stone Jewellery, New Arrivals"
}}"""

        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
                'messages': [{'role':'user','content':[
                    {'type':'image_url','image_url':{'url':f'data:{mime};base64,{b64}'}},
                    {'type':'text','text':prompt}
                ]}],
                'max_tokens': 500,
            }, timeout=30
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        content = content.replace('```json','').replace('```','').strip()
        result = json.loads(content)

        # Ensure handle is clean
        result['handle'] = slugify(result.get('handle', result.get('title', sku)))
        log(sid, f'✅ Title: {result.get("title")}', 'success')
        return result
    except Exception as e:
        log(sid, f'⚠️ Groq error: {e} — using SKU fallback', 'error')
        slug = slugify(sku)
        return {'title': sku, 'description': '', 'handle': slug,
                'seo_title': sku, 'seo_description': '', 'alt_text': sku, 'tags': ''}

# ── Shopify: create product ───────────────────────────────────────────────────
def create_shopify_product(image_path, sku, selling_price, details, sid):
    settings = load_settings()
    store  = (settings.get('shopify_store')  or os.environ.get('SHOPIFY_STORE','')).replace('https://','').replace('http://','').rstrip('/')
    token  = settings.get('shopify_token')   or os.environ.get('SHOPIFY_TOKEN','')
    vendor = settings.get('product_vendor')  or os.environ.get('PRODUCT_VENDOR','Ishhaara')
    p_type = settings.get('product_type')    or os.environ.get('PRODUCT_TYPE','')

    if not store or not token:
        raise ValueError('Shopify store or token not configured')

    base_url = f'https://{store}/admin/api/2024-01'
    headers  = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}

    title       = details.get('title', sku)
    description = details.get('description', '')
    handle      = details.get('handle', slugify(title))
    seo_title   = details.get('seo_title', f'Buy {title} Online - {vendor}')
    seo_desc    = details.get('seo_description', '')
    alt_text    = details.get('alt_text', f'{vendor} {title}')
    tags        = details.get('tags', '')

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
        'variants': [{'sku': sku, 'price': str(selling_price),
                      'inventory_management': 'shopify', 'inventory_policy': 'deny'}],
        'status': 'active',
    }}

    resp = requests.post(f'{base_url}/products.json', headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    product = resp.json()['product']
    product_id = product['id']
    log(sid, f'✅ Product created — ID {product_id}', 'success')

    # Upload image with alt text
    log(sid, '🖼️ Uploading image…')
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    img_resp = requests.post(
        f'{base_url}/products/{product_id}/images.json',
        headers=headers,
        json={'image': {'attachment': img_b64, 'filename': image_path.name, 'alt': alt_text}},
        timeout=60
    )
    if img_resp.ok:
        log(sid, '✅ Image uploaded with alt text', 'success')
    else:
        log(sid, f'⚠️ Image upload failed: {img_resp.text}', 'error')

    shopify_url = f'https://{store}/admin/products/{product_id}'
    return {'product_id': product_id, 'shopify_url': shopify_url, 'handle': handle}

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    settings = load_settings()
    has_groq    = bool(settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY'))
    has_shopify = bool(settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE'))
    shopify_store = settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE','')

    with open('index.html', 'r') as f: html = f.read()
    html = (html
        .replace('{% if has_groq %}ok{% else %}warn{% endif %}',    'ok' if has_groq    else 'warn')
        .replace('{% if not has_groq %}— not set{% endif %}',       '' if has_groq      else '— not set')
        .replace('{% if has_shopify %}ok{% else %}warn{% endif %}',  'ok' if has_shopify else 'warn')
        .replace('{% if not has_shopify %}— not set{% endif %}',     '' if has_shopify   else '— not set')
        .replace('{{ shopify_store }}', shopify_store)
    )
    return html

@app.route('/upload', methods=['POST'])
def upload():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file'}), 400
    file = request.files['image']
    sku  = request.form.get('sku','').strip().upper()
    cost = request.form.get('cost_price','0')
    if not sku:
        return jsonify({'error': 'SKU required'}), 400
    ext      = Path(file.filename).suffix.lower()
    filename = f'{sku}_{int(time.time())}{ext}'
    file.save(UPLOAD_DIR / filename)
    return jsonify({'filename': filename, 'sku': sku, 'cost_price': cost})

@app.route('/history')
def history():
    return jsonify(load_history())

@app.route('/save_settings', methods=['POST'])
def save_settings_route():
    data = request.get_json()
    current = load_settings(); current.update(data)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2))
    return jsonify({'ok': True})

# ── Socket.IO pipeline ────────────────────────────────────────────────────────
@socketio.on('start_upload')
def handle_start_upload(data):
    sid        = request.sid
    filename   = data.get('filename')
    sku        = data.get('sku','').upper()
    cost_price = float(data.get('cost_price', 0))
    selling_price = calc_sp(cost_price)
    image_path = UPLOAD_DIR / filename
    timestamp  = datetime.now().isoformat()

    log(sid, f'▶ {sku} | CP: ₹{cost_price} → SP: ₹{selling_price}')

    def run():
        try:
            if not image_path.exists():
                raise FileNotFoundError(f'Image not found: {filename}')

            details = generate_product_details(image_path, sku, sid)
            result  = create_shopify_product(image_path, sku, selling_price, details, sid)

            row = {'timestamp': timestamp, 'sku': sku, 'title': details.get('title'),
                   'handle': result.get('handle'), 'cost_price': cost_price,
                   'selling_price': selling_price, 'status': 'success',
                   'shopify_url': result['shopify_url'], 'error': None}
            append_history(row)
            log(sid, f'🎉 Done! {result["shopify_url"]}', 'success')
            socketio.emit('product_done', {
                'sku': sku, 'title': details.get('title'),
                'selling_price': selling_price, 'shopify_url': result['shopify_url'],
                'status': 'success'
            }, to=sid)
        except Exception as e:
            log(sid, f'❌ Failed for {sku}: {e}', 'error')
            append_history({'timestamp': timestamp, 'sku': sku, 'title': None,
                            'cost_price': cost_price, 'selling_price': selling_price,
                            'status': 'failed', 'shopify_url': None, 'error': str(e)})
            socketio.emit('product_done', {'sku': sku, 'status': 'failed'}, to=sid)
        finally:
            try: image_path.unlink()
            except: pass

    threading.Thread(target=run, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
