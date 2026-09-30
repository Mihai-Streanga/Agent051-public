r"""
Teste pentru contorul de incercari esuate la evaluarea calitativa.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

DE CE UN FISIER SEPARAT de tests/test_evaluare_calitativa.py: acolo se testeaza ce face
ADAPTORUL cu cifra (o pune in raport, o sorteaza), cu un `salveaza` inventat si fara disc.
Aici se testeaza ca cifra CHIAR SUPRAVIETUIESTE in baza - si asta nu se poate afla decat
cu o baza adevarata, fiindca intreaga problema e un INSERT OR REPLACE.

BAZA DE TEST E TEMPORARA, iar data/agent051.db NU E ATINSA NICIODATA. Schema vine din
store/db.py, nu e rescrisa aici.

CE VERIFICA, DE FAPT:
randul evaluarii se scrie cu INSERT OR REPLACE, deci fiecare incercare STERGE randul de
dinainte. Dupa trei respingeri, in baza arata exact ca dupa una - si de aia costul unui
anunt care esueaza la fiecare rulare era invizibil. `incercari_esuate` e singura coloana
care are voie sa treaca dintr-un rand in urmatorul: celelalte sunt "ce a spus modelul
ultima data", asta e "de cate ori am platit degeaba".
"""

import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.store import db

VERSIUNE = "9.9"

RASPUNS_BUN = {
    "ok": True,
    "date": {
        "relevant": "ideal",
        "motiv_relevanta": "Rol de automatizare in payroll.",
        "interes": "ridicat",
        "motiv_interes": "Construieste, nu opereaza.",
        "single_point_of_failure": "nu",
        "motiv_spof": "Echipa are mai multi oameni.",
    },
}

RASPUNS_RESPINS = {"ok": False, "eroare": "raspunsul nu e JSON valid"}


class TestContorulEsecurilor(unittest.TestCase):

    def setUp(self):
        self.dosar = Path(tempfile.mkdtemp(prefix="agent051-test-esecuri-"))
        self.cale = self.dosar / "test.db"

        self._cale_reala = db.CALE_DB
        self._dosar_real = db.DOSAR_DATE
        db.CALE_DB = self.cale
        db.DOSAR_DATE = self.dosar
        db.initializeaza_db()

        self._scrie(
            "INSERT INTO anunturi (id, sursa, titlu, firma, locatie, link,"
            " data_anunt, data_extragere) VALUES ('a1', 'bestjobs',"
            " 'Talent and Engagement Specialist', 'Firma SRL', 'Bucuresti',"
            " 'https://exemplu.invalid/1', '2026-08-16', '2026-08-16')"
        )

    def tearDown(self):
        db.CALE_DB = self._cale_reala
        db.DOSAR_DATE = self._dosar_real
        shutil.rmtree(self.dosar, ignore_errors=True)

    def _scrie(self, comanda: str, parametri=()):
        with closing(sqlite3.connect(self.cale)) as conexiune:
            conexiune.execute(comanda, parametri)
            conexiune.commit()

    def _citeste_contorul(self) -> int:
        with closing(sqlite3.connect(self.cale)) as conexiune:
            return conexiune.execute(
                "SELECT incercari_esuate FROM evaluari_calitative WHERE anunt_id = 'a1'"
            ).fetchone()[0]

    def test_primul_esec_e_unu(self):
        db.salveaza_evaluare_calitativa("a1", RASPUNS_RESPINS, VERSIUNE)

        self.assertEqual(self._citeste_contorul(), 1)

    def test_esecurile_se_ADUNA_peste_INSERT_OR_REPLACE(self):
        """
        Miezul fisierului. Trei respingeri, trei randuri scrise unul peste altul - si
        totusi cifra ajunge la 3. Fara ea, a treia rulare arata identic cu prima, iar
        cheltuiala care se repeta la infinit nu se vede nicaieri.
        """
        for _ in range(3):
            db.salveaza_evaluare_calitativa("a1", RASPUNS_RESPINS, VERSIUNE)

        self.assertEqual(self._citeste_contorul(), 3)

    def test_raspunsul_bun_nu_creste_contorul(self):
        db.salveaza_evaluare_calitativa("a1", RASPUNS_BUN, VERSIUNE)

        self.assertEqual(self._citeste_contorul(), 0)

    def test_reusita_de_dupa_esecuri_PASTREAZA_cifra(self):
        """
        Un anunt care a mers din a treia incercare a costat trei apeluri, si asta ramane
        adevarat dupa ce a mers. Resetarea ar sterge tocmai dovada cheltuielii.
        """
        db.salveaza_evaluare_calitativa("a1", RASPUNS_RESPINS, VERSIUNE)
        db.salveaza_evaluare_calitativa("a1", RASPUNS_RESPINS, VERSIUNE)
        db.salveaza_evaluare_calitativa("a1", RASPUNS_BUN, VERSIUNE)

        self.assertEqual(self._citeste_contorul(), 2)
        with closing(sqlite3.connect(self.cale)) as conexiune:
            status = conexiune.execute(
                "SELECT status_evaluare FROM evaluari_calitative WHERE anunt_id = 'a1'"
            ).fetchone()[0]
        self.assertEqual(status, "ok")

    def test_migrarea_crede_randul_respins_pe_o_incercare(self):
        """
        O baza veche are randuri "respins" scrise inainte sa existe coloana. Randul e
        dovada UNEI incercari esuate - n-ar exista altfel - deci 1, nu 0.

        Nu 2 si nu "cel putin 1": cate au fost inainte nu se mai poate afla, iar o cifra
        ghicita ar fi mai rea decat una mica. Se simuleaza scoatand coloana din schema.
        """
        self._scrie(
            "INSERT INTO evaluari_calitative (anunt_id, status_evaluare, eroare,"
            " versiune_criterii, data_evaluare) VALUES ('a1', 'respins',"
            " 'JSON invalid', ?, '2026-08-16T10:00:00+00:00')",
            (VERSIUNE,),
        )
        self._scrie("ALTER TABLE evaluari_calitative DROP COLUMN incercari_esuate")

        db.initializeaza_db()

        self.assertEqual(self._citeste_contorul(), 1)

    def test_migrarea_nu_atinge_randurile_reusite(self):
        """Un verdict bun n-a esuat niciodata, din cate stim. Deci 0."""
        db.salveaza_evaluare_calitativa("a1", RASPUNS_BUN, VERSIUNE)
        self._scrie("ALTER TABLE evaluari_calitative DROP COLUMN incercari_esuate")

        db.initializeaza_db()

        self.assertEqual(self._citeste_contorul(), 0)


if __name__ == "__main__":
    unittest.main()
