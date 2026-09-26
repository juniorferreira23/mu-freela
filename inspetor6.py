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
                if "muaway" in pg.url:
                    alvo = (nav, pg); break
            if alvo: break
        if alvo: break
        nav.close()
    if not alvo:
        print("pagina nao encontrada"); raise SystemExit

    nav, pg = alvo
    print("URL:", pg.url)
    print("=== HTML completo ===")
    print(pg.content())
    nav.close()
