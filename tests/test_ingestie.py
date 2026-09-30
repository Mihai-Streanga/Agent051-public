r"""
Teste pentru core/ingestie.py.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

UITA-TE CE NU E AICI.
Nu exista conexiune la Gmail. Nu exista parola. Nu exista baza de date. Nu exista
internet. Nu exista niciun fisier temporar. Nu exista "mocks" - adica obiecte false
care sa se prefaca a fi Gmail-ul, si pe care ar trebui sa le scriem si sa le
intretinem noi.

Sunt doar niste dictionare inventate, date unei functii, si un raspuns verificat.
Testul ruleaza in cateva milisecunde, in avion, cu internetul taiat, si nu poate
strica nimic - nici cutia ta postala, nici baza de date.

ASTA e motivul pentru care core/ nu are voie sa faca IO. Nu e o preferinta estetica.
Daca filtreaza_noi() ar fi stiut sa se conecteze la Gmail, ca sa o testam ar fi
trebuit sa avem internet, un cont valid, o parola in .env si niste mailuri reale
acolo - iar testul ar fi picat cand pica reteaua, nu cand se strica logica.
Un test care pica din motive care nu au legatura cu codul e un test pe care il ignori.
Iar un test pe care il ignori e un test care nu exista.

Folosim `unittest`, care vine cu Python. Nicio dependinta noua.
"""

import sys
import unittest
from pathlib import Path

# Codul proiectului sta in src/. Ii aratam lui Python calea.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core.ingestie import filtreaza_noi, uid_uri_de_adus


def mail(id_mail: str, subiect: str = "Joburi noi") -> dict:
    """Fabrica un mail de proba. Datele sunt inventate - nimic real."""
    return {
        "id": id_mail,
        "expeditor": "noreply@ejobs.ro",
        "subiect": subiect,
        "data_primire": "2026-07-13T09:15:00+03:00",
        "sursa": "ejobs",
        "corp_text": "Contabil Senior - Brasov",
    }


class TestFiltreazaNoi(unittest.TestCase):

    def test_baza_goala_toate_sunt_noi(self):
        """Prima rulare: baza e goala, deci toate mailurile sunt noi."""
        mailuri = [mail("<a@ejobs.ro>"), mail("<b@ejobs.ro>")]

        rezultat = filtreaza_noi(mailuri, set())

        self.assertEqual(len(rezultat), 2)

    def test_mailurile_deja_in_baza_sunt_sarite(self):
        """A doua rulare, aceleasi mailuri: niciunul nu mai e nou."""
        mailuri = [mail("<a@ejobs.ro>"), mail("<b@ejobs.ro>")]
        existente = {"<a@ejobs.ro>", "<b@ejobs.ro>"}

        rezultat = filtreaza_noi(mailuri, existente)

        # Asta e IDEMPOTENTA, verificata. Ruleaza ingestia de zece ori: acelasi
        # mail intra o singura data. Fara asta, peste o luna ai acelasi anunt de
        # zece ori in baza si nu mai stii care e real.
        self.assertEqual(rezultat, [])

    def test_pastreaza_doar_ce_lipseste(self):
        """Cazul obisnuit: unele mailuri le avem, altele au aparut intre timp."""
        mailuri = [mail("<vechi@ejobs.ro>"), mail("<nou@ejobs.ro>")]
        existente = {"<vechi@ejobs.ro>"}

        rezultat = filtreaza_noi(mailuri, existente)

        self.assertEqual(len(rezultat), 1)
        self.assertEqual(rezultat[0]["id"], "<nou@ejobs.ro>")

    def test_acelasi_mail_de_doua_ori_in_aceeasi_citire(self):
        """
        Un mail poate aparea de doua ori chiar in aceeasi citire - de exemplu daca
        are doua etichete Gmail. Il salvam o data, si il numaram o data.
        """
        mailuri = [mail("<x@ejobs.ro>"), mail("<x@ejobs.ro>")]

        rezultat = filtreaza_noi(mailuri, set())

        self.assertEqual(len(rezultat), 1)

    def test_mailurile_fara_id_sunt_sarite(self):
        """
        Fara Message-ID, un mail nu poate fi salvat (id-ul e cheia primara) si nici
        recunoscut data viitoare. Il sarim - nu inventam un id, fiindca un id
        inventat de fiecare data ar face acelasi mail sa intre la nesfarsit.
        """
        mailuri = [mail(""), mail("<bun@ejobs.ro>")]

        rezultat = filtreaza_noi(mailuri, set())

        self.assertEqual(len(rezultat), 1)
        self.assertEqual(rezultat[0]["id"], "<bun@ejobs.ro>")

    def test_lista_primita_nu_e_modificata(self):
        """
        Functia nu strica datele care i se dau: construieste o lista noua.
        Cine o apeleaza poate folosi lista lui mai departe, nestirbita.
        """
        mailuri = [mail("<a@ejobs.ro>"), mail("<b@ejobs.ro>")]

        filtreaza_noi(mailuri, {"<a@ejobs.ro>"})

        self.assertEqual(len(mailuri), 2)

    def test_ordinea_se_pastreaza(self):
        """Mailurile ies in ordinea in care au intrat. Fara surprize."""
        mailuri = [mail("<1@ejobs.ro>"), mail("<2@ejobs.ro>"), mail("<3@ejobs.ro>")]

        rezultat = filtreaza_noi(mailuri, set())

        self.assertEqual([m["id"] for m in rezultat], ["<1@ejobs.ro>", "<2@ejobs.ro>", "<3@ejobs.ro>"])


class TestUidUriDeAdus(unittest.TestCase):
    """
    Decizia dinaintea descarcarii: pentru care mesaje merita cerut corpul.

    Aici se masoara reparatia care a taiat 103 secunde dintr-o rulare de 134.
    """

    def test_baza_goala_se_aduc_toate(self):
        identificatori = [
            {"uid": "1", "id": "<a@ejobs.ro>"},
            {"uid": "2", "id": "<b@ejobs.ro>"},
        ]

        self.assertEqual(uid_uri_de_adus(identificatori, set()), ["1", "2"])

    def test_ce_e_deja_in_baza_nu_se_mai_descarca(self):
        """
        ASTA E REPARATIA, in doua randuri.

        A doua rulare, pe aceleasi mailuri: nu se descarca niciunul. Inainte se
        descarcau toate, si abia dupa aceea se afla ca nu era nevoie de niciunul.
        """
        identificatori = [
            {"uid": "1", "id": "<a@ejobs.ro>"},
            {"uid": "2", "id": "<b@ejobs.ro>"},
        ]
        existente = {"<a@ejobs.ro>", "<b@ejobs.ro>"}

        self.assertEqual(uid_uri_de_adus(identificatori, existente), [])

    def test_se_aduce_doar_ce_lipseste(self):
        identificatori = [
            {"uid": "1", "id": "<vechi@ejobs.ro>"},
            {"uid": "2", "id": "<nou@ejobs.ro>"},
        ]

        rezultat = uid_uri_de_adus(identificatori, {"<vechi@ejobs.ro>"})

        self.assertEqual(rezultat, ["2"])

    def test_mesajul_fara_message_id_se_aduce_intotdeauna(self):
        """
        Fara antetul Message-ID nu avem cu ce sa recunoastem mailul: id-ul lui se
        calculeaza abia din corp, ca amprenta a continutului. Deci il descarcam si
        lasam filtrul de dupa sa decida. Cateva descarcari inutile se vad in cifre;
        un mail sarit pe tacute nu se vede nicaieri.
        """
        identificatori = [
            {"uid": "1", "id": ""},
            {"uid": "2", "id": "<stiut@ejobs.ro>"},
        ]

        rezultat = uid_uri_de_adus(identificatori, {"<stiut@ejobs.ro>"})

        self.assertEqual(rezultat, ["1"])

    def test_acelasi_mail_sub_doua_etichete_se_aduce_o_data(self):
        identificatori = [
            {"uid": "1", "id": "<x@ejobs.ro>"},
            {"uid": "9", "id": "<x@ejobs.ro>"},
        ]

        self.assertEqual(uid_uri_de_adus(identificatori, set()), ["1"])

    def test_fara_uid_nu_avem_ce_cere(self):
        """Un identificator fara UID nu se poate cere serverului. Il sarim."""
        identificatori = [{"uid": "", "id": "<a@ejobs.ro>"}]

        self.assertEqual(uid_uri_de_adus(identificatori, set()), [])


if __name__ == "__main__":
    unittest.main()
