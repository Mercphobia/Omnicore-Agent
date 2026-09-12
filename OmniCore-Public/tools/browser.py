"""Browser automation tool. Playwright-based web interaction.
DNA: Cline (browser control). Optional — graceful fallback if not installed.
"""


def browse(url: str, action: str = "screenshot", selector: str = "", 
           text: str = "", timeout: int = 30) -> str:
    """Interact with a web page using Playwright.
    
    Actions: screenshot, click, type, content, title
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Browser unavailable. Install: pip install playwright && playwright install chromium"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000)

            result = ""

            if action == "screenshot":
                import base64
                import tempfile
                screenshot = page.screenshot(full_page=False)
                # Save to temp file, return path
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.write(screenshot)
                tmp.close()
                result = f"Screenshot saved: {tmp.name} ({len(screenshot)} bytes)"

            elif action == "click" and selector:
                page.click(selector, timeout=timeout * 1000)
                result = f"Clicked: {selector}"

            elif action == "type" and selector and text:
                page.fill(selector, text)
                result = f"Typed '{text[:50]}' into {selector}"

            elif action == "content":
                result = page.content()[:10000]

            elif action == "title":
                result = page.title()

            else:
                # Default: get page info
                title = page.title()
                url_current = page.url
                text_content = page.inner_text("body")[:2000]
                result = f"Title: {title}\nURL: {url_current}\n\nContent preview:\n{text_content}"

            browser.close()
            return result

    except Exception as e:
        return f"Browser error: {type(e).__name__}: {e}"


def screenshot(url: str) -> str:
    """Take a screenshot of a URL. Alias for browse(url, 'screenshot')."""
    return browse(url, "screenshot")


def fetch_content(url: str) -> str:
    """Fetch and extract text content from a URL."""
    return browse(url, "content")