import requests
import os

def test_api():
    """Test the background removal API"""
    base_url = "http://localhost:5000"
    
    # Test health check
    print("Testing health check...")
    response = requests.get(f"{base_url}/health")
    print(f"Health check: {response.json()}")
    
    # Test API info
    print("\nGetting API info...")
    response = requests.get(f"{base_url}/")
    print(f"API info: {response.json()}")
    
    # Test file upload (you need to have an image file)
    # Uncomment and modify the path below to test with an actual image
    """
    print("\nTesting file upload...")
    image_path = "path/to/your/test/image.jpg"  # Change this to your image path
    
    if os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(f"{base_url}/upload", files=files)
            
        if response.status_code == 200:
            result = response.json()
            print(f"Upload successful: {result}")
            
            # Download the processed image
            download_url = f"{base_url}{result['download_url']}"
            download_response = requests.get(download_url)
            
            if download_response.status_code == 200:
                output_filename = f"processed_image_{result['file_id']}.png"
                with open(output_filename, 'wb') as output_file:
                    output_file.write(download_response.content)
                print(f"Processed image saved as: {output_filename}")
            else:
                print(f"Download failed: {download_response.status_code}")
        else:
            print(f"Upload failed: {response.status_code} - {response.text}")
    else:
        print(f"Test image not found at: {image_path}")
    """

if __name__ == "__main__":
    test_api()