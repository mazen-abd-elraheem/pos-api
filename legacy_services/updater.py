"""
services/updater.py - Website-based auto-updater for SkyPDV POS

Checks the SkyPDV website for new versions via a version.json manifest,
downloads the .exe installer, and applies it using a batch script that
launches the installer after the app exits.
"""

import os
import sys
import json
import shutil
import logging
import tempfile
import zipfile
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# Configuration — point to YOUR website
# ══════════════════════════════════════════════════════════════════

# ▸ Change this to your actual website domain
WEBSITE_BASE_URL = "https://cyan-anteater-840173.hostingersite.com"

# The updater fetches this JSON file to know the latest version.
# Upload it to: https://yoursite.com/assets/downloads/version.json
VERSION_JSON_URL = f"{WEBSITE_BASE_URL}/assets/downloads/version.json"

CURRENT_VERSION = "1.0.2"  # Kept in sync with pyproject.toml


# Try to read version from pyproject.toml at runtime
def _read_version_from_pyproject():
    """Read version from pyproject.toml if available."""
    try:
        # Try multiple possible locations
        candidates = [
            os.path.join(os.path.dirname(__file__), '..', 'pyproject.toml'),
            os.path.join(os.path.dirname(sys.executable), 'pyproject.toml') if getattr(sys, 'frozen', False) else None,
        ]
        for path in candidates:
            if path and os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip().startswith('version'):
                            # Parse: version = "1.0.0"
                            return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        logger.debug(f"Could not read version from pyproject.toml: {e}")
    return None


def get_current_version() -> str:
    """Get the current application version."""
    return _read_version_from_pyproject() or CURRENT_VERSION


def _parse_version(version_str: str) -> tuple:
    """Parse version string like 'v1.2.3' or '1.2.3' into a tuple of ints."""
    v = version_str.strip().lstrip('v').lstrip('V')
    try:
        parts = v.split('.')
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _is_newer(remote_version: str, local_version: str) -> bool:
    """Check if remote version is newer than local version."""
    return _parse_version(remote_version) > _parse_version(local_version)


# ══════════════════════════════════════════════════════════════════
# Check for Updates (from your website)
# ══════════════════════════════════════════════════════════════════

def check_for_update() -> dict:
    """
    Check the SkyPDV website for a new version.
    
    Fetches VERSION_JSON_URL which should contain:
    {
        "version": "1.0.1",
        "download_url": "assets/downloads/SkyPDV_Setup_1.0.1.exe",
        "release_notes": "Bug fixes and improvements",
        "published_at": "2026-07-11"
    }
    
    Returns:
        dict with keys:
        - available (bool): True if update is available
        - version (str): Latest version
        - download_url (str): Full URL to download the .exe
        - release_notes (str): What's new
        - published_at (str): Release date
        - error (str|None): Error message if check failed
    """
    import httpx
    
    result = {
        'available': False,
        'version': '',
        'download_url': '',
        'release_notes': '',
        'published_at': '',
        'error': None,
    }
    
    try:
        current = get_current_version()
        logger.info(f"Checking for updates... Current version: {current}")
        
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.get(
                VERSION_JSON_URL,
                headers={
                    'User-Agent': 'SkyPDV-Updater',
                    'Cache-Control': 'no-cache',
                }
            )
        
        if response.status_code == 404:
            result['error'] = "Version info not found on server."
            return result
            
        if response.status_code != 200:
            result['error'] = f"Server error: {response.status_code}"
            return result
        
        data = response.json()
        tag = data.get('version', '')
        
        if not tag:
            result['error'] = "No version found in server response."
            return result
        
        result['version'] = tag
        result['release_notes'] = data.get('release_notes', '') or 'No release notes.'
        result['published_at'] = data.get('published_at', '')
        
        # Build the full download URL
        # The JSON can contain a relative path like "assets/downloads/SkyPDV_Setup_1.0.1.exe"
        # or an absolute URL like "https://..."
        dl = data.get('download_url', '')
        if dl and not dl.startswith('http'):
            # It's a relative path — prepend the website base URL
            dl = f"{WEBSITE_BASE_URL}/{dl.lstrip('/')}"
        
        result['download_url'] = dl
        
        # Compare versions
        if _is_newer(tag, current):
            result['available'] = True
            logger.info(f"Update available: {current} → {tag}")
        else:
            logger.info(f"Already on latest version: {current}")
        
        return result
        
    except Exception as e:
        # Silently handle - don't spam the log on every failed check
        result['error'] = f"Update check failed: {str(e)}"
        logger.debug(f"Update check error: {e}")
        return result


# ══════════════════════════════════════════════════════════════════
# Download Update
# ══════════════════════════════════════════════════════════════════

def download_update(url: str, progress_callback=None) -> str:
    """
    Download update file from the website.
    
    Args:
        url: Full download URL for the .exe or .zip
        progress_callback: Optional function(downloaded_bytes, total_bytes) for progress
        
    Returns:
        Path to the downloaded file, or empty string on failure
    """
    import httpx
    
    if not url:
        logger.error("No download URL provided")
        return ''
    
    try:
        # Create temp directory for download
        temp_dir = os.path.join(tempfile.gettempdir(), 'skypdv_update')
        os.makedirs(temp_dir, exist_ok=True)
        
        # Determine file extension from URL
        url_path = url.lower().split('?')[0]
        if url_path.endswith('.exe'):
            ext = '.exe'
        elif url_path.endswith('.zip'):
            ext = '.zip'
        else:
            ext = '.exe'  # Default to exe for your setup
        
        file_path = os.path.join(temp_dir, f'skypdv_update{ext}')
        
        logger.info(f"Downloading update from: {url}")
        
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            with client.stream('GET', url, headers={'User-Agent': 'SkyPDV-Updater'}) as response:
                if response.status_code != 200:
                    logger.error(f"Download failed with status: {response.status_code}")
                    return ''
                
                total = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            try:
                                progress_callback(downloaded, total)
                            except Exception:
                                pass
        
        file_size = os.path.getsize(file_path)
        logger.info(f"Download complete: {file_size / (1024*1024):.1f} MB → {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return ''


# ══════════════════════════════════════════════════════════════════
# Apply Update (self-replacement via batch script)
# ══════════════════════════════════════════════════════════════════

def get_app_dir() -> str:
    """Get the directory where the current app is installed."""
    if getattr(sys, 'frozen', False):
        # Running as a packaged exe (flet build / PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Running as Python script
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def apply_update(file_path: str) -> bool:
    """
    Apply a downloaded update.
    
    For .exe: Launches the Inno Setup installer silently after the app exits.
    For .zip: Extracts and copies files over the old ones.
    
    Args:
        file_path: Path to the downloaded .exe or .zip
        
    Returns:
        True if the update script was launched successfully
    """
    if not file_path or not os.path.exists(file_path):
        logger.error("Update file not found")
        return False
    
    pid = os.getpid()
    bat_path = os.path.join(tempfile.gettempdir(), 'skypdv_updater.bat')
    
    # ── .EXE installer path ──────────────────────────────────────
    if file_path.lower().endswith('.exe'):
        try:
            bat_content = f'''@echo off
title SkyPDV Updater
echo ============================================
echo   SkyPDV Auto-Updater
echo ============================================
echo.
echo Waiting for SkyPDV to close...

:wait_loop
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait_loop
)

echo SkyPDV closed. Launching installer...
timeout /t 2 /nobreak >NUL

start "" /wait "{file_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

echo Cleaning up...
del "{file_path}" 2>NUL

echo Done! This window will close in 3 seconds...
timeout /t 3 /nobreak >NUL

del "%~f0" 2>NUL
exit /b 0
'''
            with open(bat_path, 'w', encoding='utf-8') as f:
                f.write(bat_content)
            
            logger.info(f"EXE update script written to: {bat_path}")
            
            subprocess.Popen(
                ['cmd', '/c', 'start', 'SkyPDV Updater', bat_path],
                shell=False,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
            )
            
            logger.info("Update script launched. App will exit now.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply EXE update: {e}")
            return False

    # ── .ZIP fallback path ───────────────────────────────────────
    try:
        app_dir = get_app_dir()
        temp_dir = os.path.join(tempfile.gettempdir(), 'skypdv_update_extract')
        
        # Clean any previous extraction
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        # Extract the zip
        logger.info(f"Extracting update to: {temp_dir}")
        with zipfile.ZipFile(file_path, 'r') as zf:
            zf.extractall(temp_dir)
        
        # Find the actual content directory (zips often have a root folder)
        extracted_items = os.listdir(temp_dir)
        source_dir = temp_dir
        
        if len(extracted_items) == 1:
            potential_root = os.path.join(temp_dir, extracted_items[0])
            if os.path.isdir(potential_root):
                contents = os.listdir(potential_root)
                if any(f.lower() in ('skypdv.exe', 'main.py', 'flutter_windows.dll') for f in contents):
                    source_dir = potential_root
        
        # Determine the exe name
        exe_name = os.path.basename(sys.executable) if getattr(sys, 'frozen', False) else 'skypdv.exe'
        exe_path = os.path.join(app_dir, exe_name)
        
        bat_content = f'''@echo off
title SkyPDV Updater
echo ============================================
echo   SkyPDV Auto-Updater
echo ============================================
echo.
echo Waiting for SkyPDV to close...

:wait_loop
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait_loop
)

echo SkyPDV closed. Applying update...
timeout /t 2 /nobreak >NUL

echo Copying new files...
xcopy /E /Y /I /Q "{source_dir}\\*" "{app_dir}\\"
if errorlevel 1 (
    echo ERROR: Failed to copy update files!
    echo Press any key to exit...
    pause >NUL
    exit /b 1
)

echo Update applied successfully!
echo.

echo Cleaning up temp files...
rmdir /S /Q "{temp_dir}" 2>NUL
del "{file_path}" 2>NUL

echo Restarting SkyPDV...
timeout /t 1 /nobreak >NUL
start "" "{exe_path}"

echo Done! This window will close in 3 seconds...
timeout /t 3 /nobreak >NUL

del "%~f0" 2>NUL
exit /b 0
'''
        
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(bat_content)
        
        logger.info(f"ZIP update script written to: {bat_path}")
        
        subprocess.Popen(
            ['cmd', '/c', 'start', 'SkyPDV Updater', bat_path],
            shell=False,
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
        )
        
        logger.info("Update script launched. App will exit now.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to apply update: {e}")
        return False


def cleanup_update_temp():
    """Clean up any leftover temp files from previous updates."""
    try:
        temp_dirs = [
            os.path.join(tempfile.gettempdir(), 'skypdv_update'),
            os.path.join(tempfile.gettempdir(), 'skypdv_update_extract'),
        ]
        for d in temp_dirs:
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
        
        bat_path = os.path.join(tempfile.gettempdir(), 'skypdv_updater.bat')
        if os.path.exists(bat_path):
            try:
                os.remove(bat_path)
            except Exception:
                pass
    except Exception:
        pass
