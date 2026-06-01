"""Playwright-based scraper for venue channels."""
import asyncio
import os
import re
import urllib.parse
from typing import Optional
import httpx
from playwright.async_api import async_playwright, Page

# ── Exclusion list for Autres canaux auto-detection ─────────────────────────
# Sites we never audit as "Autres canaux" (social media, SaaS already covered, etc.)
EXCLUSION_DOMAINS = {
    # Social media (audited separately)
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "tiktok.com", "youtube.com", "linkedin.com", "snapchat.com",
    # Search engines & maps
    "google.com", "google.fr", "bing.com", "apple.com", "waze.com",
    # Booking SaaS (covered in SaaS section)
    "thefork.com", "lafourchette.com", "zenchef.com", "opentable.com",
    "resmio.com", "dish.co", "covermanager.com", "uniiti.com",
    "sevenrooms.com", "restoo.fr", "guestonline.io",
    # Delivery (out of scope)
    "ubereats.com", "deliveroo.fr", "justeat.fr",
    # Annuaires bar/resto spécialisés (concurrents ou hors scope)
    "timetobar.fr", "time-to-bar.fr",
    "lesbarres.fr", "les-barres.fr",
    "reserveunbar.com", "reserve-un-bar.com",
    "mistergoodbeer.com", "mister-good-beer.com",
    "kaktus.fr", "kaktusbar.fr",
    "100salles.com", "100-salles.com",
    # Joy/Privateaser already audited
    "privateaser.com", "joy.io", "prvt.re", "widget.privateaser.com",
}

# ── SaaS Individual Booking detection patterns ──────────────────────────────
SAAS_PATTERNS = {
    "TheFork":          ["thefork.com", "lafourchette.com", "module.thefork"],
    "Zenchef":          ["zenchef.com", "bookings.zenchef"],
    "CoverManager":     ["covermanager.com"],
    "Dish (Metro)":     ["dish.co", "resmio.com"],
    "Uniiti":           ["uniiti.com"],
    "OpenTable":        ["opentable.com", "otwidget.com"],
    "OKO":              ["oko.bar"],
    "Restoo":           ["restoo.fr"],
    "SevenRooms":       ["sevenrooms.com"],
    "MangezNotez":      ["mangeznotez.fr", "mangeznote.fr"],
    "1CHR":             ["1chr.fr"],
    "Eveve":            ["eveve.com"],
    "Last.app":         ["last.app"],
    "OctoTable":        ["octotable.com"],
    "BizzyBook":        ["bizzybook.com"],
    "BonsRestaurants":  ["bonsrestaurants.com"],
    "Tableo":           ["tableo.com"],
    "Solocal (PJ)":     ["solocal.com", "pagesjaunes.fr"],
    "Barestho":         ["barestho.com"],
    "e-restaurants":    ["e-restaurants.fr"],
    "ZeusManager":      ["zeusmanager.com"],
    "Guestonline":      ["guestonline.io"],
    "resOS":            ["resos.com"],
    "Overfull":         ["overfull.app"],
}

# ── Autres canaux : annuaires à vérifier automatiquement ────────────────────
AUTRES_CANAUX_TARGETS = [
    {"name": "Tripadvisor",    "domain": "tripadvisor.fr",    "search": "https://www.tripadvisor.fr/Search?q={q}"},
    {"name": "Fanzo",          "domain": "fanzo.com",         "search": "https://fanzo.com/restaurants?s={q}"},
    {"name": "Yelp",           "domain": "yelp.fr",           "search": "https://www.yelp.fr/search?find_desc={q}&find_loc=Paris"},
    {"name": "PagesJaunes",    "domain": "pagesjaunes.fr",    "search": "https://www.pagesjaunes.fr/recherche/sibling/resultats?quoiqui={q}&ou=Paris"},
    {"name": "TimeOut",        "domain": "timeout.com",       "search": "https://www.timeout.com/paris/search?q={q}"},
    {"name": "SortiraParIs",   "domain": "sortiraparis.com",  "search": "https://www.sortiraparis.com/?s={q}"},
    {"name": "Booking.com",    "domain": "booking.com",       "search": "https://www.booking.com/searchresults.fr.html?ss={q}+Paris"},
    {"name": "Mappy",          "domain": "mappy.com",         "search": "https://fr.mappy.com/#/1/M2/TSearch/S{q}+Paris/"},
    {"name": "Bonjour RATP",   "domain": "bonjour-ratp.fr",   "search": "https://www.bonjour-ratp.fr/?s={q}"},
]


async def _get_page_text(page: Page, url: str, wait_selector: Optional[str] = None) -> str:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if wait_selector:
            await page.wait_for_selector(wait_selector, timeout=5000)
        await asyncio.sleep(2)
        return await page.evaluate("document.body.innerText")
    except Exception as e:
        return f"[ERREUR SCRAPING: {e}]"


async def _get_page_html(page: Page, url: str) -> str:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        return await page.content()
    except Exception as e:
        return f"[ERREUR SCRAPING: {e}]"


def _extract_links(html: str) -> list[str]:
    return re.findall(r'href=["\']([^"\']+)["\']', html)

def _find_joy_mentions(text: str, html: str) -> list[str]:
    """Find Joy/Privateaser references in both text and HTML."""
    patterns = [
        r'https?://[^\s"\'<>]*(?:joy\.io|privateaser\.com|prvt\.re)[^\s"\'<>]*',
        r'prvt\.re/\S+',
        r'widget\.privateaser\.com/[^\s"\'<>]+',
    ]
    found = []
    for p in patterns:
        found += re.findall(p, text) + re.findall(p, html)
    return list(set(found))


async def scrape_website(url: str) -> dict:
    if not url:
        return {"available": False, "reason": "URL non fournie"}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            html = await _get_page_html(page, url)
            text = await page.evaluate("document.body.innerText")
            links = _extract_links(html)
            joy_links = _find_joy_mentions(text, html)
            email_links = [l for l in links if "mailto:" in l]
            phone_in_text = re.findall(r'(?:0[1-9])(?:[\s.\-]?\d{2}){4}', text)
            phone_mentions = re.findall(r'(?:tel:|tél\.|téléphone|appelez)[^\n<]{0,80}', text, re.IGNORECASE)
            return {
                "available": True,
                "url": url,
                "full_text": text[:8000],
                "joy_links": joy_links,
                "email_links": email_links,
                "phone_numbers_found": phone_in_text[:5],
                "phone_mentions": phone_mentions,
                "has_reservation_section": bool(re.search(r'r[ée]serv', text, re.IGNORECASE)),
                "has_privatisation_section": bool(re.search(r'privati|[ée]v[ée]nement|groupe', text, re.IGNORECASE)),
                "has_header_cta": bool(re.search(r'<header[^>]*>.*?(?:r[ée]server|r[ée]servation)', html[:5000], re.IGNORECASE | re.DOTALL)),
                "iframes_src": re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE),
            }
        finally:
            await browser.close()


async def _fetch_instagram_static(url: str) -> tuple[str, str]:
    """Try fetching Instagram with httpx + mobile UA (bypasses Playwright detection)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15) as client:
        resp = await client.get(url)
        html = resp.text
        # Extract visible text from meta tags + JSON blobs (Instagram stores bio in JSON)
        # Meta description contains the bio
        meta = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]{0,500})"', html)
        meta_desc = meta.group(1) if meta else ""
        # Also look in JSON script tags for biography
        bio_json = re.search(r'"biography"\s*:\s*"([^"]{0,500})"', html)
        biography = bio_json.group(1) if bio_json else ""
        text = meta_desc + " " + biography
        return html, text


async def scrape_instagram(url: str, linktree_url: str = "") -> dict:
    if not url:
        return {"available": False, "reason": "URL non fournie"}

    # ── Try httpx static fetch first (bypasses Playwright bot detection) ──────
    html, static_text = "", ""
    try:
        html, static_text = await _fetch_instagram_static(url)
    except Exception:
        pass

    # Check if httpx got useful content (bio/phone data)
    static_phones = re.findall(r'(?:0|\+33)\s?[1-9](?:[\s.\-]?\d{2}){4}', static_text + html)
    static_joy = _find_joy_mentions(static_text, html)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            # Expand bio "plus" button if present
            try:
                more = page.locator("xpath=//span[text()='plus' or text()='more']").first
                if await more.is_visible(timeout=2000):
                    await more.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            text = await page.evaluate("document.body.innerText")
            html = await page.content()
            # Merge httpx static data with Playwright data
            text = text + " " + static_text
            links = _extract_links(html)
            joy_links = _find_joy_mentions(text, html)
            # Detect Linktree in links or text
            linktree_links = [l for l in links if "linktree" in l or "linktr.ee" in l]
            if not linktree_url:
                linktree_url = linktree_links[0] if linktree_links else ""
                lt_match = re.search(r'https?://linktr\.ee/\S+', text)
                if lt_match and not linktree_url:
                    linktree_url = lt_match.group(0)
            # Check if linktree appears in the visible bio text
            linktree_in_bio = bool(linktree_url and "linktr" in text[:600])

            # Detect story highlights with group/event keywords (visible without login)
            highlight_labels = re.findall(r'(?:highlight|story)[^<]{0,200}(?:événement|privatisation|anniversaire|afterwork|groupe|soirée|event|party)[^<]{0,50}', html, re.IGNORECASE)
            # Also check all text for group keywords in highlight-like sections
            group_keywords_in_profile = re.findall(
                r'(?:événement|privatisation|anniversaire|afterwork|groupe|soirée|séminaire)[^\n<]{0,60}',
                text, re.IGNORECASE
            )
            bio_match = re.search(r'meta.*?description.*?content="([^"]{0,500})"', html, re.IGNORECASE)
            bio = bio_match.group(1) if bio_match else text[:500]
            post_match = re.search(r'(\d+)\s+publications?', text, re.IGNORECASE)
            # Search phone numbers in text + HTML + httpx static data (bio may be truncated)
            phone_in_text = re.findall(r'(?:0|\+33)\s?[1-9](?:[\s.\-]?\d{2}){4}', text)
            phone_in_html = re.findall(r'(?:0|\+33)\s?[1-9](?:[\s.\-]?\d{2}){4}', html)
            phone_numbers = list(set(phone_in_text + phone_in_html + static_phones))
            # Normalize: remove spaces/dots for easy comparison
            phone_normalized = [re.sub(r'[\s.\-]', '', p) for p in phone_numbers]
            return {
                "available": True,
                "url": url,
                "bio": bio,
                "full_text": text[:4000],
                "joy_links_in_bio": joy_links,
                "has_linktree": bool(linktree_url),
                "linktree_in_bio": linktree_in_bio,
                "linktree_url": linktree_url or None,
                "post_count": post_match.group(1) if post_match else None,
                "phone_numbers_found": phone_numbers,
                "phone_numbers_normalized": phone_normalized,
            }
        finally:
            await browser.close()


async def _scrape_maps_reservations(place_id: str) -> list[str]:
    """Scrape the GMB reservation links from the Google Maps place page."""
    url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)
            # Accept cookies if present
            try:
                btn = page.locator("text=Tout accepter").first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(2)
            except Exception:
                pass
            html = await page.content()
            text = await page.evaluate("document.body.innerText")
            # Extract all URLs near "Réservations" section
            reservation_section = re.search(
                r'[Rr][ée]servation[s]?.{0,2000}',
                html, re.DOTALL
            )
            links = []
            if reservation_section:
                section_html = reservation_section.group(0)
                links = re.findall(r'https?://[^\s"\'<>]+(?:privateaser|joy\.io|prvt\.re|reserve|booking)[^\s"\'<>]*', section_html)
            # Also search full page for joy/privateaser links
            all_joy = _find_joy_mentions(text, html)
            return list(set(links + all_joy))
        except Exception:
            return []
        finally:
            await browser.close()


async def scrape_gmb_places_api(venue_name: str, address: str) -> dict:
    """Fetch GMB data via Google Places API v2 (no CAPTCHA, reliable)."""
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        return {"available": False, "reason": "GOOGLE_PLACES_API_KEY non configuré"}

    async with httpx.AsyncClient() as client:
        # Places API v2 — Text Search
        resp = await client.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": (
                    "places.id,places.displayName,places.formattedAddress,"
                    "places.nationalPhoneNumber,places.websiteUri,places.types,"
                    "places.editorialSummary,places.regularOpeningHours,"
                    "places.reservable,places.goodForGroups"
                ),
                "Content-Type": "application/json",
            },
            json={"textQuery": f"{venue_name} {address}"},
            timeout=10,
        )
        places = resp.json().get("places", [])
        if not places:
            return {"available": False, "reason": f"Lieu non trouvé via Places API v2: {venue_name}"}

        place = places[0]
        phone = place.get("nationalPhoneNumber", "")
        phone_norm = re.sub(r"[\s.\-]", "", phone)
        website = place.get("websiteUri", "")
        editorial = place.get("editorialSummary", {}).get("text", "")
        types = place.get("types", [])

        joy_in_website = bool(
            website and ("joy.io" in website or "privateaser" in website or "prvt.re" in website)
        )

        place_id = place.get("id", "")

        # Step 2: Scrape the Maps page via place_id URL to get the Réservations section links
        reservation_links = []
        try:
            reservation_links = await _scrape_maps_reservations(place_id)
        except Exception:
            pass

        joy_in_reservations = any(
            "joy.io" in l or "privateaser" in l or "prvt.re" in l
            for l in reservation_links
        )
        # Count how many distinct joy/privateaser links are in reservations (doublon check)
        joy_reservation_links = [l for l in reservation_links if "joy.io" in l or "privateaser" in l or "prvt.re" in l]
        has_reservation_doublon = len(joy_reservation_links) > 1

        return {
            "available": True,
            "source": "google_places_api_v2",
            "place_id": place_id,
            "name": place.get("displayName", {}).get("text", ""),
            "address": place.get("formattedAddress", ""),
            "phone": phone,
            "phone_normalized": phone_norm,
            "website": website,
            "editorial_summary": editorial,
            "joy_in_website": joy_in_website,
            "vitrine_as_website": joy_in_website,
            "types": types,
            "is_bar_or_restaurant": any(t in types for t in ["bar", "restaurant", "night_club", "cafe"]),
            "good_for_groups": place.get("goodForGroups", False),
            "reservation_links": reservation_links,
            "joy_in_reservations": joy_in_reservations,
            "has_reservation_doublon": has_reservation_doublon,
            "joy_reservation_links": joy_reservation_links,
        }


async def scrape_gmb(url: str) -> dict:
    if not url:
        return {"available": False, "reason": "URL non fournie"}

    # Convert search URL → Maps URL for better scraping
    maps_url = url
    if "google.com/search" in url:
        q_match = re.search(r'[?&]q=([^&]+)', url)
        if q_match:
            maps_url = f"https://www.google.com/maps/search/{q_match.group(1)}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
            viewport={"width": 1280, "height": 900},
        )
        # Mask webdriver fingerprint
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        try:
            await page.goto(maps_url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(4)
            # Accept cookies if prompted
            try:
                accept = page.locator("text=Tout accepter").first
                if await accept.is_visible(timeout=2000):
                    await accept.click()
                    await asyncio.sleep(2)
            except Exception:
                pass

            text = await page.evaluate("document.body.innerText")
            html = await page.content()

            if "unusual traffic" in text.lower() or (len(text) < 300 and "captcha" in html.lower()):
                return {
                    "available": False,
                    "captcha_blocked": True,
                    "reason": "Bloqué par Google (CAPTCHA).",
                    "url": url,
                }

            joy_links = _find_joy_mentions(text, html)
            group_keywords = re.findall(
                r'(?:privatisation|privatisé|anniversaire|afterwork|groupe|[ée]v[ée]nement)[^\n]{0,80}',
                text, re.IGNORECASE
            )
            # RwG detection: Joy shown as booking partner
            joy_rwg_active = bool(re.search(r'Joy|fournis en partenariat avec Joy', text, re.IGNORECASE))
            reservation_links = _find_joy_mentions(text, html)
            phone_numbers = re.findall(r'(?:0|\+33)\s*[1-9](?:[\s.\-]?\d{2}){4}', text)

            return {
                "available": True,
                "url": url,
                "full_text": text[:5000],
                "joy_links": joy_links,
                "joy_rwg_detected": joy_rwg_active,
                "reservation_section_links": reservation_links,
                "has_group_editorial": bool(group_keywords),
                "group_keywords_found": group_keywords[:5],
                "phone_numbers_found": phone_numbers,
            }
        finally:
            await browser.close()


async def scrape_linktree(url: str) -> dict:
    if not url:
        return {"available": False, "reason": "Pas de Linktree"}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            text = await _get_page_text(page, url)
            html = await page.content()
            links = _extract_links(html)
            joy_links = [l for l in links if "joy.io" in l or "privateaser" in l or "prvt.re" in l]
            all_link_texts = re.findall(r'<a[^>]*>([^<]{1,60})</a>', html, re.IGNORECASE)
            return {
                "available": True,
                "url": url,
                "full_text": text[:3000],
                "joy_links": joy_links,
                "all_links": links[:20],
                "link_labels": all_link_texts[:15],
                "joy_link_position": next(
                    (i for i, l in enumerate(links) if "joy.io" in l or "privateaser" in l or "prvt.re" in l), None
                ),
            }
        finally:
            await browser.close()


async def _google_search(query: str, num_results: int = 10) -> list[dict]:
    """Scrape Google Search results and return list of {url, title, snippet}."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.google.fr/search?q={encoded}&num={num_results}&hl=fr&gl=fr"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
            viewport={"width": 1280, "height": 900},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        results = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            # Accept cookies if prompted
            try:
                btn = page.locator("text=Tout accepter").first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            html = await page.content()
            text = await page.evaluate("document.body.innerText")
            # Check for CAPTCHA
            if "captcha" in html.lower() or "unusual traffic" in text.lower():
                return []
            # Extract result blocks: title + URL + snippet
            # Google result structure: <div class="g">...<h3>title</h3>...<cite>url</cite>...<span>snippet</span>
            blocks = re.findall(
                r'<h3[^>]*>(.*?)</h3>.*?<cite[^>]*>(.*?)</cite>.*?<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )
            for title_raw, url_raw, snippet_raw in blocks[:num_results]:
                title = re.sub('<.*?>', '', title_raw).strip()
                result_url = re.sub('<.*?>', '', url_raw).strip()
                snippet = re.sub('<.*?>', '', snippet_raw).strip()
                if result_url and result_url.startswith('http'):
                    results.append({"url": result_url, "title": title, "snippet": snippet})
            # Fallback: extract URLs from href attributes
            if not results:
                hrefs = re.findall(r'href="(https://[^"]+)"', html)
                for href in hrefs:
                    domain = re.search(r'https?://(?:www\.)?([^/?]+)', href)
                    if domain and not any(ex in domain.group(1) for ex in ["google", "gstatic", "googleapis"]):
                        results.append({"url": href, "title": "", "snippet": ""})
        except Exception:
            pass
        finally:
            await browser.close()
        return results


async def get_instagram_bio_via_google(instagram_url: str, venue_name: str) -> dict:
    """Use Google to extract Instagram bio/phone since Instagram blocks server scrapers."""
    # Extract handle from URL
    handle_match = re.search(r'instagram\.com/([^/?]+)', instagram_url or "")
    handle = handle_match.group(1) if handle_match else venue_name

    results = await _google_search(f'site:instagram.com "{handle}"', num_results=3)
    if not results:
        # Fallback: search for venue name on Instagram
        results = await _google_search(f'instagram {venue_name}', num_results=5)

    # Extract phone numbers from snippets
    phone_numbers = []
    bio_text = ""
    for r in results:
        combined = r.get("snippet", "") + " " + r.get("title", "")
        phones = re.findall(r'(?:0|\+33)\s?[1-9](?:[\s.\-]?\d{2}){4}', combined)
        phone_numbers.extend(phones)
        bio_text += " " + combined

    phone_normalized = [re.sub(r'[\s.\-]', '', p) for p in phone_numbers]
    return {
        "source": "google_snippet",
        "bio_text": bio_text.strip()[:500],
        "phone_numbers": list(set(phone_numbers)),
        "phone_normalized": list(set(phone_normalized)),
    }


async def search_venue_online(venue_name: str, address: str, venue_website: str = "") -> list[dict]:
    """
    Google search for venue name + city, return top directory/annuaire pages.
    Excludes social media, SaaS platforms, and the venue's own website.
    """
    # Extract city from address
    city_match = re.search(r'(\d{5})\s+(.+)', address)
    city = city_match.group(2) if city_match else address.split(",")[-1].strip()

    results = await _google_search(f'"{venue_name}" {city}', num_results=15)

    # Filter results
    venue_domain = ""
    if venue_website:
        dom = re.search(r'https?://(?:www\.)?([^/?]+)', venue_website)
        if dom:
            venue_domain = dom.group(1)

    filtered = []
    seen_domains = set()
    for r in results:
        url = r["url"]
        dom_match = re.search(r'https?://(?:www\.)?([^/?]+)', url)
        if not dom_match:
            continue
        domain = dom_match.group(1)

        # Skip excluded domains
        if any(ex in domain for ex in EXCLUSION_DOMAINS):
            continue
        # Skip venue's own website
        if venue_domain and venue_domain in domain:
            continue
        # Skip duplicate domains
        if domain in seen_domains:
            continue

        seen_domains.add(domain)
        r["domain"] = domain
        # Try to identify canal name from domain
        r["canal_name"] = domain.split(".")[0].capitalize()
        for target in AUTRES_CANAUX_TARGETS:
            if target["domain"].split(".")[0] in domain:
                r["canal_name"] = target["name"]
                break
        filtered.append(r)

    return filtered[:8]  # Max 8 canaux


def detect_saas_from_scraped(website_data: dict, gmb_data: dict) -> list[str]:
    """Detect which SaaS platforms are used by the venue from scraped website/GMB."""
    detected = []
    sources = [
        website_data.get("full_text", ""),
        website_data.get("iframes_src", []),
        gmb_data.get("website", ""),
        gmb_data.get("full_text", ""),
    ]
    # Flatten sources into one searchable string
    text_blob = " ".join(str(s) for s in sources).lower()

    for saas_name, patterns in SAAS_PATTERNS.items():
        if any(p.lower() in text_blob for p in patterns):
            detected.append(saas_name)
    return detected


async def scrape_saas_booking(url: str, saas_name: str, joy_widget_url: str = "") -> dict:
    """Visit a SaaS booking page and check whether the Joy widget is integrated."""
    if not url:
        return {"available": False, "reason": "URL non fournie", "saas": saas_name}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            locale="fr-FR",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)
            text = await page.evaluate("document.body.innerText")
            html = await page.content()
            joy_links = _find_joy_mentions(text, html)
            # Look for group-specific CTA text near Joy links
            group_cta = re.findall(
                r'(?:groupe|privatisation|\\+\s*\d+\s*pax|grand groupe|plus de \d+)[^\n<]{0,200}',
                text, re.IGNORECASE
            )
            return {
                "available": True,
                "saas": saas_name,
                "url": url,
                "joy_integrated": bool(joy_links),
                "joy_links": joy_links,
                "group_cta_found": group_cta[:3],
                "full_text": text[:2000],
            }
        except Exception as e:
            return {"available": False, "saas": saas_name, "url": url, "reason": str(e)}
        finally:
            await browser.close()


async def _find_venue_on_directory(canal: dict, venue_name: str) -> Optional[str]:
    """Try to find a venue's profile URL on a given directory."""
    query = re.sub(r'[^\w\s]', '', venue_name).strip().replace(' ', '+')
    search_url = canal["search"].format(q=query)
    domain = canal["domain"]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )
        page = await context.new_page()
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            html = await page.content()
            # Find first internal link that looks like a venue profile
            links = re.findall(rf'href=["\']([^"\']*{re.escape(domain)}[^"\']*)["\']', html)
            # Also check for relative profile links
            rel_links = re.findall(r'href=["\']([/][^"\']{10,})["\']', html)
            profile_patterns = [
                r'/restaurant/', r'/lieu/', r'/etablissement/', r'/bar/', r'/attraction/',
                r'/place/', r'/venue/', r'/listing/', r'/profile/', r'-\d{5,}'
            ]
            for link in links + [f"https://{domain}{l}" for l in rel_links]:
                if any(re.search(p, link) for p in profile_patterns):
                    return link
            return None
        except Exception:
            return None
        finally:
            await browser.close()


async def scrape_autre_canal(url: str, canal_name: str, mvi: str = "", vitrine_url: str = "") -> dict:
    """Scrape a directory profile and check Joy/Vitrine links + MVI phone."""
    if not url:
        return {"available": False, "canal": canal_name, "reason": "Profil non trouvé"}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            locale="fr-FR",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            text = await page.evaluate("document.body.innerText")
            html = await page.content()
            joy_links = _find_joy_mentions(text, html)
            phone_numbers = re.findall(r'(?:0|\+33)\s?[1-9](?:[\s.\-]?\d{2}){4}', text)
            phone_norm = [re.sub(r'[\s.\-]', '', p) for p in phone_numbers]
            mvi_norm = re.sub(r'[\s.\-+]', '', mvi).replace('+33', '0')
            has_mvi = bool(mvi_norm) and any(mvi_norm in p or p in mvi_norm for p in phone_norm)
            # Look for website field pointing to Joy/Vitrine
            website_fields = re.findall(
                r'(?:site web|website|lien|url|homepage)[^<\n]{0,200}',
                text, re.IGNORECASE
            )
            website_field_has_joy = bool(joy_links) or any(
                "privateaser" in f.lower() or "prvt.re" in f.lower() or "joy.io" in f.lower()
                for f in website_fields
            )
            return {
                "available": True,
                "canal": canal_name,
                "url": url,
                "joy_links": joy_links,
                "has_joy_or_vitrine": bool(joy_links) or website_field_has_joy,
                "phone_numbers": phone_numbers[:3],
                "has_mvi_phone": has_mvi,
                "full_text": text[:2000],
            }
        except Exception as e:
            return {"available": False, "canal": canal_name, "url": url, "reason": str(e)}
        finally:
            await browser.close()


async def scrape_other_channel(url: str) -> dict:
    """Scrape a third-party channel (Tripadvisor, Fanzo, etc.) for Joy/Privateaser links."""
    if not url:
        return {"available": False, "reason": "URL non fournie"}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            text = await page.evaluate("document.body.innerText")
            html = await page.content()
            joy_links = _find_joy_mentions(text, html)
            all_links = _extract_links(html)
            phone_numbers = re.findall(r'(?:0|\+33)\s?[1-9](?:[\s.\-]?\d{2}){4}', text)
            # Detect website/link field pointing to joy
            website_field = re.search(r'(?:site web|website|lien|url)[^\n<]{0,100}(?:joy|privateaser|prvt)', text, re.IGNORECASE)
            return {
                "available": True,
                "url": url,
                "domain": re.search(r'https?://(?:www\.)?([^/]+)', url).group(1) if re.search(r'https?://(?:www\.)?([^/]+)', url) else url,
                "joy_links": joy_links,
                "phone_numbers": phone_numbers,
                "has_joy_in_website_field": bool(website_field or joy_links),
                "full_text": text[:3000],
            }
        except Exception as e:
            return {"available": False, "reason": str(e), "url": url}
        finally:
            await browser.close()


async def scrape_all_channels(params: dict) -> dict:
    """Run all scrapers in parallel and return combined results."""
    # Try Google Places API first for GMB, fall back to Playwright
    gmb_coro = (
        scrape_gmb_places_api(params.get("venue_name", ""), params.get("address", ""))
        if os.getenv("GOOGLE_PLACES_API_KEY")
        else scrape_gmb(params.get("gmb", ""))
    )

    tasks = {
        "website": scrape_website(params.get("website", "")),
        "instagram": scrape_instagram(params.get("instagram", ""), linktree_url=params.get("linktree", "")),
        "gmb": gmb_coro,
    }

    results = {}
    scraped = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for key, result in zip(tasks.keys(), scraped):
        if isinstance(result, Exception):
            results[key] = {"available": False, "reason": str(result)}
        else:
            results[key] = result

    # If GMB Places API failed, fall back to Playwright
    if not results.get("gmb", {}).get("available") and os.getenv("GOOGLE_PLACES_API_KEY"):
        try:
            results["gmb"] = await scrape_gmb(params.get("gmb", ""))
        except Exception as e:
            results["gmb"] = {"available": False, "reason": str(e)}

    # ── Detect & scrape SaaS Individual Booking (Segment 2) ──────────────────
    segment = params.get("segment", "1")
    saas_platforms_raw = params.get("saas_platforms", "").strip()
    if segment == "2":
        # Auto-detect from website + GMB if not provided
        detected_saas = detect_saas_from_scraped(
            results.get("website", {}), results.get("gmb", {})
        )
        # Merge with manually provided platforms
        manual_saas = [s.strip() for s in saas_platforms_raw.split(",") if s.strip()] if saas_platforms_raw else []
        all_saas = list(dict.fromkeys(manual_saas + detected_saas))  # deduplicate, preserve order

        saas_results = {}
        for saas_name in all_saas[:6]:  # cap at 6 platforms
            # Try to get the booking URL from params (format: "Zenchef:https://...")
            booking_url = ""
            for entry in params.get("saas_urls", "").split(","):
                if saas_name.lower() in entry.lower() and "http" in entry:
                    booking_url = entry.split(":", 1)[-1].strip() if ":" in entry else ""
            try:
                data = await scrape_saas_booking(booking_url, saas_name, params.get("joy_widget", ""))
                saas_results[saas_name] = data
            except Exception as e:
                saas_results[saas_name] = {"available": False, "saas": saas_name, "reason": str(e)}

        if saas_results or saas_platforms_raw:
            results["saas"] = {
                "available": True,
                "segment": "2",
                "detected_platforms": detected_saas,
                "platforms": saas_results,
            }
        else:
            results["saas"] = {"available": True, "applicable": False, "reason": "Aucun SaaS détecté"}
    else:
        results["saas"] = {"available": True, "applicable": False, "reason": "Segment 1 — non applicable"}

    # ── Instagram MVI via Google (last resort if both httpx + Playwright blocked) ──
    ig_data = results.get("instagram", {})
    mvi_norm = re.sub(r'[\s.\-+]', '', params.get('mvi', '').replace('+33', '0'))
    ig_phones_norm = ig_data.get("phone_numbers_normalized", [])

    if ig_data.get("available") and not ig_phones_norm and mvi_norm:
        # Neither httpx nor Playwright found phones → search Google for MVI in Instagram context
        try:
            handle = re.search(r'instagram\.com/([^/?]+)', params.get("instagram", ""))
            handle_str = handle.group(1) if handle else params.get("venue_name", "")
            # Search Google specifically for the phone in Instagram context
            google_ig = await get_instagram_bio_via_google(
                params.get("instagram", ""), params.get("venue_name", "")
            )
            if google_ig.get("phone_normalized"):
                ig_data["phone_numbers_normalized"] = google_ig["phone_normalized"]
                ig_data["phone_numbers_found"] = google_ig["phone_numbers"]
                ig_data["bio_source"] = "google_snippet"
                results["instagram"] = ig_data
        except Exception:
            pass

    # ── Autres canaux — Google Search auto-détection + URLs manuelles ─────────
    mvi = params.get("mvi", "")
    vitrine = params.get("vitrine", "")
    manually_provided_urls = [u.strip() for u in params.get("autres_canaux", "").split(",") if u.strip()]

    autres_found = {}

    # 1. Use manually provided URLs first
    for url in manually_provided_urls:
        canal_name = url
        for target in AUTRES_CANAUX_TARGETS:
            if target["domain"].split(".")[0] in url.lower():
                canal_name = target["name"]
                break
        try:
            data = await scrape_autre_canal(url, canal_name, mvi, vitrine)
            autres_found[canal_name] = data
        except Exception as e:
            autres_found[canal_name] = {"available": False, "canal": canal_name, "url": url, "reason": str(e)}

    # 2. Auto-detect via Google Search — evaluate from SERP snippet directly
    # No secondary page scraping needed: Google snippet already shows what's indexed
    try:
        google_results = await search_venue_online(
            params.get("venue_name", ""),
            params.get("address", ""),
            params.get("website", "")
        )
        joy_keywords = ["privateaser", "joy.io", "prvt.re", "widget.privateaser"]
        for r in google_results:
            canal_name = r["canal_name"]
            if canal_name in autres_found:
                continue
            snippet = (r.get("snippet", "") + " " + r.get("title", "")).lower()
            # Check if Joy/Privateaser is mentioned in the Google snippet
            has_joy = any(kw in snippet for kw in joy_keywords)
            # Check for other booking tools (signal of non-centralisation)
            has_other_booking = any(kw in snippet for kw in [
                "réserver", "reserver", "booking", "réservation"
            ]) and not has_joy
            autres_found[canal_name] = {
                "available": True,
                "canal": canal_name,
                "url": r["url"],
                "has_joy_or_vitrine": has_joy,
                "has_mvi_phone": False,  # can't detect phone from snippet
                "source": "google_snippet",
                "snippet": r.get("snippet", "")[:200],
                "detail_snippet": snippet[:300],
            }
    except Exception:
        pass

    if autres_found:
        results["autres_canaux"] = {"available": True, "channels": autres_found}
    else:
        results["autres_canaux"] = {"available": False, "reason": "Aucun canal tiers trouvé"}

    # Scrape linktree if found in instagram bio OR provided in params
    linktree_url = results.get("instagram", {}).get("linktree_url") or params.get("linktree", "")
    linktree_in_bio = results.get("instagram", {}).get("linktree_in_bio", False)
    if linktree_url:
        try:
            lt_data = await scrape_linktree(linktree_url)
            lt_data["in_bio"] = linktree_in_bio  # flag: is the LT link actually in the IG bio?
            results["linktree"] = lt_data
        except Exception as e:
            results["linktree"] = {"available": False, "reason": str(e)}

    return results
