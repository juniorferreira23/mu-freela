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
import logging
import os
import sys
import time
import traceback
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs


NOME_LOGGER = "mu_captcha_resolver"
TAMANHO_MAXIMO_LOG = 5 * 1024 * 1024
QUANTIDADE_BACKUPS_LOG = 5


def configurar_logging():
    """Configura logs no console e em arquivo rotativo persistente."""
    logger = logging.getLogger(NOME_LOGGER)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        return logger, getattr(logger, "caminho_arquivo", None)

    formato_console = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_console = sys.stdout or sys.stderr
    if stream_console is not None:
        console = logging.StreamHandler(stream_console)
        console.setLevel(logging.INFO)
        console.setFormatter(formato_console)
        logger.addHandler(console)

    if getattr(sys, "frozen", False):
        diretorio_aplicacao = Path(sys.executable).resolve().parent
    else:
        diretorio_aplicacao = Path(__file__).resolve().parent

    candidatos = [diretorio_aplicacao / "logs" / "main.log"]
    diretorio_local = os.getenv("LOCALAPPDATA")
    if diretorio_local:
        candidatos.append(Path(diretorio_local) / "MuCaptchaResolver" / "logs" / "main.log")
    else:
        candidatos.append(Path.home() / ".mu-captcha-resolver" / "logs" / "main.log")

    erros_criacao = []
    caminho_arquivo = None
    for candidato in candidatos:
        try:
            candidato.parent.mkdir(parents=True, exist_ok=True)
            arquivo = RotatingFileHandler(
                candidato,
                maxBytes=TAMANHO_MAXIMO_LOG,
                backupCount=QUANTIDADE_BACKUPS_LOG,
                encoding="utf-8",
            )
            arquivo.setLevel(logging.DEBUG)
            arquivo.setFormatter(logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] "
                "[%(funcName)s:%(lineno)d] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            logger.addHandler(arquivo)
            caminho_arquivo = candidato
            break
        except OSError as erro:
            erros_criacao.append(f"{candidato}: {type(erro).__name__}: {erro}")

    logger.caminho_arquivo = caminho_arquivo
    if caminho_arquivo:
        logger.info("Log persistente em: %s", caminho_arquivo)
        logger.info(
            "Rotação de logs habilitada (máximo de %d MB por arquivo, %d backups).",
            TAMANHO_MAXIMO_LOG // (1024 * 1024),
            QUANTIDADE_BACKUPS_LOG,
        )
    else:
        logger.error(
            "Não foi possível criar arquivo de log; os detalhes estarão apenas no console. Erros: %s",
            " | ".join(erros_criacao),
        )

    return logger, caminho_arquivo


LOGGER, CAMINHO_LOG = configurar_logging()

try:
    from dotenv import load_dotenv
    from playwright.sync_api import sync_playwright
    from anticaptchaofficial.hcaptchaproxyless import hCaptchaProxyless
    from twocaptcha import TwoCaptcha, ApiException as TwoCaptchaException
except Exception:
    LOGGER.exception("Falha ao importar uma ou mais dependências necessárias.")
    raise


def sanitizar_texto(texto, *segredos):
    """Remove credenciais conhecidas de mensagens de erro antes de registrá-las."""
    texto = str(texto)
    for segredo in segredos:
        if segredo:
            texto = texto.replace(str(segredo), "[REDACTED]")
    return texto


def registrar_excecao(mensagem, erro, *segredos, nivel=logging.ERROR):
    """Registra frames e erro sem incluir credenciais ou linhas-fonte sensíveis."""
    quadros = traceback.extract_tb(erro.__traceback__)
    frames = "".join(
        f'  File "{quadro.filename}", line {quadro.lineno}, in {quadro.name}\n'
        for quadro in quadros
    )
    erro_texto = sanitizar_texto(
        f"{type(erro).__name__}: {erro}", *segredos
    )
    LOGGER.log(
        nivel,
        "%s\nTraceback (most recent call last):\n%s%s",
        mensagem,
        frames,
        erro_texto,
    )


def url_sem_parametros(url):
    """Devolve apenas esquema, host e caminho; omite query string/sitekey."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "host-desconhecido"
        return f"{parsed.scheme}://{host}{parsed.path}"
    except Exception:
        return "<URL indisponível>"


try:
    DOTENV_CARREGADO = load_dotenv()
    LOGGER.info("load_dotenv() retornou: %s", DOTENV_CARREGADO)
except Exception as erro:
    registrar_excecao("Falha ao carregar configuração do arquivo .env", erro)
    raise

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
    inicio = time.perf_counter()
    try:
        navegador = playwright.chromium.connect_over_cdp(CDP_URL)
    except Exception as erro:
        LOGGER.debug(
            "Conexão CDP indisponível após %.3fs (%s): %s",
            time.perf_counter() - inicio,
            type(erro).__name__,
            sanitizar_texto(erro),
        )
        return None, None  # porta fechada: jogo nao abriu o WebView2 (ainda)

    total_paginas = 0
    for contexto in navegador.contexts:
        for pagina in contexto.pages:
            total_paginas += 1
            url = pagina.url
            LOGGER.debug("Página detectada no WebView2: %s", url_sem_parametros(url))
            if CAPTCHA_DOMAIN in url:
                LOGGER.info(
                    "Página de captcha localizada após %.3fs: %s",
                    time.perf_counter() - inicio,
                    url_sem_parametros(url),
                )
                return navegador, pagina

    LOGGER.debug(
        "CDP conectado após %.3fs; contextos=%d, páginas=%d, captcha não encontrado.",
        time.perf_counter() - inicio,
        len(navegador.contexts),
        total_paginas,
    )
    return navegador, None


def resolver_via_anticaptcha(url, sitekey, api_key):
    """Tenta resolver via anti-captcha. Retorna (token, sem_saldo) ou (None, sem_saldo)."""
    inicio = time.perf_counter()
    LOGGER.info("Iniciando tentativa de resolução pelo anti-captcha (%s).", url_sem_parametros(url))
    try:
        solver = hCaptchaProxyless()
        # Evita que a biblioteca imprima requisições/respostas potencialmente sensíveis.
        solver.set_verbose(0)
        solver.set_key(api_key)
        solver.set_website_url(url)
        solver.set_website_key(sitekey)

        resposta = solver.solve_and_return_solution()

        if resposta == 0:
            error_code = str(getattr(solver, "error_code", "") or "").upper()
            error_message = sanitizar_texto(
                getattr(solver, "err_string", "sem detalhes"), api_key, sitekey
            )
            sem_saldo = error_code == "ERROR_ZERO_BALANCE"
            LOGGER.error(
                "Anti-captcha falhou após %.2fs (código=%s, sem_saldo=%s): %s",
                time.perf_counter() - inicio,
                error_code or "código desconhecido",
                sem_saldo,
                error_message,
            )
            return None, sem_saldo

        LOGGER.info(
            "Anti-captcha resolveu o desafio em %.2fs; tamanho do token=%d (valor omitido).",
            time.perf_counter() - inicio,
            len(resposta),
        )
        return resposta, False
    except Exception as e:
        registrar_excecao(
            f"Exceção durante a resolução pelo anti-captcha após "
            f"{time.perf_counter() - inicio:.2f}s",
            e,
            api_key,
            sitekey,
        )
        return None, False


def resolver_via_2captcha(url, sitekey, api_key):
    """Tenta resolver via 2captcha (fallback). Retorna o token ou None."""
    inicio = time.perf_counter()
    LOGGER.info("Iniciando tentativa de resolução pelo 2captcha (%s).", url_sem_parametros(url))
    try:
        solver = TwoCaptcha(api_key)
        resultado = solver.hcaptcha(sitekey=sitekey, url=url)
    except TwoCaptchaException as e:
        registrar_excecao(
            f"Erro da API 2captcha após {time.perf_counter() - inicio:.2f}s",
            e,
            api_key,
            sitekey,
        )
        if "ERROR_ZERO_BALANCE" in str(e):
            LOGGER.critical(
                "Saldo do 2captcha esgotado; ambas as tentativas de resolução falharam. "
                "O monitor continuará tentando mais tarde."
            )
        return None
    except Exception as e:
        registrar_excecao(
            f"Exceção durante a resolução pelo 2captcha após "
            f"{time.perf_counter() - inicio:.2f}s",
            e,
            api_key,
            sitekey,
        )
        return None

    try:
        resposta = resultado["code"]
    except (KeyError, TypeError):
        LOGGER.error(
            "Resposta inesperada do 2captcha após %.2fs: campo 'code' ausente "
            "(tipo recebido=%s).",
            time.perf_counter() - inicio,
            type(resultado).__name__,
        )
        return None

    LOGGER.info(
        "2captcha resolveu o desafio em %.2fs; tamanho do token=%d (valor omitido).",
        time.perf_counter() - inicio,
        len(resposta),
    )
    return resposta


def resolver_captcha(pagina, api_key, api_key_2captcha):
    """Resolve o captcha da pagina atual e injeta o token. Retorna True se enviou."""
    url = pagina.url
    sitekey = parse_qs(urlparse(url).query).get("sitekey", [None])[0]
    if not sitekey:
        LOGGER.error("Captcha detectado, mas a URL não contém o parâmetro sitekey: %s", url_sem_parametros(url))
        return False
    LOGGER.info("Captcha detectado; sitekey presente (valor omitido). URL: %s", url_sem_parametros(url))

    resposta, sem_saldo = resolver_via_anticaptcha(url, sitekey, api_key)

    if resposta is None and sem_saldo:
        LOGGER.warning("Anti-captcha sem saldo (ERROR_ZERO_BALANCE); avaliando fallback 2captcha.")
        if not api_key_2captcha:
            LOGGER.critical(
                "Anti-captcha sem saldo e CAPTCHA_2CAPTCHA_API_KEY não configurada; "
                "nenhum fallback disponível. O monitor continuará tentando."
            )
            return False
        LOGGER.info("Chave do fallback 2captcha configurada; iniciando fallback.")
        resposta = resolver_via_2captcha(url, sitekey, api_key_2captcha)
    elif resposta is None:
        LOGGER.warning(
            "Anti-captcha não resolveu o desafio, mas não reportou ERROR_ZERO_BALANCE; "
            "o fallback 2captcha não será iniciado."
        )

    if resposta is None:
        LOGGER.warning("Nenhum token foi obtido para este desafio.")
        return False

    LOGGER.info("Token recebido; tamanho=%d (valor omitido).", len(resposta))

    # Preenche os campos de resposta e dispara o callback que o jogo escuta
    # (WebMessageReceived com prefixo "hcaptcha=")
    try:
        pagina.evaluate(JS_INJETAR_TOKEN, resposta)
    except Exception as e:
        registrar_excecao(
            "Falha ao injetar/enviar o token ao WebView2",
            e,
            api_key,
            api_key_2captcha,
            sitekey,
            resposta,
        )
        return False

    LOGGER.info("Token injetado no WebView2 e postMessage retornou sem erro.")
    return True


def proximo_intervalo_retry(intervalo_atual):
    """Aumenta o intervalo entre falhas sem deixar o monitor parar."""
    proximo = min(
        max(INTERVALO_RETRY_INICIAL_SEGUNDOS, intervalo_atual * 2),
        INTERVALO_RETRY_MAX_SEGUNDOS,
    )
    LOGGER.debug("Backoff de retry: intervalo %ds -> %ds.", intervalo_atual, proximo)
    return proximo


def main():
    inicio_sessao = time.perf_counter()
    LOGGER.info("=" * 72)
    LOGGER.info("Iniciando sessão do resolvedor de captcha.")
    LOGGER.info(
        "Ambiente: Python %s, plataforma=%s, executável=%s",
        sys.version.split()[0],
        sys.platform,
        sys.executable,
    )
    LOGGER.info("Diretório de trabalho: %s", os.getcwd())
    LOGGER.info("Arquivo de log: %s", CAMINHO_LOG or "indisponível; apenas console")
    for pacote in ("python-dotenv", "playwright", "anticaptchaofficial", "2captcha-python"):
        try:
            versao = version(pacote)
        except PackageNotFoundError:
            versao = "não encontrada nos metadados"
        except Exception as erro:
            versao = f"erro ao consultar versão ({type(erro).__name__})"
        LOGGER.info("Dependência: %s=%s", pacote, versao)

    api_key = os.getenv("CAPTCHA_API_KEY")
    if not api_key:
        LOGGER.critical("CAPTCHA_API_KEY não definida; encerrando antes de iniciar o monitoramento.")
        return 1
    api_key_2captcha = os.getenv("CAPTCHA_2CAPTCHA_API_KEY")  # fallback opcional

    LOGGER.info(
        "Configuração carregada: anti-captcha configurado=%s, fallback 2captcha configurado=%s.",
        bool(api_key),
        bool(api_key_2captcha),
    )
    LOGGER.info(
        "Monitorando CDP em %s a cada %ds; retry inicial=%ds, máximo=%ds.",
        CDP_URL,
        INTERVALO_SEGUNDOS,
        INTERVALO_RETRY_INICIAL_SEGUNDOS,
        INTERVALO_RETRY_MAX_SEGUNDOS,
    )
    LOGGER.info("Deixe o script rodando enquanto joga. Ctrl+C para sair.")

    resolucoes = 0
    intervalo_atual = INTERVALO_SEGUNDOS
    numero_ciclo = 0
    estado_anterior = None

    try:
        with sync_playwright() as p:
            LOGGER.info("Playwright iniciado; começando ciclos de monitoramento.")
            while True:
                numero_ciclo += 1
                inicio_ciclo = time.perf_counter()
                resultado_ciclo = "não concluído"
                try:
                    LOGGER.debug(
                        "Ciclo #%d iniciado; intervalo atual=%ds.",
                        numero_ciclo,
                        intervalo_atual,
                    )
                    navegador, pagina = buscar_pagina_captcha(p)

                    if navegador is None:
                        estado = "cdp_indisponível"
                        resultado_ciclo = "CDP indisponível"
                        intervalo_atual = INTERVALO_SEGUNDOS
                    elif pagina is None:
                        estado = "conectado_sem_captcha"
                        resultado_ciclo = "conectado, sem captcha"
                        intervalo_atual = INTERVALO_SEGUNDOS
                    else:
                        estado = "captcha_detectado"

                    if estado != estado_anterior:
                        LOGGER.info("Estado do monitoramento alterado: %s.", estado)
                        estado_anterior = estado

                    if pagina is not None and resolver_captcha(pagina, api_key, api_key_2captcha):
                        resolucoes += 1
                        intervalo_atual = INTERVALO_SEGUNDOS
                        resultado_ciclo = "captcha resolvido e token enviado"
                        LOGGER.info(
                            "Total resolvido nesta sessão: %d; aguardando próximo captcha.",
                            resolucoes,
                        )
                    elif pagina is not None:
                        resultado_ciclo = "captcha não resolvido"
                        intervalo_atual = proximo_intervalo_retry(intervalo_atual)
                        LOGGER.warning("Nova tentativa em %ds.", intervalo_atual)
                except Exception as e:
                    resultado_ciclo = f"erro: {type(e).__name__}"
                    registrar_excecao(
                        f"Erro inesperado no ciclo #{numero_ciclo}",
                        e,
                        api_key,
                        api_key_2captcha,
                    )
                    intervalo_atual = proximo_intervalo_retry(intervalo_atual)
                    LOGGER.warning("Nova tentativa após erro em %ds.", intervalo_atual)

                LOGGER.debug(
                    "Ciclo #%d concluído: resultado=%s, duração=%.3fs, próximo intervalo=%ds.",
                    numero_ciclo,
                    resultado_ciclo,
                    time.perf_counter() - inicio_ciclo,
                    intervalo_atual,
                )
                time.sleep(intervalo_atual)
    except KeyboardInterrupt:
        LOGGER.info(
            "Encerrado pelo usuário. Total resolvido=%d; duração da sessão=%.2fs.",
            resolucoes,
            time.perf_counter() - inicio_sessao,
        )
        return 0
    except Exception as e:
        registrar_excecao(
            "Falha fatal fora do ciclo de monitoramento",
            e,
            api_key,
            api_key_2captcha,
        )
        LOGGER.error(
            "Sessão encerrada por erro fatal após %.2fs; total resolvido=%d.",
            time.perf_counter() - inicio_sessao,
            resolucoes,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
