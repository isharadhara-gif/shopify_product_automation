import os
import json
import time
import base64
import requests
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB max upload

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

UPLOAD_DIR = Path('uploads')
UPLOAD_DIR.mkdir(exist_ok=True)

HISTORY_FILE = Path('history.json')
SETTINGS_FILE = Path('settings.json')

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_settings():
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {}

def save_settings_to_file(data):
    current = load_settings()
    current.update(data)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2))

def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []

def append_history(row):
    history = load_history()
    history.insert(0, row)
    history = history[:200]  # keep last 200
    HISTORY_FILE.write_text(json.dumps(history, indent=2))

def calc_sp(cost_price: float) -> int:
    """Mirror the JS calcSP logic: cost × 4, rounded up to nearest ×9 ending."""
    raw = cost_price * 4
    base = int(raw)
    rem = base % 10
    sp = base - rem + 9 if rem < 9 else base + 9
    if sp < raw:
        sp += 10
    return sp

def log(sid, msg, level='info'):
    socketio.emit('log', {'msg': msg, 'level': level}, to=sid)

# ── Groq: generate product title + description ────────────────────────────────
def generate_product_details(image_path: Path, sku: str, sid: str) -> dict:
    settings = load_settings()
    groq_key = settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY', '')

    if not groq_key:
        log(sid, 'Groq key not set — using SKU as title', 'muted')
        return {'title': sku, 'description': ''}

    log(sid, f'🤖 Generating product details via Groq for {sku}…')

    try:
        # Read image and encode to base64
        img_bytes = image_path.read_bytes()
        b64 = base64.b64encode(img_bytes).decode()
        ext = image_path.suffix.lower().lstrip('.')
        mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'png': 'image/png', 'webp': 'image/webp'}.get(ext, 'image/jpeg')

        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {groq_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'image_url',
                                'image_url': {'url': f'data:{mime};base64,{b64}'},
                            },
                            {
                                'type': 'text',
                                'text': (
                                    f'You are a Shopify product copywriter. '
                                    f'The SKU is {sku}. '
                                    'Write a short product title (5-8 words) and a 2-sentence description. '
                                    'Respond ONLY with JSON: {{"title": "...", "description": "..."}}'
                                ),
                            },
                        ],
                    }
                ],
                'max_tokens': 200,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        # Strip markdown fences if present
        content = content.replace('```json', '').replace('```', '').strip()
        result = json.loads(content)
        log(sid, f'✅ Title: {result.get("title")}', 'success')
        return result
    except Exception as e:
        log(sid, f'⚠️ Groq error: {e} — falling back to SKU', 'error')
        return {'title': sku, 'description': ''}

# ── Shopify: create product ───────────────────────────────────────────────────
def create_shopify_product(image_path: Path, sku: str, selling_price: int,
                           title: str, description: str, sid: str) -> dict:
    settings = load_settings()
    store   = settings.get('shopify_store')  or os.environ.get('SHOPIFY_STORE', '')
    token   = settings.get('shopify_token')  or os.environ.get('SHOPIFY_TOKEN', '')
    vendor  = settings.get('product_vendor') or os.environ.get('PRODUCT_VENDOR', '')
    p_type  = settings.get('product_type')   or os.environ.get('PRODUCT_TYPE', '')

    if not store or not token:
        raise ValueError('Shopify store or token not configured')

    store = store.replace('https://', '').replace('http://', '').rstrip('/')
    base_url = f'https://{store}/admin/api/2024-01'
    headers  = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}

    log(sid, f'📦 Creating Shopify product: {title}…')

    # Build product payload
    payload = {
        'product': {
            'title': title,
            'body_html': f'<p>{description}</p>' if description else '',
            'vendor': vendor,
            'product_type': p_type,
            'variants': [
                {
                    'sku': sku,
                    'price': str(selling_price),
                    'inventory_management': 'shopify',
                    'inventory_policy': 'deny',
                }
            ],
            'status': 'active',
        }
    }

    resp = requests.post(f'{base_url}/products.json', headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    product = resp.json()['product']
    product_id = product['id']
    log(sid, f'✅ Product created — ID {product_id}', 'success')

    # Upload image
    log(sid, '🖼️ Uploading image…')
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    img_payload = {
        'image': {
            'attachment': img_b64,
            'filename': image_path.name,
        }
    }
    img_resp = requests.post(
        f'{base_url}/products/{product_id}/images.json',
        headers=headers, json=img_payload, timeout=60
    )
    if img_resp.ok:
        log(sid, '✅ Image uploaded', 'success')
    else:
        log(sid, f'⚠️ Image upload failed: {img_resp.text}', 'error')

    shopify_url = f'https://{store}/admin/products/{product_id}'
    return {'product_id': product_id, 'shopify_url': shopify_url}

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    settings = load_settings()
    with open('index.html', 'r') as f:
        html = f.read()
    # Replace Jinja-style template vars from the HTML
    html = html.replace(
        '{% if has_groq %}ok{% else %}warn{% endif %}',
        'ok' if settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY') else 'warn'
    ).replace(
        '{% if not has_groq %}— not set{% endif %}',
        '' if settings.get('groq_api_key') or os.environ.get('GROQ_API_KEY') else '— not set'
    ).replace(
        '{% if has_shopify %}ok{% else %}warn{% endif %}',
        'ok' if settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE') else 'warn'
    ).replace(
        '{% if not has_shopify %}— not set{% endif %}',
        '' if settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE') else '— not set'
    ).replace(
        '{{ shopify_store }}',
        settings.get('shopify_store') or os.environ.get('SHOPIFY_STORE', '')
    )
    return html

@app.route('/upload', methods=['POST'])
def upload():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file'}), 400

    file      = request.files['image']
    sku       = request.form.get('sku', '').strip().upper()
    cost_price = request.form.get('cost_price', '0')

    if not sku:
        return jsonify({'error': 'SKU is required'}), 400

    # Save file
    ext      = Path(file.filename).suffix.lower()
    filename = f'{sku}_{int(time.time())}{ext}'
    dest     = UPLOAD_DIR / filename
    file.save(dest)

    return jsonify({'filename': filename, 'sku': sku, 'cost_price': cost_price})

@app.route('/history')
def history():
    return jsonify(load_history())

@app.route('/save_settings', methods=['POST'])
def save_settings_route():
    data = request.get_json()
    save_settings_to_file(data)
    return jsonify({'ok': True})

# ── Socket.IO: pipeline ───────────────────────────────────────────────────────
@socketio.on('start_upload')
def handle_start_upload(data):
    sid        = request.sid
    filename   = data.get('filename')
    sku        = data.get('sku', '').upper()
    cost_price = float(data.get('cost_price', 0))
    selling_price = calc_sp(cost_price)

    image_path = UPLOAD_DIR / filename
    timestamp  = datetime.now().isoformat()

    log(sid, f'▶ Starting pipeline for {sku} | CP: ₹{cost_price} → SP: ₹{selling_price}')

    try:
        if not image_path.exists():
            raise FileNotFoundError(f'Image not found: {filename}')

        # Step 1: Generate title/description via Groq
        details = generate_product_details(image_path, sku, sid)
        title       = details.get('title', sku)
        description = details.get('description', '')

        # Step 2: Create Shopify product
        result = create_shopify_product(
            image_path, sku, selling_price, title, description, sid
        )

        # Step 3: Log success
        row = {
            'timestamp':    timestamp,
            'sku':          sku,
            'title':        title,
            'cost_price':   cost_price,
            'selling_price': selling_price,
            'status':       'success',
            'shopify_url':  result['shopify_url'],
            'error':        None,
        }
        append_history(row)

        log(sid, f'🎉 Done! View at {result["shopify_url"]}', 'success')
        emit('product_done', {
            'sku':          sku,
            'title':        title,
            'selling_price': selling_price,
            'shopify_url':  result['shopify_url'],
            'status':       'success',
        })

    except Exception as e:
        log(sid, f'❌ Pipeline failed for {sku}: {e}', 'error')
        append_history({
            'timestamp':    timestamp,
            'sku':          sku,
            'title':        None,
            'cost_price':   cost_price,
            'selling_price': selling_price,
            'status':       'failed',
            'shopify_url':  None,
            'error':        str(e),
        })
        emit('product_done', {'sku': sku, 'status': 'failed'})

    finally:
        # Clean up uploaded file
        try:
            image_path.unlink()
        except Exception:
            pass

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
