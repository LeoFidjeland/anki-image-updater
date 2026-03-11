from utils import download_image_as_base64

def test_download_image_as_base64():
    """Test downloading a real small image and converting to base64."""
    # We use a reliable, tiny placeholder image for testing
    url = "https://raw.githubusercontent.com/github/explore/80688e429a7d4ef2fca1e82350fe8e3517d3494d/topics/python/python.png"
    
    b64_data = download_image_as_base64(url)
    
    assert b64_data is not None
    assert isinstance(b64_data, str)
    assert len(b64_data) > 0

def test_download_image_as_base64_invalid_url():
    """Test downloading an invalid URL handles exception and returns None."""
    url = "http://localhost:9999/non_existent_image.jpg"
    b64_data = download_image_as_base64(url)
    assert b64_data is None
