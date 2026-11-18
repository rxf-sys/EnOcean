# Alexa-Skill für Home Assistant – Anleitung

Stand: 18.11.2026 · eigener Alexa-Smart-Home-Skill, ohne Hue-Emulation und ohne Nabu Casa

```
Echo ──► Alexa-Cloud ──► AWS Lambda (EU Irland) ──HTTPS──► https://<name>.ts.net ──► Home Assistant ──► EnOcean-Stick
                                                              (Tailscale Funnel)      /api/alexa/smart_home
```

Die Alexa-Schnittstelle ist in Home Assistant eingebaut. Der Skill verbindet nur
Alexa mit dieser Schnittstelle. Die Lambda-Funktion (`lambda_function.py`) ist
ein schlanker Weiterleiter (ca. 100 Zeilen, nur Python-Bordmittel, getestet).

## Was du brauchst

| Konto | Wofür | Kosten |
|---|---|---|
| Amazon-Konto (dasselbe wie für Alexa) | Alexa-App | – |
| Amazon Developer (developer.amazon.com, gleiches Login) | den Skill anlegen | kostenlos |
| AWS (aws.amazon.com) | Lambda-Funktion | Free Tier: 1 Mio. Aufrufe/Monat kostenlos; Kreditkarte zur Anmeldung nötig |
| Tailscale (tailscale.com) | HTTPS-Zugang aus dem Internet, ohne Portfreigabe | kostenlos |

> **Sicherheit vorab:** Mit Funnel ist die Anmeldeseite von Home Assistant aus dem
> Internet erreichbar. **Vorher für alle HA-Benutzer die Zwei-Faktor-Anmeldung
> aktivieren** (Profil → Mehrstufige Authentifizierung → Authentifizierungs-App),
> starke Passwörter verwenden und ungenutzte Benutzer löschen (`mqtt_user`).
> Fehlversuche sperren die IP automatisch (`ip_ban_enabled`).

---

## Teil 1 – Fernzugriff (Cowork + du)

Cowork installiert die Tailscale-App in HA, du meldest dich einmal mit deinem
Tailscale-Konto an. Danach ist HA unter `https://<name>.<tailnet>.ts.net`
erreichbar, mit gültigem Zertifikat auf Port 443. Diese Adresse heißt unten
**`<HA-URL>`**.

Im Tailscale-Admin (login.tailscale.com) einmalig:

- **DNS → HTTPS Certificates: Enable**
- **Access controls:** Funnel muss erlaubt sein. Bei neuen Tailnets ist das
  Standard: `nodeAttrs` mit `"attr": ["funnel"]`.

## Teil 2 – Skill anlegen (developer.amazon.com → Alexa Developer Console)

1. **Create Skill**
   - Name: z. B. `Casa Seibel`
   - Primary locale: **German (DE)**
   - Experience: **Smart Home**
   - Hosting: **Provision your own**
   - → **Create skill**
2. Die **Skill ID** kopieren (`amzn1.ask.skill.…`), du brauchst sie in Teil 3.

## Teil 3 – Lambda-Funktion (console.aws.amazon.com)

1. Oben rechts die Region **Europe (Ireland) eu-west-1** wählen.
   **Wichtig:** Eine falsche Region führt zu einem Skill ohne klare Fehlermeldung.
2. **Lambda → Create function**
   - Author from scratch
   - Name: `ha-alexa`
   - Runtime: **Python 3.13** (oder neuer)
   - → **Create function**
3. **Code:** Den Inhalt von `alexa-skill/lambda_function.py` in das Editorfenster
   einfügen (die vorhandene Datei `lambda_function.py` ersetzen) → **Deploy**.
4. **Configuration → Environment variables → Edit → Add**
   - `BASE_URL` = `<HA-URL>`, **ohne** `/` am Ende
5. **Configuration → General configuration → Edit:** Timeout **10 s**.
6. **Add trigger → Alexa → Alexa Smart Home**
   - Skill ID verification: **enabled**
   - die Skill ID aus Teil 2 einfügen → Add
7. Die **Function ARN** oben rechts kopieren (`arn:aws:lambda:eu-west-1:…:function:ha-alexa`).

## Teil 4 – Skill fertig konfigurieren (Developer Console)

**Smart Home → Smart Home service endpoint**
- Default endpoint: die **ARN** aus Teil 3
- Haken bei **Europe, India** setzen, dort ebenfalls die ARN eintragen
- → **Save**

**Account Linking**

| Feld | Wert |
|---|---|
| Authorization Grant Type | Auth Code Grant |
| Your Web Authorization URI | `<HA-URL>/auth/authorize` |
| Access Token URI | `<HA-URL>/auth/token` |
| Your Client ID | `https://layla.amazon.com/` (**mit** `/` am Ende) |
| Your Secret | beliebig, z. B. `homeassistant` (HA prüft es nicht) |
| Your Authentication Scheme | **Credentials in request body** |
| Scope | `smart_home` |
| Domain List, Default Access Token Expiration Time | leer lassen |

→ **Save**

## Teil 5 – Home Assistant (Cowork)

Cowork installiert `packages/alexa_smart_home.yaml` mit allen 34 Geräten
(Namen und Typ Licht, Steckdose oder Rollo) und schaltet die alte
Hue-Emulation ab. Die Datei wird dabei nur archiviert, nicht gelöscht.

## Teil 6 – Alexa-App

1. In der Alexa-App die **alten Hue-Geräte entfernen**: alle Geräte, die über die
   Hue-Emulation kamen (Gerät → Einstellungen → Papierkorb). Sonst gibt es jedes
   Gerät doppelt.
2. **Mehr → Skills & Spiele → Meine Skills → Entwickler** → `Casa Seibel` →
   **Zur Verwendung aktivieren**.
3. Es öffnet sich die Anmeldeseite von Home Assistant. Mit deinem HA-Benutzer
   und dem 2-Faktor-Code anmelden.
4. **Geräte erkennen.** Erwartet werden 34 Geräte.
5. Optional die Geräte in der Alexa-App Räumen zuordnen. Dann reicht z. B. im
   Wohnzimmer „Alexa, Licht an“.

## Teil 7 – Sofortige Zustandsanzeige (optional, empfohlen)

Damit die Alexa-App den Zustand sofort zeigt, auch nach Bedienung am Wandschalter:

1. Developer Console → **Permissions → Send Alexa Events: an**. Die
   **Alexa Client Id** und das **Alexa Client Secret** kopieren.
2. In HA `secrets.yaml` ergänzen (Cowork oder File Editor):
   ```yaml
   alexa_client_id: "amzn1.application-oa2-client.…"
   alexa_client_secret: "amzn1.oa2-cs.v1.…"
   ```
3. In `packages/alexa_smart_home.yaml` unter `smart_home:` ergänzen:
   ```yaml
       endpoint: https://api.eu.amazonalexa.com/v3/events
       client_id: !secret alexa_client_id
       client_secret: !secret alexa_client_secret
   ```
4. `ha core check`, dann HA neu starten. Danach in der Alexa-App den Skill
   **deaktivieren und wieder aktivieren** (neu verknüpfen).

---

## Sprachbefehle

| Sagen | Wirkung |
|---|---|
| „Alexa, schalte Wohnzimmerlicht an / aus“ | Licht |
| „Alexa, Fernseher aus“ | Steckdose TV |
| „Alexa, öffne Rollo Mila“ / „Alexa, Rollo Mila hoch“ | Rollo hoch |
| „Alexa, schließe Rollo Bad“ / „Alexa, Rollo Bad runter“ | Rollo runter |
| „Alexa, stopp Rollo Bad“ | Rollo anhalten |

Für mehrere Geräte auf einmal legst du in der Alexa-App eine **Routine** an, z. B.
„Alexa, Rollos runter“ → alle vier Rollos schließen.

## Fehlerbilder

| Beobachtung | Ursache / Lösung |
|---|---|
| Verknüpfen schlägt fehl | `<HA-URL>` vom Handy im **Mobilfunk** öffnen: Die HA-Anmeldeseite muss erscheinen. Client ID genau `https://layla.amazon.com/` mit Schrägstrich. Authorization- und Token-URI prüfen |
| „Gerät reagiert nicht“ | AWS → Lambda → Monitor → **CloudWatch-Logs** ansehen. `BASE_URL` ohne `/` am Ende? Region eu-west-1? |
| Logs zeigen `INVALID_AUTHORIZATION_CREDENTIAL` | Skill in der Alexa-App deaktivieren und neu aktivieren |
| Geräte doppelt | alte Hue-Geräte in der Alexa-App löschen (Teil 6, Schritt 1) |
| Nach Teil 7: „Token invalid and no refresh token available“ im HA-Log | Skill neu verknüpfen, HA neu starten |
| Neues EnOcean-Gerät fehlt bei Alexa | in `alexa_smart_home.yaml` unter `include_entities` und `entity_config` eintragen, HA neu starten, „Alexa, suche Geräte“ |

Quellen: [Home Assistant – Amazon Alexa Smart Home Skill](https://www.home-assistant.io/integrations/alexa.smart_home/),
[Tailscale-App für Home Assistant](https://github.com/hassio-addons/app-tailscale).
