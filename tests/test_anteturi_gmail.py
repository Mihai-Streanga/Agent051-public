r"""
Teste pentru citirea raspunsului cu anteturi din ingest/gmail.py.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

DE CE E TESTAT AICI CEVA DIN ingest/, cand regula spune ca testam core/:
`_identificatorii_din_raspuns` e o functie PURA aflata in ingest/ - primeste octetii
pe care i-a spus serverul si intoarce o lista. Nu se conecteaza la nimic. Sta acolo
fiindca e cunoastere despre IMAP, si IMAP nu are ce cauta in core/.

Si e tocmai bucata pe care merita s-o verifici: de ea atarna sa nu se descarce degeaba
~580 de mailuri la fiecare rulare. Daca citirea UID-ului se strica, id-urile ies goale,
totul pare "nou" si ingestia se intoarce, tacut, exact la lentoarea reparata.

Octetii de mai jos sunt scrisi de mana, in forma in care raspunde un server IMAP.
Niciun mail real, nicio parola, niciun internet.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.ingest.gmail import _identificatorii_din_raspuns


class TestIdentificatoriiDinRaspuns(unittest.TestCase):

    def test_perechile_obisnuite(self):
        """Forma normala: o eticheta cu UID-ul, apoi antetul cerut."""
        linii = [
            (b"1 (UID 12 BODY[HEADER.FIELDS (MESSAGE-ID)] {40}",
             b"Message-ID: <abc@ejobs.ro>\r\n\r\n"),
            b")",
            (b"2 (UID 13 BODY[HEADER.FIELDS (MESSAGE-ID)] {40}",
             b"Message-ID: <def@bestjobs.eu>\r\n\r\n"),
            b")",
        ]

        rezultat = _identificatorii_din_raspuns(linii)

        self.assertEqual(
            rezultat,
            [
                {"uid": "12", "id": "<abc@ejobs.ro>"},
                {"uid": "13", "id": "<def@bestjobs.eu>"},
            ],
        )

    def test_mesajul_fara_message_id_iese_cu_id_gol(self):
        """
        Exista mailuri fara Message-ID. Aici doar constatam: id gol. Ce se face cu
        ele se decide in core/ingestie.py - si acolo decizia e sa li se aduca oricum
        corpul, fiindca abia din corp li se poate calcula o amprenta stabila.
        """
        linii = [
            (b"1 (UID 7 BODY[HEADER.FIELDS (MESSAGE-ID)] {2}", b"\r\n"),
            b")",
        ]

        self.assertEqual(_identificatorii_din_raspuns(linii), [{"uid": "7", "id": ""}])

    def test_ce_nu_e_pereche_se_sare(self):
        """Parantezele de inchidere si raspunsurile fara continut nu sunt mesaje."""
        linii = [b")", b"1 (UID 5)", None]

        self.assertEqual(_identificatorii_din_raspuns(linii), [])

    def test_spatiile_din_jurul_id_ului_se_taie(self):
        """
        Taierea trebuie sa fie EXACT aceeasi ca la citirea mailului intreg. Daca cele
        doua drumuri ar curata id-ul altfel, acelasi mail ar avea doua id-uri, s-ar
        descarca la fiecare rulare si ar intra de doua ori in baza.
        """
        linii = [
            (b"1 (UID 3 BODY[HEADER.FIELDS (MESSAGE-ID)] {40}",
             b"Message-ID:   <spatii@ejobs.ro>  \r\n\r\n"),
            b")",
        ]

        self.assertEqual(
            _identificatorii_din_raspuns(linii),
            [{"uid": "3", "id": "<spatii@ejobs.ro>"}],
        )


if __name__ == "__main__":
    unittest.main()
