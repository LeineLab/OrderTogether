"""Central render helper — wraps Jinja2 TemplateResponse and injects i18n."""
from starlette.requests import Request
from starlette.templating import _TemplateResponse

from app.i18n import detect_language, get_translator


def render(template_name: str, request: Request, ctx: dict) -> _TemplateResponse:
    """Render *template_name* with *ctx*, automatically injecting ``_`` and ``lang``."""
    from app.main import templates  # lazy import avoids circular dependency

    lang = detect_language(request.headers.get("accept-language", ""))
    ctx.setdefault("request", request)
    ctx["_"] = get_translator(lang)
    ctx["lang"] = lang
    return templates.TemplateResponse(template_name, ctx)
