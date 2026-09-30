r"""
Teste pentru FAPTUL pe care se sprijina rejudecata: "descrierea a aparut dupa judecata".

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

BAZA DE TEST E TEMPORARA, iar data/agent051.db NU E ATINSA NICIODATA. Schema vine din
store/db.py, nu e rescrisa aici.

CE SE TESTEAZA AICI, SI CE NU. Aici e doar faptul, calculat in SQL: cine a capatat
descriere dupa ce fusese judecat. Ce FACE adaptorul cu el (sare, rejudeca, numara) se
testeaza fara disc, in test_evaluare_calitativa.py si test_adaptor_normalizare.py.

DE CE MERITA UN TEST PE BAZA REALA: regula pare "compara doua date", dar jumatate din ea
e conditia `status_pagina = 'ok'`. `data_pagina` se scrie la ORICE incercare de pagina,
inclusiv la cele care n-au adus nimic - expirat, interzis_robots, fara_descriere. Fara
conditia aia, un anunt al carui link e mort ar fi rejudecat la fiecare rulare, ar primi
de fiecare data acelasi "incert, lipseste descrierea", si ar plati un apel de model pentru
el. Greseala asta nu se vede din adaptor: acolo ar sosi doar un `True` care pare corect.
"""

import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.store import configuratie, db

VERSIUNE_ACUM = "9.9"

# Doua momente, in ordine, ca sa nu depinda niciun test de ceasul masinii.
INAINTE = "2026-08-10T08:00:00+00:00"
DUPA = "2026-08-16T08:00:00+00:00"


class TestDescriereaAparutaDupaJudecata(unittest.TestCase):

    def setUp(self):
        self.dosar = Path(tempfile.mkdtemp(prefix="agent051-test-rejudecare-"))
        self.cale = self.dosar / "test.db"

        self._cale_reala = db.CALE_DB
        self._dosar_real = db.DOSAR_DATE
        db.CALE_DB = self.cale
        db.DOSAR_DATE = self.dosar
        db.initializeaza_db()

        # Versiunea "de acum", fixata: o urcare reala in criterii.yaml n-are voie sa faca
        # suita rosie fara ca vreo linie de cod sa fie gresita.
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

    def _anunt(self, id_anunt, status_pagina=None, data_pagina=None, cu_filtrare=True):
        self._scrie(
            "INSERT INTO anunturi (id, sursa, titlu, firma, locatie, link, descriere,"
            " data_anunt, data_extragere, status_pagina, data_pagina)"
            " VALUES (?, 'ejobs', 'Specialist Payroll', 'O firma', '',"
            " 'https://exemplu.invalid/1', 'text', '2026-08-01T08:00:00+00:00',"
            " '2026-08-01T08:00:00+00:00', ?, ?)",
            (id_anunt, status_pagina, data_pagina),
        )
        if cu_filtrare:
            self._scrie(
                "INSERT INTO anunturi_filtrate (anunt_id, verdict, versiune_criterii)"
                " VALUES (?, 'trece', ?)",
                (id_anunt, VERSIUNE_ACUM),
            )

    def _evaluare(self, id_anunt, data_evaluare, status="ok"):
        self._scrie(
            "INSERT INTO evaluari_calitative (anunt_id, relevant, motiv_relevanta,"
            " interes, motiv_interes, single_point_of_failure, motiv_spof,"
            " status_evaluare, versiune_criterii, data_evaluare)"
            " VALUES (?, 'incert', 'lipseste descrierea', 'incert', 'motiv', 'incert',"
            " 'motiv', ?, ?, ?)",
            (id_anunt, status, VERSIUNE_ACUM, data_evaluare),
        )

    def _normalizare(self, id_anunt, data_normalizare, status="ok"):
        self._scrie(
            "INSERT INTO anunturi_normalizate (anunt_id, rol_normalizat, senioritate,"
            " tip_munca, domeniu, status_normalizare, data_normalizare)"
            " VALUES (?, 'Specialist Payroll', 'senior', 'hibrid', 'payroll', ?, ?)",
            (id_anunt, status, data_normalizare),
        )

    def _marcaje_evaluare(self):
        return {
            rand["id"]: rand["descriere_dupa_evaluare"]
            for rand in db.anunturi_pentru_calitativ()
        }

    def _marcaje_normalizare(self):
        return {
            rand["id"]: rand["descriere_dupa_normalizare"]
            for rand in db.anunturi_de_normalizat()
        }

    # ------------------------------------------------------------------
    # Evaluarea calitativa
    # ------------------------------------------------------------------

    def test_pagina_luata_DUPA_verdict_marcheaza_anuntul(self):
        """Cazul pentru care exista tot capitolul: judecat pe titlu gol, acum are text."""
        self._anunt("a1", status_pagina="ok", data_pagina=DUPA)
        self._evaluare("a1", data_evaluare=INAINTE)

        self.assertTrue(self._marcaje_evaluare()["a1"])

    def test_pagina_luata_INAINTE_de_verdict_nu_marcheaza_nimic(self):
        """
        Verdictul a fost dat cu descrierea in fata. Nu s-a schimbat nimic de atunci, deci
        o rejudecata ar plati pentru exact acelasi raspuns.
        """
        self._anunt("a1", status_pagina="ok", data_pagina=INAINTE)
        self._evaluare("a1", data_evaluare=DUPA)

        self.assertFalse(self._marcaje_evaluare()["a1"])

    def test_paginile_care_NU_au_adus_text_nu_declanseaza_nimic(self):
        """
        Miezul precautiei. Toate trei au `data_pagina` mai noua decat verdictul - dar
        niciuna n-a adus un rand de descriere. Rejudecate, ar primi acelasi "incert" si ar
        costa un apel de fiecare data cand rulezi.
        """
        for status in ("expirat", "interzis_robots", "fara_descriere"):
            with self.subTest(status=status):
                id_anunt = f"a-{status}"
                self._anunt(id_anunt, status_pagina=status, data_pagina=DUPA)
                self._evaluare(id_anunt, data_evaluare=INAINTE)

                self.assertFalse(self._marcaje_evaluare()[id_anunt])

    def test_anuntul_fara_nicio_incercare_de_pagina_nu_e_marcat(self):
        """Cazul obisnuit pentru LinkedIn: nu i s-a cerut niciodata pagina."""
        self._anunt("a1", status_pagina=None, data_pagina=None)
        self._evaluare("a1", data_evaluare=INAINTE)

        self.assertFalse(self._marcaje_evaluare()["a1"])

    def test_anuntul_neevaluat_nu_e_marcat_ca_rejudecabil(self):
        """
        N-are ce sa i se rejudece: n-a primit niciodata un verdict. Intra la evaluare pe
        drumul obisnuit, ca anunt nou - vezi alege_anunturile.
        """
        self._anunt("a1", status_pagina="ok", data_pagina=DUPA)

        self.assertFalse(self._marcaje_evaluare()["a1"])

    def test_incercarea_respinsa_nu_conteaza_drept_judecata(self):
        """
        Un rand cu status "respins" (JSON stricat) nu e o evaluare. Anuntul e oricum
        eligibil - se reincearca - deci nu se numara si ca rejudecat.
        """
        self._anunt("a1", status_pagina="ok", data_pagina=DUPA)
        self._evaluare("a1", data_evaluare=INAINTE, status="respins")

        self.assertFalse(self._marcaje_evaluare()["a1"])

    # ------------------------------------------------------------------
    # Normalizarea - aceeasi intrebare, alta data de judecata
    # ------------------------------------------------------------------

    def test_normalizarea_marcheaza_dupa_aceeasi_regula(self):
        self._anunt("dupa", status_pagina="ok", data_pagina=DUPA)
        self._normalizare("dupa", data_normalizare=INAINTE)

        self._anunt("inainte", status_pagina="ok", data_pagina=INAINTE)
        self._normalizare("inainte", data_normalizare=DUPA)

        self._anunt("pagina-moarta", status_pagina="expirat", data_pagina=DUPA)
        self._normalizare("pagina-moarta", data_normalizare=INAINTE)

        self._anunt("nenormalizat", status_pagina="ok", data_pagina=DUPA)

        marcaje = self._marcaje_normalizare()

        self.assertTrue(marcaje["dupa"], "a capatat text dupa normalizare - de refacut")
        self.assertFalse(marcaje["inainte"], "textul era acolo cand s-a normalizat")
        self.assertFalse(marcaje["pagina-moarta"], "pagina n-a adus nimic de citit")
        self.assertFalse(marcaje["nenormalizat"], "n-a fost normalizat niciodata")

    def test_cele_doua_intrebari_nu_se_amesteca(self):
        """
        Aceeasi pagina, doua judecati la momente diferite: normalizarea a apucat-o, evaluarea
        nu. Trebuie sa iasa marcaje DIFERITE - altfel una din ele se ia dupa data celeilalte
        si ori plateste degeaba, ori rateaza o rejudecata.
        """
        self._anunt("a1", status_pagina="ok", data_pagina="2026-08-13T08:00:00+00:00")
        self._normalizare("a1", data_normalizare=DUPA)
        self._evaluare("a1", data_evaluare=INAINTE)

        self.assertFalse(self._marcaje_normalizare()["a1"])
        self.assertTrue(self._marcaje_evaluare()["a1"])


if __name__ == "__main__":
    unittest.main()
