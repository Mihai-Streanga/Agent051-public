"""
Consumul de model, in bani: ce a costat o rulare si cum sta luna fata de buget.

Leaga trei bucati: contorul rularii (adapters/model.py), contoarele din baza
(store/db.py) si preturile din config/cost.yaml (store/configuratie.py). Socoteala
propriu-zisa e in core/cost.py; aici doar se aduna datele si se cheama.

Luna e cea calendaristica, in UTC, ca toate momentele din baza.
"""

from datetime import datetime, timezone

from agent051.adapters.model import ContorCost, model_configurat
from agent051.core.cost import cost_usd, situatia_lunii
from agent051.store.configuratie import incarca_cost
from agent051.store.db import acumuleaza_cost, consum_lunar


def luna_curenta() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def inchide_rularea(contor: ContorCost, dry_run: bool) -> dict:
    """
    Scrie in baza ce a consumat rularea si intoarce cheia `cost` a raportului ei.

    Se scrie DOAR dupa o rulare reala care chiar a apelat modelul: un dry run nu
    cheltuie nimic, iar un model inventat din teste nu atinge contorul.
    """
    if not dry_run and contor.apeluri:
        acumuleaza_cost(
            contor.apeluri, contor.tokeni_intrare, contor.tokeni_iesire, luna_curenta()
        )
    return {
        "apeluri": contor.apeluri,
        "tokeni_intrare": contor.tokeni_intrare,
        "tokeni_iesire": contor.tokeni_iesire,
        "cost_usd": cost_usd(
            contor.tokeni_intrare, contor.tokeni_iesire, incarca_cost(), model_configurat()
        ),
    }


def estimare_usd(apeluri: int, tokeni_intrare_pe_apel: int, tokeni_iesire_pe_apel: int):
    """
    Estimarea grosiera a unui dry run, cu preturile din config/cost.yaml.

    None daca preturile nu se pot folosi - atunci nici estimarea nu se poate face.
    """
    return cost_usd(
        apeluri * tokeni_intrare_pe_apel,
        apeluri * tokeni_iesire_pe_apel,
        incarca_cost(),
        model_configurat(),
    )


def in_dolari(valoare) -> str:
    """O suma de afisat pe ecran; None iese in cuvinte, nu ca "$0"."""
    if valoare is None:
        return "necunoscut (vezi config/cost.yaml)"
    return f"${valoare:.4f}"


def rand_despre_luna(luna: dict) -> str:
    """Situatia lunii, pe un rand de ecran, pentru scripturile din linia de comanda."""
    rand = (
        f"Luna {luna['luna']}: {in_dolari(luna['cost_usd'])} "
        f"din bugetul de {in_dolari(luna['buget_usd'])}"
    )
    if luna["procent_din_buget"] is not None:
        rand += f" ({luna['procent_din_buget']}%)"
    return rand + " - doar Agent 051, fara JA.S.Mine."


def situatia_lunii_curente() -> dict:
    """Consumul lunii de acum, in tokeni si in dolari, fata de bugetul din config/cost.yaml."""
    luna = luna_curenta()
    return situatia_lunii(luna, consum_lunar(luna), incarca_cost(), model_configurat())
