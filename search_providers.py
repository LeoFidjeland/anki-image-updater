import httpx
import logging

logger = logging.getLogger(__name__)

class ImageSearcher:
    """Handles communicating with external image APIs asynchronously."""
    
    def __init__(self, config_manager):
        self.config = config_manager

    def parse_api_error(self, response):
        """Centralized helper for API requests that raises explicit auth errors."""
        try:
            if response.status_code in (401, 403):
                raise ValueError("API key is invalid or unauthorized. Please check your settings.")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP Error: {e}")
            raise Exception(f"API Error ({response.status_code}): {e}")
        except httpx.RequestError as e:
            logger.warning(f"Connection Error: {e}")
            raise Exception(f"Connection failed: {e}")

    async def make_search_request(self, url, headers):
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            return self.parse_api_error(r)

    async def search(self, provider, query, count=1, page=1):
        if provider == 'pexels':
            return await self.search_pexels(query, count, page)
        elif provider == 'unsplash':
            return await self.search_unsplash(query, count, page)
        elif provider == 'freepik':
            return await self.search_freepik(query, count, page)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def search_pexels(self, query, count=1, page=1):
        """Searches Pexels."""
        api_key = self.config.get("PEXELS_API_KEY")
        if not api_key: 
            raise ValueError("Pexels API key is missing. Please add it in Settings.")
        
        headers = {'Authorization': api_key}
        url = f"https://api.pexels.com/v1/search?query={query}&per_page={count}&page={page}"
        
        data = await self.make_search_request(url, headers)
        results = []
        if data.get('photos'):
            for photo in data['photos']:
                results.append({
                    'thumb': photo['src']['medium'],
                    'full': photo['src']['original'],
                    'context_url': photo['url'],
                    'provider': 'pexels'
                })
        return results

    async def search_unsplash(self, query, count=1, page=1):
        """Searches Unsplash."""
        access_key = self.config.get("UNSPLASH_ACCESS_KEY")
        if not access_key:
            raise ValueError("Unsplash API key is missing. Please add it in Settings.")
        
        headers = {'Authorization': f'Client-ID {access_key}'}
        url = f"https://api.unsplash.com/search/photos?query={query}&per_page={count}&page={page}"
        
        data = await self.make_search_request(url, headers)
        results = []
        if data.get('results'):
            for photo in data['results']:
                results.append({
                    'thumb': photo['urls']['small'],
                    'full': photo['urls']['raw'],
                    'context_url': photo['links']['html'],
                    'provider': 'unsplash'
                })
        return results

    async def search_freepik(self, query, count=1, page=1):
        """Searches Freepik."""
        api_key = self.config.get("FREEPIK_API_KEY")
        if not api_key: 
            raise ValueError("Freepik API key is missing. Please add it in Settings.")
        
        headers = {'x-freepik-api-key': api_key}
        url = f"https://api.freepik.com/v1/resources?term={query}&limit={count}&page={page}"
        
        data = await self.make_search_request(url, headers)
        results = []
        if data.get('data'):
            for item in data['data']:
                if 'image' in item and 'source' in item['image']:
                     results.append({
                        'thumb': item['image']['source']['url'],
                        'full': item['image']['source']['url'],
                        'context_url': item.get('url', '#'),
                        'provider': 'freepik'
                    })
        return results
