from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    for porta in (9223, 9224, 9225):
        try:
            nav = p.chromium.connect_over_cdp(f"http://localhost:{porta}")
        except Exception:
            continue
        alvo = None
        for ctx in nav.contexts:
            for pg in ctx.pages:
                if "webview.muaway.net" in pg.url:
                    alvo = pg
        if alvo:
            print("enviando mensagem teste na porta", porta)
            alvo.evaluate("() => NativeBridge.sendMessage('hcaptcha=TOKEN_DE_TESTE_FALSO')")
            print("enviado.")
            nav.close()
            break
        nav.close()
