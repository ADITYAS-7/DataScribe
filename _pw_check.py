from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto("http://localhost:8501", wait_until="networkidle")
    page.wait_for_selector("img", timeout=15000)
    page.wait_for_timeout(1500)
    page.screenshot(path="_pw_screenshot.png", full_page=False)
    print("IMG_COUNT", page.locator("img").count())
    print("ERRORS", errors)
    browser.close()
