import os
import requests
import urllib.parse
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()

APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
REDIRECT_URI = "http://localhost:8080/"  # Must exactly match your Pinterest App settings

def get_auth_url():
    """Generate the OAuth authorization URL."""
    base_url = "https://www.pinterest.com/oauth/"
    params = {
        "client_id": APP_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        # Requesting permission to read boards and write pins
        "scope": "boards:read,pins:read,pins:write,boards:write",
        "state": "creativeplay123" 
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return url

def exchange_code_for_token(auth_code):
    """Exchange the authorization code for access and refresh tokens."""
    url = "https://api.pinterest.com/v5/oauth/token"
    
    auth_string = f"{APP_ID}:{APP_SECRET}"
    import base64
    b64_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI
    }
    
    print("Exchanging code for token...")
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        tokens = response.json()
        print("\n✅ SUCCESS! Save these tokens in your .env file or GitHub Secrets:\n")
        print(f"PINTEREST_ACCESS_TOKEN=\"{tokens.get('access_token')}\"")
        print(f"PINTEREST_REFRESH_TOKEN=\"{tokens.get('refresh_token')}\"")
        print("\nNote: The refresh token lasts for 1 year. The access token lasts 30 days but our bot will auto-refresh it.")
    else:
        print(f"\n❌ Error exchanging code: {response.status_code}")
        print(response.json())

if __name__ == "__main__":
    if not APP_ID or not APP_SECRET:
        print("ERROR: Please set PINTEREST_APP_ID and PINTEREST_APP_SECRET in your .env file first.")
        exit(1)
        
    print("=== Pinterest OAuth Setup ===")
    print("\n1. Make sure you have added this exact Redirect URI to your Pinterest App settings:")
    print(f"   {REDIRECT_URI}")
    
    print("\n2. Open this URL in your browser and click 'Authorize':")
    print(f"   {get_auth_url()}")
    
    print("\n3. After you authorize, you will be redirected to localhost (it might say 'Site can't be reached' - that's fine!)")
    print("   Look at the URL in your browser address bar. It will look like:")
    print("   http://localhost:8080/?code=YOUR_AUTHORIZATION_CODE&state=...")
    
    auth_code = input("\n4. Paste the YOUR_AUTHORIZATION_CODE here: ").strip()
    
    if auth_code:
        exchange_code_for_token(auth_code)
    else:
        print("No code provided. Exiting.")
