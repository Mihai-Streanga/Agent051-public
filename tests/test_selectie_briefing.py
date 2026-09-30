r"""
Teste pentru TAIETURA briefingului: ce intra in raport si ce ramane afara.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

DE CE UN FISIER SEPARAT DE tests/test_briefing.py: acela testeaza distilarea PURA, care
merge cu discul scos si nu atinge nicio baza. Aici se testeaza selectia, care e o
interogare SQL, deci IO - si are nevoie de o baza adevarata. Doua lucruri diferite, in
doua fisiere diferite, ca sa nu ajunga cineva sa creada ca briefingul pur are nevoie de
sqlite.

BAZA DE TEST E TEMPORARA, iar data/agent051.db NU E ATINSA NICIODATA. Schema vine din
store/db.py, nu e rescrisa aici.

CE VERIFICA, DE FAPT:
ca "nou" inseamna "s-a aflat ceva despre anuntul asta dupa reper", nu "a sosit dupa
reper". Distinctia nu e teoretica - pe 16 august 2026 a ingropat definitiv 10 anunturi
evaluate la trei minute dupa un briefing marcat citit. Judecata vine intotdeauna mai
tarziu decat anuntul; o taietura pe sosire arunca fix judecata.
"""

import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.adapters.briefing import CHEIE_REPER, briefing
from agent051.store import configuratie, db

VERSIUNE_ACUM = "9.9"
VERSIUNE_VECHE = "1.1"

# Reperul fata de care se taie. Datele de mai jos sunt asezate anume in jurul lui.
REPER = "2026-08-16T15:28:42+00:00"

INAINTE = "2026-08-16T10:59:00+00:00"
DUPA = "2026-08-16T15:32:17+00:00"


class BazaDeTest(unittest.TestCase):
    """Pregatirea comuna: o baza temporara si o versiune de criterii fixata."""

    def setUp(self):
        self.dosar = Path(tempfile.mkdtemp(prefix="agent051-test-selectie-"))
        self.cale = self.dosar / "test.db"

        self._cale_reala = db.CALE_DB
        self._dosar_real = db.DOSAR_DATE
        db.CALE_DB = self.cale
        db.DOSAR_DATE = self.dosar
        db.initializeaza_db()

        # Versiunea "de acum" se fixeaza, ca sa nu depinda testul de criterii.yaml. Altfel
        # o urcare reala de versiune ar innegri suita fara ca vreun cod sa fie gresit.
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

    def _anunt(self, id_anunt: str, data_extragere: str, data_filtrare: str = INAINTE):
        self._scrie(
            "INSERT INTO anunturi (id, sursa, titlu, firma, locatie, link, descriere,"
            " data_anunt, data_extragere) VALUES (?, 'ejobs', 'Specialist Payroll',"
            " 'O firma', '', 'https://exemplu.invalid/1', 'text', ?, ?)",
            (id_anunt, data_extragere, data_extragere),
        )
        self._scrie(
            "INSERT INTO anunturi_filtrate (anunt_id, verdict, versiune_criterii,"
            " data_filtrare) VALUES (?, 'trece', ?, ?)",
            (id_anunt, VERSIUNE_ACUM, data_filtrare),
        )

    def _evaluare(self, id_anunt, data_evaluare, versiune=VERSIUNE_ACUM, status="ok"):
        self._scrie(
            "INSERT INTO evaluari_calitative (anunt_id, relevant, motiv_relevanta,"
            " interes, motiv_interes, single_point_of_failure, motiv_spof,"
            " status_evaluare, versiune_criterii, data_evaluare) VALUES (?,"
            " 'bun_in_domeniu', 'motiv', 'ridicat', 'motiv', 'nu', 'motiv', ?, ?, ?)",
            (id_anunt, status, versiune, data_evaluare),
        )

    def _id_uri_selectate(self):
        return sorted(a["id"] for a in db.anunturi_pentru_briefing(REPER))


class TestTaietura(BazaDeTest):
    """Cele cinci situatii care decid daca un anunt intra sau nu in briefing."""

    def test_sosit_inainte_dar_evaluat_dupa_reper_APARE(self):
        """
        BUG-UL REPARAT, in forma lui minima.

        Anuntul a intrat in baza dimineata, briefingul a fost marcat citit dupa-amiaza,
        iar verdictul a venit trei minute mai tarziu. Pe taietura veche (`data_extragere`)
        anuntul cadea in spatele reperului si nu mai aparea NICIODATA in vreun raport -
        ramanea in baza, dar nu-l mai vedea nimeni.
        """
        self._anunt("evaluat_dupa", data_extragere=INAINTE)
        self._evaluare("evaluat_dupa", data_evaluare=DUPA)

        self.assertEqual(self._id_uri_selectate(), ["evaluat_dupa"])

    def test_sosit_inainte_si_evaluat_inainte_NU_apare(self):
        """
        Perechea testului de mai sus, si singura lui aparare.

        Fara ea, "apare cand e evaluat dupa" s-ar putea trece si cu o taietura scoasa de
        tot - adica un briefing care spune de fiecare data tot ce e in baza. Aici nu s-a
        aflat nimic dupa reper, deci nu e nimic de raportat.
        """
        self._anunt("vechi_de_tot", data_extragere=INAINTE)
        self._evaluare("vechi_de_tot", data_evaluare="2026-08-16T11:05:00+00:00")

        self.assertEqual(self._id_uri_selectate(), [])

    def test_sosit_dupa_reper_si_neevaluat_APARE(self):
        """
        Comportamentul de dinainte, care nu are voie sa se strice.

        Un anunt proaspat, pe care inca nu s-a pronuntat nimeni, e tot o stire. Apare cu
        campurile de interpretare goale - si asa se vede ca il asteapta o evaluare, nu ca
        n-a fost gasit nimic.

        IFNULL din formula se verifica aici: fara el, MAX(data, NULL) ar da NULL, si
        anuntul asta ar disparea din orice briefing.
        """
        self._anunt("proaspat", data_extragere=DUPA)

        self.assertEqual(self._id_uri_selectate(), ["proaspat"])

    def test_evaluat_dupa_reper_dar_pe_criterii_VECHI_nu_apare(self):
        """
        Un verdict de pe alte criterii nu e o stire noua - e un verdict mort.

        Daca ar conta, o rulare veche de evaluare (sau o migrare care atinge randurile)
        ar reinvia in briefing anunturi judecate dupa reguli care nu mai sunt ale
        noastre. Taietura se sprijina pe evaluarea VALABILA, adica pe acelasi JOIN pe
        care il foloseste tot restul fisierului.
        """
        self._anunt("epoca_veche", data_extragere=INAINTE)
        self._evaluare("epoca_veche", data_evaluare=DUPA, versiune=VERSIUNE_VECHE)

        self.assertEqual(self._id_uri_selectate(), [])

    def test_incercarea_esuata_de_evaluare_nu_e_o_stire(self):
        """
        `status_evaluare = 'respins'` inseamna ca modelul a raspuns cu ceva stricat.

        Nu s-a aflat nimic despre anunt, deci n-are ce cauta in briefing ca noutate. Daca
        ar intra, o rulare cu erori ar umple raportul cu anunturi despre care tocmai NU
        stim nimic nou.
        """
        self._anunt("incercat", data_extragere=INAINTE)
        self._evaluare("incercat", data_evaluare=DUPA, status="respins")

        self.assertEqual(self._id_uri_selectate(), [])

    def test_refiltrarea_a_tot_NU_aduce_nimic_in_briefing(self):
        """
        DE CE `data_filtrare` E IN AFARA FORMULEI, verificat, nu doar scris in comentariu.

        Filtrarea e gratuita si determinista, deci se ruleaza pe TOT de fiecare data -
        sute de randuri rescrise in cateva secunde. Daca ar conta la taietura, orice
        rulare de filtrare ar face intreaga baza "noua", iar briefingul ar spune de
        fiecare data totul. Adica exact inversul distilarii.
        """
        self._anunt("vechi", data_extragere=INAINTE, data_filtrare=DUPA)
        self._evaluare("vechi", data_evaluare=INAINTE)

        self.assertEqual(self._id_uri_selectate(), [])


class TestFaraReper(BazaDeTest):
    """Primul briefing din viata bazei: n-a existat niciodata unul, deci totul e nou."""

    def test_fara_reper_vine_tot(self):
        self._anunt("unu", data_extragere=INAINTE)
        self._anunt("doi", data_extragere=DUPA)
        self._evaluare("unu", data_evaluare=INAINTE)

        id_uri = sorted(a["id"] for a in db.anunturi_pentru_briefing(None))

        self.assertEqual(id_uri, ["doi", "unu"])


class TestPrinBriefingIntreg(BazaDeTest):
    """
    Aceeasi reparatie, vazuta pe usa pe care intra JA.S.Mine: briefingul intreg.

    Testul de mai sus dovedeste ca interogarea aduce randul. Asta dovedeste ca randul
    ajunge pana in text - adica exact ce a lipsit pe 16 august, cand raportul spunea
    "Nimic nou" desi in baza erau zece verdicte proaspete.
    """

    def test_anuntul_evaluat_dupa_reper_ajunge_in_text(self):
        db.scrie_stare(CHEIE_REPER, REPER)

        self._anunt("evaluat_dupa", data_extragere=INAINTE)
        self._evaluare("evaluat_dupa", data_evaluare=DUPA)

        rezultat = briefing()

        self.assertFalse(rezultat["briefing"]["nimic_nou"])
        self.assertEqual(rezultat["briefing"]["anunturi_noi"], 1)
        self.assertEqual(
            [a["id"] for a in rezultat["briefing"]["merita_atentie"]], ["evaluat_dupa"]
        )
        self.assertNotIn("Nimic nou", rezultat["text"])

    def test_citirea_nu_mai_muta_reperul(self):
        """
        Ce NU s-a schimbat, verificat ca sa ramana asa.

        Reparatia atinge doar taietura. `marcheaza_citit` ramane implicit False, deci un
        briefing cerut din greseala nu inghite nimic - si acelasi anunt se vede si a doua
        oara. O repetitie se vede si se ignora; o lipsa, nu.
        """
        db.scrie_stare(CHEIE_REPER, REPER)

        self._anunt("evaluat_dupa", data_extragere=INAINTE)
        self._evaluare("evaluat_dupa", data_evaluare=DUPA)

        briefing()
        al_doilea = briefing()

        self.assertEqual(db.citeste_stare(CHEIE_REPER), REPER)
        self.assertEqual(al_doilea["briefing"]["anunturi_noi"], 1)


class TestStadiulAnunturilor(BazaDeTest):
    """
    FAPTELE din care briefingul afla cat lucru a ramas nefacut.

    Aici nu se testeaza REGULA ("ce inseamna in asteptare") - aia e pura si sta in
    tests/test_briefing.py, fara nicio baza. Aici se testeaza doar ca interogarea aduce
    ce trebuie: un rand per anunt, cu stadiul lui.

    Nici varsta nu se testeaza aici, si nu din lene: ea se masoara fata de ceasul de
    acum, deci un test scris pe date fixe ar innegri suita peste treizeci de zile fara
    ca vreun cod sa fie gresit.
    """

    def _stadiu(self, id_anunt: str) -> dict:
        return {s["id"]: s for s in db.stadiul_anunturilor()}[id_anunt]

    def test_un_anunt_ramane_un_rand(self):
        """
        Trei LEFT JOIN-uri si tot un rand per anunt.

        Daca vreo tabela ar putea potrivi doua randuri, fiecare cifra din avertizare ar
        fi umflata - si nu s-ar vedea, fiindca ar fi umflata "credibil".
        """
        self._anunt("unu", data_extragere=INAINTE)
        self._evaluare("unu", data_evaluare=INAINTE)
        self._anunt("doi", data_extragere=DUPA)

        stadii = db.stadiul_anunturilor()

        self.assertEqual(sorted(s["id"] for s in stadii), ["doi", "unu"])

    def test_spune_ce_are_si_ce_nu_are_anuntul(self):
        self._anunt("cu_text", data_extragere=INAINTE)

        stadiu = self._stadiu("cu_text")

        self.assertEqual(stadiu["sursa"], "ejobs")
        self.assertEqual(stadiu["are_link"], 1)
        self.assertEqual(stadiu["are_descriere"], 1)
        self.assertEqual(stadiu["verdict"], "trece")
        self.assertIsNone(stadiu["status_normalizare"])
        self.assertIsNone(stadiu["status_pagina"])

    def test_descrierea_goala_se_vede_ca_lipsa(self):
        """
        Un sir gol nu e o descriere. Fara TRIM in interogare, un anunt cu descrierea ''
        ar trece drept "are text" si nu i s-ar mai cere niciodata pagina.
        """
        self._anunt("gol", data_extragere=INAINTE)
        self._scrie("UPDATE anunturi SET descriere = '   ' WHERE id = 'gol'")

        self.assertEqual(self._stadiu("gol")["are_descriere"], 0)

    def test_evaluarea_pe_criterii_vechi_nu_conteaza_ca_evaluare(self):
        """
        Aceeasi regula ca peste tot: se citesc doar verdictele pe versiunea de acum.

        Fara ea, dupa o urcare de versiune, avertizarea ar spune "neevaluate: 0" tocmai
        cand nimic nu mai e evaluat pe criteriile care conteaza.
        """
        self._anunt("epoca_veche", data_extragere=INAINTE)
        self._evaluare("epoca_veche", data_evaluare=INAINTE, versiune=VERSIUNE_VECHE)

        self.assertEqual(self._stadiu("epoca_veche")["are_evaluare_valabila"], 0)

    def test_evaluarea_valabila_se_vede(self):
        self._anunt("judecat", data_extragere=INAINTE)
        self._evaluare("judecat", data_evaluare=INAINTE)

        self.assertEqual(self._stadiu("judecat")["are_evaluare_valabila"], 1)


class TestAvertizareaAjungeInText(BazaDeTest):
    """Regula si faptele, legate: pe o baza cu lucru nefacut, briefingul o spune."""

    def test_anuntul_neevaluat_face_briefingul_incomplet(self):
        db.scrie_stare(CHEIE_REPER, REPER)

        # Anunt trecut de filtru, fara nicio evaluare. Nu depinde de varsta, deci testul
        # da acelasi rezultat si peste un an.
        self._anunt("neevaluat", data_extragere=DUPA)

        rezultat = briefing()

        self.assertEqual(rezultat["briefing"]["in_asteptare"]["neevaluate"], 1)
        self.assertIn("neevaluate: 1", rezultat["text"])
        self.assertIn("Atentie, briefingul e incomplet", rezultat["text"])

    def test_baza_cu_totul_judecat_nu_avertizeaza_degeaba(self):
        db.scrie_stare(CHEIE_REPER, REPER)

        self._anunt("gata", data_extragere=DUPA)
        self._evaluare("gata", data_evaluare=DUPA)
        self._scrie(
            "INSERT INTO anunturi_normalizate (anunt_id, status_normalizare,"
            " data_normalizare) VALUES ('gata', 'ok', ?)",
            (DUPA,),
        )
        # Pagina i s-a luat deja, deci nici descriere nu mai asteapta.
        self._scrie("UPDATE anunturi SET status_pagina = 'ok' WHERE id = 'gata'")

        rezultat = briefing()

        self.assertEqual(rezultat["briefing"]["in_asteptare"]["total"], 0)
        self.assertNotIn("incomplet", rezultat["text"])


class TestMotiveCoada(BazaDeTest):
    """Motivele de coada (29 sept. 2026) ajung din filtrare, prin baza, in briefing."""

    def test_motivele_scrise_la_filtrare_se_citesc_in_briefing(self):
        self._anunt("A", DUPA)
        db.salveaza_filtrare(
            "A",
            {"verdict": "trece", "motive_respingere": [], "necunoscute": [],
             "motive_coada": ["salariu sub 6000 RON: max 5500"]},
            VERSIUNE_ACUM,
        )

        (anunt,) = db.anunturi_pentru_briefing(None)

        self.assertEqual(anunt["motive_coada"], ["salariu sub 6000 RON: max 5500"])

    def test_randul_filtrat_inainte_de_coloana_noua_citeste_lista_goala(self):
        # _anunt() scrie filtrarea fara motive_coada, ca un rand din baza veche (NULL).
        self._anunt("A", DUPA)

        (anunt,) = db.anunturi_pentru_briefing(None)

        self.assertEqual(anunt["motive_coada"], [])

    def test_o_baza_veche_primeste_coloana_la_initializare(self):
        with closing(sqlite3.connect(self.cale)) as conexiune:
            conexiune.execute("ALTER TABLE anunturi_filtrate DROP COLUMN motive_coada")
            conexiune.commit()

        db.initializeaza_db()

        with closing(sqlite3.connect(self.cale)) as conexiune:
            coloane = {r[1] for r in conexiune.execute("PRAGMA table_info(anunturi_filtrate)")}
        self.assertIn("motive_coada", coloane)


if __name__ == "__main__":
    unittest.main()
