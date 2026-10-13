import datetime as dt
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import jinja2
from markdown_it import MarkdownIt
from markupsafe import Markup, escape

from .data import OPSITE, BuildError
from .messages_ru import msg

HUB = "openpalliative.github.io"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; "
       "connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; "
       "form-action 'none'")
SAFE = "-_.!~*'()"
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]

_md = MarkdownIt("commonmark", {"html": False, "typographer": False}).enable("table")


def ru_date(value) -> str:
    if not value:
        return ""
    d = dt.date.fromisoformat(str(value)[:10])
    return d.strftime("%d.%m.%Y")


def ru_date_long(value) -> str:
    if not value:
        return ""
    d = dt.date.fromisoformat(str(value)[:10])
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def plural(n, one: str, few: str, many: str, with_number: bool = True) -> str:
    n = int(n)
    m10, m100 = n % 10, n % 100
    word = one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many
    return f"{n} {word}" if with_number else word


def tel(value: str) -> str:
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 11:
        return "tel:+" + digits
    return "tel:" + digits


TEL_DISPLAY = re.compile(r"^(\d{2,6}|8 \d{3,5} (\d{1,3}-)?\d{2}-\d{2})$")


def _group_local(local: str) -> str:
    head = local[:-4]
    return (head + "-" if head else "") + local[-4:-2] + "-" + local[-2:]


def tel_display(value) -> str:
    text = str(value or "").strip()
    main = re.split(r"\s*(?:,|доб|добавочн|цифра)", text, maxsplit=1)[0]
    digits = re.sub(r"\D", "", main)
    if 2 <= len(digits) <= 6 and len(digits) == len(re.sub(r"\D", "", text)):
        return digits
    if len(digits) == 10:
        digits = "8" + digits
    if len(digits) != 11 or digits[0] not in "78":
        return text
    rest = digits[1:]
    m = re.search(r"\((\d{3,5})\)", main)
    area = len(m.group(1)) if m and rest.startswith(m.group(1)) else 3
    shown = f"8 {rest[:area]} {_group_local(rest[area:])}"
    tail = text[len(main):].strip()
    if not tail:
        return shown
    return shown + (tail if tail.startswith(",") else " " + tail)


@lru_cache(maxsize=None)
def icon_names() -> frozenset:
    return frozenset(p.stem for p in (OPSITE / "ui" / "icons").glob("*.svg"))


ICON_FILE = "ui/icons.svg"
ICON_FILE_ALL = "ui/icons-all.svg"


@jinja2.pass_context
def icon(context, name: str, cls: str = "", sprite: str = "") -> Markup:
    if name not in icon_names():
        raise BuildError(f"Нет иконки {name}. Иконки добавляет только хаб в opsite/ui/icons/")
    sprite = sprite or context.get("icon_sprite", "")
    used = context.get("icons_used")
    if used is not None and sprite != "all":
        used.add(name)
    href = url(context, ICON_FILE_ALL if sprite == "all" else ICON_FILE) + "#" + name
    return Markup('<svg class="op-icon{}" aria-hidden="true"><use href="{}"></use></svg>').format(
        (" " + cls) if cls else "", href)


def sprite(names) -> str:
    parts = ['<svg xmlns="http://www.w3.org/2000/svg">']
    for name in sorted(names):
        src = (OPSITE / "ui" / "icons" / f"{name}.svg").read_text(encoding="utf-8")
        body = re.sub(r"(?s)^.*?<svg[^>]*>|</svg>\s*$", "", src)
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        body = re.sub(r"\s*\n\s*", "", body).replace(" />", "/>")
        parts.append(f'<symbol id="{name}" viewBox="0 0 24 24">{body}</symbol>')
    parts.append("</svg>")
    return "".join(parts) + "\n"


def md(text) -> Markup:
    return Markup(_md.render(str(text or "")))


def md_inline(text) -> Markup:
    return Markup(_md.renderInline(str(text or "")))


def _rel_prefix(page_out: str) -> str:
    return "../" * page_out.count("/")


@jinja2.pass_context
def url(context, path: str = "") -> str:
    path = path.lstrip("/")
    if context.get("page_absolute"):
        return context["site"]["base"] + path
    prefix = _rel_prefix(context["page_out"])
    return (prefix + path) or "./"


XPARAMS = {"s", "doc", "device", "nut", "region", "rule", "from", "norm", "back", "new", "id"}


def fragment(params: dict | None) -> str:
    if not params:
        return ""
    bad = sorted(set(params) - XPARAMS)
    if bad:
        raise BuildError(f"Параметры {', '.join(bad)} нельзя передавать в адресе. Разрешены: {', '.join(sorted(XPARAMS))}")
    return "#" + "&".join(f"{k}={quote(str(v), safe=SAFE)}" for k, v in params.items() if v not in (None, ""))


def make_xurl(site: dict, org_root: str):
    @jinja2.pass_context
    def xurl(context, repo: str, path: str = "", params: dict | None = None) -> str:
        path = path.lstrip("/")
        if repo in (site["repo"], "hub" if site["repo"] == HUB else None):
            return url(context, path) + fragment(params)
        return org_root + ("" if repo in (HUB, "hub") else repo + "/") + path + fragment(params)
    return xurl


def make_abs_url(site: dict):
    @jinja2.pass_context
    def abs_url(context, path: str | None = None) -> str:
        if path is None:
            path = context.get("page_url", "")
        return site["site_url"].rstrip("/") + site["base"] + path.lstrip("/")
    return abs_url


def make_hub(site: dict, org_root: str):
    xurl = make_xurl(site, org_root)

    @jinja2.pass_context
    def hub(context, path: str = "") -> str:
        return xurl(context, HUB, path)
    return hub


def _acts(ctx) -> list:
    if ctx.site["repo"] == "pal-norms":
        env = ctx.data.get("acts")
    else:
        env = ctx.vendor.get("pal-norms", {}).get("acts")
    return env["items"] if env else []


def norm_state(act: dict | None) -> str:
    if act is None or act.get("verified") is not True:
        return "unverified"
    if act.get("status") == "in_force":
        return "in_force"
    if act.get("status") == "repealed":
        return "repealed"
    return "unverified"


def make_norm(ctx, xurl):
    @jinja2.pass_context
    def norm(context, norm_id: str, label: str | None = None) -> Markup:
        acts = {a["id"]: a for a in _acts(ctx)}
        act = acts.get(norm_id)
        in_doc = bool(context.get("doc"))
        state = norm_state(act)
        if act is None:
            if in_doc:
                raise BuildError(msg("unknown_norm", id=norm_id))
            return Markup('<span class="op-norm op-norm--unknown">') + escape(norm_id) + \
                Markup("\u00a0") + unverified_inline(context) + Markup("</span>")
        if in_doc and state != "in_force":
            raise BuildError(msg("norm_unsafe", id=norm_id, status=act.get("status"), verified=act.get("verified")))
        text = label or act.get("short_title") or act.get("title") or norm_id
        href = xurl(context, "pal-norms", f"acts/{norm_id}/")
        link = Markup('<a class="op-norm" href="{}">{}</a>').format(href, text)
        if state == "in_force":
            return link
        mark = repealed_inline(context) if state == "repealed" else unverified_inline(context)
        return Markup('<span class="op-norm-wrap">') + link + Markup("\u00a0") + mark + Markup("</span>")
    return norm


def _inline_status(context, kind: str, icon_name: str, word: str) -> Markup:
    return Markup('<span class="op-status op-status--{} op-status--inline">').format(kind) + \
        icon(context, icon_name) + Markup("<span>{}</span></span>").format(word)


@jinja2.pass_context
def unverified_inline(context) -> Markup:
    return _inline_status(context, "unverified", "circle-help", "Не проверено")


@jinja2.pass_context
def repealed_inline(context) -> Markup:
    return _inline_status(context, "repealed", "history", "Утратил силу")


def make_env(ctx, org_root: str = "/") -> jinja2.Environment:
    loader = jinja2.ChoiceLoader([
        jinja2.FileSystemLoader(str(ctx.root / "templates")),
        jinja2.FileSystemLoader(str(OPSITE / "templates")),
    ])
    env = jinja2.Environment(loader=loader, autoescape=True, undefined=jinja2.StrictUndefined,
                             trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    xurl = make_xurl(ctx.site, org_root)
    env.globals.update(url=url, xurl=xurl, hub=make_hub(ctx.site, org_root), norm=make_norm(ctx, xurl),
                       icon=icon, unverified_inline=unverified_inline, repealed_inline=repealed_inline,
                       abs_url=make_abs_url(ctx.site), csp=CSP)
    env.filters.update(ru_date=ru_date, ru_date_long=ru_date_long, plural=plural, tel=tel, tel_display=tel_display,
                       md=md, md_inline=md_inline)
    return env


def render(env: jinja2.Environment, template: str, out_rel: str, variables: dict) -> str:
    try:
        tpl = env.get_template(template)
        return tpl.render(page_out=out_rel, **variables)
    except jinja2.TemplateError as e:
        where = getattr(e, "filename", None) or template
        line = getattr(e, "lineno", None)
        raise BuildError(msg("template_error", template=f"{where}:{line}" if line else where, error=e)) from e


def out_path_for(rel_template: Path) -> str:
    parts = list(rel_template.parts)
    name = parts[-1]
    for suf in (".html.j2", ".md"):
        if name.endswith(suf):
            name = name[: -len(suf)]
    parts[-1] = name
    if name == "index":
        return "/".join(parts[:-1] + ["index.html"])
    return "/".join(parts + ["index.html"])


def page_dir_url(out_rel: str) -> str:
    return out_rel[: -len("index.html")] if out_rel.endswith("index.html") else out_rel
