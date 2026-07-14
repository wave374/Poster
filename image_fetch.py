"""
image_fetch.py
Fetches anime artwork from AniList and Jikan (MyAnimeList).
Each image is tagged with its orientation: "portrait" or "landscape".
Fetches by EXACT anime ID first to avoid returning images from the wrong title.
"""
import os
import time
import requests

FANART_API_KEY = os.environ.get("FANART_API_KEY", "")

# ─── AniList exact-ID fetch ────────────────────────────────────────────────────

def _anilist_images_by_id(anilist_id: int) -> list[dict]:
    """Fetch banner + cover images for a specific AniList media ID."""
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        bannerImage
        coverImage { extraLarge large medium }
      }
    }
    """
    results = []
    try:
        r = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"id": anilist_id}},
            timeout=15,
        )
        if r.status_code == 200:
            media = r.json().get("data", {}).get("Media") or {}
            # Banner = landscape
            if media.get("bannerImage"):
                results.append({"url": media["bannerImage"], "orientation": "landscape"})
            # Cover = portrait
            cover = media.get("coverImage") or {}
            for key in ("extraLarge", "large", "medium"):
                if cover.get(key):
                    results.append({"url": cover[key], "orientation": "portrait"})
                    break
    except Exception:
        pass
    return results


def _anilist_images_by_title(title: str) -> list[dict]:
    """Fallback: fetch from the top AniList result only (no ID available)."""
    query = """
    query ($search: String) {
      Page(perPage: 1) {
        media(search: $search, type: ANIME) {
          bannerImage
          coverImage { extraLarge large medium }
        }
      }
    }
    """
    results = []
    try:
        r = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"search": title}},
            timeout=15,
        )
        if r.status_code == 200:
            items = r.json().get("data", {}).get("Page", {}).get("media", [])
            for item in items[:1]:   # only first (closest match)
                if item.get("bannerImage"):
                    results.append({"url": item["bannerImage"], "orientation": "landscape"})
                cover = item.get("coverImage") or {}
                for key in ("extraLarge", "large", "medium"):
                    if cover.get(key):
                        results.append({"url": cover[key], "orientation": "portrait"})
                        break
    except Exception:
        pass
    return results


# ─── Jikan (MyAnimeList) fetch ─────────────────────────────────────────────────

def _jikan_images_by_id(mal_id: int) -> list[dict]:
    """Fetch images for a specific MAL ID — covers only (portrait)."""
    results = []
    for attempt in range(3):
        try:
            r = requests.get(
                f"https://api.jikan.moe/v4/anime/{mal_id}",
                timeout=15,
                headers={"User-Agent": "AnimePosterBot/1.0"},
            )
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code == 200:
                data = r.json().get("data", {})
                images = data.get("images", {})
                for fmt in ("jpg", "webp"):
                    imgs = images.get(fmt, {})
                    for size in ("large_image_url", "image_url", "small_image_url"):
                        if imgs.get(size):
                            results.append({"url": imgs[size], "orientation": "portrait"})
                            break
                break
        except Exception:
            time.sleep(2)
    return results


def _jikan_images_by_title(title: str) -> list[dict]:
    """Fallback: fetch from top Jikan search result only."""
    results = []
    for attempt in range(3):
        try:
            r = requests.get(
                "https://api.jikan.moe/v4/anime",
                params={"q": title, "limit": 1},
                timeout=15,
                headers={"User-Agent": "AnimePosterBot/1.0"},
            )
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code == 200:
                items = r.json().get("data", [])
                for item in items[:1]:
                    images = item.get("images", {})
                    for fmt in ("jpg", "webp"):
                        imgs = images.get(fmt, {})
                        for size in ("large_image_url", "image_url"):
                            if imgs.get(size):
                                results.append({"url": imgs[size], "orientation": "portrait"})
                                break
                break
        except Exception:
            time.sleep(2)
    return results


# ─── Fanart.tv (optional) ──────────────────────────────────────────────────────

def _fanart_images(mal_id: int) -> list[dict]:
    """Fetch from Fanart.tv if API key is set (uses TVDB ID via mal_id attempt)."""
    if not mal_id or not FANART_API_KEY:
        return []
    results = []
    try:
        r = requests.get(
            f"https://webservice.fanart.tv/v3/tv/{mal_id}",
            params={"api_key": FANART_API_KEY},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            for entry in data.get("showbackground", []):
                if entry.get("url"):
                    results.append({"url": entry["url"], "orientation": "landscape"})
            for entry in data.get("tvposter", []):
                if entry.get("url"):
                    results.append({"url": entry["url"], "orientation": "portrait"})
            for entry in data.get("tvbanner", []):
                if entry.get("url"):
                    results.append({"url": entry["url"], "orientation": "landscape"})
    except Exception:
        pass
    return results


# ─── Main entry point ──────────────────────────────────────────────────────────

def fetch_official_images(
    title: str,
    anilist_id: int = None,
    mal_id: int = None,
) -> list[dict]:
    """
    Returns a deduplicated list of {"url": str, "orientation": "portrait"|"landscape"}
    for exactly the specified anime.
    - Uses anilist_id / mal_id for precise fetching when available.
    - Falls back to title search (first result only) otherwise.
    """
    raw: list[dict] = []

    if anilist_id:
        raw.extend(_anilist_images_by_id(anilist_id))
    else:
        raw.extend(_anilist_images_by_title(title))

    if mal_id:
        raw.extend(_jikan_images_by_id(mal_id))
        raw.extend(_fanart_images(mal_id))
    else:
        raw.extend(_jikan_images_by_title(title))

    # Deduplicate by URL while preserving insertion order
    seen: set[str] = set()
    deduped: list[dict] = []
    for img in raw:
        url = img.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(img)
    return deduped


def download_image(url: str) -> bytes | None:
    """Download an image URL and return raw bytes, or None on failure."""
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None
