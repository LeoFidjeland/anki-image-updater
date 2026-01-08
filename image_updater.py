import requests
import json
import base64
import os
import time
import argparse
import re
import logging
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# ================= CONFIGURATION DEFAULTS =================
DEFAULT_DECK_NAME = "The Heart of Tibetan Language -  V1"
DEFAULT_FIELD_SEARCH = "English"
DEFAULT_FIELD_IMAGE = "Image"
DEFAULT_FIELD_SOURCE = "Image Source"
DEFAULT_FIELD_NOTES = "Notes"
DEFAULT_IMAGES_PER_TERM = 5
DEFAULT_TAG = "pexels-updated"
# ==========================================================

ANKI_URL = "http://localhost:8765"

# Setup Logging
# This configures logging to write to both the console and a file named 'anki_updater.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("anki_updater.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Try to get API key from environment, otherwise user must provide it
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "YOUR_PEXELS_API_KEY_HERE")

def anki_invoke(action, params=None):
    """Helper to communicate with AnkiConnect."""
    payload = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    
    try:
        response = requests.post(ANKI_URL, json=payload).json()
        if len(response) != 2:
            raise Exception("Response has an unexpected number of fields")
        if "error" not in response:
            raise Exception("Response is missing required error field")
        if response["error"] is not None:
            raise Exception(response["error"])
        return response["result"]
    except Exception as e:
        logger.error(f"Error invoking Anki method '{action}': {e}")
        return None

def validate_api_key(api_key):
    """Checks if the API key is set and prints instructions if missing."""
    if not api_key or "YOUR_PEXELS" in api_key:
        logger.error("PEXELS_API_KEY is missing or invalid.")
        print("\n" + "="*60)
        print("❌ ERROR: Pexels API Key is required to run this script.")
        print("="*60)
        print("HOW TO FIX:")
        print("1. Go to https://www.pexels.com/api/ and sign up (it's free).")
        print("2. Copy your API Key.")
        print("3. EITHER:")
        print("   a) Create a file named '.env' in this folder and add:")
        print("      PEXELS_API_KEY=your_actual_key_here")
        print("   OR")
        print("   b) Set it as an environment variable in your terminal.")
        print("="*60 + "\n")
        return False
    return True

def search_pexels(query, api_key, count=1):
    """Searches Pexels for royalty-free images. Returns a list of URLs."""
    # Secondary check just in case
    if not api_key or "YOUR_PEXELS" in api_key:
        return []

    headers = {'Authorization': api_key}
    url = f"https://api.pexels.com/v1/search?query={query}&per_page={count}"
    
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        if data['photos']:
            return [photo['src']['medium'] for photo in data['photos']]
    except Exception as e:
        logger.warning(f"Error searching Pexels for '{query}': {e}")
    return []

def download_image_as_base64(url):
    """Downloads an image URL and converts it to base64 for Anki."""
    try:
        r = requests.get(url)
        r.raise_for_status()
        return base64.b64encode(r.content).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Anki Image Fetcher using Pexels API")
    parser.add_argument("--deck", default=DEFAULT_DECK_NAME, help="Name of the Anki deck")
    parser.add_argument("--field-term", default=DEFAULT_FIELD_SEARCH, help="Field name to search for (e.g. English)")
    parser.add_argument("--field-image", default=DEFAULT_FIELD_IMAGE, help="Field name to update with images")
    parser.add_argument("--field-source", default=DEFAULT_FIELD_SOURCE, help="Field name to store image sources")
    parser.add_argument("--field-notes", default=DEFAULT_FIELD_NOTES, help="Field name to store old images")
    parser.add_argument("--tag", default=DEFAULT_TAG, help="Tag to add to updated cards")
    parser.add_argument("--limit", type=int, default=5, help="Max number of cards to process")
    parser.add_argument("--count", type=int, default=DEFAULT_IMAGES_PER_TERM, help="Number of images to fetch per card")
    parser.add_argument("--live", action="store_true", help="Actually perform updates (default is Dry Run)")
    
    args = parser.parse_args()

    # Validate API Key BEFORE starting logic
    if not validate_api_key(PEXELS_API_KEY):
        return
    
    dry_run = not args.live
    
    logger.info(f"--- Starting Anki Image Updater ({'DRY RUN' if dry_run else 'LIVE MODE'}) ---")
    logger.info(f"Target Deck: {args.deck}")
    
    # 1. Find Cards
    logger.info(f"Scanning deck for cards...")
    note_ids = anki_invoke("findNotes", {"query": f'deck:"{args.deck}"'})
    
    if not note_ids:
        logger.warning(f"No notes found for deck '{args.deck}'. Check spelling or deck existence.")
        return

    logger.info(f"Found {len(note_ids)} notes. Processing first {args.limit}...")

    # 2. Get Note Details
    notes_info = anki_invoke("notesInfo", {"notes": note_ids[:args.limit]})
    
    for note in notes_info:
        note_id = note['noteId']
        fields = note['fields']
        
        # Extract fields
        term = fields.get(args.field_term, {}).get('value', '')
        current_image_html = fields.get(args.field_image, {}).get('value', '')
        current_notes = fields.get(args.field_notes, {}).get('value', '')
        
        # Clean the term: remove HTML, strip whitespace
        clean_term = term.split('<')[0].strip()
        
        logger.info(f"Processing ID {note_id}: '{clean_term}'")
        
        if not clean_term:
            logger.warning(f"Skipping ID {note_id}: Search term field '{args.field_term}' is empty.")
            continue

        # 3. Search for new images
        logger.info(f"Searching Pexels for '{clean_term}'...")
        new_image_urls = search_pexels(clean_term, PEXELS_API_KEY, count=args.count)
        
        if not new_image_urls:
            logger.info(f"No results found on Pexels for '{clean_term}'.")
            continue
            
        logger.info(f"Found {len(new_image_urls)} images for '{clean_term}'.")

        if dry_run:
            logger.info(f"[DRY RUN] Would update card {note_id}:")
            logger.info(f"   - Move old image to '{args.field_notes}'")
            logger.info(f"   - Add {len(new_image_urls)} new Pexels images to '{args.field_image}'")
            logger.info(f"   - Add source URLs to '{args.field_source}'")
            logger.info(f"   - Add tag '{args.tag}'")
            continue

        # 4. Download and Prepare Loop
        new_image_tags = []
        source_links = []
        
        # Create a meaningful but safe filename base
        safe_filename_base = re.sub(r'[^a-zA-Z0-9]', '_', clean_term).strip('_')
        timestamp = int(time.time())

        for index, img_url in enumerate(new_image_urls):
            image_b64 = download_image_as_base64(img_url)
            if not image_b64:
                continue

            # Filename format: pexels_{word}_{timestamp}_{index}.jpg
            filename = f"pexels_{safe_filename_base}_{timestamp}_{index}.jpg"
            
            # 5. Upload to Anki Media
            anki_invoke("storeMediaFile", {
                "filename": filename,
                "data": image_b64
            })
            
            new_image_tags.append(f'<img src="{filename}">')
            source_links.append(f'<a href="{img_url}">Source {index+1}</a>')
            time.sleep(0.2) # Polite delay between requests

        if not new_image_tags:
            logger.error(f"Failed to download any images for '{clean_term}'. Skipping update.")
            continue

        # 6. Update Note Fields
        # Append old image to notes if it exists
        if current_image_html:
            new_notes_content = current_notes + "<br><br><b>Old Image:</b><br>" + current_image_html
        else:
            new_notes_content = current_notes

        # Stack new images and sources vertically
        new_image_content = "<br>".join(new_image_tags)
        new_source_content = "<br>".join(source_links)
        
        update_payload = {
            "note": {
                "id": note_id,
                "fields": {
                    args.field_image: new_image_content,
                    args.field_source: new_source_content,
                    args.field_notes: new_notes_content
                }
            }
        }
        
        anki_invoke("updateNoteFields", update_payload)
        
        # 7. Add Tag
        anki_invoke("addTags", {
            "notes": [note_id],
            "tags": args.tag
        })

        logger.info(f"Success! Updated card {note_id} with {len(new_image_tags)} images and added tag '{args.tag}'.")
        
        # Sleep briefly to ensure we don't spam the Anki API or Pexels too hard
        time.sleep(1.0)
    
    # End of batch summary
    logger.info("--- Batch processing complete ---")
    print("\n" + "="*50)
    print("🔎 View updated cards in Anki Browser with this query:")
    print(f"tag:{args.tag}")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()