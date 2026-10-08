import os
import glob
import re
import time
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/cache/clouds"))
NOAA_FTP_HOST = "public.sos.noaa.gov"
NOAA_MEDIUM_DIR = "rt/sat/linear/medium"
FRAME_PATTERN = re.compile(r"linear_rgb_cyl_(\d{8})_(\d{4})\.jpg")

class NOAACloudService:
    """
    Manages real-time global satellite cloud composite data from NOAA Science On a Sphere (SOS).
    Fetches real-time cylindrical equirectangular IR frames (updated ~every 10 minutes),
    derives transparency alpha masks, and caches processed textures for WebGL rendering.
    """

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.latest_frame_id: Optional[str] = None
        self.latest_timestamp_str: Optional[str] = None
        self.latest_iso_time: Optional[str] = None
        self.last_fetch_attempt: float = 0.0
        self.last_successful_fetch: float = 0.0
        self.is_fetching: bool = False

    def list_remote_frames(self) -> List[str]:
        """
        Lists available real-time cylindrical JPEG frames from NOAA SOS FTP.
        Uses curl with a strict timeout for maximum resilience against network stalls.
        """
        url = f"ftp://{NOAA_FTP_HOST}/{NOAA_MEDIUM_DIR}/"
        try:
            res = subprocess.run(
                ["curl", "-s", "--connect-timeout", "10", "-m", "20", url],
                capture_output=True,
                text=True,
                timeout=25
            )
            if res.returncode != 0:
                logger.warning(f"curl list failed (exit {res.returncode}): {res.stderr[:200]}")
                return []

            lines = res.stdout.splitlines()
            frames = []
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                filename = parts[-1]
                if FRAME_PATTERN.match(filename):
                    frames.append(filename)
            frames.sort()
            return frames
        except Exception as e:
            logger.error(f"Error listing NOAA FTP frames: {e}")
            return []

    def download_frame(self, filename: str) -> Optional[str]:
        """
        Downloads a specific frame from NOAA SOS FTP into local cache.
        Returns the local path if successful.
        """
        dest_raw = os.path.join(self.cache_dir, filename)
        if os.path.exists(dest_raw) and os.path.getsize(dest_raw) > 100000:
            return dest_raw

        url = f"ftp://{NOAA_FTP_HOST}/{NOAA_MEDIUM_DIR}/{filename}"
        dest_tmp = dest_raw + ".tmp"
        try:
            logger.info(f"Downloading NOAA satellite cloud frame: {filename}")
            res = subprocess.run(
                ["curl", "-s", "--connect-timeout", "12", "-m", "35", "-o", dest_tmp, url],
                capture_output=True,
                text=True,
                timeout=40
            )
            if res.returncode == 0 and os.path.exists(dest_tmp) and os.path.getsize(dest_tmp) > 100000:
                os.replace(dest_tmp, dest_raw)
                logger.info(f"Successfully downloaded {filename} ({os.path.getsize(dest_raw)} bytes)")
                return dest_raw
            else:
                if os.path.exists(dest_tmp):
                    os.remove(dest_tmp)
                logger.warning(f"Failed to download {filename}: exit={res.returncode}")
                return None
        except Exception as e:
            logger.error(f"Exception downloading {filename}: {e}")
            if os.path.exists(dest_tmp):
                try:
                    os.remove(dest_tmp)
                except Exception:
                    pass
            return None

    def process_transparency(self, raw_jpg_path: str) -> Optional[str]:
        """
        Converts the raw NOAA infrared cylindrical composite into an RGBA PNG with alpha transparency.
        
        Algorithm:
        1. Calculates perceived luminance from RGB.
        2. Measures chroma (color saturation: max(RGB) - min(RGB)) to distinguish
           clear ocean (blue) and land deserts/vegetation from neutral white/gray clouds.
        3. Generates smoothstep alpha opacity:
           - Clear background (low lum or high chroma) -> alpha = 0.
           - Cloud decks and convective cores (high lum, low chroma) -> alpha up to 255.
        4. Retains pure soft cloud white RGB so Three.js shaders can apply dynamic
           sunlight, twilight terminator peach tint, and atmospheric scattering.
        """
        base_name = os.path.basename(raw_jpg_path)
        png_name = base_name.replace(".jpg", "_transparent.png")
        dest_png = os.path.join(self.cache_dir, png_name)

        if os.path.exists(dest_png) and os.path.getsize(dest_png) > 200000:
            return dest_png

        try:
            logger.info(f"Processing cloud transparency for {base_name}...")
            img = Image.open(raw_jpg_path).convert("RGB")
            arr = np.array(img, dtype=np.float32)

            r = arr[:, :, 0]
            g = arr[:, :, 1]
            b = arr[:, :, 2]

            # Perceived luminance (Rec.601)
            lum = 0.299 * r + 0.587 * g + 0.114 * b

            # Chroma / saturation measure (clouds are neutral gray/white; surface is colored)
            chroma = np.max(arr, axis=2) - np.min(arr, axis=2)

            # Opacity transfer curve
            # 1. Base opacity from luminance above clear background (lum > 65)
            lum_factor = np.clip((lum - 62.0) / 135.0, 0.0, 1.0)

            # 2. Suppress surface coloring (desert sands, blue coastal oceans, green forests)
            chroma_suppress = np.clip(1.0 - (chroma - 8.0) / 24.0, 0.0, 1.0)

            # 3. Dense storm core override (bright convective cloud tops are cold and bright white)
            storm_override = np.clip((lum - 195.0) / 45.0, 0.0, 1.0)

            # Composite alpha
            alpha_norm = np.clip(lum_factor * chroma_suppress + storm_override, 0.0, 1.0)
            
            # Feather curve for smooth natural clouds
            alpha_norm = np.power(alpha_norm, 1.15)
            alpha = (alpha_norm * 255.0).astype(np.uint8)

            # Soft white cloud RGB
            rgb = np.ones((img.height, img.width, 3), dtype=np.uint8) * 255
            rgba = np.dstack([rgb, alpha])

            out_img = Image.fromarray(rgba, mode="RGBA")
            dest_tmp = dest_png + ".tmp"
            out_img.save(dest_tmp, format="PNG", optimize=True)
            os.replace(dest_tmp, dest_png)

            # Also create/update latest_transparent.png symlink or copy
            latest_copy = os.path.join(self.cache_dir, "latest_transparent.png")
            try:
                if os.path.exists(latest_copy):
                    os.remove(latest_copy)
                import shutil
                shutil.copy2(dest_png, latest_copy)
            except Exception as e:
                logger.warning(f"Could not update latest_transparent.png copy: {e}")

            logger.info(f"Processed transparent cloud PNG saved to {dest_png} ({os.path.getsize(dest_png)} bytes)")
            return dest_png
        except Exception as e:
            logger.error(f"Error processing cloud transparency for {raw_jpg_path}: {e}")
            return None

    def fetch_latest_frame(self) -> Optional[str]:
        """
        Fetches the newest NOAA cloud frame, downloads it, processes transparency,
        and returns the processed PNG path.
        """
        if self.is_fetching:
            return self.get_latest_processed_path()

        self.is_fetching = True
        self.last_fetch_attempt = time.time()
        try:
            frames = self.list_remote_frames()
            if not frames:
                logger.warning("No remote NOAA cloud frames found; falling back to local cache")
                return self.get_latest_processed_path()

            newest_frame = frames[-1]
            match = FRAME_PATTERN.match(newest_frame)
            if match:
                date_str, time_str = match.groups()
                self.latest_timestamp_str = f"{date_str}_{time_str}"
                try:
                    dt = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                    self.latest_iso_time = dt.isoformat()
                except Exception:
                    self.latest_iso_time = datetime.now(timezone.utc).isoformat()
            
            self.latest_frame_id = newest_frame

            raw_path = self.download_frame(newest_frame)
            if not raw_path:
                return self.get_latest_processed_path()

            processed_path = self.process_transparency(raw_path)
            if processed_path:
                self.last_successful_fetch = time.time()
                # Clean up old cached frames older than 48 hours to conserve disk
                self._prune_old_cache()
                return processed_path
            return self.get_latest_processed_path()
        finally:
            self.is_fetching = False

    def get_latest_processed_path(self) -> Optional[str]:
        """
        Returns the path to the latest available processed transparent PNG.
        Checks memory, cache directory for newest matching file, or latest_transparent.png.
        """
        latest_file = os.path.join(self.cache_dir, "latest_transparent.png")
        if os.path.exists(latest_file) and os.path.getsize(latest_file) > 100000:
            return latest_file

        processed_files = sorted(glob.glob(os.path.join(self.cache_dir, "*_transparent.png")))
        if processed_files:
            return processed_files[-1]

        return None

    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns real-time satellite clouds status, NOAA SOS provenance, and valid timestamp.
        """
        processed_path = self.get_latest_processed_path()
        has_data = processed_path is not None and os.path.exists(processed_path)
        
        # Determine timestamp from filename or file modification
        timestamp_iso = self.latest_iso_time
        frame_id = self.latest_frame_id

        if not timestamp_iso and processed_path:
            base = os.path.basename(processed_path)
            match = re.search(r"(\d{8})_(\d{4})", base)
            if match:
                d_str, t_str = match.groups()
                try:
                    dt = datetime.strptime(f"{d_str}{t_str}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                    timestamp_iso = dt.isoformat()
                    frame_id = f"linear_rgb_cyl_{d_str}_{t_str}.jpg"
                except Exception:
                    pass

        if not timestamp_iso:
            timestamp_iso = datetime.now(timezone.utc).isoformat()

        age_seconds = time.time() - self.last_successful_fetch if self.last_successful_fetch > 0 else 0
        is_live = has_data and (age_seconds < 3600 or self.last_successful_fetch == 0)

        return {
            "status": "LIVE" if is_live else "CACHED",
            "dataset": "NOAA Clouds - Real-time (Science On a Sphere)",
            "source_agency": "NOAA / Aviation Weather Center",
            "satellites": ["GOES-West (136.9°W)", "GOES-East (75°W)", "Meteosat-10 (0°)", "Meteosat-9 (45.5°E)", "Himawari (140.7°E)", "Suomi-NPP & JPSS"],
            "cadence": "10 minutes",
            "resolution": "2048x1024",
            "projection": "Cylindrical Equirectangular",
            "timestamp": timestamp_iso,
            "frame_id": frame_id or "latest",
            "texture_url": "/api/clouds/texture/latest",
            "last_fetch_attempt": datetime.fromtimestamp(self.last_fetch_attempt, tz=timezone.utc).isoformat() if self.last_fetch_attempt else None,
            "last_successful_fetch": datetime.fromtimestamp(self.last_successful_fetch, tz=timezone.utc).isoformat() if self.last_successful_fetch else None,
            "available": has_data
        }

    def _prune_old_cache(self, keep_count: int = 12):
        """Keep only the latest N frames in cache to save disk space."""
        try:
            for pattern in ["linear_rgb_cyl_*.jpg", "linear_rgb_cyl_*_transparent.png"]:
                files = sorted(glob.glob(os.path.join(self.cache_dir, pattern)))
                if len(files) > keep_count:
                    for old_file in files[:-keep_count]:
                        try:
                            os.remove(old_file)
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Error pruning cloud cache: {e}")

# Global singleton
cloud_service = NOAACloudService()
