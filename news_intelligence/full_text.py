"""Limited primary-source text acquisition; no paywalls, redirects or crawls."""
from __future__ import annotations
import time
from collections import OrderedDict
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import httpx
from .enrichment import plain_text

HOST = 'www.federalreserve.gov'
USER_AGENT = 'SharipovAI-NewsIntelligence/1.0'


class PrimaryTextCollector:
    def __init__(self):
        self.cache = OrderedDict()
        self.robots_at = 0.0
        self.robots = None
        self.robots_missing = False

    def _read(self, url):
        start = time.monotonic(); chunks = []; size = 0
        with httpx.stream('GET', url, headers={'User-Agent': USER_AGENT}, timeout=5,
                          follow_redirects=False, trust_env=False) as response:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 524288 or time.monotonic()-start > 8:
                    raise ValueError('primary_text_resource_limit')
                chunks.append(chunk)
            return response.status_code, b''.join(chunks).decode('utf-8', errors='replace')

    def fetch(self, url: str) -> dict:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return {"status": "not_allowlisted"}
        if (parsed.scheme != 'https' or parsed.netloc != HOST or parsed.query or parsed.fragment
                or not parsed.path.startswith('/newsevents/pressreleases/') or not parsed.path.endswith('.htm')):
            return {'status': 'not_allowlisted'}
        previous = self.cache.get(url)
        if previous and (previous[1].get('status') == 'ok' or time.monotonic()-previous[0] < 900):
            return previous[1]
        try:
            if time.monotonic()-self.robots_at > 21600 or not self.robots_at:
                status, text = self._read(f'https://{HOST}/robots.txt')
                self.robots = None; self.robots_missing = status == 404
                if status == 200:
                    self.robots = RobotFileParser(); self.robots.parse(text.splitlines())
                self.robots_at = time.monotonic()
            if not self.robots_missing and (self.robots is None or not self.robots.can_fetch(USER_AGENT, url)):
                return {'status': 'robots_denied_or_unavailable'}
            status, html = self._read(url)
            if status != 200:
                raise ValueError(f'primary_text_http_{status}')
            text = plain_text(html, article_only=True)
            if len(text) < 100 or re_restricted(text):
                raise ValueError('primary_text_missing_or_restricted')
            result = {'status': 'ok', 'text': text[:16000], 'truncated': len(text) > 16000,
                      'observed_at_ms': int(time.time()*1000), 'url': url,
                      'rights_basis': 'https://www.federalreserve.gov/disclaimer.htm'}
        except (httpx.HTTPError, ValueError) as error:
            result = {'status': 'unavailable', 'reason': str(error)[:180]}
        self.cache[url] = (time.monotonic(), result)
        while len(self.cache) > 128: self.cache.popitem(last=False)
        return result


def re_restricted(text):
    # Do not copy identified third-party copyrighted text.
    return '©' in text or 'all rights reserved' in text.lower()
