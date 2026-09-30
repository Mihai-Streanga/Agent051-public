r"""
Teste pentru regula "se citesc doar evaluarile de pe versiunea de criterii de acum".

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

BAZA DE TEST E TEMPORARA, iar data/agent051.db NU E ATINSA NICIODATA. Schema vine din
store/db.py, nu e rescrisa aici.

DE CE EXISTA REGULA: un verdict inseamna ceva doar impreuna cu criteriile dupa care a
fost dat. Pe 1.1, `relevant` era da/nu; de la 1.2 e o treapta din trei. Amestecate intr-un
raport, doua randuri care arata identic intr-un SELECT raspund de fapt la doua intrebari
diferite - iar cine le citeste (inclusiv JA.S.Mine) n-are cum sa observe.

CE VERIFICA:
1. ca verdictele de pe versiuni vechi nu mai ajung in niciun raport;
2. ca randurile vechi RAMAN in tabela - sunt istoric, nu gunoi;
3. ca o evaluare respinsa (JSON stricat) nu trece drept evaluare existenta;
4. ca lipsa se numara si se spune, in loc sa faca briefingul sa para gol.
"""

import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.adapters.briefing import briefing
from agent051.adapters.interogari import cauta, oportunitati_noi, stare_pipeline
from agent051.store import configuratie, db

VERSIUNE_ACUM = "9.9"
VERSIUNE_VECHE = "1.1"


class TestCitireaPeVersiune(unittest.TestCase):

    def setUp(self):
        self.dosar = Path(tempfile.mkdtemp(prefix="agent051-test-versiune-"))
        self.cale = self.dosar / "test.db"

        self._cale_reala = db.CALE_DB
        self._dosar_real = db.DOSAR_DATE
        db.CALE_DB = self.cale
        db.DOSAR_DATE = self.dosar
        db.initializeaza_db()

        # Fixam versiunea "de acum" ca sa nu depinda testul de ce scrie in criterii.yaml.
        # Altfel, o urcare de versiune reala ar face suita rosie fara ca vreun cod sa fie
        # gresit - exact greseala pe care o evita si tests/test_filtrare.py.
        self._versiune_reala = configuratie.versiune_criterii
        configuratie.versiune_criterii = lambda: VERSIUNE_ACUM
        db.versiune_criterii = lambda: VERSIUNE_ACUM

    def tearDown(self):
        db.CALE_DB = self._cale_reala
        db.DOSAR_DATE = self._dosar_real
        configuratie.versiune_criterii = self._versiune_reala
        db.versiune_criterii = self._versiune_reala
        shutil.rmtree(self.dosar, ignore_errors=True)

    def _scrie(self, comanda: str, parametri=()):
        with closing(sqlite3.connect(self.cale)) as conexiune:
            conexiune.execute(comanda, parametri)
            conexiune.commit()

    def _intreaba(self, comanda: str, parametri=()):
        with closing(sqlite3.connect(self.cale)) as conexiune:
            return conexiune.execute(comanda, parametri).fetchall()

    def _anunt(self, id_anunt: str, titlu: str = "Specialist Payroll"):
        self._scrie(
            "INSERT INTO anunturi (id, sursa, titlu, firma, locatie, link, descriere,"
            " data_anunt, data_extragere) VALUES (?, 'ejobs', ?, 'O firma', '',"
            " 'https://exemplu.invalid/1', 'text', '2026-07-24T08:00:00+00:00',"
            " '2026-07-24T08:00:00+00:00')",
            (id_anunt, titlu),
        )
        self._scrie(
            "INSERT INTO anunturi_filtrate (anunt_id, verdict, versiune_criterii)"
            " VALUES (?, 'trece', ?)",
            (id_anunt, VERSIUNE_ACUM),
        )

    def _evaluare(self, id_anunt, relevant, versiune, status="ok"):
        self._scrie(
            "INSERT INTO evaluari_calitative (anunt_id, relevant, motiv_relevanta,"
            " interes, motiv_interes, single_point_of_failure, motiv_spof,"
            " status_evaluare, versiune_criterii) VALUES (?, ?, 'motiv', 'ridicat',"
            " 'motiv', 'nu', 'motiv', ?, ?)",
            (id_anunt, relevant, status, versiune),
        )

    def test_verdictul_vechi_nu_se_citeste(self):
        self._anunt("a1")
        self._evaluare("a1", "ideal", VERSIUNE_VECHE)

        anunturi = db.anunturi_pentru_briefing(None)

        self.assertEqual(len(anunturi), 1)
        self.assertIsNone(anunturi[0]["relevant"])
        # Dar se STIE ca exista una - altfel n-am putea deosebi "neevaluat" de "vechi".
        self.assertTrue(anunturi[0]["are_evaluare_oarecare"])

    def test_verdictul_curent_se_citeste(self):
        self._anunt("a1")
        self._evaluare("a1", "ideal", VERSIUNE_ACUM)

        anunturi = db.anunturi_pentru_briefing(None)

        self.assertEqual(anunturi[0]["relevant"], "ideal")

    def test_randurile_vechi_RAMAN_in_tabela(self):
        """Sunt istoric, nu gunoi. Regula spune ca nu se citesc, nu ca se sterg."""
        self._anunt("a1")
        self._evaluare("a1", "da", VERSIUNE_VECHE)

        db.anunturi_pentru_briefing(None)
        briefing()

        self.assertEqual(
            self._intreaba("SELECT COUNT(*) FROM evaluari_calitative")[0][0], 1
        )

    def test_evaluarea_respinsa_nu_trece_drept_evaluare(self):
        """
        Un rand cu status "respins" e o incercare esuata (modelul a raspuns cu JSON
        stricat), nu o evaluare. Daca ar trece drept una, ar ASCUNDE un gol - adica exact
        opusul a ce vrem.
        """
        self._anunt("a1")
        self._evaluare("a1", None, VERSIUNE_ACUM, status="respins")

        anunturi = db.anunturi_pentru_briefing(None)

        self.assertIsNone(anunturi[0]["relevant"])
        self.assertTrue(anunturi[0]["are_evaluare_oarecare"])

    def test_cautarea_nu_arata_verdicte_vechi(self):
        """Aceeasi regula, alta usa. Anuntul apare - dar fara un verdict din alta epoca."""
        self._anunt("a1", titlu="Specialist Payroll")
        self._evaluare("a1", "ideal", VERSIUNE_VECHE)

        rezultat = cauta("Payroll")

        self.assertEqual(rezultat["gasite"], 1)
        self.assertIsNone(rezultat["anunturi"][0]["relevant"])

    def test_oportunitatile_nu_se_sprijina_pe_verdicte_vechi(self):
        """
        Anuntul ramane in lista (a trecut filtrul dur), dar motivarea spune ca verdictul
        lui nu mai e valabil. Nu dispare si nu se prezinta cu o motivare veche.
        """
        self._anunt("a1")
        self._evaluare("a1", "ideal", VERSIUNE_VECHE)

        rezultat = oportunitati_noi()

        self.assertEqual(len(rezultat["oportunitati"]), 1)
        self.assertIn("fara verdict pe criteriile de acum", rezultat["oportunitati"][0]["motiv"])

    def test_briefingul_pe_o_baza_DOAR_cu_evaluari_vechi(self):
        """
        CAZUL CERUT. O baza in care fiecare evaluare e de pe criterii vechi nu are voie
        sa produca un briefing care pare gol.
        """
        # Titluri diferite: trei anunturi cu acelasi titlu si aceeasi firma sunt acelasi
        # job repostat si ar iesi pe un singur rand (vezi _strange_repostarile).
        for numar in range(3):
            self._anunt(f"a{numar}", titlu=f"Specialist Payroll {numar}")
            self._evaluare(f"a{numar}", "ideal", VERSIUNE_VECHE)

        rezultat = briefing()

        self.assertEqual(rezultat["briefing"]["fara_evaluare"]["de_reevaluat"], 3)
        self.assertEqual(rezultat["briefing"]["fara_evaluare"]["niciodata"], 0)
        self.assertEqual(len(rezultat["briefing"]["merita_atentie"]), 3)
        self.assertIn("Fara verdict pe criteriile de acum: 3", rezultat["text"])
        self.assertIn("de reevaluat: 3", rezultat["text"])

    def test_selectia_pentru_evaluare_marcheaza_cine_are_deja_verdict(self):
        """
        Aceeasi regula de versiune, in celalalt sens: la citiri ferea de a citi prea mult,
        aici fereste de a PLATI prea mult. Cele trei situatii, pe rand.
        """
        self._anunt("gata")
        self._evaluare("gata", "ideal", VERSIUNE_ACUM)

        self._anunt("vechi")
        self._evaluare("vechi", "ideal", VERSIUNE_VECHE)

        self._anunt("respins")
        self._evaluare("respins", None, VERSIUNE_ACUM, status="respins")

        self._anunt("nou")

        marcaje = {
            rand["id"]: rand["are_evaluare_valabila"]
            for rand in db.anunturi_pentru_calitativ()
        }

        self.assertTrue(marcaje["gata"], "verdict bun pe criteriile de acum - de sarit")
        self.assertFalse(marcaje["vechi"], "verdict de pe alte criterii - de reevaluat")
        self.assertFalse(marcaje["respins"], "incercare esuata, nu evaluare - de reincercat")
        self.assertFalse(marcaje["nou"], "nicio incercare - de evaluat")

    def test_starea_arata_curente_si_vechi_separat(self):
        self._anunt("a1")
        self._anunt("a2")
        self._evaluare("a1", "ideal", VERSIUNE_ACUM)
        self._evaluare("a2", "da", VERSIUNE_VECHE)

        etape = stare_pipeline()["etape"]

        self.assertEqual(etape["versiune_criterii"], VERSIUNE_ACUM)
        self.assertEqual(etape["evaluate_calitativ_curente"], 1)
        self.assertEqual(etape["evaluate_calitativ_vechi"], 1)


class TestVersiuneaVineDintrUnSingurLoc(unittest.TestCase):
    """
    Versiunea e folosita in doua feluri opuse - se SCRIE pe fiecare verdict si se CERE
    la fiecare citire. Daca cele doua ar calcula-o fiecare in felul ei, s-ar putea scrie
    randuri pe care nu le mai citeste nimeni, fara ca nimic sa dea eroare.
    """

    def test_scrierea_si_citirea_folosesc_aceeasi_functie(self):
        import inspect

        from agent051.adapters import evaluare_calitativa, filtrare

        for modul in (filtrare, evaluare_calitativa, db):
            sursa = inspect.getsource(modul)
            self.assertIn(
                "versiune_criterii", sursa, f"{modul.__name__} nu cere versiunea"
            )
            # Nimeni nu si-o mai scoate cu mana din meta - asta era duplicarea.
            self.assertNotIn(
                'get("versiune")', sursa,
                f"{modul.__name__} isi calculeaza singur versiunea, in loc s-o ceara",
            )


if __name__ == "__main__":
    unittest.main()
