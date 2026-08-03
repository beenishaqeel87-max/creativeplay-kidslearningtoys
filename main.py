import os
import io
import json
import random
import requests
import textwrap
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from shared_data_manager import SharedDataManager
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
REFRESH_TOKEN = os.getenv("PINTEREST_REFRESH_TOKEN")

# Board mapping (Category to Board ID)
DEFAULT_BOARD_ID = os.getenv("BOARD_ID_STEM", "845691704968020775")

BOARD_MAPPING = {
    "STEM Toys": os.getenv("BOARD_ID_STEM") or DEFAULT_BOARD_ID,
    "Montessori": os.getenv("BOARD_ID_MONTESSORI") or DEFAULT_BOARD_ID,
    "Crafts & Art": os.getenv("BOARD_ID_CRAFTS") or DEFAULT_BOARD_ID
}

def get_new_pinterest_token():
    """Refresh the Pinterest Access Token using the Refresh Token."""
    print("Refreshing Pinterest Access Token...")
    url = "https://api.pinterest.com/v5/oauth/token"
    
    import base64
    auth_string = f"{APP_ID}:{APP_SECRET}"
    b64_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN
    }
    
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        print("Successfully refreshed token!")
        return response.json().get("access_token")
    else:
        print(f"Failed to refresh token: {response.text}")
        return None

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
    - Title: Catchy, click-worthy (max 60 chars). It MUST NOT be in the exact list of previously used titles (I will verify this).
    - Description: SEO optimized, engaging description explaining why parents need this toy/activity, ending with relevant hashtags (max 400 chars).
    - Image_Prompt: A highly detailed text-to-image prompt to generate a photo of this toy/activity. It should describe a brightly colored, high-quality, professional photo suitable for Pinterest (9:16 vertical aspect ratio). Do NOT include text in the image prompt.
    - Alt_Text: Simple description for visually impaired users.
    
    Return ONLY a raw JSON object with exactly these keys: title, description, image_prompt, alt_text.
    No markdown formatting, no backticks.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        # Parse JSON from response
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        content = json.loads(text)
        
        # Prevent duplicates
        if data_manager.is_title_used(content['title']):
            print("Generated a duplicate title. Trying again...")
            return generate_pin_content(data_manager)
            
        content['category'] = category
        return content
        
    except Exception as e:
        print(f"Error generating content: {e}")
        return None

def generate_image(prompt):
    """Phase 2: Ask Hugging Face to generate the image."""
    print("Generating image with Hugging Face...")
    API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
    
    # Enhance the prompt for Pinterest aesthetics
    full_prompt = f"Vertical portrait photography, high quality, bright lighting, colorful kids educational toy, {prompt}"
    
    payload = {
        "inputs": full_prompt,
        "parameters": {
            "width": 768,
            "height": 1344 # 9:16 aspect ratio
        }
    }
    
    response = requests.post(API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        return Image.open(io.BytesIO(response.content))
    else:
        print(f"Error generating image: {response.text}")
        return None

def add_text_to_image(image, title):
    """Phase 3: Add a beautiful gradient and text overlay to the image using Pillow."""
    print("Designing pin with Pillow...")
    
    # Ensure image is in RGB
    image = image.convert("RGBA")
    width, height = image.size
    
    # Create a gradient overlay for text readability (bottom up)
    gradient = Image.new('RGBA', (width, height), color=(0,0,0,0))
    draw_gradient = ImageDraw.Draw(gradient)
    
    # Dark gradient at the top for title
    gradient_height = int(height * 0.4)
    for y in range(gradient_height):
        alpha = int(255 * (1 - (y / gradient_height)))
        draw_gradient.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
        
    image = Image.alpha_composite(image, gradient)
    
    # Add Text
    draw = ImageDraw.Draw(image)
    
    # Try to load a nice font, fallback to default
    try:
        font = ImageFont.truetype("arialbd.ttf", 60)
    except:
        font = ImageFont.load_default(size=40)
        
    # Wrap text
    margin = 50
    max_width = width - (margin * 2)
    
    # Simple text wrapping logic
    words = title.split()
    lines = []
    current_line = []
    
    for word in words:
        current_line.append(word)
        # Check width
        bbox = draw.textbbox((0,0), " ".join(current_line), font=font)
        if bbox[2] > max_width:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
        
    # Draw text lines
    y_text = 60
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x_text = (width - line_width) / 2
        
        # Text shadow/outline for readability
        draw.text((x_text+3, y_text+3), line, font=font, fill=(0,0,0,200))
        draw.text((x_text, y_text), line, font=font, fill=(255,255,255,255))
        y_text += (bbox[3] - bbox[1]) + 10
        
    # Save final image to bytes
    img_byte_arr = io.BytesIO()
    image.convert("RGB").save(img_byte_arr, format='JPEG', quality=90)
    return img_byte_arr.getvalue()

def publish_to_pinterest(access_token, image_bytes, content):
    """Phase 4: Upload image and create Pin on Pinterest."""
    print("Publishing to Pinterest...")
    board_id = BOARD_MAPPING.get(content['category'])
    
    if not board_id or board_id == "your_board_id_here":
        print(f"Warning: No valid board ID for category '{content['category']}'. Skipping publish.")
        return False
        
    # 1. Register media upload
    print("Registering media upload...")
    register_url = "https://api.pinterest.com/v5/media"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {"media_type": "image"}
    
    reg_res = requests.post(register_url, headers=headers, json=payload)
    if reg_res.status_code != 201:
        print(f"Failed to register media: {reg_res.text}")
        return False
        
    upload_data = reg_res.json()
    media_id = upload_data['media_id']
    upload_url = upload_data['upload_url']
    upload_params = upload_data['upload_parameters']
    
    # 2. Upload the file to the S3 bucket provided by Pinterest
    print("Uploading image to Pinterest CDN...")
    files = {'file': ('pin.jpg', image_bytes, 'image/jpeg')}
    upload_res = requests.post(upload_url, data=upload_params, files=files)
    
    if upload_res.status_code not in (200, 204):
        print(f"Failed to upload image: {upload_res.status_code}")
        return False
        
    # 3. Create the Pin
    print("Creating Pin...")
    pin_url = "https://api.pinterest.com/v5/pins"
    pin_payload = {
        "link": "https://beenishaqeel87-max.github.io/creativeplay-kidslearningtoys/",
        "title": content['title'],
        "description": content['description'],
        "alt_text": content['alt_text'],
        "board_id": board_id,
        "media_source": {
            "source_type": "image_base64",
            "content_type": "image/jpeg",
            "data": base64.b64encode(image_bytes).decode('utf-8')
        }
    }
    
    # Note: We upload using base64 direct creation instead of the media_id for simpler flow if preferred
    # Since we already have the bytes, let's use the base64 method directly to avoid waiting for media processing
    import base64
    pin_payload_base64 = {
        "link": "https://beenishaqeel87-max.github.io/creativeplay-kidslearningtoys/",
        "title": content['title'],
        "description": content['description'],
        "alt_text": content['alt_text'],
        "board_id": board_id,
        "media_source": {
            "source_type": "image_base64",
            "content_type": "image/jpeg",
            "data": base64.b64encode(image_bytes).decode('utf-8')
        }
    }
    
    create_res = requests.post(pin_url, headers=headers, json=pin_payload_base64)
    if create_res.status_code == 201:
        pin_data = create_res.json()
        print(f"✅ Successfully published Pin! ID: {pin_data.get('id')}")
        return True
    else:
        print(f"❌ Failed to create pin: {create_res.text}")
        return False

def main():
    print("Starting Pinterest Automation Bot...")
    
    # Ensure APIs are set
    if not GEMINI_API_KEY or not HUGGINGFACE_API_KEY or not REFRESH_TOKEN:
        print("Missing required API keys. Check your .env file.")
        return
        
    data_manager = SharedDataManager()
    
    # 1. Brain: Generate Content
    content = generate_pin_content(data_manager)
    if not content:
        return
        
    print(f"\nGenerated Title: {content['title']}")
    print(f"Category: {content['category']}")
    print(f"Image Prompt: {content['image_prompt']}\n")
    
    # 2. Artist: Generate Image
    raw_image = generate_image(content['image_prompt'])
    if not raw_image:
        return
        
    # 3. Designer: Add Text
    final_image_bytes = add_text_to_image(raw_image, content['title'])
    
    # 4. Publisher: Refresh Token and Publish
    access_token = get_new_pinterest_token()
    if not access_token:
        return
        
    success = publish_to_pinterest(access_token, final_image_bytes, content)
    
    if success:
        # Save title to prevent duplicates
        data_manager.add_title(content['title'])

if __name__ == "__main__":
    main()
