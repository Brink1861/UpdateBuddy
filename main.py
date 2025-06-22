
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from discord_webhook import DiscordWebhook
import time, json
from urllib.parse import urljoin, urlparse

# ============ CONFIGURATION ============
BOARD_URL = "https://vusa.forums.net/board/21/news"
WEBHOOK_URL = "https://discord.com/api/webhooks/1383854712389894328/dCQkcReZFXk0E_P6zw5_L5dAMIpPQj4Xbri10zELZLL3wTQr178wWGWAO1g64webttKq"
SEEN_FILE = "seen_posts.json"
THREADS_FILE = "monitored_threads.json"
INTERVAL = 300  # seconds between checks (increased for multiple threads)

# ============ SELECTORS ============
THREAD_LINK_SELECTOR = "a[href*='/thread/']"  # Selector for thread links on board page
POST_SELECTOR = ".post"
ID_ATTRIBUTE = "id"
AUTHOR_SELECTOR = "a.user-link"
CONTENT_SELECTOR = "div.message"

# ============ HELPER FUNCTIONS ============
def load_seen():
    try:
        return set(json.load(open(SEEN_FILE)))
    except:
        return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def load_threads():
    try:
        return json.load(open(THREADS_FILE))
    except:
        return {}

def save_threads(threads):
    with open(THREADS_FILE, "w") as f:
        json.dump(threads, f, indent=2)

def create_browser_page():
    """Create a configured browser page"""
    browser = playwright_instance.chromium.launch(
        headless=True,
        args=['--no-sandbox', '--disable-dev-shm-usage']
    )
    page = browser.new_page()
    page.set_extra_http_headers({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    return browser, page

def fetch_thread_urls():
    """Fetch all thread URLs from the board page"""
    print(f"[INFO] Fetching thread URLs from {BOARD_URL}...")
    try:
        browser, page = create_browser_page()
        page.goto(BOARD_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=20000)
        html = page.content()
        browser.close()
        
        print(f"[DEBUG] Board page HTML length: {len(html)} characters")
        print(f"[DEBUG] Board page title: {BeautifulSoup(html, 'html.parser').title.text if BeautifulSoup(html, 'html.parser').title else 'No title'}")
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Debug different possible thread link selectors
        possible_thread_selectors = [
            "a.thread-title",
            "a[href*='/thread/']",
            ".thread-title",
            "a[data-thread-id]",
            ".topic-title a",
            ".thread-link",
            "a[href*='topic']"
        ]
        
        print("[DEBUG] Testing thread link selectors:")
        for selector in possible_thread_selectors:
            elements = soup.select(selector)
            print(f"[DEBUG] '{selector}' found {len(elements)} elements")
            if elements:
                for i, elem in enumerate(elements[:3]):  # Show first 3
                    print(f"[DEBUG]   {i+1}. Text: '{elem.text.strip()[:50]}...' Href: '{elem.get('href', 'NO HREF')}'")
        
        thread_links = {}
        
        for link in soup.select(THREAD_LINK_SELECTOR):
            href = link.get('href')
            title = link.text.strip()
            if href and '/thread/new/' not in href:  # Skip "Create Thread" links
                full_url = urljoin(BOARD_URL, href)
                thread_links[full_url] = title
        
        print(f"[INFO] Found {len(thread_links)} threads on the board")
        return thread_links
        
    except Exception as e:
        print(f"[ERROR] Failed to fetch thread URLs: {e}")
        return {}

def fetch_posts_from_thread(thread_url, thread_title):
    """Fetch posts from a specific thread"""
    print(f"[INFO] Checking thread: {thread_title}")
    posts = []
    try:
        browser, page = create_browser_page()
        page.goto(thread_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=20000)
        html = page.content()
        browser.close()
        
        soup = BeautifulSoup(html, "html.parser")
        
        for div in soup.select(POST_SELECTOR):
            post_id = div.get(ID_ATTRIBUTE)
            author_tag = div.select_one(AUTHOR_SELECTOR)
            content_tag = div.select_one(CONTENT_SELECTOR)

            if not post_id or not author_tag or not content_tag:
                continue

            author = author_tag.text.strip()
            content = content_tag.text.strip()
            posts.append((post_id, author, content, thread_url, thread_title))

        print(f"[INFO] Found {len(posts)} posts in '{thread_title}'")
        return posts
        
    except Exception as e:
        print(f"[ERROR] Failed to fetch posts from {thread_url}: {e}")
        return []

# ============ MAIN LOOP ============
def main():
    global playwright_instance
    
    seen = load_seen()
    monitored_threads = load_threads()
    print(f"[INFO] Loaded {len(seen)} previously seen posts.")
    print(f"[INFO] Monitoring {len(monitored_threads)} known threads.")
    
    with sync_playwright() as p:
        playwright_instance = p
        
        while True:
            try:
                # Get current thread URLs from board
                current_threads = fetch_thread_urls()
                
                # Update our monitored threads list
                new_threads = set(current_threads.keys()) - set(monitored_threads.keys())
                if new_threads:
                    print(f"[INFO] Found {len(new_threads)} new threads to monitor")
                    monitored_threads.update(current_threads)
                    save_threads(monitored_threads)
                
                # Check each thread for new posts
                all_new_posts = []
                for thread_url, thread_title in monitored_threads.items():
                    posts = fetch_posts_from_thread(thread_url, thread_title)
                    new_posts = [(pid, author, content, url, title) for pid, author, content, url, title in posts if pid not in seen]
                    all_new_posts.extend(new_posts)
                
                # Process new posts
                for post_id, author, content, thread_url, thread_title in all_new_posts:
                    print(f"[NEW POST] {thread_title} - {author}: {content[:60]}...")
                    seen.add(post_id)
                    post_link = f"{thread_url}#{post_id}"
                    
                    webhook = DiscordWebhook(
                        url=WEBHOOK_URL,
                        content=f"🆕 **{author}** replied in **{thread_title}**:\n{content[:200]}…\n\n🔗 [View Post]({post_link})"
                    )
                    webhook.execute()
                    time.sleep(1)  # Small delay between Discord messages
                
                if all_new_posts:
                    save_seen(seen)
                    print(f"[INFO] Processed {len(all_new_posts)} new posts. Total seen: {len(seen)}")
                else:
                    print("[INFO] No new posts found")
                    
            except Exception as e:
                print(f"[ERROR] {e}")

            print(f"[INFO] Waiting {INTERVAL} seconds before next check...")
            time.sleep(INTERVAL)

# ============ START ============
if __name__ == "__main__":
    main()
