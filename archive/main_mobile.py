"""
Resolve o captcha hCaptcha do MuAwaY MOBILE rodando em emulador (BlueStacks/MSI App Player).

Como funciona:
    1. Conecta no emulador via ADB (127.0.0.1:5555).
    2. Descobre o socket de depuracao do WebView do app (chrome_devtools_remote_<pid>)
       e faz adb forward para a porta local 9223.
    3. Fica vigiando: quando a pagina webview.muaway.net (captcha) abre,
       resolve via anti-captcha e injeta o token chamando
       NativeBridge.sendMessage("hcaptcha=" + token) - ponte que o app escuta.

Pre-requisitos:
    - BlueStacks 5 com ADB habilitado (Configuracoes > Avancado > Android Debug Bridge)
    - Emulador aberto, jogo logado; o captcha pode ainda nao estar na tela.

Uso:
    .venv\\Scripts\\python main_mobile.py
    Ctrl+C para parar.
"""
import os
import re
import subprocess
import sys
import time
from functools import partial
from urllib.parse import urlparse, parse_qs

print = partial(print, flush=True)  # logs em tempo real (sem buffering)

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from anticaptchaofficial.hcaptchaproxyless import hCaptchaProxyless

load_dotenv()

ADB = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
EMULADOR = "emulator-5554"  # serial do BlueStacks oficial (veja com: HD-Adb.exe devices)
PORTA_LOCAL = 9223
DOMINIO_CAPTCHA = "webview.muaway.net"

INTERVALO_SEGUNDOS = 3
CONFIRMACOES_PARA_SAIR = 5  # checks sem captcha (apos ter resolvido) -> encerra
MAX_RESOLUCOES = 30         # trava de seguranca de creditos

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


def adb(*args):
    return subprocess.run([ADB, "-s", EMULADOR, *args], capture_output=True, text=True, timeout=30)


def garantir_forwards():
    """Garante forwards para TODOS os sockets devtools do app (webview e chrome).

    O app pode ter varios processos WebView (net.muway.app:webview);
    a pagina do captcha pode estar em qualquer um deles.
    Retorna lista de portas locais com forward ativo.
    """
    adb("connect", "127.0.0.1:5555")
    saida = adb("shell", "cat /proc/net/unix").stdout
    sockets = []
    for nome in re.findall(r"(?:chrome|webview)_devtools_remote_\d+", saida):
        s = f"localabstract:{nome}"
        if s not in sockets:
            sockets.append(s)

    forwards = adb("forward", "--list").stdout
    portas = []
    for indice, socket in enumerate(sockets):
        porta = PORTA_LOCAL + indice
        alvo_atual = f"tcp:{porta} {socket}"
        if alvo_atual not in forwards:
            # adb forward nao atualiza um binding existente; remove antes
            if f"tcp:{porta}" in forwards:
                adb("forward", "--remove", f"tcp:{porta}")
            adb("forward", f"tcp:{porta}", socket)
            print(f"[+] Forward ativo: tcp:{porta} -> {socket}")
        portas.append(porta)
    return portas


def buscar_pagina_captcha(playwright, portas):
    """Conecta em cada porta com forward e devolve (navegador, pagina) do captcha."""
    for porta in portas:
        try:
            navegador = playwright.chromium.connect_over_cdp(f"http://localhost:{porta}")
        except Exception:
            continue
        try:
            urls = []
            for contexto in navegador.contexts:
                for pagina in contexto.pages:
                    urls.append(pagina.url)
                    if DOMINIO_CAPTCHA in pagina.url:
                        return navegador, pagina
            if urls:
                print(f"[i] Porta {porta} - paginas abertas (sem captcha): {urls}")
        except Exception:
            pass
        try:
            navegador.close()
        except Exception:
            pass
    return None, None


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
    print(f"[+] Sitekey: {sitekey}")

    # nonce para furar o cache do anti-captcha e garantir token FRESCO
    # (token hCaptcha expira em ~2 min e e de uso unico; a validacao
    #  e por dominio+sitekey, entao um parametro extra nao interfere)
    url_solver = f"{url}&nc={int(time.time())}"

    solver = hCaptchaProxyless()
    solver.set_verbose(1)
    solver.set_key(api_key)
    solver.set_website_url(url_solver)
    solver.set_website_key(sitekey)

    print("[*] Resolvendo captcha via anti-captcha (pode levar ~1 min)...")
    resposta = solver.solve_and_return_solution()
    if resposta == 0:
        print(f"[-] Falha ao resolver: {solver.err_string}")
        return False

    print(f"[+] Token recebido ({len(resposta)} chars)")
    limpar_logcat()
    pagina.evaluate(JS_INJETAR_TOKEN, resposta)
    print("[+] Token injetado (com sufixo #ok). Aguardando validacao do servidor...")

    resultado = aguardar_validacao()
    if resultado is True:
        print("[+] SUCESSO REAL: servidor aceitou o token (HTTP 200 em auth.muaway.net/hCaptcha).")
        return True
    if resultado is False:
        print("[-] FALHA REAL: logcat registrou erro de captcha (token rejeitado).")
        return False
    print("[?] Sem confirmacao no logcat dentro do timeout (tratando como falha).")
    return False


def main():
    api_key = os.getenv("CAPTCHA_API_KEY")
    if not api_key:
        sys.exit("CAPTCHA_API_KEY nao definida no .env")

    portas = garantir_forwards()
    if not portas:
        print("[*] WebView do jogo ainda nao disponivel. Aguardando o emulador/jogo...")
        while not portas:
            time.sleep(INTERVALO_SEGUNDOS)
            portas = garantir_forwards()
    print(f"[+] WebView do jogo localizado (portas: {portas}).")

    print("[*] Vigiando o captcha... (Ctrl+C para sair)")
    resolvidos = 0
    sem_captcha_seguidos = 0

    with sync_playwright() as p:
        while True:
            navegador, pagina = buscar_pagina_captcha(p, portas)

            if pagina is not None:
                sem_captcha_seguidos = 0
                print(f"[+] Captcha detectado: {pagina.url}")
                try:
                    if resolver_captcha(pagina, api_key):
                        resolvidos += 1
                except Exception as erro:
                    print(f"[-] Erro ao resolver: {erro}")
                try:
                    navegador.close()
                except Exception:
                    pass

                if resolvidos >= MAX_RESOLUCOES:
                    print(f"[*] Limite de seguranca atingido ({MAX_RESOLUCOES}). Encerrando.")
                    break
            else:
                sem_captcha_seguidos += 1
                if resolvidos > 0 and sem_captcha_seguidos >= CONFIRMACOES_PARA_SAIR:
                    print(f"[*] Captcha resolvido e nao reapareceu. Encerrando.")
                    break
                # sockets podem mudar se o app reiniciar o WebView; refaz os forwards
                portas = garantir_forwards()

            time.sleep(INTERVALO_SEGUNDOS)

    print(f"[*] Fim. Resolvidos nesta sessao: {resolvidos}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Interrompido pelo usuario.")
