r"""
Teste pentru adapters/normalizare.py - lantul intreg: prompt -> model -> validare.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

UITA-TE CE NU E AICI.
Niciun apel catre vreun model. Nicio cheie de API. Nicio adresa de internet. Nicio
dependinta noua. Testele astea ruleaza in avion, si costa zero lei de fiecare data
cand le rulezi - inclusiv de o suta de ori pe zi, cat scrii cod.

Si asta desi fisierul testat E un adaptor, adica exact locul unde traieste IO-ul.
Cum se poate: `normalizeaza_anunt` primeste functia care vorbeste cu modelul ca
PARAMETRU, deci in test ii dam noi una. Mai jos e o galerie de modele inventate -
unul corect si cinci feluri de a gresi. Nu sunt "mocks" de intretinut: sunt functii
de trei randuri care intorc un sir de caractere.

ASTA e ce cumpara injectarea, in termeni practici: un adaptor care ar fi construit
singur clientul si ar fi citit singur cheia n-ar fi putut fi testat fara cheie, fara
internet si fara sa platesti fiecare rulare. Aici nu doar ca se poate - se poate si
testa ce se intampla cand modelul MINTE, ceea ce cu un model real e aproape
imposibil de provocat la comanda.

CE VERIFICA, DE FAPT, FIECARE TEST DE MAI JOS:
ca un raspuns prost NU ajunge in baza deghizat in raspuns bun.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Codul proiectului sta in src/. Ii aratam lui Python calea.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.adapters.model import EroareInfrastructura
from agent051.adapters.normalizare import normalizeaza_anunt, normalizeaza_lotul

ANUNT = {
    "titlu": "Specialist Payroll (m/f/d) - URGENT!!",
    "firma": "Firma Inventata SRL",
    "corp_text": "Cautam specialist salarizare, munca remote, 5 ani experienta.",
}

RASPUNS_BUN = """{
    "rol_normalizat": "Specialist Payroll",
    "senioritate": "senior",
    "tip_munca": "remote",
    "domeniu": "payroll"
}"""


# ---------------------------------------------------------------------------
# Galeria de modele inventate. Fiecare e o functie (str) -> str, exact ce
# asteapta normalizeaza_anunt. Niciuna nu iese din calculator.
# ---------------------------------------------------------------------------

def model_corect(prompt: str) -> str:
    """Modelul ideal: JSON curat, campuri complete, valori din lista."""
    return RASPUNS_BUN


def model_cu_json_stricat(prompt: str) -> str:
    """A uitat o virgula intre campuri."""
    return '{"rol_normalizat": "Specialist Payroll" "senioritate": "senior"}'


def model_fara_senioritate(prompt: str) -> str:
    """JSON perfect valid, dar ii lipseste un camp cerut."""
    return """{
        "rol_normalizat": "Specialist Payroll",
        "tip_munca": "remote",
        "domeniu": "payroll"
    }"""


def model_cu_senioritate_inventata(prompt: str) -> str:
    """A inventat o valoare care nu e in lista permisa: "expert"."""
    return """{
        "rol_normalizat": "Specialist Payroll",
        "senioritate": "expert",
        "tip_munca": "remote",
        "domeniu": "payroll"
    }"""


def model_gol(prompt: str) -> str:
    """N-a raspuns nimic. Se intampla la limite de cereri sau la timeout."""
    return ""


def model_infrastructura_picata(prompt: str) -> str:
    """
    Nu e o respingere de continut: e DRUMUL catre model care s-a rupt (biblioteca lipsa,
    cheie respinsa, retea cazuta). In productie asta iese ca EroareInfrastructura din
    adapters/model.py; aici o imitam direct. Nu trebuie sa se prefaca in "respins".
    """
    raise EroareInfrastructura("biblioteca `anthropic` nu e instalata")


class TestNormalizeazaAnunt(unittest.TestCase):
    """
    Fiecare test de aici da o alta functie ca `cheama_model`. Asta e demonstratia
    practica a principiului: schimbi modelul dand alt parametru, fara sa atingi
    nicio linie din codul agentului si fara sa ai vreo cheie de API.
    """

    def test_modelul_corect_produce_date(self):
        rezultat = normalizeaza_anunt(ANUNT, model_corect)

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["domeniu"], "payroll")

    def test_raspunsurile_proaste_de_continut_sunt_respinse(self):
        """
        Cele patru feluri de RASPUNS PROST, la rand. Niciunul nu trece ca "ok".

        Toate au un lucru comun: modelul A RASPUNS, dar raspunsul e prost (minte, uita un
        camp, inventeaza o valoare, tace). Aia e o respingere de CONTINUT - se salveaza si
        rularea merge mai departe. Caderea de infrastructura NU e aici: aia e alt fel de
        esec, cu alt tratament (vezi testul urmator).
        """
        modele_proaste = {
            "json stricat": model_cu_json_stricat,
            "camp lipsa": model_fara_senioritate,
            "valoare inventata": model_cu_senioritate_inventata,
            "raspuns gol": model_gol,
        }

        for nume, model in modele_proaste.items():
            with self.subTest(model=nume):
                rezultat = normalizeaza_anunt(ANUNT, model)

                self.assertFalse(rezultat["ok"])
                self.assertNotIn("date", rezultat)
                self.assertTrue(rezultat["eroare"])

    def test_esecul_de_infrastructura_PROPAGA_nu_se_preface_in_respins(self):
        """
        Miezul reparatiei: un esec de infrastructura NU devine "respins" - iese in sus.

        Daca drumul catre model se rupe (biblioteca lipsa, cheie respinsa, retea cazuta),
        nu stim nimic despre anunt. A-l marca "respins" ar fi o minciuna care se strecoara
        in baza si ar face o rulare cu biblioteca lipsa sa "respinga" tacut anunturi bune.
        Deci exceptia trece prin normalizeaza_anunt neatinsa, catre lot, care opreste tot.
        """
        with self.assertRaises(EroareInfrastructura):
            normalizeaza_anunt(ANUNT, model_infrastructura_picata)

    def test_modelul_primeste_promptul_construit_de_noi(self):
        """
        Ce ajunge la model e exact ce a construit construieste_prompt().

        Verificam ca nimic nu se pierde pe drum: functia injectata primeste un prompt
        care chiar contine datele anuntului, nu un sir gol sau trunchiat. Adaptorul
        duce datele dintr-o parte in alta - testul asta verifica tocmai caratul.
        """
        primite = []

        def model_care_isi_noteaza_promptul(prompt: str) -> str:
            primite.append(prompt)
            return RASPUNS_BUN

        normalizeaza_anunt(ANUNT, model_care_isi_noteaza_promptul)

        self.assertEqual(len(primite), 1)
        self.assertIn("Specialist Payroll", primite[0])

    def test_modelul_e_chemat_o_singura_data(self):
        """
        Un anunt = un apel. Fara reincercari ascunse.

        Conteaza fiindca apelurile costa bani, iar banii nu sunt ai agentului: sunt
        ai lui JA.S.Mine, care injecteaza cheia. Un adaptor care ar reincerca in tacere
        de trei ori ar tripla nota de plata fara sa spuna nimanui. Daca vreodata
        vrem reincercari, se cer explicit - nu se strecoara.
        """
        apeluri = []

        def model_care_numara(prompt: str) -> str:
            apeluri.append(prompt)
            return RASPUNS_BUN

        normalizeaza_anunt(ANUNT, model_care_numara)

        self.assertEqual(len(apeluri), 1)


# ---------------------------------------------------------------------------
# Lotul: cele trei plase de siguranta (varsta, deja normalizat, limita) plus dry run.
# Toate se testeaza cu o lista injectata, un model inventat, un salveaza care doar
# noteaza si un `acum` fix - fara disc, fara internet, fara model real.
# ---------------------------------------------------------------------------

# Un moment fix, ca testul de varsta sa dea acelasi rezultat oriunde si oricand ar rula.
ACUM = datetime(2026, 7, 24, tzinfo=timezone.utc)
ZILE = 30


def _anunt(id_anunt, data_anunt, status=None, descriere_dupa_normalizare=False):
    """Un anunt de test, cu exact campurile pe care le citeste lotul."""
    return {
        "id": id_anunt,
        "titlu": "Specialist Payroll",
        "firma": "Firma Inventata SRL",
        "corp_text": "Cautam specialist salarizare.",
        "data_anunt": data_anunt,
        "status_normalizare": status,
        "descriere_dupa_normalizare": descriere_dupa_normalizare,
    }


def _model_care_explodeaza(prompt: str) -> str:
    """Un model care NU are voie sa fie chemat. Daca e chemat, testul trebuie sa pice."""
    raise AssertionError("modelul a fost chemat cand NU trebuia (dry run sau anunt sarit)")


class TestNormalizeazaLotul(unittest.TestCase):

    def _salveaza_noteaza(self, jurnal):
        """Un `salveaza` fals (anunt_id, rezultat) -> None, care doar tine minte. Fara disc."""
        def salveaza(anunt_id, rezultat):
            jurnal.append((anunt_id, rezultat))
        return salveaza

    def test_filtrul_de_varsta_taie_anuntul_vechi_si_lasa_recentul(self):
        """
        Plasa care apara banii: arhiva veche nu se da pe mana modelului.

        Un anunt din 2018 e mort - postul e ocupat de ani. Un apel de model pe el sunt
        bani aruncati. Doar cel recent ajunge la model; cel vechi si cel fara data se
        opresc inainte (fara data = varsta necunoscuta, deci nu riscam).
        """
        anunturi = [
            _anunt("recent", "2026-07-20T10:00:00+00:00"),
            _anunt("vechi", "2018-01-01T10:00:00+00:00"),
            _anunt("fara-data", None),
        ]
        vazute = []

        def model_care_numara(prompt: str) -> str:
            vazute.append(prompt)
            return RASPUNS_BUN

        jurnal = []
        raport = normalizeaza_lotul(
            anunturi, model_care_numara, self._salveaza_noteaza(jurnal),
            ACUM, ZILE, limita=50, dry_run=False,
        )

        # Modelul a fost chemat exact o data: pentru anuntul recent.
        self.assertEqual(len(vazute), 1)
        self.assertEqual(raport["sarite_vechi"], 2)
        self.assertEqual(raport["de_procesat"], 1)
        self.assertEqual(raport["procesate"], 1)
        # Doar recentul a fost salvat.
        self.assertEqual({rand[0] for rand in jurnal}, {"recent"})

    def test_anuntul_deja_normalizat_e_sarit(self):
        """Un anunt cu status 'ok' nu se renormalizeaza - n-am plati de doua ori acelasi raspuns."""
        anunturi = [
            _anunt("nou", "2026-07-20T10:00:00+00:00", status=None),
            _anunt("deja-ok", "2026-07-20T10:00:00+00:00", status="ok"),
            _anunt("respins-inainte", "2026-07-20T10:00:00+00:00", status="respins"),
        ]
        vazute = []

        def model_care_numara(prompt: str) -> str:
            vazute.append(prompt)
            return RASPUNS_BUN

        raport = normalizeaza_lotul(
            anunturi, model_care_numara, self._salveaza_noteaza([]),
            ACUM, ZILE, limita=50, dry_run=False,
        )

        # 'ok' e sarit; 'None' si 'respins' se reincearca. Deci doua apeluri.
        self.assertEqual(len(vazute), 2)
        self.assertEqual(raport["sarite_deja_normalizate"], 1)
        self.assertEqual(raport["procesate"], 2)

    def test_limita_opreste_la_N(self):
        """
        Plasa impotriva unei rulari scapate: cu limita 3, modelul vede cel mult 3 anunturi,
        chiar daca sunt 5 eligibile. Restul asteapta o rulare viitoare.
        """
        anunturi = [
            _anunt(f"a{i}", "2026-07-20T10:00:00+00:00") for i in range(5)
        ]
        apeluri = []

        def model_care_numara(prompt: str) -> str:
            apeluri.append(prompt)
            return RASPUNS_BUN

        raport = normalizeaza_lotul(
            anunturi, model_care_numara, self._salveaza_noteaza([]),
            ACUM, ZILE, limita=3, dry_run=False,
        )

        self.assertEqual(len(apeluri), 3)
        self.assertEqual(raport["procesate"], 3)
        self.assertEqual(raport["de_procesat"], 5)
        self.assertEqual(raport["oprite_de_limita"], 2)

    def test_dry_run_NU_cheama_modelul(self):
        """
        Testul-cheie al plasei de siguranta: dry run calculeaza tot, dar nu atinge modelul.

        Ii dam un model care EXPLODEAZA daca e chemat. Daca dry run-ul l-ar atinge fie si
        o data, testul pica. Asa se dovedeste, nu se presupune, ca simularea e gratuita.
        """
        anunturi = [
            _anunt("a1", "2026-07-20T10:00:00+00:00"),
            _anunt("a2", "2026-07-20T10:00:00+00:00"),
        ]
        jurnal = []

        raport = normalizeaza_lotul(
            anunturi, _model_care_explodeaza, self._salveaza_noteaza(jurnal),
            ACUM, ZILE, limita=50, dry_run=True,
        )

        # Modelul n-a fost chemat (altfel ar fi aruncat AssertionError), nimic salvat.
        self.assertEqual(raport["procesate"], 0)
        self.assertEqual(jurnal, [])
        # Dar socoteala e facuta: stim ca AR procesa doua anunturi.
        self.assertTrue(raport["dry_run"])
        self.assertEqual(raport["de_procesat"], 2)
        self.assertEqual(raport["ar_procesa"], 2)

    def test_esecul_de_infrastructura_opreste_lotul_la_prima_aparitie(self):
        """
        Bug-ul raportat, in test: infrastructura picata NU marcheaza 50 de anunturi respinse.

        Un model care ridica EroareInfrastructura (ex: biblioteca lipsa) opreste lotul la
        PRIMUL anunt. Nu se salveaza nimic (anunturile raman de reincercat), iar esecul iese
        separat in raport - NU ca "respins". Asa nu se mai confunda "n-am ajuns la model" cu
        "modelul a zis nu".
        """
        anunturi = [
            _anunt("a1", "2026-07-20T10:00:00+00:00"),
            _anunt("a2", "2026-07-20T10:00:00+00:00"),
            _anunt("a3", "2026-07-20T10:00:00+00:00"),
        ]
        apeluri = []

        def model_care_pica_infra(prompt: str) -> str:
            apeluri.append(prompt)
            raise EroareInfrastructura("biblioteca `anthropic` nu e instalata")

        jurnal = []
        raport = normalizeaza_lotul(
            anunturi, model_care_pica_infra, self._salveaza_noteaza(jurnal),
            ACUM, ZILE, limita=50, dry_run=False,
        )

        # A picat la primul apel si s-a oprit - nu a mai incercat celelalte doua.
        self.assertEqual(len(apeluri), 1)
        # Nimic marcat ca respins de continut, nimic salvat: anunturile raman de reincercat.
        self.assertEqual(raport["procesate"], 0)
        self.assertEqual(raport["respinse"], 0)
        self.assertEqual(jurnal, [])
        # Esecul iese separat, cu mesaj clar.
        self.assertEqual(raport["esuate_infrastructura"], 1)
        self.assertIn("anthropic", raport["esec_infrastructura"])


class TestDescriereaNouaDeclanseazaRenormalizarea(unittest.TestCase):
    """
    Singura gaura din plasa "deja normalizat": anuntul a capatat descriere DUPA
    normalizare.

    DE CE. Un anunt de la eJobs a fost normalizat cand in baza erau doar titlul si firma.
    Modelul a ghicit ce a putut din patru cuvinte. Cand descrierea ajunge in baza din
    pagina publica, raspunsul vechi nu mai e "acelasi raspuns" - a fost dat pe alte date.

    Faptul (`descriere_dupa_normalizare`) vine gata calculat din store/db.py si e adevarat
    doar cand pagina chiar a adus text. Aici se testeaza ce face adaptorul cu el.
    """

    def _salveaza_noteaza(self, jurnal):
        def salveaza(anunt_id, rezultat):
            jurnal.append(anunt_id)
        return salveaza

    def test_normalizatul_care_a_capatat_descriere_se_reface(self):
        anunturi = [
            _anunt("cu-descriere-noua", "2026-07-20T10:00:00+00:00", status="ok",
                   descriere_dupa_normalizare=True),
            _anunt("normalizat-linistit", "2026-07-20T10:00:00+00:00", status="ok"),
        ]
        jurnal = []

        raport = normalizeaza_lotul(
            anunturi, model_corect, self._salveaza_noteaza(jurnal),
            ACUM, ZILE, limita=50, dry_run=False,
        )

        # Exact unul se reface; celalalt ramane sarit.
        self.assertEqual(jurnal, ["cu-descriere-noua"])
        self.assertEqual(raport["renormalizate_descriere_noua"], 1)
        self.assertEqual(raport["sarite_deja_normalizate"], 1)
        self.assertEqual(raport["de_procesat"], 1)

    def test_anuntul_niciodata_normalizat_nu_se_numara_ca_renormalizare(self):
        """
        Contorul numara raspunsuri INLOCUITE. Un anunt fara nicio normalizare intra oricum,
        ca "nou" - numarat si acolo, ar umfla cifra cu care se justifica cheltuiala.
        """
        anunturi = [
            _anunt("nou", "2026-07-20T10:00:00+00:00", status=None,
                   descriere_dupa_normalizare=True),
        ]
        jurnal = []

        raport = normalizeaza_lotul(
            anunturi, model_corect, self._salveaza_noteaza(jurnal),
            ACUM, ZILE, limita=50, dry_run=False,
        )

        self.assertEqual(jurnal, ["nou"])
        self.assertEqual(raport["renormalizate_descriere_noua"], 0)

    def test_varsta_ramane_deasupra_descrierii_noi(self):
        """
        Ordinea plaselor nu se schimba: un anunt din 2018 nu se renormalizeaza fiindca i-a
        venit textul. Postul e mort de ani; apelul ar fi bani aruncati. Si nici nu se
        numara ca renormalizare - un raport care ar promite una care nu se intampla e mai
        rau decat unul tacut.
        """
        anunturi = [
            _anunt("vechi", "2018-01-01T10:00:00+00:00", status="ok",
                   descriere_dupa_normalizare=True),
        ]
        jurnal = []

        raport = normalizeaza_lotul(
            anunturi, _model_care_explodeaza, self._salveaza_noteaza(jurnal),
            ACUM, ZILE, limita=50, dry_run=False,
        )

        self.assertEqual(jurnal, [])
        self.assertEqual(raport["sarite_vechi"], 1)
        self.assertEqual(raport["renormalizate_descriere_noua"], 0)

    def test_dry_run_arata_renormalizarea_fara_sa_cheme_modelul(self):
        anunturi = [
            _anunt("cu-descriere-noua", "2026-07-20T10:00:00+00:00", status="ok",
                   descriere_dupa_normalizare=True),
            _anunt("normalizat-linistit", "2026-07-20T10:00:00+00:00", status="ok"),
        ]

        raport = normalizeaza_lotul(
            anunturi, _model_care_explodeaza, self._salveaza_noteaza([]),
            ACUM, ZILE, limita=50, dry_run=True,
        )

        self.assertEqual(raport["procesate"], 0)
        self.assertEqual(raport["ar_procesa"], 1)
        self.assertEqual(raport["renormalizate_descriere_noua"], 1)


if __name__ == "__main__":
    unittest.main()
