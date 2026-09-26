"""
Diagnostico rapido do WebView do MuAwaY no emulador. Roda uma vez e termina.

Mostra:
    1. Se o ADB conecta no emulador
    2. Processos do app e sockets de depuracao (por PID)
    3. Forward de cada socket para uma porta local (9223+)
    4. Quais paginas cada porta enxerga via CDP (e se acha o captcha)

Uso:
    .venv\\Scripts\\python -u debug_mobile.py
"""
import re
import subprocess
import sys
import urllib.request

ADB = r"C:\Program Files\BlueStacks_msi5\HD-Adb.exe"
EMULADOR = "127.0.0.1:5555"
PORTA_BASE = 9223
DOMINIO_CAPTCHA = "webview.muaway.net"


def adb(*args):
    return subprocess.run([ADB, *args], capture_output=True, text=True, timeout=30)


def main():
    print("=== 1. Testando conexao ADB ===")
    r = adb("connect", EMULADOR)
    print(r.stdout.strip() or r.stderr.strip())
    devs = adb("devices").stdout
    print(devs.strip())
    if EMULADOR not in devs or "offline" in devs:
        print("\n[ERRO] Emulador nao conectado. Ative o ADB nas config do BlueStacks.")
        sys.exit(1)

    print("\n=== 2. Processos do app ===")
    ps = adb("shell", "ps -A").stdout
    linhas = [l for l in ps.splitlines() if "muway" in l]
    if not linhas:
        print("[ERRO] Jogo nao esta rodando no emulador.")
    for l in linhas:
        print(l.strip())

    print("\n=== 3. Sockets de depuracao ===")
    unix = adb("shell", "cat /proc/net/unix").stdout
    sockets = []
    for nome in re.findall(r"(?:chrome|webview)_devtools_remote_\d+", unix):
        s = f"localabstract:{nome}"
        if s not in sockets:
            sockets.append(s)
    if not sockets:
        print("[ERRO] Nenhum socket de depuracao. Abra a tela do captcha no jogo.")
    for s in sockets:
        pid = re.search(r"_(\d+)$", s).group(1)
        dono = adb("shell", f"cat /proc/{pid}/cmdline").stdout.strip() or "?"
        print(f"  {s}  (dono: {dono})")

    print("\n=== 4. Forward + consulta CDP de cada socket ===")
    forwards = adb("forward", "--list").stdout
    for i, socket in enumerate(sockets):
        porta = PORTA_BASE + i
        if f"tcp:{porta} {socket}" not in forwards:
            if f"tcp:{porta}" in forwards:
                adb("forward", "--remove", f"tcp:{porta}")
            adb("forward", f"tcp:{porta}", socket)
        try:
            dados = urllib.request.urlopen(f"http://localhost:{porta}/json/list", timeout=8).read().decode()
        except Exception as e:
            print(f"  tcp:{porta} -> {socket}: ERRO {e}")
            continue
        alvos = re.findall(r'"url": "(.*?)"', dados)
        print(f"  tcp:{porta} -> {socket}")
        if not alvos:
            print("    (nenhuma pagina)")
        achou = False
        for url in alvos:
            marca = "  <<<< CAPTCHA AQUI!" if DOMINIO_CAPTCHA in url else ""
            if marca:
                achou = True
            print(f"    pagina: {url}{marca}")
        if achou:
            print(f"\n[OK] Captcha acessivel pela porta {porta}. O main_mobile.py resolveria agora.")

    print("\n=== Fim do diagnostico ===")


if __name__ == "__main__":
    main()
