"""Bounded, local news descriptors. They do not establish truth or alter votes."""
from __future__ import annotations
import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from .council_lineage import publication_seconds


class TextParser(HTMLParser):
    def __init__(self, *, article_only: bool = False):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.article_only = article_only
        self.depth = 0
        self.article_depth = None
        self.paragraph = 0
        self.found_article = False

    def handle_starttag(self, tag, attrs):
        if tag in {'br', 'hr', 'img', 'meta', 'link', 'input', 'wbr', 'source', 'area', 'base', 'embed', 'param', 'track'}:
            return
        self.depth += 1
        if tag in {'script', 'style', 'noscript'}:
            self.skip += 1
        if dict(attrs).get('id') == 'article' and self.article_depth is None:
            self.article_depth = self.depth
            self.found_article = True
        if tag in {'p', 'li', 'h2', 'h3'}:
            self.paragraph += 1

    def handle_endtag(self, tag):
        if tag in {'br', 'hr', 'img', 'meta', 'link', 'input', 'wbr', 'source', 'area', 'base', 'embed', 'param', 'track'}:
            return
        if tag in {'script', 'style', 'noscript'}:
            self.skip = max(0, self.skip - 1)
        if tag in {'p', 'li', 'h2', 'h3'}:
            self.paragraph = max(0, self.paragraph - 1)
        if self.article_depth == self.depth:
            self.article_depth = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, value):
        if not self.skip and (not self.article_only or (self.article_depth is not None and self.paragraph)):
            self.parts.append(value)


def plain_text(html: str, *, article_only: bool = False) -> str:
    parser = TextParser(article_only=article_only)
    parser.feed(str(html)[:524288])
    return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()


def publisher_host(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        return parsed.hostname if parsed.scheme in {'http', 'https'} else None
    except ValueError:
        return None


def descriptors(article, fetched) -> dict:
    text = plain_text(f'{article.title} {article.summary} {article.content}')[:24000]
    lower = text.lower()
    words = set(re.findall(r'\b\w+\b', lower))
    language = ('ru' if re.search('[ыэёъ]', lower) and len(re.findall('[а-яё]', lower)) >= 8 else
                'en' if len(words & {'the','and','of','to','is','for','with','from','on','in','an','by'}) >= 2 else 'und')
    patterns = {'BTC': r'\b(bitcoin|btc)\b', 'ETH': r'\b(ethereum|ether|eth)\b',
                'SOL': r'\b(solana|sol)\b', 'XRP': r'\b(xrp|ripple)\b',
                'BNB': r'\b(bnb|binance coin)\b'}
    assets = [asset for asset, pattern in patterns.items() if re.search(pattern, lower)]
    title = article.title.lower()
    if re.search(r'\b(rumou?r|unconfirmed|alleged|reportedly)\b|слух|неподтвержд', lower):
        kind = 'unconfirmed_report'
    elif re.search(r'\b(forecast|prediction|could|might|expects?|outlook)\b|прогноз', title):
        kind = 'forecast'
    elif re.search(r'\b(opinion|editorial|commentary|analysis)\b|мнение', title):
        kind = 'opinion'
    elif article.category in {'macro_official', 'regulatory_official'} or article.source_type == 'official':
        kind = 'primary_statement'
    else:
        kind = 'reported_event'
    published = publication_seconds(article.published_at)
    delay = fetched.received_at_ms - published * 1000 if published is not None else None
    return {'method': 'bounded_rules_v1', 'detected_language': language, 'language_method': 'script_heuristic',
            'assets': assets, 'claim_type': kind, 'fact_confirmed': False,
            'primary_url': article.link, 'publisher_host': publisher_host(article.link),
            'publication_delay_ms': delay if delay is not None and delay >= 0 else None,
            'publication_time_status': 'unknown' if delay is None else 'future' if delay < 0 else 'known',
            'content_scope': article.content_scope, 'content_characters': len(article.content),
            'content_sha256': hashlib.sha256(article.content.encode()).hexdigest() if article.content else None,
            'content_observed_at_ms': article.content_observed_at_ms or fetched.received_at_ms,
            'available_at_ms': max(fetched.received_at_ms, article.content_observed_at_ms),
            'news_predictive_utility': 'NOT_VALIDATED', 'execution_authority': False}


def corroboration_candidates(envelope, memory) -> list[dict]:
    """Surface similar independent-host reports for verification, never votes.

    Host diversity is not ownership/source independence. Near-identical copies
    and explicit syndication are excluded rather than counted as confirmations.
    """
    article = envelope.article
    at = publication_seconds(article.published_at)
    tokens = set(re.findall(r'[a-z]{3,}', article.title.lower()))
    if at is None or len(tokens) < 5:
        return []
    host = publisher_host(article.link)
    result = []
    for other in list(memory)[-200:]:
        b = other.article; bt = publication_seconds(b.published_at)
        if (not host or host == publisher_host(b.link) or article.source == b.source
                or bt is None or abs(at-bt) > 86400):
            continue
        combined = f'{article.summary} {b.summary}'.lower()
        if re.search(r'\b(reuters|associated press|syndicated|republished)\b', combined):
            continue
        other_tokens = set(re.findall(r'[a-z]{3,}', b.title.lower()))
        similarity = len(tokens & other_tokens) / max(len(tokens | other_tokens), 1)
        if .65 <= similarity < 1 and plain_text(article.summary) != plain_text(b.summary):
            result.append({'article_id': b.article_id, 'url': b.link, 'title_similarity': round(similarity, 3),
                           'independence': 'NOT_ESTABLISHED', 'fact_confirmed': False})
    return result[:5]
