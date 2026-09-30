"""
Cat costa, in bani, consumul de model - si cat e asta din bugetul lunar.

Functii pure: primesc cifrele (tokeni, preturi, buget) si intorc cifre. Nu citesc
config/cost.yaml si nu citesc baza - asta fac adaptoarele, care le dau aici.

VALIDAREA RESPINGE, NU REPARA: daca preturile lipsesc, nu sunt numere, sau sunt ale
altui model decat cel folosit, costul iese None, cu motivul scris. Un cost calculat
cu un pret ghicit ar fi o cifra falsa care arata ca una adevarata.
"""

CHEI_OBLIGATORII = (
    "model",
    "pret_intrare_usd_pe_milion",
    "pret_iesire_usd_pe_milion",
    "buget_lunar_usd",
)


def motivul_pentru_care_nu_se_poate_calcula(config: dict, model_folosit: str):
    """
    None daca preturile se pot folosi pentru `model_folosit`; altfel, motivul, in cuvinte.
    """
    lipsa = [cheie for cheie in CHEI_OBLIGATORII if cheie not in (config or {})]
    if lipsa:
        return "config/cost.yaml lipseste sau n-are: " + ", ".join(lipsa)
    for cheie in CHEI_OBLIGATORII[1:]:
        valoare = config[cheie]
        # bool e si el int in Python; un "true" scris din greseala nu e un pret.
        if isinstance(valoare, bool) or not isinstance(valoare, (int, float)) or valoare < 0:
            return f"config/cost.yaml: `{cheie}` nu e un numar pozitiv"
    if not model_folosit:
        return "MODEL_NORMALIZARE lipseste din .env - nu se stie ce model s-a folosit"
    if config["model"] != model_folosit:
        return (
            f"preturile din config/cost.yaml sunt pentru {config['model']}, "
            f"dar agentul foloseste {model_folosit}"
        )
    return None


def cost_usd(tokeni_intrare: int, tokeni_iesire: int, config: dict, model_folosit: str):
    """Costul in dolari, rotunjit la 4 zecimale, sau None daca preturile nu se pot folosi."""
    if motivul_pentru_care_nu_se_poate_calcula(config, model_folosit):
        return None
    intrare = tokeni_intrare * config["pret_intrare_usd_pe_milion"]
    iesire = tokeni_iesire * config["pret_iesire_usd_pe_milion"]
    return round((intrare + iesire) / 1_000_000, 4)


def situatia_lunii(luna: str, consum: dict, config: dict, model_folosit: str) -> dict:
    """
    Consumul lunii, in tokeni si in bani, fata de buget.

    `consum` are cheile apeluri, tokeni_intrare, tokeni_iesire (cum le da store/db.py).
    Cand costul nu se poate calcula, cheile raman, cu None, iar `motiv` spune de ce.
    """
    situatia = {
        "luna": luna,
        "apeluri": consum["apeluri"],
        "tokeni_intrare": consum["tokeni_intrare"],
        "tokeni_iesire": consum["tokeni_iesire"],
        "cost_usd": None,
        "buget_usd": None,
        "procent_din_buget": None,
        # Cheia API e comuna; restul consumului ei nu trece pe aici.
        "nota": "doar consumul Agent 051; JA.S.Mine foloseste aceeasi cheie si nu apare aici",
    }
    motiv = motivul_pentru_care_nu_se_poate_calcula(config, model_folosit)
    if motiv:
        situatia["motiv"] = motiv
        return situatia

    cost = cost_usd(consum["tokeni_intrare"], consum["tokeni_iesire"], config, model_folosit)
    buget = config["buget_lunar_usd"]
    situatia["cost_usd"] = cost
    situatia["buget_usd"] = buget
    # Un buget de 0 e o alegere legitima ("nu cheltui nimic"), dar nu se imparte la el.
    situatia["procent_din_buget"] = round(100 * cost / buget, 1) if buget else None
    return situatia
