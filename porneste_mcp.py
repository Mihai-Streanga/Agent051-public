r"""
Porneste serverul MCP al Agent 051.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe porneste_mcp.py

Serverul ramane pornit pana il opresti cu Ctrl+C. Cat timp merge, JA.S.Mine se poate
conecta la el si poate chema uneltele.

CE EXPUNE: zece unelte, in trei feluri.
  - sapte deterministe si gratuite: briefing, oportunitati_noi, cauta, stare_pipeline,
    ingesteaza, extrage, filtreaza;
  - una care iese in lume pe gratis: descrie() - nu cheama niciun model, dar cere pagini
    de pe serverul altcuiva, cu pauza intre cereri. Moneda e rabdarea, nu banii;
  - doua care CHEAMA MODELUL si COSTA bani la fiecare apel: normalizeaza(), evalueaza().
    Alea au nevoie de ANTHROPIC_API_KEY in .env - de aia pornirea spune daca cheia e
    acolo. Fara ea, serverul porneste si merge, dar cele doua esueaza abia cand le
    cheama cineva.

descrie() e cea mai noua (16 august 2026). Pana atunci uneltele erau noua, iar completarea
descrierilor nu se putea cere prin MCP deloc.

UNDE ASCULTA: pe 0.0.0.0, adica pe toate interfetele, nu doar pe localhost. E necesar
fiindca clientul ruleaza in Docker, iar de acolo "localhost" inseamna containerul.
Consecinta: serverul e vizibil pe toata reteaua locala - de aia MCP_TOKEN e OBLIGATORIU.
Fara el, serverul refuza sa porneasca si spune de ce. Vezi .env.example.

Fisierul asta e doar linia de comanda. Nicio logica aici.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import uvicorn

from agent051.adapters.mcp_server import (
    CALE_MCP,
    MESAJ_FARA_TOKEN,
    construieste_aplicatia,
    host_configurat,
    port_configurat,
    token_configurat,
)
from agent051.adapters.model import cheie_prezenta


def main() -> int:
    # Verificarea vine INAINTEA bannerului. Altfel ecranul ar scrie „server deschis",
    # iar o clipa mai tarziu serverul ar refuza sa porneasca — un ecran care afirma
    # ceva neadevarat e defect, nu aproximare.
    if token_configurat() is None:
        print()
        print("  Agent 051 - REFUZ SA PORNESC")
        print()
        for rand in MESAJ_FARA_TOKEN.splitlines():
            print(("  " + rand) if rand else "")
        print()
        return 1

    host = host_configurat()
    port = port_configurat()
    are_cheie = cheie_prezenta()

    print()
    print("  Agent 051 - server MCP (10 unelte: 7 deterministe + descrie + 2 cu model)")
    print(f"  Endpoint:       http://{host}:{port}{CALE_MCP}")
    if host == "0.0.0.0":
        print(f"  Din alt calculator sau din Docker, inlocuieste 0.0.0.0 cu IP-ul masinii.")
    # Fara ramura „NU": pana aici nu se ajunge fara token.
    print("  Autentificare:  DA (Bearer token)")
    print(f"  Cheie model:    {'DA - normalizeaza() si evalueaza() COSTA bani la fiecare apel' if are_cheie else 'NU - ANTHROPIC_API_KEY lipseste din .env'}")
    if not are_cheie:
        print("                  normalizeaza() si evalueaza() vor esua la primul apel.")
        print("                  Celelalte opt unelte merg normal.")
    print()
    print("  Ctrl+C pentru oprire.")
    print()

    uvicorn.run(construieste_aplicatia(), host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
