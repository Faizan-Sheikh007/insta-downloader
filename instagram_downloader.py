from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import yt_dlp
import os
import re
import logging
from datetime import datetime
from typing import Optional
import asyncio

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
    description="Download Instagram videos, reels, and IGTV content",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Create downloads directory if it doesn't exist
download_dir = os.path.join(os.getcwd(), 'downloads')
os.makedirs(download_dir, exist_ok=True)

# Mount static files for serving downloaded videos
app.mount("/downloads", StaticFiles(directory=download_dir), name="downloads")

def extract_instagram_id(url: str) -> Optional[str]:
    """Extract Instagram video/reel ID from URL"""
    patterns = [
        r'instagram\.com/p/([\w-]+)',
        r'instagram\.com/reel/([\w-]+)',
        r'instagram\.com/tv/([\w-]+)',
        r'instagram\.com/reels/([\w-]+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
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
    logger.info("Instagram Downloader API starting up...")
    clean_old_downloads()

@app.post("/download")
async def download(request: Request):
    """
    Download Instagram video/reel

    Request body:
    {
        "url": "https://www.instagram.com/reel/xxxxx/"
    }
    """
    try:
        data = await request.json()
        url = data.get("url")

        if not url:
            logger.warning("Download request received without URL")
            return JSONResponse(
                content={"error": "No URL provided"},
                status_code=400
            )

        # Validate Instagram URL
        if 'instagram.com' not in url:
            logger.warning(f"Invalid Instagram URL received: {url}")
            return JSONResponse(
                content={"error": "Invalid Instagram URL. Please provide a valid Instagram video, reel, or IGTV link."},
                status_code=400
            )

        logger.info(f"Processing download request for: {url}")

        # Configure yt-dlp options for Instagram
        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            # Instagram specific options
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            },
            # Optional: Add cookie file for better reliability
            # 'cookiefile': 'instagram_cookies.txt',
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract video info
                logger.info("Extracting video information...")
                info = ydl.extract_info(url, download=True)

                # Get video details
                video_id = info.get('id', 'video')
                ext = info.get('ext', 'mp4')
                title = info.get('title', 'Instagram Video')
                author = info.get('uploader', info.get('uploader_id', 'Unknown'))
                thumbnail = info.get('thumbnail', '')

                # Get caption with multiple fallback options
                caption = (
                    info.get('description') or
                    info.get('alt_title') or
                    info.get('title') or
                    "No caption available"
                )

                # Construct file path
                filename = f"{video_id}.{ext}"
                file_path = os.path.join(download_dir, filename)

                # Verify file exists
                if not os.path.exists(file_path):
                    logger.error(f"Downloaded file not found: {file_path}")
                    return JSONResponse(
                        content={"error": "Video download failed - file not found after download"},
                        status_code=500
                    )

                logger.info(f"Successfully downloaded: {filename}")

                # Return video info and download URL
                return JSONResponse(content={
                    "success": True,
                    "video": f"/downloads/{filename}",
                    "title": title,
                    "author": author,
                    "thumbnail": thumbnail,
                    "filename": filename,
                    "caption": caption
                })

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"yt-dlp download error: {error_msg}")

            if "Private" in error_msg or "login required" in error_msg.lower():
                return JSONResponse(
                    content={"error": "This video is private or requires login. Only public Instagram videos can be downloaded."},
                    status_code=400
                )
            elif "Video unavailable" in error_msg or "not available" in error_msg.lower():
                return JSONResponse(
                    content={"error": "Video not found or unavailable. It may have been deleted or the link is incorrect."},
                    status_code=404
                )
            elif "age" in error_msg.lower() or "restricted" in error_msg.lower():
                return JSONResponse(
                    content={"error": "This content is age-restricted and cannot be downloaded without authentication."},
                    status_code=400
                )
            elif "HTTP Error 429" in error_msg or "Too Many Requests" in error_msg:
                return JSONResponse(
                    content={"error": "Instagram is rate-limiting requests. Please try again in a few minutes."},
                    status_code=429
                )
            else:
                return JSONResponse(
                    content={"error": f"Download failed: {error_msg}"},
                    status_code=400
                )

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return JSONResponse(
            content={"error": f"Internal server error. Please try again later."},
            status_code=500
        )

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Instagram Downloader API",
        "version": "1.0.0",
        "downloads_dir": download_dir,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Instagram Video Downloader API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "/download": {
                "method": "POST",
                "description": "Download Instagram video/reel",
                "body": {"url": "Instagram video URL"}
            },
            "/health": {
                "method": "GET",
                "description": "Check service health"
            },
            "/downloads/{filename}": {
                "method": "GET",
                "description": "Retrieve downloaded file"
            },
            "/cleanup": {
                "method": "POST",
                "description": "Clean up old downloads"
            }
        }
    }

@app.post("/cleanup")
async def manual_cleanup():
    """Manually trigger cleanup of old downloads"""
    try:
        clean_old_downloads(max_age_hours=1)
        return {"status": "success", "message": "Cleanup completed"}
    except Exception as e:
        logger.error(f"Manual cleanup failed: {str(e)}")
        return JSONResponse(
            content={"error": "Cleanup failed"},
            status_code=500
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
