"""
TikTok uploader via Selenium — for use during warm-up period before API access.

Uses a persistent Chrome profile so you only need to log in once.
The first run opens Chrome and pauses for manual login.
Subsequent runs reuse the saved session automatically.

Usage:
    python3 scripts/library.py tiktok-post POST_ID
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CHROME_PROFILE_DIR = Path.home() / ".shorts_pipeline" / "chrome_profile"
TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=upload&lang=en"
TIKTOK_LOGIN_URL = "https://www.tiktok.com/login"
UPLOAD_TIMEOUT = 180  # seconds to wait for video processing


def _build_caption(caption: str, hashtags: list[str]) -> str:
    tags = " ".join(f"#{h}" for h in hashtags)
    return f"{caption}\n\n{tags}"


class TikTokSeleniumPublisher:
    """Uploads a single video to TikTok using a real Chrome browser session."""

    def __init__(self, headless: bool = False):
        self._headless = headless
        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    def _make_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        if self._headless:
            options.add_argument("--headless=new")

        # Selenium 4.6+ uses Selenium Manager to auto-download the correct chromedriver
        driver = webdriver.Chrome(options=options)
        driver.set_window_size(1280, 900)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        return driver

    def publish_post(self, manifest_path: Path) -> bool:
        """Upload tiktok_45s.mp4 to TikTok. Returns True on success."""
        manifest = json.loads(manifest_path.read_text())
        video_path = manifest_path.parent / "tiktok_45s.mp4"

        if not video_path.exists():
            logger.error(f"Video not found: {video_path}")
            return False

        caption = _build_caption(
            manifest["tiktok"]["caption"],
            manifest["tiktok"]["hashtags"],
        )

        driver = self._make_driver()
        try:
            return self._upload(driver, video_path, caption)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    def _upload(self, driver, video_path: Path, caption: str) -> bool:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        logger.info("Opening TikTok upload page...")
        driver.get(TIKTOK_UPLOAD_URL)
        time.sleep(4)

        # If redirected to login, poll URL until user completes login
        if self._needs_login(driver):
            print("\n" + "="*60)
            print("  TikTok: inicia sesión en el navegador que se ha abierto.")
            print("  El script esperará hasta 5 min a que llegues al upload.")
            print("="*60)
            deadline = time.time() + 300  # 5 min
            while time.time() < deadline:
                time.sleep(3)
                if not self._needs_login(driver):
                    break
            if self._needs_login(driver):
                logger.error("Timeout esperando login")
                return False
            # Ensure we're on the upload page after login
            if "upload" not in driver.current_url:
                driver.get(TIKTOK_UPLOAD_URL)
                time.sleep(4)

        wait = WebDriverWait(driver, 30)

        # Find file input (may be inside iframe or directly on page)
        file_input = self._find_file_input(driver, wait)
        if not file_input:
            logger.error("No se encontró el input de archivo")
            return False

        driver.execute_script("arguments[0].style.display = 'block';", file_input)
        file_input.send_keys(str(video_path.resolve()))
        logger.info(f"Archivo enviado: {video_path.name}")

        # Wait for video to finish processing
        logger.info("Esperando a que TikTok procese el video...")
        self._wait_for_processing(driver, timeout=UPLOAD_TIMEOUT)

        # Fill in caption
        self._fill_caption(driver, caption)

        # Click Post
        try:
            post_btn = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[@data-e2e='post_video_button' or contains(normalize-space(.), 'Post') or contains(normalize-space(.), 'Publicar')]"
                ))
            )
            post_btn.click()
            logger.info("Botón Post pulsado")
        except Exception as e:
            logger.error(f"No se pudo pulsar Post: {e}")
            print("\n  Sube el video manualmente desde la ventana abierta.")
            input("  Pulsa ENTER cuando termines para cerrar: ")
            return False

        time.sleep(6)
        logger.info("✓ Video publicado")
        return True

    def _needs_login(self, driver) -> bool:
        url = driver.current_url.lower()
        return "login" in url or "signup" in url

    def _find_file_input(self, driver, wait):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC

        # Try direct input first
        try:
            return wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
            )
        except Exception:
            pass

        # Try iframes
        iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                inp = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                return inp
            except Exception:
                driver.switch_to.default_content()
                continue
        return None

    def _wait_for_processing(self, driver, timeout: int = 180):
        """Wait until the caption area is editable (meaning upload is done)."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "div[contenteditable='true']")
                )
            )
        except Exception:
            time.sleep(20)

    def _fill_caption(self, driver, caption: str):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            field = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "div[contenteditable='true']")
                )
            )
            field.click()
            time.sleep(0.5)
            field.send_keys(Keys.COMMAND + "a")
            field.send_keys(Keys.DELETE)
            time.sleep(0.3)

            lines = caption.split("\n")
            for i, line in enumerate(lines):
                field.send_keys(line)
                if i < len(lines) - 1:
                    field.send_keys(Keys.SHIFT + Keys.ENTER)

            time.sleep(1)
            logger.info("Caption escrito")
        except Exception as e:
            logger.warning(f"No se pudo rellenar el caption: {e}")
            print(f"\n  Pega manualmente este caption:\n  {caption}\n")
