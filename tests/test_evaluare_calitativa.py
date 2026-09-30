r"""
Teste pentru evaluarea calitativa - capetele pure (core) si orchestrarea (adapter).

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

UITA-TE CE NU E AICI.
Niciun apel catre vreun model. Nicio cheie de API. Nicio adresa de internet. Nicio
baza de date. Modelul se INJECTEAZA ca functie (str) -> str: mai jos e o galerie de
modele inventate, unul corect si mai multe feluri de a gresi. Iar lotul se testeaza cu
o lista de anunturi si un `salveaza` care doar noteaza - deci fara disc.

CE VERIFICA, DE FAPT, FIECARE TEST:
1. ca un raspuns prost al modelului NU trece de valideaza deghizat in raspuns bun;
2. ca modelul PRIMESTE criteriile calitative, dar NU pragul salarial sau locatia;
3. ca un anunt respins de filtrul dur NU ajunge la model (nu risipim tokeni);
4. ca modelul e chemat exact o data per anunt;
5. ca relevanta are TREI trepte (ideal / bun_in_domeniu / exclus), ca modelul le vede pe
   toate trei descrise, si ca orice alta valoare - inclusiv "da"/"nu" de pe scala veche -
   e respinsa, nu tradusa.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.adapters.evaluare_calitativa import (
    alege_anunturile,
    evalueaza_anunt,
    evalueaza_lotul,
)
from agent051.adapters.model import EroareInfrastructura
from agent051.core.evaluare_calitativa import (
    CAMPURI_OBLIGATORII,
    TREPTE_RELEVANTA,
    construieste_prompt_calitativ,
    valideaza_calitativ,
)

# Felia calitativa, in forma pe care o intoarce store.configuratie.criterii_calitative.
# Cu valori proprii, ca testele sa nu depinda de ce scrie in criterii.yaml.
CRITERII = {
    "tinta": "Aplicarea AI si automatizarii pe procese de payroll / HR-Ops.",
    "traiectorie": {"A_acum": "AI + automatizare IN payroll."},
    "trepte": {
        "ideal": {
            "descriere": "AI si automatizare pe procese de HR-Ops.",
            "exemple": ["Payroll Transformation Specialist"],
        },
        "bun_in_domeniu": {
            "descriere": "Rol senior in domeniu, fara componenta de automatizare.",
            "exemple": ["Senior HR Generalist", "Payroll Manager"],
            "nota": "Expertiza conteaza acolo din prima zi.",
        },
        "exclus": {
            "descriere": "Executie repetitiva.",
            "exemple": ["payroll clerk", "data entry"],
        },
    },
    "exclus": [
        {"rol": "executie payroll clasica", "motiv": "repetitiv, automatizabil"},
        {"rol": "programator pur", "motiv": "fara domeniu, e un junior"},
    ],
    "semnale_pozitive": ["construieste ceva, nu opereaza ceva", "se invata ceva"],
    "semnale_negative": ["volum mare, termene dure, zero autonomie"],
}

ANUNT = {
    "titlu": "Payroll Transformation Specialist",
    "firma": "Firma Inventata SRL",
    "descriere": "Automatizezi procese de salarizare, construiesti validari noi.",
    "verdict": "trece",
}

RASPUNS_BUN = """{
    "relevant": "ideal",
    "motiv_relevanta": "Rol de automatizare in payroll, exact tinta.",
    "interes": "ridicat",
    "motiv_interes": "Construieste validari, nu opereaza doar.",
    "single_point_of_failure": "nu",
    "motiv_spof": "Nu apare vreun cutoff cu o singura persoana responsabila."
}"""

# Treapta din mijloc: rol senior in domeniu, fara automatizare. Pe scala binara de
# dinainte, asta primea "nu" si disparea din briefing - motivul pentru care exista 1.2.
RASPUNS_TREAPTA_MIJLOC = """{
    "relevant": "bun_in_domeniu",
    "motiv_relevanta": "Rol senior de HR in domeniu, dar fara componenta de automatizare.",
    "interes": "mediu",
    "motiv_interes": "Opereaza procese existente, cu ceva spatiu de imbunatatit.",
    "single_point_of_failure": "nu",
    "motiv_spof": "Echipa are mai multi oameni pe aceleasi procese."
}"""


# ---------------------------------------------------------------------------
# Galeria de modele inventate. Fiecare e o functie (str) -> str.
# ---------------------------------------------------------------------------

def model_corect(prompt: str) -> str:
    return RASPUNS_BUN


def model_treapta_mijloc(prompt: str) -> str:
    return RASPUNS_TREAPTA_MIJLOC


def model_fara_spof(prompt: str) -> str:
    """JSON valid, dar ii lipseste single_point_of_failure."""
    return """{
        "relevant": "ideal",
        "motiv_relevanta": "Rol de payroll.",
        "interes": "ridicat",
        "motiv_interes": "Construieste ceva."
    }"""


def model_cu_interes_inventat(prompt: str) -> str:
    """"foarte mare" nu e in enum-ul permis pentru interes."""
    return """{
        "relevant": "ideal",
        "motiv_relevanta": "Rol de payroll.",
        "interes": "foarte mare",
        "motiv_interes": "Suna excelent.",
        "single_point_of_failure": "nu",
        "motiv_spof": "Nu pare."
    }"""


def model_cu_treapta_inventata(prompt: str) -> str:
    """"foarte_potrivit" nu e o treapta. Nu se traduce in "ideal" - se respinge."""
    return """{
        "relevant": "foarte_potrivit",
        "motiv_relevanta": "Rol de automatizare in payroll.",
        "interes": "ridicat",
        "motiv_interes": "Construieste ceva.",
        "single_point_of_failure": "nu",
        "motiv_spof": "Nu pare."
    }"""


def model_cu_relevanta_binara(prompt: str) -> str:
    """
    Raspunde pe scala VECHE, da/nu. E tot o valoare inventata fata de contractul de azi.

    Cazul asta e cel mai perfid dintre toate: "da" arata a raspuns bun, exista in baza pe
    randuri scrise inainte de 1.2, si ar fi tentant sa fie "tradus" in "ideal". Nu se
    traduce. Un model care nu a inteles scala trebuie sa se vada, nu sa fie reparat.
    """
    return """{
        "relevant": "da",
        "motiv_relevanta": "Se potriveste.",
        "interes": "ridicat",
        "motiv_interes": "Construieste ceva.",
        "single_point_of_failure": "nu",
        "motiv_spof": "Nu pare."
    }"""


def model_cu_json_stricat(prompt: str) -> str:
    """A uitat o virgula intre campuri."""
    return '{"relevant": "ideal" "interes": "ridicat"}'


def model_politicos(prompt: str) -> str:
    """Raspunsul bun, dar impachetat in amabilitati si bloc de cod."""
    return "Sigur! Iata evaluarea:\n\n```json\n" + RASPUNS_BUN + "\n```\nSper ca ajuta!"


def model_gol(prompt: str) -> str:
    return ""


def model_infrastructura_picata(prompt: str) -> str:
    """Drumul catre model rupt (biblioteca lipsa, cheie respinsa). NU o respingere."""
    raise EroareInfrastructura("biblioteca `anthropic` nu e instalata")


# ===========================================================================
# CORE: construieste_prompt_calitativ
# ===========================================================================

class TestConstruiestePrompt(unittest.TestCase):

    def test_promptul_contine_anuntul_si_criteriile(self):
        """Modelul trebuie sa vada si anuntul, si tinta - altfel n-are ce judeca."""
        prompt = construieste_prompt_calitativ(ANUNT, CRITERII)

        self.assertIn("Payroll Transformation Specialist", prompt)
        self.assertIn("Firma Inventata SRL", prompt)
        self.assertIn("automatizarii pe procese de payroll", prompt)
        self.assertIn("executie payroll clasica", prompt)
        self.assertIn("construieste ceva, nu opereaza ceva", prompt)

    def test_promptul_cere_toate_campurile(self):
        """Fiecare camp validat trebuie si cerut in prompt, altfel raspunsul cade mereu."""
        prompt = construieste_prompt_calitativ(ANUNT, CRITERII)

        for camp in CAMPURI_OBLIGATORII:
            self.assertIn(camp, prompt)

    def test_promptul_descrie_toate_cele_trei_trepte(self):
        """
        Modelul trebuie sa vada si NUMELE treptei, si ce inseamna ea.

        Numai numele n-ar ajunge: "bun_in_domeniu" nu spune de la sine ca acopera un
        Senior HR Generalist fara automatizare - exact confuzia care a produs verdictele
        gresite pe scala binara.
        """
        prompt = construieste_prompt_calitativ(ANUNT, CRITERII)

        for treapta in TREPTE_RELEVANTA:
            self.assertIn(treapta, prompt)

        self.assertIn("Rol senior in domeniu, fara componenta de automatizare", prompt)
        self.assertIn("Senior HR Generalist", prompt)
        self.assertIn("Executie repetitiva", prompt)

    def test_treptele_apar_in_ordinea_din_cod_nu_din_fisier(self):
        """
        Ordinea e ideal -> bun_in_domeniu -> exclus, oricum ar fi asezate in criterii.yaml.

        Altfel o rearanjare a fisierului ar schimba promptul fara sa schimbe criteriile,
        si aceleasi date ar putea da doua raspunsuri.
        """
        pe_dos = dict(CRITERII)
        pe_dos["trepte"] = {
            "exclus": CRITERII["trepte"]["exclus"],
            "bun_in_domeniu": CRITERII["trepte"]["bun_in_domeniu"],
            "ideal": CRITERII["trepte"]["ideal"],
        }

        prompt = construieste_prompt_calitativ(ANUNT, pe_dos)
        pozitii = [prompt.index(f'"{treapta}":') for treapta in TREPTE_RELEVANTA]

        self.assertEqual(pozitii, sorted(pozitii))

    def test_treptele_lipsa_din_fisier_apar_totusi_ca_valori(self):
        """
        Fisier fara sectiunea `trepte`: numele treptelor tot trebuie sa ajunga in prompt.

        Sunt valorile permise in raspuns. Daca modelul ar vedea doar doua din trei, ar
        alege dintre doua, iar validarea ar respinge degeaba - un apel platit, aruncat.
        """
        fara_trepte = {k: v for k, v in CRITERII.items() if k != "trepte"}
        prompt = construieste_prompt_calitativ(ANUNT, fara_trepte)

        for treapta in TREPTE_RELEVANTA:
            self.assertIn(treapta, prompt)

    def test_promptul_NU_contine_salariu_sau_locatie(self):
        """
        Miezul separarii dintre straturi: modelul primeste DOAR felia calitativa.
        Pragul salarial si locatia sunt constrangeri dure - le-a rezolvat filtrul, si
        modelul nu are voie sa le recantareasca. Daca ar aparea aici, un rol "interesant"
        ar putea "scuza" un salariu mic. Nu.
        """
        criterii_cu_zgomot = dict(CRITERII)
        prompt = construieste_prompt_calitativ(ANUNT, criterii_cu_zgomot)

        jos = prompt.lower()
        self.assertNotIn("prag", jos)
        self.assertNotIn("5000", jos)
        self.assertNotIn("salariu", jos)
        self.assertNotIn("locatie", jos)

    def test_anuntul_incomplet_nu_crapa(self):
        """Fara firma sau descriere, tot iese un prompt utilizabil."""
        prompt = construieste_prompt_calitativ({"titlu": "Payroll Officer"}, CRITERII)

        self.assertIn("Payroll Officer", prompt)
        self.assertIn("(fara descriere)", prompt)

    def test_criteriile_goale_nu_crapa(self):
        """Felie calitativa goala (fisier incomplet) -> prompt cu note, nu o eroare."""
        prompt = construieste_prompt_calitativ(ANUNT, {})

        self.assertIn("Payroll Transformation Specialist", prompt)
        self.assertIn("(niciunul precizat)", prompt)


# ===========================================================================
# CORE: valideaza_calitativ
# ===========================================================================

class TestValideaza(unittest.TestCase):

    def test_raspunsul_bun_e_acceptat(self):
        rezultat = valideaza_calitativ(RASPUNS_BUN)

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["relevant"], "ideal")
        self.assertEqual(rezultat["date"]["interes"], "ridicat")
        self.assertEqual(rezultat["date"]["single_point_of_failure"], "nu")

    def test_treapta_din_mijloc_e_acceptata(self):
        """Miezul lui 1.2: "bun_in_domeniu" e un raspuns valid, nu o eroare."""
        rezultat = valideaza_calitativ(RASPUNS_TREAPTA_MIJLOC)

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["relevant"], "bun_in_domeniu")

    def test_toate_cele_trei_trepte_plus_incert_sunt_acceptate(self):
        """Fiecare valoare din contract trece. Daca una ar cadea, s-ar pierde in tacere."""
        for valoare in TREPTE_RELEVANTA + ("incert",):
            with self.subTest(relevant=valoare):
                rezultat = valideaza_calitativ(
                    """{
                        "relevant": "%s",
                        "motiv_relevanta": "ok",
                        "interes": "mediu",
                        "motiv_interes": "ok",
                        "single_point_of_failure": "nu",
                        "motiv_spof": "ok"
                    }""" % valoare
                )
                self.assertTrue(rezultat["ok"], rezultat.get("eroare"))
                self.assertEqual(rezultat["date"]["relevant"], valoare)

    def test_treapta_inventata_e_respinsa(self):
        """"foarte_potrivit" nu e o treapta. Nu il apropiem de "ideal" - cade tot."""
        rezultat = valideaza_calitativ(model_cu_treapta_inventata(""))

        self.assertFalse(rezultat["ok"])
        self.assertIn("foarte_potrivit", rezultat["eroare"])
        self.assertIn("relevant", rezultat["eroare"])

    def test_relevanta_pe_scala_veche_e_respinsa(self):
        """
        "da" era valid pe criteriile 1.1. Azi nu mai e, si NU se traduce in "ideal".

        Traducerea ar parea inofensiva - "da" chiar insemna treapta de sus - dar ar
        insemna ca in baza intra o treapta pe care modelul n-a ales-o, imposibil de
        deosebit peste doua luni de una aleasa. Randurile vechi raman ce sunt; raspunsurile
        noi respecta contractul nou.
        """
        for valoare_veche in ("da", "nu"):
            with self.subTest(relevant=valoare_veche):
                rezultat = valideaza_calitativ(
                    model_cu_relevanta_binara("").replace('"da"', f'"{valoare_veche}"', 1)
                )
                self.assertFalse(rezultat["ok"])
                self.assertIn("relevant", rezultat["eroare"])

    def test_campul_lipsa_e_respins(self):
        """Fara single_point_of_failure, raspunsul cade intreg. Nu-l completam noi."""
        rezultat = valideaza_calitativ(model_fara_spof(""))

        self.assertFalse(rezultat["ok"])
        self.assertIn("single_point_of_failure", rezultat["eroare"])

    def test_valoarea_inventata_e_respinsa(self):
        """"foarte mare" nu e in enum. Nu il traducem in "ridicat" - raspunsul cade."""
        rezultat = valideaza_calitativ(model_cu_interes_inventat(""))

        self.assertFalse(rezultat["ok"])
        self.assertIn("foarte mare", rezultat["eroare"])

    def test_json_stricat_e_respins_fara_sa_crape(self):
        """O virgula lipsa iese ca respingere, nu ca exceptie."""
        rezultat = valideaza_calitativ(model_cu_json_stricat(""))

        self.assertFalse(rezultat["ok"])
        self.assertIn("JSON invalid", rezultat["eroare"])

    def test_json_impachetat_in_text_e_extras_curat(self):
        """"Sigur! Iata:" + bloc de cod: desfacem ambalajul si acceptam continutul."""
        rezultat = valideaza_calitativ(model_politicos(""))

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["interes"], "ridicat")

    def test_raspunsul_gol_e_respins(self):
        for gol in ("", "   ", None):
            with self.subTest(raspuns=repr(gol)):
                self.assertFalse(valideaza_calitativ(gol)["ok"])

    def test_textul_fara_json_e_respins(self):
        """Model care raspunde in proza. Nu citim printre randuri."""
        rezultat = valideaza_calitativ("Nu pot evalua acest anunt.")

        self.assertFalse(rezultat["ok"])

    def test_campul_motiv_gol_e_respins(self):
        """Un motiv prezent dar gol e ca si cum ar lipsi. Nu intra in baza cu 'ok'."""
        rezultat = valideaza_calitativ(
            """{
                "relevant": "ideal",
                "motiv_relevanta": "   ",
                "interes": "ridicat",
                "motiv_interes": "ok",
                "single_point_of_failure": "nu",
                "motiv_spof": "ok"
            }"""
        )

        self.assertFalse(rezultat["ok"])

    def test_campurile_in_plus_nu_intra_in_date(self):
        """Schema e a noastra. Un camp in plus nu strica, dar nici nu se salveaza."""
        rezultat = valideaza_calitativ(
            """{
                "relevant": "ideal",
                "motiv_relevanta": "ok",
                "interes": "ridicat",
                "motiv_interes": "ok",
                "single_point_of_failure": "nu",
                "motiv_spof": "ok",
                "scor_inventat": 42
            }"""
        )

        self.assertTrue(rezultat["ok"])
        self.assertNotIn("scor_inventat", rezultat["date"])


# ===========================================================================
# ADAPTER: evalueaza_anunt (un anunt) si evalueaza_lotul (mai multe)
# ===========================================================================

class TestEvalueazaAnunt(unittest.TestCase):

    def test_modelul_corect_produce_date(self):
        rezultat = evalueaza_anunt(ANUNT, CRITERII, model_corect)

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["relevant"], "ideal")

    def test_treapta_din_mijloc_ajunge_intreaga_la_capat(self):
        """Un "bun_in_domeniu" trece tot lantul prompt -> model -> validare, nemodificat."""
        rezultat = evalueaza_anunt(ANUNT, CRITERII, model_treapta_mijloc)

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["relevant"], "bun_in_domeniu")

    def test_raspunsurile_proaste_de_continut_sunt_respinse(self):
        """Raspuns prost (modelul a raspuns, dar gresit) = respingere de continut, salvata."""
        for nume, model in {
            "json stricat": model_cu_json_stricat,
            "camp lipsa": model_fara_spof,
            "valoare inventata": model_cu_interes_inventat,
            "treapta inventata": model_cu_treapta_inventata,
            "relevanta pe scala veche": model_cu_relevanta_binara,
            "raspuns gol": model_gol,
        }.items():
            with self.subTest(model=nume):
                rezultat = evalueaza_anunt(ANUNT, CRITERII, model)
                self.assertFalse(rezultat["ok"])
                self.assertNotIn("date", rezultat)
                self.assertTrue(rezultat["eroare"])

    def test_esecul_de_infrastructura_PROPAGA_nu_se_preface_in_respins(self):
        """Infrastructura picata iese in sus, nu se preface in 'respins'. Vezi normalizare."""
        with self.assertRaises(EroareInfrastructura):
            evalueaza_anunt(ANUNT, CRITERII, model_infrastructura_picata)

    def test_modelul_e_chemat_o_singura_data(self):
        """Un anunt = un apel. Fara reincercari ascunse, care ar dubla nota de plata."""
        apeluri = []

        def model_care_numara(prompt: str) -> str:
            apeluri.append(prompt)
            return RASPUNS_BUN

        evalueaza_anunt(ANUNT, CRITERII, model_care_numara)

        self.assertEqual(len(apeluri), 1)


class TestEvalueazaLotul(unittest.TestCase):

    def _salveaza_noteaza(self, jurnal):
        """Un `salveaza` fals, care doar tine minte ce s-a salvat. Fara disc."""
        def salveaza(anunt_id, rezultat, versiune):
            jurnal.append((anunt_id, rezultat, versiune))
        return salveaza

    def test_anuntul_respins_de_filtru_NU_ajunge_la_model(self):
        """
        Testul-cheie al bucatii: modelul costa, deci nu-l chemam pe ce a taiat deja o
        regula certa. Un anunt cu verdict "respins" e sarit; nu i se construieste prompt
        si nu i se cheama modelul.
        """
        anunturi = [
            {"id": "a-trece", "titlu": "Payroll Automation", "verdict": "trece"},
            {"id": "a-incert", "titlu": "HR Systems", "verdict": "incert"},
            {"id": "a-respins", "titlu": "Payroll cu on-call", "verdict": "respins"},
        ]
        vazute = []

        def model_care_numara(prompt: str) -> str:
            vazute.append(prompt)
            return RASPUNS_BUN

        jurnal = []
        raport = evalueaza_lotul(
            anunturi, CRITERII, model_care_numara, self._salveaza_noteaza(jurnal), "test"
        )

        # Modelul a fost chemat exact de doua ori: pentru trece si incert, nu si respins.
        self.assertEqual(len(vazute), 2)
        self.assertEqual(raport["evaluate"], 2)
        self.assertEqual(raport["sarite_respins"], 1)
        # Anuntul respins nu apare nici in ce s-a salvat.
        ids_salvate = {rand[0] for rand in jurnal}
        self.assertNotIn("a-respins", ids_salvate)
        self.assertEqual(ids_salvate, {"a-trece", "a-incert"})

    def test_un_apel_de_model_per_anunt_evaluat(self):
        """Doua anunturi eligibile -> exact doua apeluri. Fara reincercari ascunse."""
        anunturi = [
            {"id": "a1", "titlu": "Payroll Automation", "verdict": "trece"},
            {"id": "a2", "titlu": "HR Systems", "verdict": "incert"},
        ]
        apeluri = []

        def model_care_numara(prompt: str) -> str:
            apeluri.append(prompt)
            return RASPUNS_BUN

        evalueaza_lotul(
            anunturi, CRITERII, model_care_numara, self._salveaza_noteaza([]), "test"
        )

        self.assertEqual(len(apeluri), 2)

    def test_raportul_numara_verdictele_valide(self):
        """Raportul aduna distributia verdictelor, ca la filtrare. Modelul respins nu intra."""
        anunturi = [
            {"id": "a1", "titlu": "x", "verdict": "trece"},
            {"id": "a2", "titlu": "y", "verdict": "trece"},
        ]

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_corect, self._salveaza_noteaza([]), "1.2"
        )

        self.assertEqual(raport["ok"], 2)
        self.assertEqual(raport["respinse_model"], 0)
        self.assertEqual(raport["verdicte"]["relevant"]["ideal"], 2)
        self.assertEqual(raport["versiune_criterii"], "1.2")

    def test_raportul_numara_treptele_separat(self):
        """
        Distributia pe relevanta trebuie sa distinga treptele, nu doar "bun/prost".

        E numaratoarea din care se vede daca 1.2 chiar a schimbat ceva: cate anunturi
        pica pe treapta din mijloc, adica exact cele pe care scala binara le arunca.
        """
        anunturi = [
            {"id": "a1", "titlu": "x", "verdict": "trece"},
            {"id": "a2", "titlu": "y", "verdict": "trece"},
        ]
        raspunsuri = iter([RASPUNS_BUN, RASPUNS_TREAPTA_MIJLOC])

        raport = evalueaza_lotul(
            anunturi, CRITERII, lambda prompt: next(raspunsuri),
            self._salveaza_noteaza([]), "1.2",
        )

        self.assertEqual(raport["verdicte"]["relevant"]["ideal"], 1)
        self.assertEqual(raport["verdicte"]["relevant"]["bun_in_domeniu"], 1)

    def test_limita_opreste_la_N(self):
        """Cu limita 2 si 4 anunturi eligibile, modelul vede cel mult 2. Restul asteapta."""
        anunturi = [
            {"id": f"a{i}", "titlu": "x", "verdict": "trece"} for i in range(4)
        ]
        apeluri = []

        def model_care_numara(prompt: str) -> str:
            apeluri.append(prompt)
            return RASPUNS_BUN

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_care_numara, self._salveaza_noteaza([]),
            "test", limita=2, dry_run=False,
        )

        self.assertEqual(len(apeluri), 2)
        self.assertEqual(raport["evaluate"], 2)
        self.assertEqual(raport["de_procesat"], 4)
        self.assertEqual(raport["oprite_de_limita"], 2)

    def test_dry_run_NU_cheama_modelul(self):
        """
        Dry run calculeaza cate ar merge la model, dar nu atinge modelul.

        Model care explodeaza daca e chemat: daca dry run-ul l-ar atinge, testul pica.
        """
        def model_care_explodeaza(prompt: str) -> str:
            raise AssertionError("modelul a fost chemat in dry run")

        anunturi = [
            {"id": "a1", "titlu": "x", "verdict": "trece"},
            {"id": "a2", "titlu": "y", "verdict": "incert"},
        ]
        jurnal = []

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_care_explodeaza, self._salveaza_noteaza(jurnal),
            "test", limita=50, dry_run=True,
        )

        self.assertEqual(raport["evaluate"], 0)
        self.assertEqual(jurnal, [])
        self.assertTrue(raport["dry_run"])
        self.assertEqual(raport["de_procesat"], 2)

    def test_esecul_de_infrastructura_opreste_lotul(self):
        """Infrastructura picata opreste lotul la primul apel; nimic marcat respins."""
        anunturi = [
            {"id": "a1", "titlu": "x", "verdict": "trece"},
            {"id": "a2", "titlu": "y", "verdict": "incert"},
        ]
        apeluri = []

        def model_care_pica_infra(prompt: str) -> str:
            apeluri.append(prompt)
            raise EroareInfrastructura("biblioteca `anthropic` nu e instalata")

        jurnal = []
        raport = evalueaza_lotul(
            anunturi, CRITERII, model_care_pica_infra, self._salveaza_noteaza(jurnal),
            "test", limita=50, dry_run=False,
        )

        self.assertEqual(len(apeluri), 1)
        self.assertEqual(raport["evaluate"], 0)
        self.assertEqual(raport["respinse_model"], 0)
        self.assertEqual(jurnal, [])
        self.assertEqual(raport["esuate_infrastructura"], 1)
        self.assertIn("anthropic", raport["esec_infrastructura"])


class TestCostulEsecurilorRepetateSeVede(unittest.TestCase):
    """
    Datoria din 17 august 2026: un anunt care refuza sa raspunda cu JSON valid e eligibil
    la fiecare rulare urmatoare - deliberat - dar costul lui era invizibil in raport.

    Un anunt real din arhiva ("Talent and Engagement Specialist") a mancat 4.483 de tokeni
    pe o rulare care n-a produs nimic altceva: zero anunturi noi, zero verdicte noi. Nimic
    din raport nu spunea "am platit iar pentru asta", si cheltuiala nu scade si nu se
    plafoneaza de la sine.

    Ce se repara AICI e vizibilitatea, nu comportamentul: nu se opreste nimic. Un plafon
    de incercari pus in tacere ar ascunde chiar informatia pentru care se plateste.
    """

    def _salveaza_noteaza(self, jurnal):
        def salveaza(anunt_id, rezultat, versiune):
            jurnal.append((anunt_id, rezultat, versiune))
        return salveaza

    def test_raportul_spune_de_cate_ori_a_esuat_fiecare_anunt(self):
        anunturi = [
            {"id": "incapatanat", "titlu": "Talent and Engagement Specialist",
             "verdict": "trece", "incercari_esuate": 2},
        ]

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_cu_json_stricat, self._salveaza_noteaza([]),
            "test", dry_run=False,
        )

        self.assertEqual(raport["respinse_model"], 1)
        self.assertEqual(len(raport["esecuri_pe_anunt"]), 1)
        esec = raport["esecuri_pe_anunt"][0]
        self.assertEqual(esec["anunt_id"], "incapatanat")
        self.assertEqual(esec["titlu"], "Talent and Engagement Specialist")
        # Doua esecuri in baza plus cel de acum: cifra CRESTE la fiecare rulare, si de aia
        # se vede. Un "1 respins" ar fi aratat la fel la prima si la a zecea.
        self.assertEqual(esec["incercari"], 3)

    def test_anuntul_care_esueaza_prima_data_porneste_de_la_unu(self):
        """Fara nicio istorie in baza, primul esec e 1 - nu 0 si nu 2."""
        anunturi = [{"id": "nou", "titlu": "HR Systems", "verdict": "trece"}]

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_cu_json_stricat, self._salveaza_noteaza([]),
            "test", dry_run=False,
        )

        self.assertEqual(raport["esecuri_pe_anunt"][0]["incercari"], 1)

    def test_anuntul_care_raspunde_bine_nu_apare_in_lista(self):
        """Lista e despre ce s-a platit degeaba, nu despre tot ce s-a evaluat."""
        anunturi = [{"id": "bun", "titlu": "Payroll Automation", "verdict": "trece"}]

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_corect, self._salveaza_noteaza([]),
            "test", dry_run=False,
        )

        self.assertEqual(raport["ok"], 1)
        self.assertEqual(raport["esecuri_pe_anunt"], [])

    def test_cele_mai_incapatanate_sunt_primele(self):
        """
        Ordinea nu e cosmetica: un anunt la a cincea respingere e o informatie despre
        prompt, unul la prima e o zi proasta. La egalitate, id-ul - ca doua rulari pe
        aceleasi date sa dea acelasi raport.
        """
        anunturi = [
            {"id": "b-o-data", "titlu": "Unu", "verdict": "trece", "incercari_esuate": 0},
            {"id": "a-de-multe", "titlu": "Multe", "verdict": "trece",
             "incercari_esuate": 4},
            {"id": "a-o-data", "titlu": "Unu bis", "verdict": "trece",
             "incercari_esuate": 0},
        ]

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_cu_json_stricat, self._salveaza_noteaza([]),
            "test", dry_run=False,
        )

        self.assertEqual(
            [e["anunt_id"] for e in raport["esecuri_pe_anunt"]],
            ["a-de-multe", "a-o-data", "b-o-data"],
        )

    def test_dry_run_spune_cati_au_esuat_deja_INAINTE_de_plata(self):
        """
        Singura cifra despre esecuri care apare si la simulare. "Ar face 2 apeluri" nu e o
        propozitie pe care poti decide; "ar face 2 apeluri, dintre care unul pentru un
        anunt care a refuzat deja de doua ori" e.
        """
        anunturi = [
            {"id": "curat", "titlu": "Payroll Automation", "verdict": "trece"},
            {"id": "incapatanat", "titlu": "Talent and Engagement Specialist",
             "verdict": "trece", "incercari_esuate": 2},
        ]

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_corect, self._salveaza_noteaza([]),
            "test", dry_run=True,
        )

        self.assertEqual(raport["de_procesat"], 2)
        self.assertEqual(raport["eligibile_cu_esecuri_vechi"], 1)
        # La dry run nu s-a chemat modelul, deci nu exista esecuri de acum.
        self.assertEqual(raport["esecuri_pe_anunt"], [])

    def test_nimic_nu_se_opreste_din_cauza_esecurilor(self):
        """
        Un anunt cu istorie lunga de esecuri tot ajunge la model. Asta NU e o scapare: un
        "nu se mai incearca" pus in tacere ar ascunde exact informatia pentru care se
        plateste - ca modelul raspunde prost la anuntul asta.
        """
        anunturi = [{"id": "vechi_esec", "titlu": "Ceva", "verdict": "trece",
                     "incercari_esuate": 99}]
        apeluri = []

        def model_care_numara(prompt: str) -> str:
            apeluri.append(prompt)
            return RASPUNS_BUN

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_care_numara, self._salveaza_noteaza([]),
            "test", dry_run=False,
        )

        self.assertEqual(len(apeluri), 1)
        self.assertEqual(raport["evaluate"], 1)


class TestNuSePlatesteDeDouaOri(unittest.TestCase):
    """
    Un anunt deja evaluat nu se mai da o data pe mana modelului.

    Aceeasi regula ca STATUS_GATA de la normalizare, plus conditia de versiune: un verdict
    inseamna ceva doar impreuna cu criteriile dupa care a fost dat. Fara plasa asta,
    simularea spunea "ar evalua 32" cand corect era 1 - restul aveau deja raspunsul in
    baza, iar o rulare pe bune ar fi platit de 32 de ori pentru 31 de raspunsuri identice.

    `are_evaluare_valabila` vine gata judecat din store/db.py, calculat cu aceeasi bucata
    de SQL prin care trec si citirile. Aici se testeaza CE FACE adaptorul cu el.
    """

    def _anunt(self, id_anunt, verdict="trece", are_evaluare_valabila=False,
               descriere_dupa_evaluare=False):
        return {
            "id": id_anunt,
            "titlu": "Payroll Automation",
            "verdict": verdict,
            "are_evaluare_valabila": are_evaluare_valabila,
            "descriere_dupa_evaluare": descriere_dupa_evaluare,
        }

    def test_cu_evaluare_valabila_pe_versiunea_curenta_e_SARIT(self):
        ales = alege_anunturile([self._anunt("a1", are_evaluare_valabila=True)])

        self.assertEqual(ales["eligibile"], [])
        self.assertEqual(ales["sarite"]["evaluate_deja"], 1)

    def test_fara_nicio_evaluare_e_ELIGIBIL(self):
        ales = alege_anunturile([self._anunt("a1")])

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["a1"])
        self.assertEqual(ales["sarite"]["evaluate_deja"], 0)

    def test_evaluarea_de_pe_versiune_veche_NU_conteaza(self):
        """
        Un verdict dat pe alte criterii raspunde la alta intrebare. Baza il marcheaza ca
        nevalabil (are_evaluare_valabila fals), deci anuntul merge din nou la model.
        """
        ales = alege_anunturile([self._anunt("a1", are_evaluare_valabila=False)])

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["a1"])

    def test_incercarea_respinsa_NU_conteaza_drept_evaluare(self):
        """
        Cazul real din baza: modelul a raspuns cu JSON stricat, randul are status
        "respins". Nu e o evaluare, e o incercare esuata - se reincearca. Daca ar trece
        drept evaluare, anuntul n-ar mai primi niciodata un verdict.
        """
        ales = alege_anunturile([self._anunt("a1", are_evaluare_valabila=False)])

        self.assertEqual(len(ales["eligibile"]), 1)

    def test_respinsul_de_filtru_se_numara_separat_de_cel_evaluat_deja(self):
        """
        Punctul 2: raportul trebuie sa spuna DE CE a fost sarit fiecare. Altfel
        "ar evalua 1 din 3" nu se poate verifica.
        """
        anunturi = [
            self._anunt("a-respins", verdict="respins"),
            self._anunt("a-gata", are_evaluare_valabila=True),
            self._anunt("a-nou"),
        ]

        ales = alege_anunturile(anunturi)

        self.assertEqual(ales["sarite"]["respinse_de_filtru"], 1)
        self.assertEqual(ales["sarite"]["evaluate_deja"], 1)
        self.assertEqual([a["id"] for a in ales["eligibile"]], ["a-nou"])

    def test_fortarea_trimite_din_nou_tot_ce_e_eligibil(self):
        """
        Punctul 3: cand schimbi promptul fara sa urci versiunea criteriilor, verdictele
        existente sunt pe versiunea buna dar raspund la alta intrebare. Nicio regula
        automata n-are cum sa stie asta - deci e o decizie omeneasca, explicita.
        """
        anunturi = [
            self._anunt("a-respins", verdict="respins"),
            self._anunt("a-gata", are_evaluare_valabila=True),
            self._anunt("a-nou"),
        ]

        ales = alege_anunturile(anunturi, reevalueaza=True)

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["a-gata", "a-nou"])
        self.assertEqual(ales["sarite"]["evaluate_deja"], 0)
        # Fortarea ignora evaluarile existente, NU si filtrul dur. Un anunt respins pe o
        # regula certa ramane respins - altfel ai plati pentru joburi pe care nu le iei.
        self.assertEqual(ales["sarite"]["respinse_de_filtru"], 1)

    def test_modelul_chiar_nu_e_chemat_pentru_cele_deja_evaluate(self):
        """Numaratoarea de mai sus e degeaba daca apelul se face oricum."""
        anunturi = [
            self._anunt("a-gata", are_evaluare_valabila=True),
            self._anunt("a-nou"),
        ]
        apeluri = []

        def model_care_numara(prompt: str) -> str:
            apeluri.append(prompt)
            return RASPUNS_BUN

        jurnal = []
        raport = evalueaza_lotul(
            anunturi, CRITERII, model_care_numara,
            lambda anunt_id, rezultat, versiune: jurnal.append(anunt_id), "test",
        )

        self.assertEqual(len(apeluri), 1)
        self.assertEqual(jurnal, ["a-nou"])
        self.assertEqual(raport["de_procesat"], 1)
        self.assertEqual(raport["sarite_evaluate_deja"], 1)
        self.assertFalse(raport["reevalueaza"])

    def test_fortarea_ajunge_pana_la_model(self):
        anunturi = [
            self._anunt("a-gata", are_evaluare_valabila=True),
            self._anunt("a-nou"),
        ]
        apeluri = []

        raport = evalueaza_lotul(
            anunturi, CRITERII, lambda prompt: apeluri.append(prompt) or RASPUNS_BUN,
            lambda *a: None, "test", reevalueaza=True,
        )

        self.assertEqual(len(apeluri), 2)
        self.assertEqual(raport["de_procesat"], 2)
        self.assertTrue(raport["reevalueaza"])

    def test_dry_run_nu_cheama_modelul_nici_la_fortare(self):
        """Fortarea schimba PE CINE se evalueaza, nu DACA se cheltuie. Plasele raman."""
        apeluri = []

        raport = evalueaza_lotul(
            [self._anunt("a-gata", are_evaluare_valabila=True)], CRITERII,
            lambda prompt: apeluri.append(prompt) or RASPUNS_BUN,
            lambda *a: None, "test", dry_run=True, reevalueaza=True,
        )

        self.assertEqual(apeluri, [])
        self.assertEqual(raport["evaluate"], 0)
        self.assertEqual(raport["de_procesat"], 1)


class TestDescriereaNouaDeclanseazaRejudecata(unittest.TestCase):
    """
    Singura exceptie de la "nu se plateste de doua ori": anuntul a capatat DESCRIERE
    dupa ce primise verdictul.

    DE CE. Descrierea vine in mail doar de la BestJobs; eJobs si LinkedIn trimit titlu si
    firma. Anunturile alea au fost evaluate pe titlu gol, iar modelul a raspuns cuminte
    "incert, lipseste descrierea". Cand textul ajunge in baza din pagina publica, verdictul
    vechi nu se repara singur - raspundea la un anunt pe care modelul nu-l vazuse.

    SI DE CE E INGUSTA. Nu "s-a atins anuntul", ci "a aparut text nou dupa judecata".
    Faptul vine gata calculat din store/db.py (`descriere_dupa_evaluare`) si e adevarat
    doar pentru paginile luate cu succes - o pagina expirata sau una din care parserul
    n-a scos nimic nu declanseaza nimic, fiindca modelul tot n-ar avea ce citi.

    Aici se testeaza CE FACE adaptorul cu faptul. Ca faptul insusi e calculat corect se
    testeaza pe o baza reala, in tests/test_rejudecare_descriere.py.
    """

    def _anunt(self, id_anunt, are_evaluare_valabila=False,
               descriere_dupa_evaluare=False, verdict="trece"):
        return {
            "id": id_anunt,
            "titlu": "Payroll Automation",
            "verdict": verdict,
            "are_evaluare_valabila": are_evaluare_valabila,
            "descriere_dupa_evaluare": descriere_dupa_evaluare,
        }

    def test_evaluatul_care_a_capatat_descriere_INTRA_din_nou(self):
        ales = alege_anunturile([
            self._anunt("a1", are_evaluare_valabila=True, descriere_dupa_evaluare=True)
        ])

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["a1"])
        self.assertEqual(ales["sarite"]["evaluate_deja"], 0)
        self.assertEqual(ales["rejudecate_descriere_noua"], 1)

    def test_evaluatul_fara_descriere_noua_ramane_SARIT(self):
        """Celalalt capat al aceleiasi reguli: rejudecata nu se intinde peste tot."""
        ales = alege_anunturile([
            self._anunt("a1", are_evaluare_valabila=True, descriere_dupa_evaluare=False)
        ])

        self.assertEqual(ales["eligibile"], [])
        self.assertEqual(ales["sarite"]["evaluate_deja"], 1)
        self.assertEqual(ales["rejudecate_descriere_noua"], 0)

    def test_descrierea_noua_NU_invie_un_anunt_respins_de_filtrul_dur(self):
        """
        Filtrul dur ramane primul strat. Un anunt picat pe o regula certa (salariu sub
        prag, cuvant exclus) nu se rejudeca fiindca i-a venit textul - ar fi bani dati pe
        o opinie despre un job pe care oricum nu-l iei.
        """
        ales = alege_anunturile([
            self._anunt("a1", verdict="respins", are_evaluare_valabila=True,
                        descriere_dupa_evaluare=True)
        ])

        self.assertEqual(ales["eligibile"], [])
        self.assertEqual(ales["sarite"]["respinse_de_filtru"], 1)
        self.assertEqual(ales["rejudecate_descriere_noua"], 0)

    def test_rejudecarea_nu_dubleaza_anuntul_neevaluat(self):
        """
        Un anunt care n-a fost niciodata evaluat intra o singura data, ca "nou", nu si ca
        "rejudecat". Contorul numara doar verdicte inlocuite - altfel "12 rejudecate" ar
        include si anunturi care n-au avut niciodata un verdict de inlocuit.
        """
        ales = alege_anunturile([
            self._anunt("nou", are_evaluare_valabila=False, descriere_dupa_evaluare=True)
        ])

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["nou"])
        self.assertEqual(ales["rejudecate_descriere_noua"], 0)

    def test_raportul_numara_exact_cine_a_fost_rejudecat(self):
        """
        Criteriul din plan: rejudecari pentru EXACT anunturile care au capatat descriere,
        zero pentru celelalte. Si numarul trebuie sa se poata verifica in raport, altfel
        "au mai aparut 2" ramane o afirmatie pe cuvant.
        """
        anunturi = [
            self._anunt("cu-descriere-noua", are_evaluare_valabila=True,
                        descriere_dupa_evaluare=True),
            self._anunt("evaluat-linistit", are_evaluare_valabila=True),
            self._anunt("niciodata-evaluat"),
            self._anunt("respins-de-filtru", verdict="respins"),
        ]
        apeluri = []
        jurnal = []

        raport = evalueaza_lotul(
            anunturi, CRITERII,
            lambda prompt: apeluri.append(prompt) or RASPUNS_BUN,
            lambda anunt_id, rezultat, versiune: jurnal.append(anunt_id), "test",
        )

        # Modelul vede doi: cel rejudecat si cel niciodata evaluat.
        self.assertEqual(jurnal, ["cu-descriere-noua", "niciodata-evaluat"])
        self.assertEqual(len(apeluri), 2)
        self.assertEqual(raport["rejudecate_descriere_noua"], 1)
        self.assertEqual(raport["sarite_evaluate_deja"], 1)
        self.assertEqual(raport["sarite_respins"], 1)
        self.assertEqual(raport["de_procesat"], 2)
        # Rejudecarea e automata: nu s-a cerut nicio fortare.
        self.assertFalse(raport["reevalueaza"])

    def test_dry_run_arata_rejudecarea_FARA_sa_cheme_modelul(self):
        """
        Simularea trebuie sa spuna dinainte cate verdicte s-ar inlocui. Altfel afli cat
        costa rejudecarea abia dupa ce ai platit-o.
        """
        anunturi = [
            self._anunt("a1", are_evaluare_valabila=True, descriere_dupa_evaluare=True),
            self._anunt("a2", are_evaluare_valabila=True),
        ]

        def model_care_explodeaza(prompt: str) -> str:
            raise AssertionError("dry run-ul a chemat modelul")

        raport = evalueaza_lotul(
            anunturi, CRITERII, model_care_explodeaza, lambda *a: None, "test",
            dry_run=True,
        )

        self.assertEqual(raport["evaluate"], 0)
        self.assertEqual(raport["de_procesat"], 1)
        self.assertEqual(raport["rejudecate_descriere_noua"], 1)


if __name__ == "__main__":
    unittest.main()
