# OPUS-Relais anlernen – Kurzanleitung

Stand: 18.11.2026 · gilt für die Anlage mit USB-300-Stick (Base-ID `FF:C8:31:80`)

Kennzeichnung: **✅ vor Ort bestätigt** · *ℹ️ laut baugleicher Eltako-Anleitung, nicht selbst geprüft*

---

## 1. Grundprinzip

```
Home Assistant ──USB──► USB-300-Stick ──Funk──► Antennenmodul 561.151 ──Bus──► Relais
```

- Die Relais im Verteiler haben **keinen eigenen Funkempfänger**. Alle Funktelegramme
  kommen über das Antennenmodul (GN-E-R12V-AM, 561.151) auf den Bus, und **jedes**
  Relais sieht **jedes** Telegramm.
- Ein Relais reagiert nur auf Sender, die es **gelernt** hat. Ein Sender ist eine
  Funk-ID, z. B. ein Wandschalter oder ein „unsichtbarer Schalter“ von Home Assistant.
- Home Assistant hat **128 eigene Sender-IDs** (`FF:C8:31:80` bis `FF:C8:31:FF`).
  **Jeder Kanal bekommt eine eigene ID**, sonst schalten mehrere Leuchten gemeinsam.
- Die Relais senden **keine Rückmeldung**. Home Assistant merkt sich den Zustand selbst.
  Bei Bedienung am Wandschalter führt das Mithören (`wall_switches`) ihn nach.

### Welche ID für welchen Kanal?

| Relais | ID-Bereich | Regel | Beispiel |
|---|---|---|---|
| SR-4 (4 Kanäle) | `90`–`9B` | Aktor 13 → `90`–`93`, 14 → `94`–`97`, 15 → `98`–`9B` | 13.1 = `90` |
| MF-2 (2 Kontakte) | `A0`–`BF` | Aktor n, Kontakt c → `A0 + 2·(n−1) + (c−1)` | Aktor 3, Kontakt 2 = `A5` |
| JRG-2 (2 Motoren) | `C0`–`DF` | Aktor n, Motor m → `C0 + 2·(n−1) + (m−1)` | Aktor 2, Motor 1 = `C2` |

Die vollständige Belegung steht im Dashboard-Tab **Geräte** und in `docs/devices.md`.

---

## 2. Goldene Regeln (für alle drei Relais)

1. **Vorher fotografieren** und die Stellung aller Drehschalter aufschreiben. Danach
   **exakt zurückstellen**.
2. **Immer nur ein Relais auf LRN.** Im Lernmodus speichert ein Relais **das nächste
   Telegramm, das ankommt**, auch einen Fensterkontakt, der gerade zufällig sendet.
   Deshalb die Aktion in Home Assistant **vorher bereitlegen** und **sofort** senden.
3. **LED beobachten:** Blinkt sie ruhig, ist das Relais lernbereit. Geht sie aus,
   hat es gelernt.
4. ⚠️ **Steht der mittlere Schalter auf CLR, den oberen Schalter nicht drehen.**
   Dreimal bis zum Rechtsanschlag und zurück innerhalb von 10 s löscht den **gesamten**
   Speicher. Danach funktionieren auch die Wandschalter nicht mehr.
5. **Den unteren Schalter nicht verstellen,** außer beim SR-4 zur Kanalwahl. Bei MF-2
   und JRG-2 legt er die Betriebsart fest.
6. **Nach dem Einlernen testen:** EIN, AUS, und prüfen, dass **kein anderes** Gerät
   mitschaltet.

### Die Aktion in Home Assistant

Entwicklerwerkzeuge → Aktionen → YAML-Modus. Am besten zwei Tabs öffnen, einen für
EIN/HOCH und einen für AUS/RUNTER:

```yaml
action: enocean_new.send_rps
data:
  sender_id: [0xFF, 0xC8, 0x31, 0x90]   # letzte Stelle = ID des Kanals
  data_byte: 0x70                       # 0x70 = EIN / HOCH, 0x50 = AUS / RUNTER
```

### Einen falsch gelernten Sender gezielt löschen

1. Mittleren Schalter auf **CLR**. Die LED blinkt schnell. Beim SR-4 vorher den
   unteren Schalter auf den betroffenen Kanal stellen.
2. **Dieselbe** Aktion (gleiche ID) einmal senden. Die LED geht aus, der Sender ist
   gelöscht.
3. Alle Schalter auf die notierte Stellung zurück.

Wandschalter und andere Sender bleiben dabei erhalten. ✅

---

## 3. GN-A-R12V-SR-4 (561.152) – 4-Kanal-Schaltrelais

4 Kanäle, je 4 A. Baugleich mit Eltako FSR12-4x. Beschriftet z. B. mit „13“ (Kanäle 13.1–13.4).

### Die Drehschalter

| Schalter | Im Betrieb | Beim Einlernen |
|---|---|---|
| **Oben** (ES · UT/RT · EW 2–25 s · ER) | Betriebsart **aller 4 Kanäle**: **ES-RT** = Richtungstaster (eine Seite EIN, eine AUS) ✅ · **ES-UT** = Universaltaster (jeder Druck schaltet um) ✅ · *ℹ️ EW = einschalten, nach 2–25 s automatisch aus · ER = Relais, an solange gedrückt* | **0** = „Richtungstaster EIN“ lernen ✅ · **2** = „Richtungstaster AUS“ lernen ✅ · *ℹ️ 5 / 10 = Universaltaster* |
| **Mitte** (AUTO · LRN · CLR …) | **AUTO** | **LRN** = lernen, **CLR** = löschen |
| **Unten** (AUTO · ZE · ZA · 1–4) | **AUTO** | **1–4** = Kanal wählen · *ℹ️ ZE / ZA = Zentral-EIN / Zentral-AUS lernen* |

> **Wichtig ✅:** Im Betrieb muss der obere Schalter auf **RT** stehen. Auf **UT**
> schaltet jeder Tastendruck um, egal ob oben oder unten, auch aus Home Assistant.
> Dann stimmt der angezeigte Zustand nicht mehr.

### Anlernen (pro Kanal, zwei Schritte) ✅

| Schritt | Unten | Oben | Mitte | Aktion | LED |
|---|---|---|---|---|---|
| EIN lernen | Kanal 1–4 | **0** | **LRN** | `0x70` senden | aus |
| AUS lernen | gleich | **2** | kurz AUTO → **LRN** | `0x50` senden | aus |
| Abschluss | **AUTO** | zurück auf **RT** | **AUTO** | – | – |
| Test | | | | `0x70` = an, `0x50` = aus | |

Welcher Kanal welche Leuchte schaltet, steht auf der Belegungsliste im Schrank.
Fehlt sie, ermittelst du es durch Ausprobieren: nur EIN lernen, testen, falls falsch
gezielt löschen, dann den nächsten Kanal probieren.

---

## 4. GN-A-R12V-MF-2 (561.177) – Multifunktions-Relais, 2 Kontakte

2 Schließer, je 16 A. Baugleich mit Eltako FMS12 (Ausführung mit „2xS“).
Beschriftet 1, 2, 3, …

### Die Drehschalter

| Schalter | Im Betrieb | Beim Einlernen |
|---|---|---|
| **Oben** (1–10, „LRN“) | Stellung notieren und danach wiederherstellen | Lernfunktion: **5** = Richtungstaster, ganze Wippe, **beide Kontakte gemeinsam** ✅ · **9** = Richtungstaster **Kontakt 1** ✅ · **10** = Richtungstaster **Kontakt 2** ✅ · *ℹ️ 2 = Zentral-AUS · 3 = Universaltaster · 4 = Zentral-EIN · 7 / 8 = Universaltaster Kontakt 1 / 2* |
| **Mitte** (AUTO · LRN · CLR) | **AUTO** | **LRN** = lernen, **CLR** = löschen |
| **Unten** (2S (2xS) · WS · SS1–3 · GS · 2R · WR · RR · GR) | **Betriebsart, nicht verstellen.** In der Anlage steht er auf **„2S (2xS)“** ✅ | – |

**Betriebsarten des unteren Schalters** *(ℹ️ laut Eltako FMS12)*:

| Stellung | Bedeutung |
|---|---|
| **2S (2xS)** | 2 Stromstoß-Schließer. Gelernt mit 5: beide gemeinsam. Gelernt mit 9/10: jeder Kontakt einzeln (2xS) ✅ |
| WS | Stromstoßschalter mit 1 Schließer + 1 Öffner |
| SS1–SS3 | Serienschalter (Kontakte schalten in einer festen Reihenfolge) |
| GS | Gruppenschalter (Kontakte abwechselnd) |
| 2R / WR / RR / GR | Relais-Funktionen (Kontakt folgt dem Tastendruck) |

### Anlernen (ein Schritt pro Kontakt) ✅

Der MF-2 lernt die **ganze Wippe auf einmal** (EIN und AUS).

| Fall | Oben | Mitte | Aktion | LED |
|---|---|---|---|---|
| Beide Kontakte gemeinsam (eine ID) | **5** | **LRN** | `0x70` mit ID von Kontakt 1 | aus |
| Kontakt 1 einzeln | **9** | **LRN** | `0x70` mit ID von Kontakt 1 | aus |
| Kontakt 2 einzeln | **10** | **LRN** | `0x70` mit ID von Kontakt 2 | aus |
| Abschluss | zurück auf notierte Stellung | **AUTO** | – | – |

> **Erfahrung aus Aktor 1 ✅:** Wurde ein Sender einmal mit **5** gelernt, schaltet
> er weiter beide Kontakte, auch wenn er später mit 9/10 nachgelernt wird. Dann den
> Sender zuerst **gezielt löschen** und danach mit 9 bzw. 10 neu lernen.

Schaltet `0x70` aus statt ein, ist das kein Problem: In der Konfiguration
`on_data` und `off_data` tauschen.

---

## 5. GN-A-R12V-JRG-2 (561.153) – Jalousie-Relais, 2 Motoren

2 Motoren, 4 Ausgänge, je 4 A. Baugleich mit Eltako FSB12. Pro Motor gibt es zwei
Ausgänge, einen für **ZU** und einen für **AUF** (laut Liste z. B. 1.1 Mila ZU,
1.2 Mila AUF).

### Die Drehschalter

| Schalter | Im Betrieb | Beim Einlernen |
|---|---|---|
| **Oben – RV (s)** 10…200 | **Laufzeit** in Sekunden: So lange fährt der Motor nach einem Tastendruck höchstens. Muss etwas länger sein als die komplette Fahrt | **10** = Richtungstaster **Motor 1** ✅ · **30** = Richtungstaster **Motor 2** ✅ · *ℹ️ 20 / 40 = Universaltaster Motor 1 / 2* |
| **Mitte – WA (s)** CLR · 0…5 · LRN | **Wendezeit** der Lamellen (kurzes Antippen dreht die Lamellen) | **LRN** = lernen (ganz rechts), **CLR** = löschen (ganz links) |
| **Unten** (AUTO 1–4, ▲ ▼) | **Betriebsart, nicht verstellen** | – |

> **Wichtig:** Oben und Mitte haben im Betrieb eine echte Funktion. Werden sie nach
> dem Einlernen nicht exakt zurückgestellt, fährt die Jalousie zu kurz oder zu lang,
> oder die Lamellen wenden falsch. **Foto und Werte aufschreiben ist hier Pflicht.**

### Anlernen (ein Schritt pro Motor) ✅

| Schritt | Oben (RV) | Mitte (WA) | Aktion | LED |
|---|---|---|---|---|
| Motor 1 | **10** | **LRN** | `0x70` mit ID Motor 1 | aus |
| Motor 2 | **30** | **LRN** | `0x70` mit ID Motor 2 | aus |
| Abschluss | **notierter RV-Wert** | **notierter WA-Wert** | – | – |

**Test:** `0x70` fährt hoch. Ein zweites `0x70` während der Fahrt stoppt. `0x50` fährt
runter. Reagiert nur eine Richtung, den Lernschritt mit `0x50` wiederholen.

**Sicherheit:** Beim Testen fahren die Jalousien wirklich. Fensterbereich freihalten.

---

## 6. Nach dem Anlernen: in Home Assistant eintragen

Neue Geräte kommen in das Paket `/config/packages/enocean.yaml`
(Vorlage im Repo: `ha-config/packages/enocean.yaml`):

```yaml
switch:
  - platform: enocean_new
    name: "Leuchte Gäste-WC"
    sender_id: [0xFF, 0xC8, 0x31, 0x90]
    actuator: "SR-4 13.1"
    on_data: 0x70
    off_data: 0x50
    wall_switches:              # optional: Wandschalter mithören
      - id: [0x00, 0x24, 0x55, 0x01]
        on_data: 0x70           # Code der Taste, die einschaltet (im Monitor ablesen)
        off_data: 0x50

cover:
  - platform: enocean_new
    name: "Jalousie Mila"
    sender_id: [0xFF, 0xC8, 0x31, 0xC0]
    actuator: "JRG-2 1, Motor 1"
```

Danach: `ha core check`, dann HA neu starten. Das Gerät erscheint automatisch im
Dashboard-Tab **Geräte**.

> **Hinweis ✅:** Welche Wippenseite welchen Code sendet (`0x70` oder `0x50`), hängt
> vom Wandschalter ab. Nicht raten, sondern im Tab **EnOcean-Monitor** ablesen:
> Taste drücken und den Code in der neuesten Zeile nehmen.

---

## 7. Fehlerbilder

| Beobachtung | Ursache | Lösung |
|---|---|---|
| LED blinkt nach dem Senden weiter | Telegramm nicht angekommen | Aktion wiederholen; prüfen, ob die Integration läuft (Monitor zeigt Telegramme) |
| Andere oder zwei Leuchten reagieren | falscher Kanal, oder ID doppelt gelernt | Sender gezielt löschen, richtigen Kanal neu lernen |
| SR-4: jeder Druck schaltet um | oberer Schalter auf **UT** | auf **RT** stellen ✅ |
| MF-2: beide Kontakte schalten trotz 9/10 | Sender war vorher mit **5** gelernt | Sender löschen, mit 9/10 neu lernen ✅ |
| Jalousie fährt nicht ganz hoch oder runter | RV-Laufzeit verstellt | RV auf den notierten Wert zurückstellen |
| `0x70` schaltet AUS statt EIN | Wippe andersherum gelernt | `on_data` und `off_data` in der Konfiguration tauschen |
| HA zeigt falschen Zustand nach Wandschalter-Bedienung | Wandschalter nicht eingetragen, oder Codes vertauscht | `wall_switches` eintragen; Codes im Monitor prüfen |
| Rote Fehlermeldung „Dongle rejected …“ / „not allowed“ | ID außerhalb `FF:C8:31:80`–`FF` | ID aus dem gültigen Bereich verwenden |
| Alle Wandschalter eines Relais tot | Speicher komplett gelöscht (CLR + oberen Schalter gedreht) | Wandschalter und HA-Sender neu lernen |
