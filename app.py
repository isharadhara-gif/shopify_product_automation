import os, json, time, base64, re, io, csv, threading
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, Response
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

UPLOAD_DIR = Path('uploads'); UPLOAD_DIR.mkdir(exist_ok=True)
HISTORY_FILE = Path('history.json')
SETTINGS_FILE = Path('settings.json')

# Limit how many products upload to Shopify concurrently (Shopify rate limits apply)
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
    """cost * markup, rounded UP to nearest charm-price tier (x99 / x999 / x9999...)."""
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
        # Use the first image as the reference for AI content generation
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
  "description": "2-3 sentence HTML product description highlighting material, craftsmanship, occasion suitability",
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

# ── Shopify: create product with MULTIPLE images ─────────────────────────────
def create_shopify_product(image_paths, sku, selling_price, details, sid, manual_title=None):
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
    description = details.get('description', '')
    handle = details.get('handle', slugify(title))
    seo_title = details.get('seo_title', f'Buy {title} Online - {vendor}')
    seo_desc = details.get('seo_description', '')
    alt_text = details.get('alt_text', f'{vendor} {title}')
    tags = details.get('tags', '')

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

    # Upload ALL images, in order, first one becomes the featured image
    total = len(image_paths)
    for i, img_path in enumerate(image_paths, start=1):
        log(sid, f'🖼️ Uploading image {i}/{total}…')
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        img_alt = alt_text if i == 1 else f'{alt_text} - view {i}'
        img_resp = requests.post(
            f'{base_url}/products/{product_id}/images.json',
            headers=headers,
            json={'image': {'attachment': img_b64, 'filename': img_path.name, 'alt': img_alt}},
            timeout=60
        )
        if img_resp.ok:
            log(sid, f'✅ Image {i}/{total} uploaded', 'success')
        else:
            log(sid, f'⚠️ Image {i}/{total} failed: {img_resp.text}', 'error')

    shopify_url = f'https://{store}/admin/products/{product_id}'
    return {'product_id': product_id, 'shopify_url': shopify_url, 'handle': handle, 'title': title}

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
    """Accepts ONE OR MORE images for a single product (same SKU)."""
    files = request.files.getlist('images')
    if not files:
        # backward-compat single field
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
        file.save(UPLOAD_DIR / filename)
        saved.append(filename)

    return jsonify({'filenames': saved, 'sku': sku})

@app.route('/history')
def history():
    return jsonify(load_history())

@app.route('/history/csv')
def history_csv():
    rows = load_history()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Timestamp', 'SKU', 'Title', 'Cost Price', 'Selling Price', 'Status', 'Shopify URL', 'Error'])
    for r in rows:
        writer.writerow([r.get('timestamp'), r.get('sku'), r.get('title'), r.get('cost_price'),
                          r.get('selling_price'), r.get('status'), r.get('shopify_url'), r.get('error')])
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
    selling_price = calc_sp(cost_price, markup)
    image_paths = [UPLOAD_DIR / fn for fn in filenames]
    timestamp = datetime.now().isoformat()

    log(sid, f'▶ {sku} | {len(filenames)} image(s) | CP: ₹{cost_price} → SP: ₹{selling_price}')

    def run():
        with upload_semaphore:
            try:
                missing = [p for p in image_paths if not p.exists()]
                if missing:
                    raise FileNotFoundError(f'Image(s) not found: {[p.name for p in missing]}')

                details = generate_product_details(image_paths, sku, sid)
                result = create_shopify_product(image_paths, sku, selling_price, details, sid, manual_title)

                row = {'timestamp': timestamp, 'sku': sku, 'title': result.get('title'),
                       'handle': result.get('handle'), 'cost_price': cost_price,
                       'selling_price': selling_price, 'status': 'success',
                       'shopify_url': result['shopify_url'], 'error': None,
                       'image_count': len(filenames)}
                append_history(row)
                log(sid, f'🎉 Done! {result["shopify_url"]}', 'success')
                socketio.emit('product_done', {
                    'sku': sku, 'title': result.get('title'),
                    'selling_price': selling_price, 'shopify_url': result['shopify_url'],
                    'status': 'success'
                }, to=sid)
            except Exception as e:
                log(sid, f'❌ Failed for {sku}: {e}', 'error')
                append_history({'timestamp': timestamp, 'sku': sku, 'title': manual_title,
                                'cost_price': cost_price, 'selling_price': selling_price,
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
