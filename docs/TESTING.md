# LearningSteps – Testdokumentation

## 1. Ziel und Umfang

Dieses Dokument beschreibt die funktionalen, sicherheitsrelevanten und betrieblichen Tests der LearningSteps-Anwendung.

LearningSteps wurde auf Microsoft Azure mit Azure Kubernetes Service (AKS), FastAPI, PostgreSQL, Microsoft Entra ID und Azure AI umgesetzt.

Die Testdokumentation soll nachvollziehbar machen:

- Welche Funktionen überprüft wurden
- Welche Sicherheitsmaßnahmen praktisch getestet wurden
- Welche Ergebnisse beobachtet wurden
- Welche Einschränkungen bestehen
- Welche Tests für eine weitergehende Sicherheitsbewertung noch fehlen

**Teststand:** 20. November 2026

Die Ergebnisse beziehen sich auf die zum Testzeitpunkt vorhandene Umgebung. Sie sind keine Garantie für zukünftige Bereitstellungen.

## 2. Testumgebung

| Komponente | Umgebung |
|---|---|
| Cloud | Microsoft Azure |
| Resource Group | `rg-learningsteps-devsecops` |
| Kubernetes | AKS `aks-learningsteps` |
| Namespace | `learningsteps` |
| Container Registry | Azure Container Registry |
| Backend | Python / FastAPI |
| Frontend | JavaScript / Nginx / MSAL |
| Datenbank | Azure Database for PostgreSQL 16 |
| KI | Azure AI, Deployment `learningsteps-summary` |
| CI/CD | GitHub Actions |
| Monitoring | Azure Monitor / Log Analytics |
| Infrastructure as Code | Terraform |

Öffentlicher Anwendungseinstiegspunkt:

`https://learningsteps.6aff4a07cf83170001eabf87.westeurope.aksapp.io`

Die Tests wurden überwiegend über `tracemanager`, Azure CLI, `kubectl`, Terraform und den Webbrowser durchgeführt.

### Ergebnis-Kategorien

| Status | Bedeutung |
|---|---|
| PASS | Test tatsächlich durchgeführt und erwartetes Ergebnis beobachtet |
| PARTIAL | Teilweise überprüft, aber kein vollständiger Nachweis |
| CODE REVIEW | Implementierung im Quellcode kontrolliert |
| SIMULATED | Logisches Verhalten anhand künstlicher Testbedingungen geprüft |
| OPEN | Test noch nicht durchgeführt |

## 3. Funktionstests

### FT-01 – Frontend über HTTPS erreichbar

**Ziel:** Nachweis, dass das Frontend über das öffentliche Kubernetes Gateway erreichbar ist.

**Vorgehen:**

- Öffnen der öffentlichen HTTPS-Adresse im Browser
- Überprüfung der ausgelieferten Anwendung

**Erwartetes Ergebnis:** Frontend lädt erfolgreich.

**Beobachtetes Ergebnis:** Anwendung im Browser erreichbar.

**Status:** PASS

### FT-02 – Microsoft-Entra-Anmeldung

**Ziel:** Überprüfung des Anmeldeprozesses über Microsoft Entra ID.

**Vorgehen:**

- Frontend öffnen
- Microsoft-Entra-Anmeldung durchführen
- Anwendung nach erfolgreicher Authentifizierung verwenden

**Erwartetes Ergebnis:** Authentifizierter Benutzer kann geschützte Anwendungsfunktionen verwenden.

**Beobachtetes Ergebnis:** Anmeldung erfolgreich; Lernnotizen konnten anschließend verwaltet werden.

**Status:** PASS

### FT-03 – CRUD-Operationen

**Ziel:** Überprüfung der grundlegenden Datenbankfunktionen.

**Vorgehen:**

1. Vorhandene Lernnotizen anzeigen
2. Neue Testnotiz erstellen
3. Testnotiz bearbeiten
4. Aktualisierte Notiz erneut anzeigen
5. Testnotiz löschen
6. Verifizieren, dass die übrigen Notizen erhalten bleiben

**Erwartetes Ergebnis:** Alle Operationen funktionieren ohne unbeabsichtigten Datenverlust.

**Beobachtetes Ergebnis:** Erstellen, Anzeigen, Bearbeiten und Löschen der Testnotiz erfolgreich.

**Status:** PASS

**Hinweis:** Der Endpunkt `DELETE /entries` kann mehrere Einträge löschen und wird nicht als gewöhnlicher Funktionstest ausgeführt.

### FT-04 – API-Liveness

**Ziel:** Nachweis, dass der API-Prozess erreichbar ist.

**Testkommando:**

```bash
curl -i \
  "https://learningsteps.6aff4a07cf83170001eabf87.westeurope.aksapp.io/api/health/live"
```

**Erwartetes Ergebnis:** HTTP 200.

**Beobachtetes Ergebnis:** API-Liveness im Rahmen der bisherigen Gesundheitsprüfungen erfolgreich; der Endpunkt ist in der API implementiert.

**Status:** PASS

### FT-05 – API-Readiness inklusive Datenbank

**Ziel:** Überprüfung der API-Verfügbarkeit und PostgreSQL-Konnektivität.

**Testkommando:**

```bash
curl -sS \
  --connect-timeout 5 \
  --max-time 15 \
  -o /dev/null \
  -w "HTTP %{http_code} | Dauer: %{time_total}s\n" \
  "https://learningsteps.6aff4a07cf83170001eabf87.westeurope.aksapp.io/api/health/ready"
```

**Erwartetes Ergebnis:** HTTP 200.

**Beobachtetes Ergebnis:**

```text
HTTP 200 | Dauer: 0.135414s
```

Der Endpunkt führt eine PostgreSQL-Abfrage `SELECT 1` aus und antwortet bei einem Fehler mit HTTP 503.

**Status:** PASS

**Einschränkung:** Ein absichtlich verursachter Datenbankausfall wurde nicht durchgeführt.

## 4. Authentifizierungs- und Autorisierungstests

### ST-01 – API ohne Bearer-Token

**Ziel:** Überprüfen, dass geschützte Endpunkte nicht anonym aufgerufen werden können.

**Testkommando:**

```bash
curl -i \
  "https://learningsteps.6aff4a07cf83170001eabf87.westeurope.aksapp.io/api/entries"
```

**Erwartetes Ergebnis:** HTTP 401.

**Beobachtetes Ergebnis:**

```text
HTTP 401
{"detail":"Authentication required"}
```

**Status:** PASS

### ST-02 – Ungültiger Bearer-Token

**Ziel:** Überprüfen, dass ein ungültiges Zugriffstoken abgelehnt wird.

**Beobachtetes Ergebnis:**

```text
HTTP 401
{"detail":"Invalid access token"}
```

**Status:** PASS

Für reproduzierbare Tests dürfen ausschließlich künstliche, offensichtlich ungültige Tokenwerte verwendet werden. Gültige Zugriffstokens gehören nicht in Screenshots oder Testdokumentationen.

### ST-03 – JWT-Validierung

**Ziel:** Kontrolle der serverseitigen Tokenprüfung.

**Geprüfte Datei:** `api/security/auth.py`

**Festgestellte Kontrollen:**

- JWT-Signaturprüfung mittels Entra-ID-JWKS
- RS256 als erlaubter Signaturalgorithmus
- Validierung von Audience und Issuer
- Verpflichtender `exp`-Claim
- Tenant-ID-Validierung
- Tokenversionsprüfung
- Validierung der autorisierten Client-Anwendung über `azp`
- UUID-Prüfung der Benutzerkennung
- Ablehnung von Tokens mit `idtyp = app`
- Prüfung des erforderlichen Scopes `access_as_user`

**Status:** CODE REVIEW

**Offen:** Separat reproduzierbare Negativtests für falsche Audience, falschen Issuer, fehlenden Scope und abgelaufene beziehungsweise falsch signierte Tokens.

### ST-04 – Benutzerisolation

**Ziel:** Sicherstellen, dass ein Benutzer nicht auf Lernnotizen eines anderen Benutzers zugreifen kann.

**Geprüfte Implementierung:** `api/repositories/postgres_repository.py`

Die Datenbankabfrage für KI-Zusammenfassungen verwendet einen parametrisierten Filter:

```sql
WHERE owner_id = $1
```

Die übergebene Benutzerkennung wird aus dem validierten Tokenkontext abgeleitet.

**Status:** PARTIAL / CODE REVIEW

**Offen:** Praktischer Test mit zwei unterschiedlichen Entra-Konten und gezielten Zugriffen auf fremde Eintrags-IDs.

## 5. Kubernetes-Netzwerksicherheit

### ST-05 – Zugriff über das Istio Gateway

**Ziel:** Nachweis, dass legitime Verbindungen zu API und Frontend funktionieren.

**Vorgehen:**

- Zugriff auf das Frontend über HTTPS
- Zugriff auf API-Healthchecks über HTTPS
- Überprüfung der Antwortcodes

**Beobachtetes Ergebnis:** Verbindungen erfolgreich; API-Healthcheck HTTP 200.

**Status:** PASS

### ST-06 – Nicht autorisierter Pod-Zugriff

**Ziel:** Überprüfen, ob direkte Zugriffe aus einem nicht autorisierten Pod blockiert werden.

**Vorgehen:**

- Temporären Test-Pod im Namespace `learningsteps` starten
- Direkten Verbindungsversuch zu den internen API- und Web-Services durchführen
- Ergebnis kontrollieren
- Test-Pod entfernen

**Erwartetes Ergebnis:** Direkte Verbindung wird durch NetworkPolicies blockiert.

**Beobachtetes Ergebnis:** Verbindungsversuche aus dem Test-Pod liefen in Timeouts.

**Status:** PASS

Die Ingress-NetworkPolicies beschränken Zugriffe auf Gateway-Pods und die benötigten TCP-Ports 8000 beziehungsweise 8080.

**Einschränkung:** Die Tests beweisen keine vollständige Egress-Isolation.

## 6. Container-Härtung

### ST-07 – Nicht privilegierte Container

**Ziel:** Kontrolle der Container-Sicherheitskonfiguration.

**Geprüfte Konfiguration:**

| Eigenschaft | API | Web |
|---|---|---|
| Non-Root | UID 100 | UID 101 |
| Privilege Escalation | Deaktiviert | Deaktiviert |
| Linux Capabilities | Drop ALL | Drop ALL |
| Read-only Root Filesystem | Aktiviert | Aktiviert |
| Seccomp | RuntimeDefault | RuntimeDefault |

**Status:** CODE REVIEW und Deployment-Verifikation

### ST-08 – Schreibschutz des Root-Dateisystems

**Ziel:** Nachweis, dass Container nicht beliebig in das Root-Dateisystem schreiben können.

**Vorgehen:**

- Schreibversuch außerhalb der freigegebenen Verzeichnisse
- Schreibversuch im temporären Verzeichnis `/tmp`

**Beobachtetes Ergebnis:**

- Schreibzugriff auf das Root-Dateisystem verweigert
- Schreibzugriff in `/tmp` erfolgreich

**Status:** PASS

### ST-09 – Kubernetes-Probes

**Ziel:** Überprüfung der definierten Gesundheitsprüfungen.

**Testkommando:**

```bash
kubectl get deployment learningsteps-api \
  -n learningsteps \
  -o json |
jq '.spec.template.spec.containers[]
  | select(.name == "api")
  | {startupProbe, readinessProbe, livenessProbe}'
```

**Beobachtetes Ergebnis:**

- Readiness: `/health/ready`, alle 15 Sekunden
- Liveness: `/health/live`, alle 20 Sekunden
- Startup-Probe ebenfalls konfiguriert
- Aktueller API-Pod meldete `Ready: True`

**Status:** PASS für die Konfiguration und den beobachteten Bereitzustand.

**Offen:** Kontrollierter Test des Verhaltens bei dauerhaft fehlschlagenden Probes.

## 7. Azure Identity und Secret Management

### ST-10 – Key Vault CSI

**Ziel:** Nachweis der Secret-Bereitstellung im berechtigten API-Pod.

**Vorgehen:**

- CSI-Konfiguration prüfen
- Secret-Mount im API-Pod überprüfen
- Lesbarkeit der benötigten Secret-Datei kontrollieren

**Beobachtetes Ergebnis:** Secret-Datei für die Anwendung verfügbar.

**Status:** PASS

**Sicherheitshinweis:** Der Inhalt des Secrets wird nicht in der Testdokumentation ausgegeben.

### ST-11 – Azure AI Workload Identity

**Ziel:** Nachweis eines authentifizierten Modellaufrufs ohne statischen Azure-AI-API-Key.

**Vorgehen:**

- AI-Smoke-Test als Kubernetes Job ausführen
- Azure Workload Identity verwenden
- Modellantwort und erfolgreichen Jobabschluss überprüfen

**Beobachtetes Ergebnis:**

```text
AI RESPONSE:
Du hast Terraform und Kubernetes gelernt und eine CI/CD-Pipeline erstellt.
MODEL CALL SUCCESSFUL
```

Der Kubernetes Job erreichte den Status `Complete`.

**Status:** PASS

## 8. KI-End-to-End-Tests

### FT-06 – KI-Lernzusammenfassung

**Ziel:** Nachweis der vollständigen Kommunikation zwischen Frontend, API, PostgreSQL und Azure AI.

**Vorgehen:**

1. `AI_SUMMARY_ENABLED` auf `true` setzen
2. ConfigMap anwenden
3. API-Deployment kontrolliert neu ausrollen
4. API-Readiness überprüfen
5. Im Frontend anmelden
6. Lernzusammenfassung starten

**Beobachtetes Ergebnis:**

- KI-Zusammenfassung erfolgreich generiert
- Eine Lernnotiz analysiert
- Modellname `learningsteps-summary` angezeigt
- Zusammenfassung im Frontend dargestellt

**Status:** PASS

### ST-12 – Prompt-Injection-Schutz

**Ziel:** Prüfung der Behandlung potenziell manipulierter Notizinhalte.

**Implementiert:**

- System-Prompt mit Verbot der Befolgung von Notizanweisungen
- Strukturierte Übergabe der Notizen als JSON
- Maximale Anzahl von 20 Notizen
- Begrenzung der einzelnen Textfelder auf 500 Zeichen

**Status:** CODE REVIEW

**Offen:** Gezielte adversariale Prompt-Injection-Tests.

Die vorhandenen Schutzmaßnahmen bieten keine vollständige Sicherheitsgarantie gegen Prompt Injection.

## 9. CI/CD-Tests

### CI-01 – Codequalität und Funktionstests

**Werkzeuge:** Ruff, Pytest

**Nachweis:** GitHub-Actions-Workflow `ci.yml`

**Beobachtetes Ergebnis:** CI-Quality-Job erfolgreich.

**Status:** PASS

### CI-02 – Infrastructure Security

**Werkzeug:** Trivy

**Prüfbereiche:**

- Terraform-Konfiguration
- Kubernetes-Manifeste
- Secrets
- Container-Schwachstellen

**Beobachtetes Ergebnis:** Die konfigurierten CI-Sicherheitsprüfungen wurden erfolgreich abgeschlossen.

**Status:** PASS

Ein erfolgreicher Scan beweist nicht die Abwesenheit sämtlicher Schwachstellen.

### CI-03 – Kubernetes-Schema-Validierung

**Werkzeug:** Kubeconform

**Vorgehen:**

- Kubernetes-Manifeste gegen Schemas validieren
- Zusätzliche CRD-Schemas verwenden
- Verwendetes Kubeconform-Binary mittels SHA-256 prüfen

**Beobachtetes Ergebnis:** Schema-Validierung erfolgreich.

**Status:** PASS

### CI-04 – GitHub-Actions-Pipeline

**Nachweis:** Erfolgreiche Workflow-Ausführung nach den implementierten Sicherheits- und Dokumentationsänderungen.

**Status:** PASS für die beobachteten CI-Ausführungen.

Die Ergebnisse gelten jeweils für die geprüften Commits und ersetzen keine Laufzeit-Sicherheitsüberprüfung.

## 10. Monitoring-Tests

### MT-01 – Datenerfassung in Log Analytics

**Ziel:** Nachweis aktueller Kubernetes-Telemetrie.

**Verwendete Tabellen:**

- `ContainerLogV2`
- `KubePodInventory`
- `InsightsMetrics`

**Beobachtete Datensätze innerhalb von 24 Stunden:**

| Tabelle | Datensätze |
|---|---:|
| ContainerLogV2 | 3.813 |
| KubePodInventory | 28.654 |
| InsightsMetrics | 32.107 |

**Status:** PASS

Die Zahlen sind Datensätze, keine unterschiedlichen Container oder Benutzeranfragen.

### MT-02 – API-Container-Neustarts

**Ziel:** Prüfen, ob die Neustartzähler der API- und Web-Container im untersuchten Zeitraum gestiegen sind.

**Beobachtetes Ergebnis:** Keine Zunahme innerhalb des abgefragten Zeitfensters erkannt.

**Status:** PASS für das untersuchte Zeitfenster.

### MT-03 – Monitoring-KQL-Simulation

**Ziel:** Überprüfung der vorbereiteten Alarmzustandslogik.

| Szenario | Erwarteter Alarmwert | Beobachtet |
|---|---:|---:|
| API läuft | 0 | 0 |
| Simuliert fehlende API | 1 | 1 |
| Simuliert fehlende Telemetrie | 2 | 2 |

**Status:** SIMULATED

Die Tests beweisen die Berechnung der KQL-Zustände, nicht die tatsächliche Auslösung einer Azure-Monitor-Alarmregel.

### MT-04 – Azure-Monitor-Alarm

**Status:** OPEN

Die Terraform-Datei `infra-terraform/alerts.tf` enthält eine vorbereitete, deaktivierte Alarmregel.

Die Regel wurde noch nicht in Azure bereitgestellt und besitzt keine produktive Benachrichtigungskonfiguration.

## 11. Terraform- und Infrastrukturtests

### IT-01 – Terraform-Validierung

**Testkommandos:**

```bash
terraform fmt -check
terraform validate
terraform plan
```

**Beobachtetes Ergebnis:** Konfiguration gültig, Terraform-Plan erfolgreich erstellt.

**Status:** PASS

### IT-02 – Terraform-State-Storage-Härtung

**Ziel:** Verbesserung des Schutzes vor versehentlichem Löschen und Überschreiben.

**Umgesetzte Maßnahmen:**

- Blob Soft Delete aktiviert
- Aufbewahrung sieben Tage
- Blob-Versionierung aktiviert

**Verifikation:**

- Azure-CLI-Abfrage der Blob-Service-Eigenschaften
- `terraform state list`
- `terraform plan`

**Beobachtetes Ergebnis:** Schutzfunktionen aktiviert; Terraform-Zugriff weiterhin erfolgreich.

Der anschließende Plan enthielt:

```text
Plan: 1 to add, 0 to change, 0 to destroy.
```

Die einzige geplante Änderung war die noch nicht bereitgestellte Monitoring-Alarmregel.

**Status:** PASS

**Offen:** Tatsächliche Wiederherstellung einer früheren State-Version.

### IT-03 – Private Azure-Dienste

**Ziel:** Kontrolle der privaten Netzwerkbereitstellung.

**Geprüfte Terraform-Konfiguration:**

- PostgreSQL mit deaktiviertem öffentlichem Netzwerkzugriff
- Key Vault über Private Endpoint
- Backup-Storage über Private Endpoint
- Private DNS-Zonen und VNet-Verknüpfungen

**Status:** CODE REVIEW; entsprechende Azure-Ressourcen wurden in der Infrastruktur-Bestandsaufnahme bestätigt.

Ein vollständiger Netzwerkerreichbarkeitstest aus jedem möglichen Quellnetz wurde nicht durchgeführt.

## 12. Noch offene Tests

| Test-ID | Test | Priorität |
|---|---|---|
| OT-01 | Cross-User-Autorisierung mit zwei Entra-Konten | Hoch |
| OT-02 | Gezielte JWT-Negativtests | Hoch |
| OT-03 | Prompt-Injection-Tests | Mittel |
| OT-04 | Wiederherstellung einer Terraform-State-Version | Hoch |
| OT-05 | PostgreSQL-Restore-Test | Hoch |
| OT-06 | Automatische Alarm-Auslösung und Benachrichtigung | Mittel |
| OT-07 | Externer automatisierter HTTPS-Verfügbarkeitstest | Mittel |
| OT-08 | Vollständige Egress-Policy-Tests | Mittel |
| OT-09 | Rate-Limiting- und KI-Kostenmissbrauchstests | Mittel |

## 13. Gesamtbewertung

Die wesentlichen Anwendungsfunktionen wurden erfolgreich Ende zu Ende überprüft.

Zusätzlich wurden mehrere sicherheitsrelevante Kontrollen praktisch getestet, darunter:

- API-Authentifizierung
- Kubernetes NetworkPolicies
- Container-Dateisystemhärtung
- Azure Workload Identity
- Key-Vault-Secret-Bereitstellung
- Automatisierte CI-Sicherheitsprüfungen

Auch die Monitoring-Datenerfassung und der Zugriff auf den gehärteten Terraform-State wurden erfolgreich validiert.

**Nicht nachgewiesen** sind bislang eine vollständige Cross-User-Isolation, umfassende adversariale Tests, zuverlässige automatische Alarmierung und vollständige Wiederherstellungsprozesse.

LearningSteps erfüllt damit die dokumentierten Lern- und Demonstrationsziele in wesentlichen Bereichen. Eine vollständige Produktionsfreigabe lässt sich aus den bisherigen Tests nicht ableiten.

Die Testdokumentation wird bei weiteren Änderungen und durchgeführten Prüfungen fortgeschrieben.