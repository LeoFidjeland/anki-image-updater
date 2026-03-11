import httpx
import logging

logger = logging.getLogger(__name__)

class AnkiClient:
    """Handles communication with the local AnkiConnect instance."""
    
    def __init__(self, url="http://localhost:8765"):
        self.url = url

    async def invoke(self, action, params=None):
        """Helper to communicate with AnkiConnect asynchronously."""
        payload = {"action": action, "version": 6}
        if params:
            payload["params"] = params
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.url, json=payload)
                response.raise_for_status()
                data = response.json()
                
            if len(data) != 2:
                raise Exception("Response has an unexpected number of fields")
            if "error" not in data:
                raise Exception("Response is missing required error field")
            if data["error"] is not None:
                raise Exception(data["error"])
            return data["result"]
        except httpx.RequestError as e:
            logger.error(f"Connection error to Anki: {e}")
            return None
        except Exception as e:
            logger.error(f"Error invoking Anki method '{action}': {e}")
            return None

    async def fetch_decks(self):
        """Returns a list of all deck names."""
        return await self.invoke("deckNames") or []

    async def find_notes(self, query):
        """Returns a list of note IDs matching the query string."""
        return await self.invoke("findNotes", {"query": query}) or []

    async def get_notes_info(self, note_ids):
        """Returns list of note info dicts for given IDs."""
        return await self.invoke("notesInfo", {"notes": note_ids}) or []

    async def store_media_file(self, filename, base64_data):
        """Stores a base64 encoded media file in Anki."""
        return await self.invoke("storeMediaFile", {
            "filename": filename,
            "data": base64_data
        })

    async def update_note_fields(self, note_id, fields):
        """Updates specific fields for a note ID."""
        return await self.invoke("updateNoteFields", {
            "note": {
                "id": note_id,
                "fields": fields
            }
        })

    async def add_tags(self, note_ids, tags):
        """Adds space-separated tags to a list of note IDs."""
        return await self.invoke("addTags", {"notes": note_ids, "tags": tags})

    async def get_media_file_base64(self, filename):
        """Retrieves an image from Anki media collection as base64."""
        return await self.invoke("retrieveMediaFile", {"filename": filename})
