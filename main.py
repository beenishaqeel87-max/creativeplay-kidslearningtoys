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
from google.genai import types

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
# Use the direct Sandbox Access Token (no refresh flow needed for Sandbox apps)
ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN") or base64.b64decode(
    "cGluYV9BTUEzWVJRWUFCRVJLQUFBR0NBTFlDNUpMU1I0TkhZQkFDR1NPNk5MUk9FNUxVVzI2N1dPUTY2MlFRQlo0RjVGUEZPUlYyWlFaSkY0WEdJTkE2RDRUTVRJREJYNVRKQUE="
).decode()

# Sandbox API base URL
PINTEREST_BASE_URL = "https://api-sandbox.pinterest.com/v5"

# Board mapping (Category to Board ID)
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

    # gemini-3.1-flash-lite-preview is the only confirmed working free-tier model for this account
    models_to_try = [
        "gemini-3.1-flash-lite-preview",
    ]

    last_error = None
    for model_name in models_to_try:
        try:
            print(f"Trying Gemini model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )

            text = response.text.strip()
            # Clean any markdown code fences
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            content = json.loads(text.strip())

            # Prevent duplicate titles
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
    """Phase 2: Generate image using Gemini native image generation."""
    import time

    full_prompt = (
        f"Create a high quality vertical portrait photo (9:16 aspect ratio) of "
        f"colorful kids educational toy, bright studio lighting, vibrant colors, "
        f"professional product photography style. {prompt}"
    )

    # Try Gemini image models in order
    image_models = [
        "gemini-3.1-flash-lite-image",
        "gemini-3.1-flash-image",
        "gemini-2.5-flash-image",
    ]

    client = genai.Client(api_key=GEMINI_API_KEY)

    for model_name in image_models:
        for attempt in range(1, 3):
            try:
                print(f"Generating image with {model_name} (attempt {attempt})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"]
                    )
                )

                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        image_data = base64.b64decode(part.inline_data.data)
                        print(f"Image generated successfully with {model_name}!")
                        return Image.open(io.BytesIO(image_data))

                print(f"No image in response from {model_name}")

            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                    print(f"Rate limited on {model_name}, waiting 20s...")
                    time.sleep(20)
                elif "404" in err or "not found" in err.lower():
                    print(f"Model {model_name} not available, trying next...")
                    break
                else:
                    print(f"Error with {model_name} attempt {attempt}: {err[:150]}")
                    time.sleep(5)

    print("All Gemini image models failed.")
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

    # Use image_base64 source_type — simplest method, works directly with Sandbox
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

    # Validate required keys
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is missing!")
        return
    if not HUGGINGFACE_API_KEY:
        print("ERROR: HUGGINGFACE_API_KEY is missing!")
        return
    if not ACCESS_TOKEN:
        print("ERROR: No Pinterest Access Token available!")
        return

    print(f"Using board: {DEFAULT_BOARD_ID}")
    print(f"Gemini key: {GEMINI_API_KEY[:10]}...")
    print(f"HuggingFace key: {HUGGINGFACE_API_KEY[:10]}...")
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
