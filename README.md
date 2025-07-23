# Background Removal API

A simple Flask API that removes backgrounds from images and replaces them with a white background. Perfect for beginners who want to create a dynamic image processing service.

## Features

- **Remove background** from any image
- **Replace with white background** automatically
- **Multiple format support**: PNG, JPG, JPEG, GIF, BMP, WEBP
- **RESTful API** with JSON responses
- **File upload and download** functionality
- **Automatic cleanup** of temporary files
- **CORS enabled** for frontend integration

## Quick Start

### 1. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt
```

### 2. Run the Application

```bash
python app.py
```

The API will start on `http://localhost:5000`

### 3. Test the API

```bash
# Check if the API is running
curl http://localhost:5000/health

# Get API information
curl http://localhost:5000/
```

## API Endpoints

### GET `/`
Get API information and available endpoints.

**Response:**
```json
{
  "message": "Background Removal API",
  "endpoints": {
    "/": "API information",
    "/upload": "POST - Upload image for background removal",
    "/health": "GET - Health check"
  },
  "supported_formats": ["png", "jpg", "jpeg", "gif", "bmp", "webp"]
}
```

### GET `/health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "background-removal-api"
}
```

### POST `/upload`
Upload an image for background removal.

**Request:**
- Method: POST
- Content-Type: multipart/form-data
- Body: File with key `file`

**Response (Success):**
```json
{
  "message": "Image processed successfully",
  "download_url": "/download/uuid_output.png",
  "file_id": "unique-uuid"
}
```

**Response (Error):**
```json
{
  "error": "Error message"
}
```

### GET `/download/<filename>`
Download the processed image.

**Response:**
- Returns the processed image file as PNG
- File is automatically deleted after download

## Usage Examples

### Using cURL

```bash
# Upload an image
curl -X POST -F "file=@your_image.jpg" http://localhost:5000/upload

# Response will include download URL like:
# {"message": "Image processed successfully", "download_url": "/download/abc123_output.png", "file_id": "abc123"}

# Download the processed image
curl -O http://localhost:5000/download/abc123_output.png
```

### Using Python Requests

```python
import requests

# Upload image
with open('your_image.jpg', 'rb') as f:
    files = {'file': f}
    response = requests.post('http://localhost:5000/upload', files=files)

if response.status_code == 200:
    result = response.json()
    download_url = f"http://localhost:5000{result['download_url']}"
    
    # Download processed image
    img_response = requests.get(download_url)
    with open('processed_image.png', 'wb') as f:
        f.write(img_response.content)
    
    print("Image processed and saved!")
```

### Using JavaScript/Frontend

```javascript
// HTML form upload
const formData = new FormData();
formData.append('file', fileInput.files[0]);

fetch('http://localhost:5000/upload', {
    method: 'POST',
    body: formData
})
.then(response => response.json())
.then(data => {
    if (data.download_url) {
        // Create download link
        const downloadLink = document.createElement('a');
        downloadLink.href = `http://localhost:5000${data.download_url}`;
        downloadLink.download = 'processed_image.png';
        downloadLink.click();
    }
});
```

## File Structure

```
.
├── app.py              # Main Flask application
├── requirements.txt    # Python dependencies
├── test_api.py        # API testing script
├── README.md          # This file
├── uploads/           # Temporary upload folder (auto-created)
└── processed/         # Processed images folder (auto-created)
```

## How It Works

1. **Upload**: User uploads an image via POST request to `/upload`
2. **Process**: 
   - Image background is removed using the `rembg` library
   - A white background is added to replace the transparent background
   - Processed image is saved as PNG format
3. **Download**: User downloads the processed image via the provided download URL
4. **Cleanup**: Temporary files are automatically deleted after download

## Supported Image Formats

- PNG
- JPG/JPEG
- GIF
- BMP
- WEBP

## Error Handling

The API includes comprehensive error handling for:
- Invalid file types
- Missing files
- Processing errors
- File not found errors
- Server errors

## Dependencies

- **Flask**: Web framework
- **rembg**: Background removal
- **Pillow**: Image processing
- **flask-cors**: Cross-origin resource sharing
- **numpy**: Numerical operations
- **opencv-python**: Computer vision operations

## Tips for Beginners

1. **Start simple**: Test with the provided examples
2. **Check logs**: The console will show detailed information
3. **File formats**: PNG works best for images with transparency
4. **Memory**: Large images may take longer to process
5. **Frontend**: Use the CORS-enabled API with any frontend framework

## Next Steps

To extend this API, you could add:
- Different background colors/images
- Image resizing options
- Batch processing
- User authentication
- Database storage
- Progress tracking for large files

## Troubleshooting

**Installation Issues:**
```bash
# If you have issues with rembg, try:
pip install --upgrade pip
pip install rembg[gpu]  # For GPU acceleration (optional)
```

**Port Already in Use:**
```bash
# Change the port in app.py:
app.run(debug=True, host='0.0.0.0', port=5001)  # Use different port
```

**Memory Issues:**
- Try with smaller images first
- Consider adding image size limits in the code 
