from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    alvo = None
    for porta in (9223, 9224, 9225, 9226):
        try:
            nav = p.chromium.connect_over_cdp(f"http://localhost:{porta}")
        except Exception:
            continue
        for ctx in nav.contexts:
            for pg in ctx.pages:
                if "webview.muaway.net" in pg.url:
                    alvo = (nav, pg, porta)
                    break
        if alvo:
            break
        nav.close()
    if not alvo:
        print("captcha nao encontrado"); raise SystemExit

    nav, pagina, porta = alvo
    print("porta:", porta)
    print("url:", pagina.url)
    print("NativeBridge:", pagina.evaluate("() => typeof NativeBridge"))
    print("chrome.webview:", pagina.evaluate("() => typeof (window.chrome && window.chrome.webview)"))
    print("textareas:", pagina.evaluate("() => [...document.querySelectorAll('textarea')].map(t => t.name)"))
    print("hcaptcha obj:", pagina.evaluate("() => typeof hcaptcha"))
    r = pagina.evaluate("() => document.body.innerText.slice(0, 200)")
    print("texto visivel:", r)
    nav.close()
