"""HTTP access to novelpia.com (login, novel page, episode list, viewer data, images)."""

import secrets

import requests

BASE = "https://novelpia.com"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
)
TIMEOUT = 30


def random_loginkey():
    return f"{secrets.token_hex(16)}_{secrets.token_hex(16)}"


class Novelpia:
    def __init__(self, loginkey=None):
        self.loginkey = loginkey or random_loginkey()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _headers(self, referer=None):
        headers = {"Cookie": f"LOGINKEY={self.loginkey};"}
        if referer:
            headers["Referer"] = referer
        return headers

    def get(self, url):
        r = self.session.get(url, headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    def post(self, url, data=None, referer=None):
        headers = self._headers(referer)
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        r = self.session.post(url, data=data or "", headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    def login(self, email, password):
        # Login binds the (fresh) LOGINKEY cookie to the account.
        resp = self.post(f"{BASE}/proc/login", {"redirectrurl": "", "email": email, "wd": password})
        return "감사합니다" in resp

    def novel_page(self, novel_no):
        return self.get(f"{BASE}/novel/{novel_no}")

    def episode_list(self, novel_no, page):
        return self.post(
            f"{BASE}/proc/episode_list",
            {"novel_no": novel_no, "sort": "DOWN", "page": page},
            referer=f"{BASE}/",
        )

    def viewer_data(self, chapter_id):
        return self.post(f"{BASE}/proc/viewer_data/{chapter_id}", referer=f"{BASE}/")

    def fetch_bytes(self, url):
        if not url.startswith("http"):
            url = "https:" + url
        r = self.session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.content
