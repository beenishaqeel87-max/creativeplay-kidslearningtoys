import os
import io
import json
import base64
import random
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from shared_data_manager import SharedDataManager
from google import genai

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
CF_API_TOKEN = os.getenv("CF_API_TOKEN")
APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")

# Use direct Sandbox Access Token
ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN") or base64.b64decode(
    "cGluYV9BTUEzWVJRWUFCRVJLQUFBR0NBTFlDNUpMU1I0TkhZQkFDR1NPNk5MUk9FNUxVVzI2N1dPUTY2MlFRQlo0RjVGUEZPUlYyWlFaSkY0WEdJTkE2RDRUTVRJREJYNVRKQUE="
).decode()

# Sandbox API base URL
PINTEREST_BASE_URL = "https://api-sandbox.pinterest.com/v5"

# Board mapping
DEFAULT_BOARD_ID = os.getenv("BOARD_ID_STEM", "845691704968020775")
BOARD_MAPPING = {
    "STEM Toys": os.getenv("BOARD_ID_STEM") or DEFAULT_BOARD_ID,
    "Montessori": os.getenv("BOARD_ID_MONTESSORI") or DEFAULT_BOARD_ID,
    "Crafts & Art": os.getenv("BOARD_ID_CRAFTS") or DEFAULT_BOARD_ID
}


def generate_pin_content(data_manager):
    """Phase 1: Ask Gemini to generate the pin details."""
    print("Generating content with Gemini...")
    client = genai.Client(api_key=GEMINI_API_KEY)

    categories = list(BOARD_MAPPING.keys())
    category = random.choice(categories)

    prompt = f"""
    You are an expert Pinterest manager in the 'Kids Learning Toys' niche.
    Create a highly engaging pin about a kids educational toy or activity in the '{category}' category.

    Requirements:
    - Title: Catchy, click-worthy (max 60 chars).
    - Description: SEO optimized, engaging description for parents, ending with relevant hashtags (max 400 chars).
    - Image_Prompt: A highly detailed text-to-image prompt. Describe a brightly colored, high-quality, professional 9:16 vertical photo of this toy/activity. Do NOT include text in the image prompt.
    - Alt_Text: Simple description for visually impaired users.

    Return ONLY a raw JSON object with exactly these keys: title, description, image_prompt, alt_text.
    No markdown formatting, no backticks, no extra text.
    """

    models_to_try = ["gemini-3.1-flash-lite-preview"]
    last_error = None

    for model_name in models_to_try:
        try:
            print(f"Trying Gemini model: {model_name}")
            response = client.models.generate_content(model=model_name, contents=prompt)
            text = response.text.strip()

            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            content = json.loads(text.strip())

            if data_manager.is_title_used(content['title']):
                print("Duplicate title detected, regenerating...")
                return generate_pin_content(data_manager)

            content['category'] = category
            print(f"Generated with {model_name}: {content['title']} [{category}]")
            return content

        except Exception as e:
            print(f"Model {model_name} failed: {e}")
            last_error = e
            continue

    print(f"All Gemini models failed. Last error: {last_error}")
    return None


def generate_image(prompt):
    """Phase 2: Generate image. HuggingFace → Cloudflare → Picsum fallback."""
    import time

    full_prompt = (
        f"Vertical portrait photo, bright studio lighting, colorful kids educational toy, "
        f"vibrant colors, professional product photography style. {prompt}"
    )

    # ── Option 1: HuggingFace FLUX.1-schnell ──────────────────────────────────
    if HUGGINGFACE_API_KEY:
        hf_headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
        # Try new router endpoint first (different hostname, may bypass DNS block)
        hf_endpoints = [
            "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
            "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
        ]

        for endpoint in hf_endpoints:
            try:
                print(f"HuggingFace attempt via: {endpoint[:50]}...")
                resp = requests.post(
                    endpoint,
                    headers=hf_headers,
                    json={"inputs": full_prompt, "parameters": {"width": 768, "height": 1344}},
                    timeout=90
                )
                if resp.status_code == 200 and "image" in resp.headers.get("Content-Type", ""):
                    print("HuggingFace image generated successfully!")
                    return Image.open(io.BytesIO(resp.content))
                elif resp.status_code == 503:
                    wait = min(int(resp.json().get("estimated_time", 20)) + 5, 45)
                    print(f"HF model loading, waiting {wait}s...")
                    time.sleep(wait)
                    # retry same endpoint
                    resp2 = requests.post(endpoint, headers=hf_headers, json={"inputs": full_prompt, "parameters": {"width": 768, "height": 1344}}, timeout=90)
                    if resp2.status_code == 200 and "image" in resp2.headers.get("Content-Type", ""):
                        print("HuggingFace image generated successfully (retry)!")
                        return Image.open(io.BytesIO(resp2.content))
                elif resp.status_code == 429:
                    print("HF rate limited, waiting 30s...")
                    time.sleep(30)
                else:
                    print(f"HF error {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"HF error ({endpoint[:40]}): {str(e)[:120]}")
    else:
        print("No HuggingFace API key — skipping.")


    # ── Option 2: Cloudflare Workers AI FLUX.1-schnell ────────────────────────
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        cf_url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell"
        cf_headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
        cf_payload = {"prompt": full_prompt, "num_steps": 4}

        for attempt in range(1, 3):
            try:
                print(f"Cloudflare FLUX.1-schnell attempt {attempt}/2...")
                resp = requests.post(cf_url, headers=cf_headers, json=cf_payload, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("result", {}).get("image"):
                        image_bytes = base64.b64decode(data["result"]["image"])
                        print("Cloudflare image generated successfully!")
                        return Image.open(io.BytesIO(image_bytes))
                else:
                    print(f"Cloudflare error {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"Cloudflare error attempt {attempt}: {str(e)[:120]}")
            if attempt < 2:
                time.sleep(5)
    else:
        print("No Cloudflare credentials — skipping.")

    # ── Option 3: Picsum Photos (always works) ────────────────────────────────
    print("Using Picsum Photos fallback...")
    seed = abs(hash(prompt[:40])) % 1000
    try:
        resp = requests.get(f"https://picsum.photos/seed/{seed}/768/1344", timeout=20, allow_redirects=True)
        if resp.status_code == 200:
            print(f"Picsum fallback image fetched (seed={seed})!")
            return Image.open(io.BytesIO(resp.content))
    except Exception as e:
        print(f"Picsum error: {e}")

    print("All image sources failed.")
    return None


def add_text_to_image(image, title):
    """Phase 3: Add gradient + title text overlay using Pillow."""
    print("Adding text overlay with Pillow...")

    image = image.convert("RGBA")
    width, height = image.size

    # Create gradient overlay at top
    gradient = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
    draw_gradient = ImageDraw.Draw(gradient)
    gradient_height = int(height * 0.4)
    for y in range(gradient_height):
        alpha = int(200 * (1 - (y / gradient_height)))
        draw_gradient.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    image = Image.alpha_composite(image, gradient)
    draw = ImageDraw.Draw(image)

    # Load font
    try:
        font = ImageFont.truetype("arialbd.ttf", 58)
    except Exception:
        font = ImageFont.load_default(size=40)

    # Wrap text
    margin = 40
    max_width = width - (margin * 2)
    words = title.split()
    lines = []
    current_line = []

    for word in words:
        current_line.append(word)
        bbox = draw.textbbox((0, 0), " ".join(current_line), font=font)
        if bbox[2] > max_width:
            current_line.pop()
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    # Draw text with shadow
    y_text = 50
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x_text = (width - line_width) / 2
        draw.text((x_text + 3, y_text + 3), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x_text, y_text), line, font=font, fill=(255, 255, 255, 255))
        y_text += (bbox[3] - bbox[1]) + 12

    img_byte_arr = io.BytesIO()
    image.convert("RGB").save(img_byte_arr, format='JPEG', quality=90)
    print("Pin image designed successfully!")
    return img_byte_arr.getvalue()


def publish_to_pinterest(image_bytes, content):
    """Phase 4: Publish Pin directly to Pinterest Sandbox API using base64."""
    print("Publishing Pin to Pinterest Sandbox API...")

    board_id = BOARD_MAPPING.get(content['category'], DEFAULT_BOARD_ID)

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    pin_payload = {
        "board_id": board_id,
        "title": content['title'],
        "description": content['description'],
        "link": "https://beenishaqeel87-max.github.io/creativeplay-kidslearningtoys/",
        "alt_text": content.get('alt_text', ''),
        "media_source": {
            "source_type": "image_base64",
            "content_type": "image/jpeg",
            "data": base64.b64encode(image_bytes).decode('utf-8')
        }
    }

    response = requests.post(
        f"{PINTEREST_BASE_URL}/pins",
        headers=headers,
        json=pin_payload,
        timeout=30
    )

    if response.status_code == 201:
        pin_data = response.json()
        print(f"✅ Successfully published Pin! ID: {pin_data.get('id')}")
        return True
    else:
        print(f"❌ Failed to create pin ({response.status_code}): {response.text[:500]}")
        return False


def main():
    print("=" * 50)
    print("Pinterest Automation Bot Starting...")
    print("=" * 50)

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is missing!")
        return
    if not ACCESS_TOKEN:
        print("ERROR: No Pinterest Access Token available!")
        return

    print(f"Using board: {DEFAULT_BOARD_ID}")
    print(f"Gemini key: {GEMINI_API_KEY[:10]}...")
    print(f"Access Token: {ACCESS_TOKEN[:15]}...")

    data_manager = SharedDataManager()

    # Phase 1: Generate content
    content = generate_pin_content(data_manager)
    if not content:
        print("ERROR: Failed to generate content.")
        return

    # Phase 2: Generate image
    raw_image = generate_image(content['image_prompt'])
    if not raw_image:
        print("ERROR: Failed to generate image.")
        return

    # Phase 3: Design pin
    final_image_bytes = add_text_to_image(raw_image, content['title'])

    # Phase 4: Publish to Pinterest
    success = publish_to_pinterest(final_image_bytes, content)

    if success:
        data_manager.add_title(content['title'])
        print("🎉 Pin published and tracked successfully!")
    else:
        print("Pipeline completed but pin publishing failed. Check errors above.")


if __name__ == "__main__":
    main()
