"""
Resolve os captchas hCaptcha do MuAwaY conectando no WebView2 do jogo via CDP.

O script fica monitorando a porta de depuração do WebView2: toda vez que a
janela de captcha aparecer (o jogo pode pedir vários em sequência), ele
resolve e envia o token automaticamente. Roda indefinidamente até o
usuário parar com Ctrl+C.

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
from twocaptcha import TwoCaptcha, ApiException as TwoCaptchaException

load_dotenv()

CDP_URL = "http://localhost:9222"
CAPTCHA_DOMAIN = "captcha.muaway.net"

INTERVALO_SEGUNDOS = 3          # intervalo entre verificacoes
INTERVALO_RETRY_INICIAL_SEGUNDOS = 15
INTERVALO_RETRY_MAX_SEGUNDOS = 120

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


def resolver_via_anticaptcha(url, sitekey, api_key):
    """Tenta resolver via anti-captcha. Retorna (token, sem_saldo) ou (None, sem_saldo)."""
    try:
        solver = hCaptchaProxyless()
        solver.set_verbose(1)
        solver.set_key(api_key)
        solver.set_website_url(url)
        solver.set_website_key(sitekey)

        print("[*] Resolvendo captcha via anti-captcha (pode levar ~1 min)...")
        resposta = solver.solve_and_return_solution()

        if resposta == 0:
            error_code = str(getattr(solver, "error_code", "") or "").upper()
            error_message = getattr(solver, "err_string", "sem detalhes")
            sem_saldo = error_code == "ERROR_ZERO_BALANCE"
            print(f"[-] Falha no anti-captcha ({error_code or 'codigo desconhecido'}): "
                  f"{error_message}")
            return None, sem_saldo
        return resposta, False
    except Exception as e:
        print(f"[-] Excecao no anti-captcha ({type(e).__name__}): {e}")
        return None, False


def resolver_via_2captcha(url, sitekey, api_key):
    """Tenta resolver via 2captcha (fallback). Retorna o token ou None."""
    try:
        solver = TwoCaptcha(api_key)
        print("[*] Resolvendo captcha via 2captcha (pode levar ~1 min)...")
        resultado = solver.hcaptcha(sitekey=sitekey, url=url)
    except TwoCaptchaException as e:
        print(f"[-] Falha no 2captcha: {e}")
        if "ERROR_ZERO_BALANCE" in str(e):
            print("\n" + "=" * 70)
            print("[!!!] SALDO DAS DUAS APIS ESGOTADO (anti-captcha e 2captcha)")
            print("[!!!] Recarregue os creditos. O script continuara tentando mais tarde.")
            print("=" * 70)
        return None
    except Exception as e:
        print(f"[-] Excecao no 2captcha ({type(e).__name__}): {e}")
        return None

    try:
        return resultado["code"]
    except (KeyError, TypeError):
        print("[-] Resposta inesperada do 2captcha: token nao encontrado")
        return None


def resolver_captcha(pagina, api_key, api_key_2captcha):
    """Resolve o captcha da pagina atual e injeta o token. Retorna True se enviou."""
    url = pagina.url
    sitekey = parse_qs(urlparse(url).query).get("sitekey", [None])[0]
    if not sitekey:
        print("[-] Sitekey nao encontrada na URL da pagina")
        return False
    print(f"[+] Captcha detectado. Sitekey: {sitekey}")

    resposta, sem_saldo = resolver_via_anticaptcha(url, sitekey, api_key)

    if resposta is None and sem_saldo:
        print("[!] Anti-captcha sem saldo (ERROR_ZERO_BALANCE). "
              "Tentando fallback no 2captcha...")
        if not api_key_2captcha:
            print("\n" + "=" * 70)
            print("[!!!] SALDO DA API ANTI-CAPTCHA ESGOTADO (ERROR_ZERO_BALANCE)")
            print("[!!!] Sem chave CAPTCHA_2CAPTCHA_API_KEY configurada para")
            print("[!!!] fallback. Recarregue creditos ou configure o 2captcha.")
            print("[!!!] O script continuara monitorando e tentara novamente.")
            print("=" * 70)
            return False
        resposta = resolver_via_2captcha(url, sitekey, api_key_2captcha)

    if resposta is None:
        return False

    print(f"[+] Token recebido ({len(resposta)} chars)")

    # Preenche os campos de resposta e dispara o callback que o jogo escuta
    # (WebMessageReceived com prefixo "hcaptcha=")
    pagina.evaluate(JS_INJETAR_TOKEN, resposta)
    print("[+] Token injetado e enviado ao jogo.")
    return True


def proximo_intervalo_retry(intervalo_atual):
    """Aumenta o intervalo entre falhas sem deixar o monitor parar."""
    return min(
        max(INTERVALO_RETRY_INICIAL_SEGUNDOS, intervalo_atual * 2),
        INTERVALO_RETRY_MAX_SEGUNDOS,
    )


def main():
    api_key = os.getenv("CAPTCHA_API_KEY")
    if not api_key:
        sys.exit("CAPTCHA_API_KEY nao definida no .env")
    api_key_2captcha = os.getenv("CAPTCHA_2CAPTCHA_API_KEY")  # fallback opcional

    print(f"[*] Monitorando o captcha do jogo (a cada {INTERVALO_SEGUNDOS}s).")
    print("[*] Deixe este script rodando enquanto joga. Ctrl+C para sair.\n")

    resolucoes = 0
    intervalo_atual = INTERVALO_SEGUNDOS

    try:
        with sync_playwright() as p:
            while True:
                try:
                    navegador, pagina = buscar_pagina_captcha(p)

                    if pagina is None:
                        intervalo_atual = INTERVALO_SEGUNDOS
                    elif resolver_captcha(pagina, api_key, api_key_2captcha):
                        resolucoes += 1
                        intervalo_atual = INTERVALO_SEGUNDOS
                        print(f"[*] Total resolvido nesta sessao: {resolucoes}. "
                              f"Aguardando proximo captcha...\n")
                    else:
                        intervalo_atual = proximo_intervalo_retry(intervalo_atual)
                        print(f"[*] Nova tentativa em {intervalo_atual}s.")
                except Exception as e:
                    intervalo_atual = proximo_intervalo_retry(intervalo_atual)
                    print(f"[-] Erro no ciclo de monitoramento ({type(e).__name__}): {e}")
                    print(f"[*] Nova tentativa em {intervalo_atual}s.")

                time.sleep(intervalo_atual)
    except KeyboardInterrupt:
        print(f"\n[*] Encerrado pelo usuario. "
              f"Total resolvido nesta sessao: {resolucoes}.")


if __name__ == "__main__":
    main()
