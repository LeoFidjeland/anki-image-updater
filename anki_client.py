import requests
import logging

logger = logging.getLogger(__name__)

class AnkiClient:
    """Handles communication with the local AnkiConnect instance."""
    
    def __init__(self, url="http://localhost:8765"):
        self.url = url

    def invoke(self, action, params=None):
        """Helper to communicate with AnkiConnect."""
        payload = {"action": action, "version": 6}
        if params:
            payload["params"] = params
        
        try:
            response = requests.post(self.url, json=payload).json()
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

    def fetch_decks(self):
        """Returns a list of all deck names."""
        return self.invoke("deckNames") or []

    def find_notes(self, query):
        """Returns a list of note IDs matching the query string."""
        return self.invoke("findNotes", {"query": query}) or []

    def get_notes_info(self, note_ids):
        """Returns list of note info dicts for given IDs."""
        return self.invoke("notesInfo", {"notes": note_ids}) or []

    def store_media_file(self, filename, base64_data):
        """Stores a base64 encoded media file in Anki."""
        return self.invoke("storeMediaFile", {
            "filename": filename,
            "data": base64_data
        })

    def update_note_fields(self, note_id, fields):
        """Updates specific fields for a note ID."""
        return self.invoke("updateNoteFields", {
            "note": {
                "id": note_id,
                "fields": fields
            }
        })

    def add_tags(self, note_ids, tags):
        """Adds space-separated tags to a list of note IDs."""
        return self.invoke("addTags", {"notes": note_ids, "tags": tags})

    def get_media_file_base64(self, filename):
        """Retrieves an image from Anki media collection as base64."""
        return self.invoke("retrieveMediaFile", {"filename": filename})
