' Porneste serverul MCP al Agent 051, ascuns (fara fereastra de consola).
' Se cheama la login, prin scurtatura din folderul Startup al utilizatorului.
'
' a. Daca portul 8051 raspunde deja, mai ruleaza o instanta - iesim fara sa
'    pornim nimic. Altfel a doua ar cadea pe 10048 (adresa deja folosita).
'    Verificarea e o cerere HTTP catre endpoint: daca vine ORICE raspuns
'    (200, 401, 406 - nu conteaza), portul e ocupat. Doar "conexiune refuzata"
'    ridica eroare, si aia inseamna port liber.
Dim http, ocupat
ocupat = False
On Error Resume Next
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
http.setTimeouts 2000, 2000, 2000, 2000
http.open "GET", "http://127.0.0.1:8051/mcp", False
http.send
If Err.Number = 0 Then ocupat = True
Err.Clear
On Error GoTo 0
If ocupat Then WScript.Quit 0

' b. Directorul de lucru trebuie sa fie folderul agentului: acolo isi cauta
'    .env-ul si de acolo isi rezolva caile. Folderul e cel in care sta scriptul
'    asta, iar Python-ul e cel din .venv-ul lui - ca sa nu depinda de PATH sau
'    de vreun venv activat.
Dim ws, fso, folder
Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = folder
ws.Run """" & folder & "\.venv\Scripts\python.exe"" porneste_mcp.py", 0
