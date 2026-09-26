"""
Resolve os captchas hCaptcha do MuAwaY conectando no WebView2 do jogo via CDP.

O script fica monitorando a porta de depuração do WebView2: toda vez que a
janela de captcha aparecer (o jogo pode pedir vários em sequência), ele
resolve e envia o token automaticamente. Encerra sozinho quando o captcha
não aparecer mais, ou com Ctrl+C.

Pre-requisito (uma vez só, como administrador):
    Chave de registro HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge\\WebView2\\AdditionalBrowserArguments
    com valor "muaway_v3.exe" = "--remote-debugging-port=9222"
    (apps elevados ignoram a variavel WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS)

Uso:
    1. Abra o jogo e faca login (rode este script antes ou depois, tanto faz).
    2. Rode: python main.py
"""
import os
import sys
import time
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from anticaptchaofficial.hcaptchaproxyless import hCaptchaProxyless

load_dotenv()

CDP_URL = "http://localhost:9222"
CAPTCHA_DOMAIN = "captcha.muaway.net"

INTERVALO_SEGUNDOS = 3          # intervalo entre verificacoes
CONFIRMACOES_PARA_SAIR = 5      # nº de verificacoes seguidas sem captcha para encerrar
MAX_RESOLUCOES = 30             # limite de seguranca para nao gastar creditos a toa

JS_INJETAR_TOKEN = """
(token) => {
    document.querySelectorAll(
        'textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]'
    ).forEach((campo) => {
        campo.value = token;
        campo.innerHTML = token;
        campo.dispatchEvent(new Event('change', { bubbles: true }));
    });
    window.chrome.webview.postMessage("hcaptcha=" + token);
}
"""


def buscar_pagina_captcha(playwright):
    """Retorna (navegador, pagina) se a aba do captcha estiver aberta, senao (None, None)."""
    try:
        navegador = playwright.chromium.connect_over_cdp(CDP_URL)
    except Exception:
        return None, None  # porta fechada: jogo nao abriu o WebView2 (ainda)
    for contexto in navegador.contexts:
        for pagina in contexto.pages:
            if CAPTCHA_DOMAIN in pagina.url:
                return navegador, pagina
    return navegador, None


def resolver_captcha(pagina, api_key):
    """Resolve o captcha da pagina atual e injeta o token. Retorna True se enviou."""
    url = pagina.url
    sitekey = parse_qs(urlparse(url).query).get("sitekey", [None])[0]
    if not sitekey:
        print("[-] Sitekey nao encontrada na URL da pagina")
        return False
    print(f"[+] Captcha detectado. Sitekey: {sitekey}")

    solver = hCaptchaProxyless()
    solver.set_verbose(1)
    solver.set_key(api_key)
    solver.set_website_url(url)
    solver.set_website_key(sitekey)

    print("[*] Resolvendo captcha via anti-captcha (pode levar ~1 min)...")
    resposta = solver.solve_and_return_solution()

    if resposta == 0:
        print(f"[-] Falha ao resolver: {solver.err_string}")
        return False

    print(f"[+] Token recebido ({len(resposta)} chars)")

    # Preenche os campos de resposta e dispara o callback que o jogo escuta
    # (WebMessageReceived com prefixo "hcaptcha=")
    pagina.evaluate(JS_INJETAR_TOKEN, resposta)
    print("[+] Token injetado e enviado ao jogo.")
    return True


def main():
    api_key = os.getenv("CAPTCHA_API_KEY")
    if not api_key:
        sys.exit("CAPTCHA_API_KEY nao definida no .env")

    print(f"[*] Monitorando o captcha do jogo (a cada {INTERVALO_SEGUNDOS}s).")
    print("[*] Deixe este script rodando enquanto joga. Ctrl+C para sair.\n")

    resolucoes = 0
    sem_captcha = 0

    try:
        with sync_playwright() as p:
            while resolucoes < MAX_RESOLUCOES:
                navegador, pagina = buscar_pagina_captcha(p)

                if pagina is None:
                    sem_captcha += 1
                    if resolucoes > 0 and sem_captcha >= CONFIRMACOES_PARA_SAIR:
                        print(f"\n[*] Nenhum captcha por "
                              f"{CONFIRMACOES_PARA_SAIR * INTERVALO_SEGUNDOS}s. "
                              f"Encerrando ({resolucoes} resolvido(s) no total).")
                        return
                else:
                    sem_captcha = 0
                    if resolver_captcha(pagina, api_key):
                        resolucoes += 1
                        print(f"[*] Total resolvido nesta sessao: {resolucoes}. "
                              f"Aguardando proximo captcha...\n")

                time.sleep(INTERVALO_SEGUNDOS)
    except KeyboardInterrupt:
        print(f"\n[*] Encerrado pelo usuario. "
              f"Total resolvido nesta sessao: {resolucoes}.")

    if resolucoes >= MAX_RESOLUCOES:
        print(f"[!] Limite de seguranca de {MAX_RESOLUCOES} resolucoes atingido. "
              f"Encerrando para nao gastar creditos a toa.")


if __name__ == "__main__":
    main()
