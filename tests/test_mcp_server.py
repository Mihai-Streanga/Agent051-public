r"""
Teste pentru adapters/mcp_server.py - invelisul MCP.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

UITA-TE CE NU E AICI.
Niciun server pornit, niciun port deschis, nicio cerere HTTP reala, nicio conexiune
la Gmail si nicio atingere a bazei de date. Uneltele sunt chemate ca functii obisnuite,
iar adaptoarele din spatele lor sunt inlocuite cu functii care doar isi noteaza ca au
fost apelate.

CE VERIFICA, DE FAPT, TESTELE ASTEA:
ca invelisul chiar e SUBTIRE. Fiecare unealta trebuie sa duca parametrii la adaptorul
potrivit si sa aduca raspunsul inapoi, fara sa schimbe nimic pe drum. Un invelis care
"ajuta" - completeaza o valoare implicita, repara un parametru, prinde un caz special -
devine un al doilea loc in care traieste logica, iar cele doua se despart in timp.

Plus doua lucruri pe care nu le poti verifica citind codul:
  - ca uneltele care au nevoie de model NU sunt expuse (faza 2, nu acum);
  - ca usa se inchide cand exista un token, si ce se intampla cand lipseste.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path

# Codul proiectului sta in src/. Ii aratam lui Python calea.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.adapters import mcp_server


def unelte_inregistrate() -> set:
    """Numele uneltelor pe care serverul le declara catre client."""
    return {unealta.name for unealta in asyncio.run(mcp_server.server.list_tools())}


class ApelNotat:
    """
    Un adaptor fals: retine cu ce a fost chemat si intoarce ce i s-a spus.

    Tine locul unui adaptor adevarat, care ar atinge Gmail-ul sau baza. Trei randuri,
    fara nicio biblioteca de imitatii - la fel ca modelele inventate din celelalte suite.
    """

    def __init__(self, intoarce=None, arunca: Exception = None):
        self.apeluri = []
        self.intoarce = intoarce if intoarce is not None else {"gata": True}
        self.arunca = arunca

    def __call__(self, *argumente, **parametri):
        self.apeluri.append((argumente, parametri))
        if self.arunca is not None:
            raise self.arunca
        return self.intoarce


class TestUneltele(unittest.TestCase):

    def test_sunt_expuse_exact_cele_zece_unelte(self):
        """
        Nici una in minus (clientul n-ar avea ce chema), nici una in plus.

        Lista e scrisa aici pe de-a-ntregul, dinadins. Daca maine cineva adauga o
        unealta, testul pica si il obliga sa treaca si pe la documentul de contract -
        care e citit de JA.S.Mine si trebuie sa ramana adevarat.

        Din faza 2, lista are si `normalizeaza` si `evalueaza` - cele doua unelte care
        CHEAMA modelul. Inainte erau nepublicate: nu se stia cine injecteaza `cheama_model`
        printr-o interfata MCP. Acum agentul e autonom si isi injecteaza singur functia,
        deci se pot expune (vezi adapters/model.py).

        `descrie` s-a adaugat la urma: etapa exista de mult in linia de comanda, dar
        lipsea din MCP - deci JA.S.Mine putea porni tot lantul in afara de singura etapa
        care aduce descrierile, si nu avea de unde sti ca ii lipseste.
        """
        self.assertEqual(
            unelte_inregistrate(),
            {
                "briefing",
                "oportunitati_noi",
                "cauta",
                "stare_pipeline",
                "ingesteaza",
                "extrage",
                "descrie",
                "filtreaza",
                "normalizeaza",
                "evalueaza",
            },
        )

    def test_uneltele_cu_model_sunt_expuse_din_faza_2(self):
        """
        Normalizarea si evaluarea SUNT publicate acum - cu avertisment de cost in descriere.

        In faza 1 erau ascunse fiindca nu se stia cine plateste apelul cand vine prin MCP.
        Faza 2 a raspuns: agentul, cu cheia lui. Deci se expun. Verificam si ca descrierea
        fiecareia spune apasat ca modelul din JA.S.Mine citeste - COSTA - ca nimeni sa nu le
        apese crezand ca-s gratis ca restul.
        """
        expuse = unelte_inregistrate()

        self.assertIn("normalizeaza", expuse)
        self.assertIn("evalueaza", expuse)

        # Descrierea uneltei (docstring-ul) trebuie sa avertizeze ca operatiunea costa.
        self.assertIn("COSTA", mcp_server.normalizeaza.__doc__)
        self.assertIn("COSTA", mcp_server.evalueaza.__doc__)

    def test_fiecare_unealta_cheama_adaptorul_ei(self):
        """
        Legatura unealta -> adaptor, verificata una cate una.

        E testul care apara "invelisul e subtire": daca cineva rescrie o unealta ca sa
        faca treaba pe cont propriu, adaptorul nu mai e chemat si testul pica.
        """
        perechi = [
            ("briefing", "ruleaza_briefingul", mcp_server.briefing),
            ("oportunitati_noi", "ia_oportunitatile", mcp_server.oportunitati_noi),
            ("cauta", "cauta_anunturi", lambda: mcp_server.cauta("payroll")),
            ("stare_pipeline", "ia_starea", mcp_server.stare_pipeline),
            ("ingesteaza", "ruleaza_ingestia", mcp_server.ingesteaza),
            ("extrage", "ruleaza_extragerea", mcp_server.extrage),
            ("descrie", "ruleaza_descrierile", mcp_server.descrie),
            ("filtreaza", "ruleaza_filtrarea", mcp_server.filtreaza),
            ("normalizeaza", "ruleaza_normalizarea", mcp_server.normalizeaza),
            ("evalueaza", "ruleaza_evaluarea", mcp_server.evalueaza),
        ]

        for nume_unealta, nume_adaptor, cheama_unealta in perechi:
            with self.subTest(unealta=nume_unealta):
                fals = ApelNotat(intoarce={"martor": nume_unealta})
                original = getattr(mcp_server, nume_adaptor)
                setattr(mcp_server, nume_adaptor, fals)
                try:
                    rezultat = cheama_unealta()
                finally:
                    setattr(mcp_server, nume_adaptor, original)

                self.assertEqual(len(fals.apeluri), 1)
                self.assertTrue(rezultat["ok"])
                self.assertEqual(rezultat["date"], {"martor": nume_unealta})


class TestParametri(unittest.TestCase):

    def test_briefing_nu_marcheaza_citit_implicit(self):
        """
        Apelat fara parametru, briefingul NU consuma reperul.

        Testul asta pazeste decizia cea mai importanta din toata unealta. Daca
        implicitul s-ar inversa vreodata, un buton apasat din curiozitate ar face ca
        anunturile de pana atunci sa nu mai apara in niciun briefing viitor - o
        pierdere care nu se vede cand se intampla si nu se mai poate repara.
        """
        fals = ApelNotat()
        original = mcp_server.ruleaza_briefingul
        mcp_server.ruleaza_briefingul = fals
        try:
            mcp_server.briefing()
        finally:
            mcp_server.ruleaza_briefingul = original

        argumente, _ = fals.apeluri[0]
        self.assertEqual(argumente, (False,))

    def test_briefing_duce_mai_departe_marcheaza_citit_cerut(self):
        fals = ApelNotat()
        original = mcp_server.ruleaza_briefingul
        mcp_server.ruleaza_briefingul = fals
        try:
            mcp_server.briefing(marcheaza_citit=True)
        finally:
            mcp_server.ruleaza_briefingul = original

        argumente, _ = fals.apeluri[0]
        self.assertEqual(argumente, (True,))

    def test_limitele_ajung_neatinse_la_adaptor(self):
        """Invelisul nu are voie sa "corecteze" o limita ceruta de client."""
        fals = ApelNotat()
        original = mcp_server.ia_oportunitatile
        mcp_server.ia_oportunitatile = fals
        try:
            mcp_server.oportunitati_noi(limita=3)
        finally:
            mcp_server.ia_oportunitatile = original

        self.assertEqual(fals.apeluri[0][0], (3,))

    def test_descrie_ruleaza_pe_bune_si_duce_limita_neatinsa(self):
        """
        Prin MCP se cer paginile pe bune, iar singura frana e `limita`.

        Doua lucruri se pazesc aici. Intai, dry_run=False: un dry run strecurat pe calea
        asta ar raporta vesel "ar cere 30 de pagini" fara sa aduca nimic, iar JA.S.Mine
        ar crede ca etapa s-a facut. Apoi, limita dusa neatinsa: plafonul e apararea
        serverelor de la care cerem, si nu are voie sa fie "corectat" de invelis.
        """
        fals = ApelNotat()
        original = mcp_server.ruleaza_descrierile
        mcp_server.ruleaza_descrierile = fals
        try:
            mcp_server.descrie(limita=7)
        finally:
            mcp_server.ruleaza_descrierile = original

        _, parametri = fals.apeluri[0]
        self.assertEqual(parametri, {"limita": 7, "dry_run": False})

    def test_cauta_duce_textul_si_limita(self):
        fals = ApelNotat()
        original = mcp_server.cauta_anunturi
        mcp_server.cauta_anunturi = fals
        try:
            mcp_server.cauta("salarizare", limita=25)
        finally:
            mcp_server.cauta_anunturi = original

        self.assertEqual(fals.apeluri[0][0], ("salarizare", 25))


class TestContractDeErori(unittest.TestCase):

    def test_o_exceptie_devine_raspuns_nu_prabusire(self):
        """
        Gmail-ul cade, iar clientul primeste un raspuns citibil, nu un esec de protocol.

        Diferenta conteaza pentru JA.S.Mine: cu un raspuns structurat poate deosebi
        "reincearca peste un minut" de "repara configurarea". Cu o exceptie scapata
        prin MCP, ar sti doar ca "ceva n-a mers".
        """
        fals = ApelNotat(arunca=ConnectionError("conexiune intrerupta"))
        original = mcp_server.ruleaza_ingestia
        mcp_server.ruleaza_ingestia = fals
        try:
            rezultat = mcp_server.ingesteaza()
        finally:
            mcp_server.ruleaza_ingestia = original

        self.assertFalse(rezultat["ok"])
        self.assertEqual(rezultat["eroare"], "ingestia din Gmail a esuat")
        self.assertIn("ConnectionError", rezultat["detaliu"])
        self.assertIn("conexiune intrerupta", rezultat["detaliu"])
        # La esec NU exista "date". Un client care se uita dupa "date" trebuie sa
        # dea peste lipsa lui, nu peste un dictionar gol care s-ar citi ca "zero
        # rezultate" - alea doua sunt situatii complet diferite.
        self.assertNotIn("date", rezultat)

    def test_toate_uneltele_respecta_acelasi_contract_la_esec(self):
        """
        Consecventa, verificata pe toate uneltele deodata.

        Un client care trateaza esecurile trebuie sa poata scrie o singura bucata de
        cod pentru toate uneltele. Daca una singura ar raspunde altfel, exceptia aia
        ar trebui tinuta minte de programatorul din JA.S.Mine - adica exact felul de
        detaliu care se uita.
        """
        perechi = [
            ("ruleaza_briefingul", mcp_server.briefing),
            ("ia_oportunitatile", mcp_server.oportunitati_noi),
            ("cauta_anunturi", lambda: mcp_server.cauta("x")),
            ("ia_starea", mcp_server.stare_pipeline),
            ("ruleaza_ingestia", mcp_server.ingesteaza),
            ("ruleaza_extragerea", mcp_server.extrage),
            ("ruleaza_descrierile", mcp_server.descrie),
            ("ruleaza_filtrarea", mcp_server.filtreaza),
            ("ruleaza_normalizarea", mcp_server.normalizeaza),
            ("ruleaza_evaluarea", mcp_server.evalueaza),
        ]

        for nume_adaptor, cheama_unealta in perechi:
            with self.subTest(adaptor=nume_adaptor):
                fals = ApelNotat(arunca=ValueError("ceva stricat"))
                original = getattr(mcp_server, nume_adaptor)
                setattr(mcp_server, nume_adaptor, fals)
                try:
                    rezultat = cheama_unealta()
                finally:
                    setattr(mcp_server, nume_adaptor, original)

                self.assertEqual(set(rezultat), {"ok", "eroare", "detaliu"})
                self.assertFalse(rezultat["ok"])
                self.assertTrue(rezultat["eroare"])
                self.assertIn("ValueError", rezultat["detaliu"])


class TestConfigurare(unittest.TestCase):
    """
    Fiecare test isi pune singur variabilele de mediu si le curata dupa.

    Fara asta, testele ar citi .env-ul real al masinii si ar da alt rezultat la tine
    fata de mine - adica exact genul de test in care nu poti avea incredere.
    """

    def _cu_mediu(self, **valori):
        vechi = {nume: os.environ.get(nume) for nume in valori}
        for nume, valoare in valori.items():
            if valoare is None:
                os.environ.pop(nume, None)
            else:
                os.environ[nume] = valoare
        self.addCleanup(self._reface, vechi)

    def _reface(self, vechi: dict):
        for nume, valoare in vechi.items():
            if valoare is None:
                os.environ.pop(nume, None)
            else:
                os.environ[nume] = valoare

    def test_hostul_implicit_asculta_pe_toate_interfetele(self):
        """
        0.0.0.0, nu 127.0.0.1 - altfel clientul din Docker nu ajunge la server.

        Din interiorul unui container, "localhost" inseamna containerul. Un server
        legat pe 127.0.0.1 pe gazda i-ar fi complet invizibil, iar simptomul
        ("connection refused") nu spune deloc de ce.
        """
        self._cu_mediu(MCP_HOST="0.0.0.0")

        self.assertEqual(mcp_server.host_configurat(), "0.0.0.0")

    def test_portul_se_ia_din_mediu(self):
        self._cu_mediu(MCP_PORT="9999")

        self.assertEqual(mcp_server.port_configurat(), 9999)

    def test_un_port_scris_gresit_cade_pe_implicit_in_loc_sa_crape(self):
        """
        MCP_PORT="opt mii" nu are voie sa impiedice pornirea serverului.

        Alternativa - o exceptie la pornire - ar lasa serverul oprit din cauza unei
        greseli de tastare intr-un fisier de configurare. Mai bine porneste pe portul
        implicit, unde il gasesti si il repari.
        """
        self._cu_mediu(MCP_PORT="opt mii")

        self.assertEqual(mcp_server.port_configurat(), mcp_server.PORT_IMPLICIT)

    def test_un_token_lipsa_se_citeste_ca_None(self):
        """
        Ce verifica: doar CITIREA. token_configurat() nu decide nimic.

        Numele vechi era `test_fara_token_serverul_e_deschis` si descria contractul
        de dinainte. Serverul nu mai e deschis fara token - refuza sa porneasca.
        Decizia aia se verifica in TestFailClosed, mai jos.
        """
        self._cu_mediu(MCP_TOKEN=None)

        # Ne asiguram ca nici .env-ul real nu strecoara un token in test.
        if mcp_server.token_configurat() is not None:
            self.skipTest("masina asta are MCP_TOKEN in .env")

        self.assertIsNone(mcp_server.token_configurat())

    def test_un_token_doar_din_spatii_se_citeste_ca_lipsa(self):
        """
        MCP_TOKEN="   " nu inseamna "token setat". Inseamna camp uitat gol.

        Daca l-am fi luat de bun, serverul ar fi cerut un antet "Bearer    " - un
        secret pe care il ghiceste oricine, dar care ar da impresia ca usa e incuiata.
        Mai bine deschis pe fata decat incuiat de gluma.
        """
        self._cu_mediu(MCP_TOKEN="   ")

        self.assertIsNone(mcp_server.token_configurat())


class TestFailClosed(unittest.TestCase):
    """
    Fara token, aplicatia NU se construieste. Asta e usa, nu un avertisment.

    DE CE inlocuim token_configurat() in loc sa golim MCP_TOKEN din mediu:
    _mediu() reincarca .env la fiecare apel, iar load_dotenv nu suprascrie ce e deja
    in mediu - deci pe o masina care ARE token in .env, golirea variabilei nu ajunge:
    tokenul se intoarce din fisier. Un test care sare (`skipTest`) pe masina de
    dezvoltare e exact gaura pe care testul asta o astupa: cineva „simplifica" inapoi
    la fail-open, suita trece verde, si nimeni nu afla.
    """

    def _fara_token(self):
        original = mcp_server.token_configurat
        mcp_server.token_configurat = lambda: None
        self.addCleanup(setattr, mcp_server, "token_configurat", original)

    def test_fara_token_construirea_aplicatiei_ridica_eroare(self):
        self._fara_token()

        with self.assertRaises(RuntimeError):
            mcp_server.construieste_aplicatia()

    def test_un_token_doar_din_spatii_opreste_si_el_pornirea(self):
        """Un token din spatii se citeste ca lipsa, deci trebuie sa opreasca la fel."""
        original = mcp_server.token_configurat
        mcp_server.token_configurat = lambda: None   # ce intoarce _mediu() pentru "   "
        self.addCleanup(setattr, mcp_server, "token_configurat", original)

        with self.assertRaises(RuntimeError):
            mcp_server.construieste_aplicatia()

    def test_mesajul_spune_ce_lipseste_si_unde_se_pune(self):
        """
        Un refuz care nu spune ce sa faci lasa omul sa caute prin cod.

        Verificam ca mesajul poarta numele variabilei, calea fisierului si motivul —
        nu formularea exacta, care are voie sa se schimbe.
        """
        self._fara_token()

        with self.assertRaises(RuntimeError) as prins:
            mcp_server.construieste_aplicatia()

        mesaj = str(prins.exception)
        self.assertIn("MCP_TOKEN", mesaj)
        self.assertIn(".env", mesaj)
        self.assertIn("0.0.0.0", mesaj)
        self.assertIn("ingesteaza", mesaj)

    def test_cu_token_aplicatia_se_construieste(self):
        """Fata cealalta a monedei: usa incuiata nu inseamna usa blocata."""
        original = mcp_server.token_configurat
        mcp_server.token_configurat = lambda: "token-de-test"
        self.addCleanup(setattr, mcp_server, "token_configurat", original)

        self.assertIsNotNone(mcp_server.construieste_aplicatia())


class TestAutentificare(unittest.TestCase):
    """
    Verificarea tokenului, fara sa pornim niciun server.

    Middleware-ul e o functie ASGI: primeste un dictionar cu cererea si doua functii
    prin care citeste si scrie. Le construim de mana si ne uitam ce iese. Nicio
    conexiune, niciun port.
    """

    def _cere(self, middleware, antete: list):
        """Trece o cerere prin middleware si intoarce (status, a_ajuns_la_aplicatie)."""
        raspuns = {}
        a_ajuns = []

        async def aplicatia_din_spate(scope, receive, send):
            a_ajuns.append(True)

        middleware.app = aplicatia_din_spate

        async def primeste():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def trimite(mesaj):
            if mesaj["type"] == "http.response.start":
                raspuns["status"] = mesaj["status"]

        scope = {"type": "http", "headers": antete, "method": "POST", "path": "/mcp"}
        asyncio.run(middleware(scope, primeste, trimite))

        return raspuns.get("status"), bool(a_ajuns)

    def test_cererea_fara_antet_e_respinsa_cu_401(self):
        middleware = mcp_server._CereToken(None, token="secret-de-test")

        status, a_ajuns = self._cere(middleware, antete=[])

        self.assertEqual(status, 401)
        self.assertFalse(a_ajuns)

    def test_tokenul_gresit_e_respins(self):
        middleware = mcp_server._CereToken(None, token="secret-de-test")

        status, a_ajuns = self._cere(
            middleware, antete=[(b"authorization", b"Bearer altceva")]
        )

        self.assertEqual(status, 401)
        self.assertFalse(a_ajuns)

    def test_tokenul_corect_trece(self):
        middleware = mcp_server._CereToken(None, token="secret-de-test")

        status, a_ajuns = self._cere(
            middleware, antete=[(b"authorization", b"Bearer secret-de-test")]
        )

        self.assertIsNone(status)
        self.assertTrue(a_ajuns)

    def test_antetul_se_citeste_indiferent_de_litere_mari_sau_mici(self):
        """
        HTTP spune ca numele antetelor nu tin cont de majuscule. Unele clienturi
        trimit "Authorization", altele "authorization". Amandoua trebuie sa mearga -
        altfel serverul respinge un client corect si nimeni nu intelege de ce.
        """
        middleware = mcp_server._CereToken(None, token="secret-de-test")

        status, a_ajuns = self._cere(
            middleware, antete=[(b"AUTHORIZATION", b"Bearer secret-de-test")]
        )

        self.assertIsNone(status)
        self.assertTrue(a_ajuns)

    def test_pornirea_aplicatiei_nu_cere_token(self):
        """
        Evenimentele de pornire/oprire (lifespan) nu sunt cereri HTTP si nu au antete.

        Daca middleware-ul ar cere token si acolo, serverul n-ar mai porni deloc -
        iar mesajul de eroare n-ar avea nicio legatura cu autentificarea.
        """
        middleware = mcp_server._CereToken(None, token="secret-de-test")
        a_ajuns = []

        async def aplicatia_din_spate(scope, receive, send):
            a_ajuns.append(True)

        middleware.app = aplicatia_din_spate

        async def gol(*argumente):
            return {}

        asyncio.run(middleware({"type": "lifespan"}, gol, gol))

        self.assertTrue(a_ajuns)


class TestGazdaDinDocker(unittest.TestCase):
    """
    O cerere venita din containerul Open WebUI trebuie sa ajunga la protocol.

    DE CE EXISTA: din mcp 2.x, daca aplicatia nu primeste gazda, SDK-ul presupune
    127.0.0.1 si porneste singur protectia anti-DNS-rebinding - care accepta doar
    cereri adresate lui localhost. Din container, cererea vine cu
    "Host: host.docker.internal:8051", deci ar fi respinsa cu 421. Asta s-a vazut la
    actualizarea din 29 septembrie 2026, citind SDK-ul; toate celelalte teste treceau.

    Cererea merge prin TestClient, adica in interiorul procesului: niciun port
    deschis, nicio retea. Gazda si tokenul se inlocuiesc, ca sa nu depinda de .env.
    """

    CERERE = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    ANTETE = {
        "host": "host.docker.internal:8051",
        "authorization": "Bearer token-de-test",
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }

    def _cu(self, nume: str, valoare):
        original = getattr(mcp_server, nume)
        setattr(mcp_server, nume, lambda: valoare)
        self.addCleanup(setattr, mcp_server, nume, original)

    def _trimite(self, aplicatie) -> int:
        from starlette.testclient import TestClient

        with TestClient(aplicatie) as client:
            return client.post(mcp_server.CALE_MCP, json=self.CERERE, headers=self.ANTETE).status_code

    def test_cererea_din_container_trece(self):
        self._cu("token_configurat", "token-de-test")
        self._cu("host_configurat", "0.0.0.0")

        self.assertEqual(self._trimite(mcp_server.construieste_aplicatia()), 200)

    def test_fara_gazda_sdk_ul_ar_respinge_cererea(self):
        """
        Proba inversa: arata ca testul de mai sus chiar poate pica.

        Daca pica ASTA, SDK-ul si-a schimbat purtarea implicita - capcana poate nu mai
        exista, iar comentariul din construieste_aplicatia() trebuie recitit.
        """
        aplicatie = mcp_server.server.streamable_http_app(streamable_http_path=mcp_server.CALE_MCP)

        self.assertEqual(self._trimite(aplicatie), 421)


if __name__ == "__main__":
    unittest.main()
