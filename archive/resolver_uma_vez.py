"""
Resolve o captcha do emulador UMA unica vez e encerra (sem loop/sentinela).

Pre-requisito: captcha aberto na tela do emulador.

Uso:
    .venv\\Scripts\\python -u resolver_uma_vez.py
"""
import os
import re
import subprocess
import sys
import time
from functools import partial
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from anticaptchaofficial.hcaptchaproxyless import hCaptchaProxyless

print = partial(print, flush=True)
load_dotenv()

ADB = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
EMULADOR = "emulator-5554"  # serial do BlueStacks oficial (veja com: HD-Adb.exe devices)
PORTA_BASE = 9223
DOMINIO_CAPTCHA = "webview.muaway.net"

# O app espera o sufixo "#ok" no final (assinatura real capturada de uma
# resolucao manual: 'NativeBridge RECEIVE message hcaptcha=<token>#ok').
JS_INJETAR_TOKEN = """
(token) => {
    document.querySelectorAll(
        'textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]'
    ).forEach((campo) => {
        campo.value = token;
        campo.innerHTML = token;
        campo.dispatchEvent(new Event('change', { bubbles: true }));
    });
    NativeBridge.sendMessage("hcaptcha=" + token + "#ok");
}
"""

# Marcadores reais observados no logcat do emulador (resolucao manual):
# - SUCESSO: resposta HTTP 200 de http://auth.muaway.net/hCaptcha
# - FALHA:   "Captcha token validation failed" / "token error" / "hcaptcha_error"
MARCADOR_SUCESSO = ("code=200", "auth.muaway.net/hCaptcha")
MARCADORES_FALHA = ("Captcha token validation failed", "token error", "hcaptcha_error")
TIMEOUT_VALIDACAO = 90  # segundos esperando o logcat confirmar


def limpar_logcat():
    try:
        adb("logcat", "-c")
    except Exception:
        pass


def aguardar_validacao():
    """Observa o logcat ate o servidor aceitar/rejeitar o token (ou timeout)."""
    inicio = time.time()
    while time.time() - inicio < TIMEOUT_VALIDACAO:
        try:
            saida = adb("logcat", "-d").stdout
        except Exception:
            saida = ""
        for linha in saida.splitlines():
            if all(m in linha for m in MARCADOR_SUCESSO):
                return True
            if any(m in linha for m in MARCADORES_FALHA):
                return False
        time.sleep(2)
    return None  # timeout: sem confirmacao


def adb(*args):
    return subprocess.run([ADB, "-s", EMULADOR, *args], capture_output=True, text=True, timeout=30)


def main():
    api_key = os.getenv("CAPTCHA_API_KEY")
    if not api_key:
        sys.exit("CAPTCHA_API_KEY nao definida no .env")

    # 1. Descobre todos os sockets devtools e cria forwards
    adb("connect", "127.0.0.1:5555")
    unix = adb("shell", "cat /proc/net/unix").stdout
    sockets = []
    for nome in re.findall(r"(?:chrome|webview)_devtools_remote_\d+", unix):
        s = f"localabstract:{nome}"
        if s not in sockets:
            sockets.append(s)
    if not sockets:
        sys.exit("Nenhum socket devtools. Abra o jogo com o captcha na tela.")

    forwards = adb("forward", "--list").stdout
    portas = []
    for i, socket in enumerate(sockets):
        porta = PORTA_BASE + i
        if f"tcp:{porta} {socket}" not in forwards:
            if f"tcp:{porta}" in forwards:
                adb("forward", "--remove", f"tcp:{porta}")
            adb("forward", f"tcp:{porta}", socket)
        portas.append(porta)
    print(f"[+] Sockets: {len(sockets)} | portas: {portas}")

    # 2. Localiza a pagina do captcha varrendo as portas
    with sync_playwright() as p:
        navegador, pagina = None, None
        for porta in portas:
            try:
                n = p.chromium.connect_over_cdp(f"http://localhost:{porta}")
            except Exception:
                continue
            for ctx in n.contexts:
                for pg in ctx.pages:
                    if DOMINIO_CAPTCHA in pg.url:
                        navegador, pagina = n, pg
                        break
            if pagina:
                print(f"[+] Captcha encontrado na porta {porta}")
                break
            n.close()
        if not pagina:
            sys.exit("Captcha nao encontrado em nenhum WebView.")

        url = pagina.url
        print(f"[+] URL: {url}")
        sitekey = parse_qs(urlparse(url).query).get("sitekey", [None])[0]
        if not sitekey:
            sys.exit("Sitekey nao encontrado na URL")

        # 3. Resolve com token FRESCO (nonce fura o cache do anti-captcha)
        url_solver = f"{url}&nc={int(time.time())}"
        solver = hCaptchaProxyless()
        solver.set_verbose(1)
        solver.set_key(api_key)
        solver.set_website_url(url_solver)
        solver.set_website_key(sitekey)
        solver.set_is_enterprise(True)
        print("[*] Resolvendo (token fresco, ~1 min)...")
        resposta = solver.solve_and_return_solution()
        if resposta == 0:
            sys.exit(f"Falha: {solver.err_string}")
        print(f"[+] Token FRESCO recebido ({len(resposta)} chars): {resposta[:30]}...")

        # 4. Injeta imediatamente (somente nesta pagina; token e de uso unico)
        pagina.bring_to_front()
        pagina.evaluate(JS_INJETAR_TOKEN, resposta)
        print("[+] Token injetado e enviado via NativeBridge (unica pagina).")
        navegador.close()

    print("[*] Fim (one-shot).")


if __name__ == "__main__":
    main()
