# AI Background Removal Tool

A professional AI-powered background removal service with a modern web interface.

## Features

- **AI-Powered Background Removal**: Automatically remove backgrounds from images using advanced AI models
- **Modern Web Interface**: Beautiful, responsive design with dark theme
- **Drag & Drop Upload**: Easy file upload with drag and drop support
- **Real-time Preview**: See before and after images side by side
- **High Quality Output**: Support for high-resolution images up to 4K
- **No Registration Required**: Use the tool immediately without signing up
- **Mobile Responsive**: Works perfectly on all devices

## Quick Start

### Frontend Only
If you just want to see the modern interface:

1. Open `index.html` in your browser
2. The interface will load but won't process images without the backend

### Full Application (with AI processing)

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the Flask Backend**:
   ```bash
   python app.py
   ```

3. **Open the Frontend**:
   - Open `index.html` in your browser, or
   - Serve it via a local server for best experience:
   ```bash
   python -m http.server 8080
   ```
   Then visit `http://localhost:8080`

## File Structure

```
├── index.html          # Modern frontend interface
├── style.css           # Professional styling
├── frontend_example.html # Original simple frontend
├── app.py              # Flask backend API
├── run.py              # Alternative backend runner
├── requirements.txt    # Python dependencies
├── assets/             # Images and resources
│   ├── logo.png        # Company logo
│   ├── ai-icon.png     # AI feature icon
│   ├── upload-icon.png # Upload button icon
│   ├── image-icon.png  # Image selection icon
│   ├── upload-graphic.png # Upload area graphic
│   ├── demo-before.png # Demo before image
│   └── demo-after.png  # Demo after image
└── README.md           # This file
```

## API Endpoints

- `GET /health` - Check if the API is running
- `POST /upload` - Upload and process an image
- `GET /download/<filename>` - Download processed image

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Technologies Used

### Frontend
- HTML5 with semantic markup
- CSS3 with modern features (Grid, Flexbox, Gradients)
- Vanilla JavaScript (ES6+)
- Font Awesome icons
- Google Fonts (Inter, Poppins)

### Backend
- Python Flask
- AI background removal models
- Image processing libraries

## Design Features

- **Dark Theme**: Modern dark interface with gradient accents
- **Glassmorphism**: Frosted glass effects with backdrop filters
- **Smooth Animations**: Hover effects and transitions
- **Responsive Design**: Mobile-first approach
- **Accessibility**: ARIA labels and keyboard navigation
- **Professional Typography**: Beautiful font combinations

## Customization

### Colors
The main brand colors can be modified in `style.css`:
- Primary: `#46EDD5` (Teal)
- Secondary: `#0DB5AA` (Dark Teal)
- Accent: `#B28EFF` (Purple)

### Fonts
Current fonts:
- Primary: Inter (body text)
- Secondary: Poppins (headings)

## Development

To modify the interface:

1. Edit `index.html` for structure changes
2. Edit `style.css` for styling changes
3. Restart the backend if you modify Python files

## License

This project is licensed under the MIT License.

## Support

For issues or questions, please check the API health endpoint first to ensure the backend is running properly. 
