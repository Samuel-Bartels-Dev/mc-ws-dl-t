# scraper.py

# Import libraries (tools) that help us do things like talk to websites or control a browser
import requests  # Lets us fetch web pages from the internet (like using a browser but behind the scenes)
import logging   # Helps us record what's happening in the code, like a diary for debugging
import time      # Lets us pause the program for a few seconds when needed

# These next ones are for using a browser automatically (when a website needs JavaScript to show stuff)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.common.exceptions import WebDriverException

# --------------------------
# LOGGING SETUP
# --------------------------
# This sets up a logging system so we can track what's happening or going wrong in our program
logging.basicConfig(
    level=logging.INFO,  # We want to see messages like INFO, WARNING, and ERROR
    format="%(asctime)s [%(levelname)s] %(message)s",  # This is the format for each log message
    handlers=[
        logging.FileHandler("scraper.log"),  # Save logs to a file called scraper.log
        logging.StreamHandler()              # Also print logs to the screen
    ]
)

# A list of websites we already know use JavaScript to load their pages
# This helps us decide if we should use a real browser to see their content
DYNAMIC_SITES = [
    "mangakakalot.com",
    "manganato.com",
    "webtoons.com",
    "mangadex.org"
]

# --------------------------
# FUNCTION: is_dynamic_site
# --------------------------
def is_dynamic_site(url: str) -> bool:
    """
    This function checks if the website needs JavaScript to load.
    We look at the URL and see if it matches one of the known dynamic sites.
    If yes, return True (use browser). If no, return False (use simple request).
    """
    return any(domain in url for domain in DYNAMIC_SITES)  # Checks if any dynamic site is in the URL


# --------------------------
# FUNCTION: fetch_html_static
# --------------------------
def fetch_html_static(url: str) -> str:
    """
    This function fetches the web page using just a simple request (like reading a file).
    This only works if the site loads its content using normal HTML (not JavaScript).
    """
    logging.info(f"Trying static fetch for: {url}")  # Log that we're starting a static fetch

    # Pretend to be a real browser by adding a User-Agent so some websites don't block us
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36"
    }

    try:
        # Ask the website to give us the page
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # If something goes wrong (like a 404), this stops and shows an error
        logging.info("Static fetch successful.")
        return response.text  # Return the full HTML code from the page
    except requests.RequestException as e:
        # If there's a problem (like no internet), log it
        logging.error(f"Static fetch failed: {e}")
        return ""  # Return nothing if it fails


# --------------------------
# FUNCTION: fetch_html_dynamic
# --------------------------
def fetch_html_dynamic(url: str, wait_time=5, browser="chrome") -> str:
    """
    This function uses Selenium to open a real (but invisible) browser to load the page.
    This works even if the page uses JavaScript to show content.
    """
    logging.info(f"Trying dynamic fetch for: {url}")  # Log that we're starting a dynamic fetch
    html = ""  # Start with empty HTML

    try:
        # Set up a special "headless" browser (invisible but fully functional)
        if browser.lower() == "chrome":
            options = ChromeOptions()
            options.add_argument("--headless")        # No window shown
            options.add_argument("--disable-gpu")     # Saves system resources
            options.add_argument("--no-sandbox")      # Needed for some systems
            driver = webdriver.Chrome(options=options)  # Start Chrome
        else:
            options = FirefoxOptions()
            options.add_argument("--headless")        # Same idea, but for Firefox
            driver = webdriver.Firefox(options=options)

        driver.get(url)  # Tell the browser to go to the page
        logging.info(f"Waiting {wait_time}s for page to fully render...")
        time.sleep(wait_time)  # Wait a bit so JavaScript can finish loading

        html = driver.page_source  # Get the fully loaded page's HTML
        logging.info("Dynamic fetch successful.")
        driver.quit()  # Close the browser

    except WebDriverException as e:
        # If something goes wrong, write it in the log
        logging.error(f"Dynamic fetch failed: {e}")
        if 'driver' in locals():
            driver.quit()

    return html  # Return the HTML we got


# --------------------------
# FUNCTION: fetch_page
# --------------------------
def fetch_page(url: str) -> str:
    """
    This is the main function you'll use.
    It decides whether to use static or dynamic fetching and returns the page HTML.
    """
    # First, check if the website likely needs JavaScript
    if is_dynamic_site(url):
        html = fetch_html_dynamic(url)
        if html:
            return html

    # Try static method if not dynamic or if dynamic failed
    html = fetch_html_static(url)
    if html:
        return html

    # If static failed, try dynamic as backup
    logging.warning("Static fetch failed or empty — trying dynamic as fallback...")
    html = fetch_html_dynamic(url)

    if not html:
        logging.error("Failed to fetch page content.")
    return html


# --------------------------
# TESTING BLOCK
# --------------------------
# This part runs only when this file is run directly (not when it's imported as a module)
if __name__ == "__main__":
    test_url = "https://mangakakalot.com/read-abc123456"  # Example manga page
    html = fetch_page(test_url)  # Try to get the page HTML

    # Print message depending on success or failure
    if html:
        print("✅ Page fetched successfully!")
    else:
        print("❌ Failed to fetch page.")