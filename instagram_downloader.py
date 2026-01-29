from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import os
import re
import logging
import requests
import json
from datetime import datetime
from typing import Optional, Dict, Any
import asyncio
from urllib.parse import urlparse, parse_qs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('instagram_downloader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Instagram Video Downloader API",
    description="Download Instagram videos without cookies using multiple methods",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range", "Content-Type", "Accept-Ranges"]
)

# Create downloads directory
download_dir = os.path.join(os.getcwd(), 'downloads')
os.makedirs(download_dir, exist_ok=True)

def extract_instagram_shortcode(url: str) -> Optional[str]:
    """Extract Instagram shortcode from URL"""
    patterns = [
        r'instagram\.com/(?:p|reel|tv|reels)/([\w-]+)',
        r'instagram\.com/[\w.]+/(?:p|reel)/([\w-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_with_requests(url: str, shortcode: str) -> Dict[str, Any]:
    """
    Method 1: Direct API scraping without authentication
    Uses Instagram's public endpoints
    """
    try:
        logger.info(f"Attempting direct API method for {shortcode}")

        # Instagram's public API endpoint (no auth required for public posts)
        api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'X-IG-App-ID': '936619743392459',
            'X-ASBD-ID': '198387',
            'X-IG-WWW-Claim': '0',
            'Origin': 'https://www.instagram.com',
            'Referer': f'https://www.instagram.com/p/{shortcode}/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }

        response = requests.get(api_url, headers=headers, timeout=30)

        if response.status_code == 200:
            try:
                data = response.json()

                # Navigate through the JSON structure
                if 'items' in data and len(data['items']) > 0:
                    media = data['items'][0]
                elif 'graphql' in data:
                    media = data['graphql']['shortcode_media']
                else:
                    return None

                # Extract video URL
                video_url = None
                if 'video_url' in media:
                    video_url = media['video_url']
                elif 'video_versions' in media and len(media['video_versions']) > 0:
                    video_url = media['video_versions'][0]['url']

                if video_url:
                    # Get caption
                    caption = ""
                    if 'caption' in media and media['caption']:
                        caption = media['caption'].get('text', '')
                    elif 'edge_media_to_caption' in media:
                        edges = media['edge_media_to_caption'].get('edges', [])
                        if edges:
                            caption = edges[0]['node']['text']

                    # Get author
                    author = media.get('owner', {}).get('username', 'Unknown')

                    # Download video
                    video_response = requests.get(video_url, headers=headers, stream=True, timeout=60)
                    if video_response.status_code == 200:
                        filename = f"{shortcode}.mp4"
                        filepath = os.path.join(download_dir, filename)

                        with open(filepath, 'wb') as f:
                            for chunk in video_response.iter_content(chunk_size=8192):
                                f.write(chunk)

                        logger.info(f"Successfully downloaded via direct API: {filename}")
                        return {
                            'success': True,
                            'filepath': filepath,
                            'filename': filename,
                            'title': f'Instagram Video - {shortcode}',
                            'author': author,
                            'caption': caption or 'No caption available',
                            'method': 'direct_api'
                        }
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON from direct API")

    except Exception as e:
        logger.error(f"Direct API method failed: {str(e)}")

    return None

def download_with_oembed(url: str, shortcode: str) -> Dict[str, Any]:
    """
    Method 2: Use Instagram's oEmbed endpoint (public, no auth)
    """
    try:
        logger.info(f"Attempting oEmbed method for {shortcode}")

        oembed_url = f"https://api.instagram.com/oembed/?url={url}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(oembed_url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()

            # oEmbed gives us metadata, we still need the video
            # Try to extract from thumbnail or use another method
            logger.info(f"Got oEmbed data: {data.get('title', 'No title')}")

    except Exception as e:
        logger.error(f"oEmbed method failed: {str(e)}")

    return None

def download_with_ytdlp_public(url: str, shortcode: str) -> Dict[str, Any]:
    """
    Method 3: yt-dlp with public-only settings (no cookies)
    """
    try:
        logger.info(f"Attempting yt-dlp public method for {shortcode}")

        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(download_dir, f'{shortcode}.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'nocheckcertificate': True,
            'merge_output_format': 'mp4',
            # Don't use cookies
            'cookiefile': None,
            # More aggressive headers
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0',
            },
            # Retry settings
            'retries': 3,
            'fragment_retries': 3,
            # Additional options
            'geo_bypass': True,
            'age_limit': None,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            video_id = info.get('id', shortcode)
            ext = info.get('ext', 'mp4')
            filename = f"{video_id}.{ext}"
            filepath = os.path.join(download_dir, filename)

            if os.path.exists(filepath):
                return {
                    'success': True,
                    'filepath': filepath,
                    'filename': filename,
                    'title': info.get('title', 'Instagram Video'),
                    'author': info.get('uploader', 'Unknown'),
                    'caption': info.get('description', 'No caption available'),
                    'thumbnail': info.get('thumbnail', ''),
                    'method': 'ytdlp_public'
                }

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.warning(f"yt-dlp public method failed: {error_msg}")

    except Exception as e:
        logger.error(f"yt-dlp public method error: {str(e)}")

    return None

def download_with_instaloader_like(url: str, shortcode: str) -> Dict[str, Any]:
    """
    Method 4: Scrape HTML directly (public posts only)
    """
    try:
        logger.info(f"Attempting HTML scraping for {shortcode}")

        post_url = f"https://www.instagram.com/p/{shortcode}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        response = requests.get(post_url, headers=headers, timeout=30)

        if response.status_code == 200:
            html = response.text

            # Try to find JSON data in script tags
            pattern = r'<script type="application/ld\+json">({.*?})</script>'
            matches = re.findall(pattern, html, re.DOTALL)

            for match in matches:
                try:
                    data = json.loads(match)
                    if 'video' in data and isinstance(data['video'], dict):
                        video_url = data['video'].get('contentUrl')
                        if video_url:
                            # Download the video
                            video_response = requests.get(video_url, headers=headers, stream=True, timeout=60)
                            if video_response.status_code == 200:
                                filename = f"{shortcode}.mp4"
                                filepath = os.path.join(download_dir, filename)

                                with open(filepath, 'wb') as f:
                                    for chunk in video_response.iter_content(chunk_size=8192):
                                        f.write(chunk)

                                logger.info(f"Successfully downloaded via HTML scraping: {filename}")
                                return {
                                    'success': True,
                                    'filepath': filepath,
                                    'filename': filename,
                                    'title': data.get('caption', 'Instagram Video'),
                                    'author': data.get('author', {}).get('name', 'Unknown'),
                                    'caption': data.get('caption', 'No caption available'),
                                    'method': 'html_scraping'
                                }
                except json.JSONDecodeError:
                    continue

    except Exception as e:
        logger.error(f"HTML scraping method failed: {str(e)}")

    return None

def clean_old_downloads(max_age_hours: int = 24):
    """Clean up old downloaded files"""
    try:
        current_time = datetime.now().timestamp()
        for filename in os.listdir(download_dir):
            file_path = os.path.join(download_dir, filename)
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > (max_age_hours * 3600):
                    os.remove(file_path)
                    logger.info(f"Cleaned up old file: {filename}")
    except Exception as e:
        logger.error(f"Error cleaning downloads: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    logger.info("Instagram Downloader API v2.0 starting up...")
    logger.info("Cookie-less mode enabled - trying multiple methods")
    clean_old_downloads()

@app.post("/download")
async def download(request: Request):
    """
    Download Instagram video using multiple fallback methods (no cookies required)
    """
    try:
        data = await request.json()
        url = data.get("url")

        if not url:
            return JSONResponse(
                content={"error": "No URL provided"},
                status_code=400
            )

        if 'instagram.com' not in url:
            return JSONResponse(
                content={"error": "Invalid Instagram URL"},
                status_code=400
            )

        logger.info(f"Processing download request for: {url}")

        # Extract shortcode
        shortcode = extract_instagram_shortcode(url)
        if not shortcode:
            return JSONResponse(
                content={"error": "Could not extract video ID from URL"},
                status_code=400
            )

        logger.info(f"Extracted shortcode: {shortcode}")

        # Try multiple methods in order
        methods = [
            ("Direct API", lambda: download_with_requests(url, shortcode)),
            ("HTML Scraping", lambda: download_with_instaloader_like(url, shortcode)),
            ("yt-dlp (Public)", lambda: download_with_ytdlp_public(url, shortcode)),
            ("oEmbed", lambda: download_with_oembed(url, shortcode)),
        ]

        result = None
        for method_name, method_func in methods:
            logger.info(f"Trying method: {method_name}")
            try:
                result = method_func()
                if result and result.get('success'):
                    logger.info(f"✅ Success with method: {method_name}")
                    break
            except Exception as e:
                logger.error(f"Method {method_name} failed: {str(e)}")
                continue

        if result and result.get('success'):
            file_size = os.path.getsize(result['filepath'])

            return JSONResponse(content={
                "success": True,
                "video": f"/downloads/{result['filename']}",
                "title": result.get('title', 'Instagram Video'),
                "author": result.get('author', 'Unknown'),
                "thumbnail": result.get('thumbnail', ''),
                "filename": result['filename'],
                "caption": result.get('caption', 'No caption available'),
                "file_size": file_size,
                "method": result.get('method', 'unknown')
            })
        else:
            return JSONResponse(
                content={
                    "error": "Unable to download video. This might be a private post, age-restricted content, or Instagram has blocked the request. Try with a different public Instagram video.",
                    "suggestion": "Make sure the Instagram post is:\n1. Public (not private account)\n2. Not age-restricted\n3. Not deleted\n4. Accessible without login in your browser"
                },
                status_code=400
            )

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return JSONResponse(
            content={"error": f"Internal server error: {str(e)}"},
            status_code=500
        )

@app.get("/downloads/{filename}")
async def serve_video(filename: str):
    """Serve video file"""
    try:
        file_path = os.path.join(download_dir, filename)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        file_size = os.path.getsize(file_path)

        return FileResponse(
            path=file_path,
            media_type='video/mp4',
            filename=filename,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache",
            }
        )

    except Exception as e:
        logger.error(f"Error serving file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "ok",
        "service": "Instagram Downloader API (Cookie-less)",
        "version": "2.0.0",
        "methods": ["direct_api", "html_scraping", "ytdlp_public", "oembed"],
        "timestamp": datetime.now().isoformat()
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Instagram Video Downloader API - Cookie-less Mode",
        "version": "2.0.0",
        "status": "running",
        "note": "Uses multiple fallback methods to download public Instagram videos without authentication"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
