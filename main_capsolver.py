"""Resolve e envia uma única resposta hCaptcha da página aberta no WebView2.

Pré-requisitos: jogo aberto com a depuração remota do WebView2 na porta 9222,
CAPSOLVER_API_KEY configurada no .env e dependências capsolver/playwright.
Execute com: python main_capsolver.py
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

try:
    import capsolver
    from playwright.sync_api import sync_playwright
except ImportError as erro:
    print(
        "Dependência ausente. Instale com: "
        "pip install capsolver playwright python-dotenv"
    )
    print(f"Detalhe: {erro}")
    raise SystemExit(1)


CDP_URL = "http://localhost:9222"
CAPTCHA_DOMAIN = "captcha.muaway.net"

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


def url_sem_parametros(url):
    """Retorna URL sem query string, que pode conter o sitekey."""
    parsed = urlparse(url)
    host = parsed.hostname or "host-desconhecido"
    return f"{parsed.scheme}://{host}{parsed.path}"


def mensagem_sem_segredos(erro, *segredos):
    mensagem = str(erro)
    for segredo in segredos:
        if segredo:
            mensagem = mensagem.replace(str(segredo), "[REDACTED]")
    return mensagem


def detalhe_erro_capsolver(erro):
    """Extrai o código e a descrição da resposta sem registrar dados da requisição."""
    resposta = getattr(erro, "json_body", None)
    if isinstance(resposta, dict):
        codigo = resposta.get("errorCode") or resposta.get("errorId")
        descricao = resposta.get("errorDescription")
        partes = [str(item) for item in (codigo, descricao) if item]
        if partes:
            return ": ".join(partes)
    return str(erro)


def buscar_pagina_captcha(playwright):
    """Localiza uma página hCaptcha já aberta no WebView2 conectado por CDP."""
    navegador = playwright.chromium.connect_over_cdp(CDP_URL)
    for contexto in navegador.contexts:
        for pagina in contexto.pages:
            if CAPTCHA_DOMAIN in pagina.url:
                return pagina
    return None


def resolver_uma_vez(pagina, api_key):
    """Envia um único desafio ao CapSolver e injeta a resposta retornada."""
    url = pagina.url
    sitekey = parse_qs(urlparse(url).query).get("sitekey", [None])[0]
    if not sitekey:
        print(f"A página não contém sitekey na URL: {url_sem_parametros(url)}")
        return False

    print(f"Enviando um desafio ao CapSolver: {url_sem_parametros(url)}")
    capsolver.api_key = api_key
    try:
        solucao = capsolver.solve({
            "type": "HCaptchaTaskProxyLess",
            "websiteURL": url,
            "websiteKey": sitekey,
        })
    except Exception as erro:
        detalhe = mensagem_sem_segredos(
            detalhe_erro_capsolver(erro), api_key, sitekey
        )
        print(f"Falha na resolução pelo CapSolver: {detalhe}")
        return False

    token = solucao.get("gRecaptchaResponse") if isinstance(solucao, dict) else None
    if not isinstance(token, str) or not token:
        print("CapSolver não retornou um gRecaptchaResponse válido.")
        return False

    try:
        pagina.evaluate(JS_INJETAR_TOKEN, token)
    except Exception as erro:
        detalhe = mensagem_sem_segredos(erro, api_key, sitekey, token)
        print(f"Falha ao enviar a resposta ao WebView2: {detalhe}")
        return False

    print("Desafio resolvido e resposta enviada ao WebView2 (token omitido).")
    return True


def main():
    api_key = os.getenv("CAPSOLVER_API_KEY")
    if not api_key:
        print("CAPSOLVER_API_KEY não está definida no ambiente ou no arquivo .env.")
        return 1

    try:
        with sync_playwright() as playwright:
            pagina = buscar_pagina_captcha(playwright)
            if pagina is None:
                print(
                    "Nenhuma página de captcha foi encontrada. "
                    "Confirme que o jogo está aberto e conectado à porta 9222."
                )
                return 1

            return 0 if resolver_uma_vez(pagina, api_key) else 1
    except Exception as erro:
        print(
            "Não foi possível concluir a tentativa: "
            f"{mensagem_sem_segredos(erro, api_key)}"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
