import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOSTS = ("publication.pravo.gov.ru", "roszdravnadzor.gov.ru")
USER_AGENT = "openpalliative-watch (+https://github.com/openpalliative)"
PAUSES = (5, 10, 20, 30)
TIMEOUT = 120
MAX_BYTES = 20 * 1024 * 1024


class SourceDown(Exception):
    pass


class HostNotAllowed(ValueError):
    pass


def check_host(url: str) -> None:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise HostNotAllowed(f"хост {host} не разрешён, можно только {', '.join(ALLOWED_HOSTS)}")


class TooLarge(SourceDown):
    pass


def get(url: str, *, timeout: int = TIMEOUT, pauses=PAUSES, sleep=time.sleep, max_bytes: int = MAX_BYTES) -> bytes:
    check_host(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last = None
    for attempt in range(len(pauses) + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise TooLarge(f"{url}: ответ больше {max_bytes // (1024 * 1024)} МБ")
            if not body:
                raise SourceDown(f"пустой ответ: {url}")
            return body
        except TooLarge:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, SourceDown) as e:
            last = e
            if attempt < len(pauses):
                sleep(pauses[attempt])
    raise SourceDown(f"{url}: {last}")
