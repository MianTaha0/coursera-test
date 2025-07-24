# 🎨 Background Removal API

A Flask-based web application that removes backgrounds from images using AI. This project provides both a backend API and a frontend web interface for easy image processing.

## 🌟 Features

- **AI-powered background removal** using the `rembg` library
- **White background replacement** for processed images
- **Modern web interface** with drag-and-drop support
- **Real-time processing** with progress indicators
- **Multiple image formats** supported (PNG, JPG, JPEG, GIF, BMP, WEBP)
- **RESTful API** for programmatic access

## 📋 Requirements

- Python 3.7 or higher
- Virtual environment (recommended)
- Modern web browser

## 🚀 Quick Start

### 1. Setup Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Linux/Mac
# or
venv\Scripts\activate     # On Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the Server

**Option A: Using the startup script (Linux/Mac)**
```bash
chmod +x start.sh
./start.sh
```

**Option B: Using Python directly**
```bash
source venv/bin/activate
python3 app.py
```

**Option C: Using the setup script**
```bash
python3 run.py
```

### 4. Open the Website

1. Open your web browser
2. Navigate to the `frontend_example.html` file by:
   - **File method**: Open the file directly in your browser
   - **Local server method**: Use a local HTTP server for better functionality:
     ```bash
     # In a new terminal, navigate to the project folder
     python3 -m http.server 8000
     # Then visit: http://localhost:8000/frontend_example.html
     ```

## 🖥️ Usage

### Web Interface

1. Open `frontend_example.html` in your browser
2. Drag and drop an image or click "Choose Image"
3. Click "Remove Background" to process the image
4. Download the processed image with the white background

### API Endpoints

#### Health Check
```bash
GET http://localhost:5000/health
```

#### API Information
```bash
GET http://localhost:5000/
```

#### Upload and Process Image
```bash
POST http://localhost:5000/upload
Content-Type: multipart/form-data
Body: file=<image_file>
```

#### Download Processed Image
```bash
GET http://localhost:5000/download/<filename>
```

## 📝 API Response Examples

### Health Check Response
```json
{
  "status": "healthy",
  "service": "background-removal-api"
}
```

### Upload Response
```json
{
  "message": "Image processed successfully",
  "download_url": "/download/uuid_output.png",
  "file_id": "unique-id"
}
```

## 🛠️ Development

### Project Structure
```
├── app.py                  # Main Flask application
├── run.py                  # Setup and startup script
├── start.sh               # Quick startup script (Linux/Mac)
├── frontend_example.html  # Web interface
├── requirements.txt       # Python dependencies
├── test_api.py           # API testing script
├── uploads/              # Temporary upload folder
├── processed/            # Temporary processed images folder
└── venv/                 # Virtual environment
```

### Testing the API

```bash
# Activate virtual environment
source venv/bin/activate

# Run the test script
python3 test_api.py
```

### Supported Image Formats

- PNG
- JPG/JPEG
- GIF
- BMP
- WEBP

## 🔧 Configuration

The application runs on:
- **Host**: `0.0.0.0` (accessible from all network interfaces)
- **Port**: `5000`
- **Debug mode**: Enabled (for development)

## 📚 Dependencies

Key Python packages:
- `Flask`: Web framework
- `flask-cors`: Cross-origin resource sharing
- `rembg`: AI background removal
- `Pillow`: Image processing
- `numpy`: Numerical computing
- `onnxruntime`: AI model runtime

## 🌐 CORS Configuration

The API is configured with CORS enabled to allow frontend access from different origins.

## 🔒 Security Notes

- This is a development server - not suitable for production
- Files are automatically cleaned up after processing
- No persistent storage of uploaded images

## 🐛 Troubleshooting

### Common Issues

1. **Import errors**: Make sure virtual environment is activated
2. **Port already in use**: Change the port in `app.py`
3. **Permission denied**: Make sure `start.sh` is executable
4. **Missing dependencies**: Run `pip install -r requirements.txt`

### Error Messages

- **"No file provided"**: Ensure you're uploading a file
- **"File type not allowed"**: Check that your image format is supported
- **"Failed to process image"**: Try with a different image or check server logs

## 📄 License

This project is open source and available under the MIT License.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 🚀 Quick Commands Reference

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start server
python3 app.py

# Test API
curl http://localhost:5000/health

# Upload image
curl -X POST -F "file=@image.jpg" http://localhost:5000/upload
```

Enjoy removing backgrounds from your images! 🎨✨ 
