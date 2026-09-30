"""
Unelte mici pentru text, folosite de mai multe module din core/.

De ce fisier separat: aceeasi functie de scos diacriticele era scrisa de doua ori, in
esecuri.py si filtrare.py, cu doua rezultate usor diferite. Doua copii ale aceleiasi
reguli ajung, cu timpul, sa spuna lucruri diferite - asa ca exista una singura.
"""
import unicodedata


def fara_diacritice(text: str) -> str:
    """
    Textul, cu litere mici si fara semne diacritice, pentru comparatii.

    DE CE: "Brașov", "Brasov" si "BRAȘOV" trebuie sa fie acelasi lucru. Acelasi
    "s cu virgula" apare in date scris in mai multe feluri (s cu virgula, s cu sedila,
    caracterul turcesc care seamana) - mailuri din ani diferiti, programe diferite.
    O comparatie pe textul brut ar rata o parte din potriviri, si ar rata-o TACUT.

    Cum: NFKD desface fiecare litera cu semn in litera de baza + semnul separat, apoi
    semnele se arunca: "ș" devine "s". NFKD (nu NFD) aduce la forma simpla si
    caracterele "de compatibilitate" - ligatura "ﬁ" devine "fi", spatiul care nu se
    rupe devine spatiu obisnuit.
    """
    descompus = unicodedata.normalize("NFKD", text)
    fara_semne = "".join(c for c in descompus if not unicodedata.combining(c))
    return fara_semne.lower()
