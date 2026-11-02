"""Shows the QR code the app reads to fill in the server address and the Mangalate key.

Run in server/: py parear.py.  The key only appears on this screen, never in a file or log.
"""
import socket
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
PORT = 5003


def local_address():
    """This computer's address on the Wi-Fi/cable network (no packet is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def pairing_link(address, key):
    """What the QR code holds; the app reads the same format (MangalatePairing)."""
    return "mangalate://parear?" + urlencode({"url": f"http://{address}:{PORT}", "chave": key})


def lan_enabled(root=ROOT):
    try:
        lines = (root / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return "MANGALATE_BIND=0.0.0.0" in (line.strip() for line in lines)


def qr_text(link):
    """The QR code drawn with text blocks; None when the qrcode package is missing."""
    try:
        import qrcode
    except ImportError:
        return None
    import io
    code = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    code.add_data(link)
    out = io.StringIO()
    code.print_ascii(out=out, invert=True)
    return out.getvalue()


def show(root=ROOT, address=None, out=print):
    """Prints the QR code (or what is missing). Returns True when a code was shown."""
    try:
        key = (root / "secrets/mangalate_key.txt").read_text().strip()
    except OSError:
        out("Chave Mangalate não encontrada. Rode py setup.py primeiro.")
        return False
    if not lan_enabled(root):
        out("O servidor só aceita este computador. Para o celular conectar, rode py setup.py e")
        out("responda s em \"Celular na mesma rede Wi-Fi?\".")
        return False
    address = address or local_address()
    if not address:
        out("Não achei o endereço deste computador na rede. Confira se o Wi-Fi ou o cabo está conectado.")
        return False
    drawing = qr_text(pairing_link(address, key))
    if drawing is None:
        out("Para mostrar o QR code, instale o pacote qrcode uma vez e rode de novo:")
        out("  py -m pip install qrcode")
        return False
    out("\nNo app: Mais › Tradução (Mangalate) › Servidor › Ler QR code.")
    out(drawing)
    out(f"Endereço: http://{address}:{PORT}")
    out("Esse código contém a Chave Mangalate: não tire print nem mostre a ninguém.")
    return True


if __name__ == "__main__":
    sys.exit(0 if show() else 1)
