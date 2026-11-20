# LearningSteps – Security Documentation

## 1. Sicherheitsüberblick

LearningSteps ist eine cloudnative Lernjournal-Anwendung auf Microsoft Azure. Die Sicherheitsarchitektur berücksichtigt Identitätsverwaltung, Netzwerksicherheit, Container-Härtung, Secret Management, Software Supply Chain Security und KI-Sicherheit.

Das Projekt verfolgt einen mehrschichtigen Sicherheitsansatz (*Defense in Depth*).

**Schutzziele:**

- Vertraulichkeit und Integrität benutzerbezogener Lernnotizen
- Verhinderung unberechtigter API- und Datenbankzugriffe
- Schutz sensibler Zugangsdaten und Azure-Identitäten
- Begrenzung der Auswirkungen kompromittierter Container
- Erkennung unsicherer Infrastruktur- und Anwendungskonfigurationen
- Nachvollziehbarkeit sicherheitsrelevanter Ereignisse

Die Anwendung ist eine Lern- und Demonstrationsumgebung. Eine vollständige Produktionshärtung oder unabhängige Sicherheitsprüfung wird nicht beansprucht.

## 2. Threat Model

### Schutzbedürftige Ressourcen

| Ressource | Schutzziel |
|---|---|
| Lernnotizen | Vertraulichkeit und Integrität |
| Entra-ID-Zugriffstokens | Schutz vor Missbrauch |
| PostgreSQL-Datenbank | Verfügbarkeit und Datenintegrität |
| Azure Key Vault | Schutz von Secrets |
| Azure Managed Identities | Begrenzung von Azure-Berechtigungen |
| Container-Images | Integrität der bereitgestellten Software |
| Terraform-State | Schutz gespeicherter Infrastrukturinformationen und Secrets |
| Azure-AI-Anfragen | Schutz der übertragenen Inhalte |

### Angriffsflächen und Vertrauensgrenzen

Zu den relevanten Angriffsflächen gehören das öffentlich erreichbare HTTPS-Gateway, die API-Endpunkte, Authentifizierungstokens, Benutzerinhalte, Container-Abhängigkeiten und die CI/CD-Pipeline.

Besondere Vertrauensgrenzen bestehen zwischen:

1. Internet und öffentlichem Kubernetes Gateway
2. Browser und authentifizierter API
3. Kubernetes-Workloads untereinander
4. AKS und privaten Azure-Diensten
5. Anwendung und Azure-AI-Modell
6. GitHub Actions und Azure-Ressourcen

## 3. Identity & Access Management

### Microsoft Entra ID

LearningSteps verwendet Microsoft Entra ID für die Anmeldung.

Geschützte API-Endpunkte erwarten ein Bearer-Token, das serverseitig validiert wird.

**Durchgeführte Tests:**

- API-Aufruf ohne Bearer-Token: HTTP 401
- API-Aufruf mit ungültigem Bearer-Token: HTTP 401
- Authentifizierte Anmeldung und CRUD-Operationen über das Frontend: erfolgreich

Diese Tests bestätigen die Ablehnung fehlender und ungültiger Tokens. Sie ersetzen keinen vollständigen Test sämtlicher JWT-Validierungsbedingungen, beispielsweise Issuer, Audience und Tokenablauf.

### Benutzerbezogene Autorisierung

Lernnotizen werden einer Benutzerkennung zugeordnet.

Für die KI-Zusammenfassung verwendet das Backend eine parametrisierte PostgreSQL-Abfrage:

```sql
SELECT data
FROM entries
WHERE owner_id = $1
ORDER BY created_at DESC, id DESC
LIMIT $2
```

Die Benutzerkennung stammt aus dem authentifizierten Benutzerkontext.

**Status:** Implementierung durch Codeprüfung bestätigt.

**Offen:** Ein vollständiger Cross-User-Test mit zwei unterschiedlichen Entra-Konten, einschließlich gezielter Zugriffsversuche auf fremde Eintrags-IDs.

### Azure Workload Identity

Die FastAPI verwendet die dedizierte User Assigned Managed Identity `id-learningsteps-api`.

Das zugehörige Federated Identity Credential ist auf den Kubernetes-ServiceAccount beschränkt:

`system:serviceaccount:learningsteps:learningsteps-api`

Die Audience lautet `api://AzureADTokenExchange`.

Die Identität besitzt die Azure-Rolle `Key Vault Secrets User` auf dem LearningSteps-Key-Vault.

Für Azure AI besteht eine zusätzliche entsprechende Rollenberechtigung.

Der Azure-AI-Smoke-Test hat die tokenbasierte Authentifizierung mit Workload Identity erfolgreich nachgewiesen.

**Restrisiko:** Eine Kompromittierung eines Pods, der die berechtigte Workload Identity verwenden kann, könnte den Missbrauch der zugewiesenen Azure-Berechtigungen ermöglichen.

## 4. Network Security

### Azure Virtual Network

Das VNet `vnet-learningsteps-weu` verwendet `10.30.0.0/16`.

| Subnetz | CIDR | Verwendung |
|---|---|---|
| `snet-aks` | `10.30.1.0/24` | AKS |
| `snet-postgres` | `10.30.2.0/24` | PostgreSQL |
| `snet-private-endpoints` | `10.30.3.0/24` | Private Endpoints |
| `snet-maintenance` | `10.30.4.0/27` | Wartungsumgebung |

Die Aufteilung in Subnetze schafft logische Netzwerkgrenzen. Eine vollständige Isolation zwischen allen Subnetzen ergibt sich daraus allein nicht.

### Private Azure-Dienste

**PostgreSQL**

- Flexible Server mit delegiertem Subnetz
- Öffentlicher Netzwerkzugriff deaktiviert
- Private DNS-Auflösung

**Azure Key Vault**

- Öffentlicher Netzwerkzugriff deaktiviert
- Zugriff über Private Endpoint
- Netzwerk-Standardregel `Deny`
- Trusted-Services-Bypass `None`

**Backup-Storage**

- Öffentlicher Netzwerkzugriff deaktiviert
- Private Endpoint für Blob Storage
- Shared-Key-Authentifizierung deaktiviert
- HTTPS und mindestens TLS 1.2
- Keine öffentlich zugänglichen Blob-Unterelemente

### Kubernetes NetworkPolicies

Die Anwendung besitzt separate Ingress-NetworkPolicies für API und Frontend.

| Workload | Zugelassene Quelle | Zielport |
|---|---|---|
| API | Pods des LearningSteps-Gateways | TCP 8000 |
| Frontend | Pods des LearningSteps-Gateways | TCP 8080 |

Die Gateway-Pods werden über ihren Kubernetes-Label-Selektor identifiziert.

**Durchgeführte Tests:**

- Erlaubte HTTPS-Verbindungen über das Gateway: erfolgreich
- Direkte Verbindungen aus einem nicht autorisierten Test-Pod: blockiert

**Restrisiko:** Die Policies beschränken den eingehenden Verkehr, enthalten aber keine vollständige restriktive Egress-Kontrolle.

## 5. Container Security

API- und Frontend-Container werden mit eingeschränkten Berechtigungen ausgeführt.

| Schutzmaßnahme | API | Frontend |
|---|---|---|
| Non-Root-Benutzer | UID 100 | UID 101 |
| Privilege Escalation | Deaktiviert | Deaktiviert |
| Linux Capabilities | Alle entfernt | Alle entfernt |
| Root-Dateisystem | Schreibgeschützt | Schreibgeschützt |
| Seccomp | RuntimeDefault | RuntimeDefault |
| Temporärer Schreibbereich | `/tmp` | `/tmp` |
| Ressourcenlimits | Konfiguriert | Konfiguriert |
| Readiness-/Liveness-Probes | Konfiguriert | Konfiguriert |

Das Secret-Volume der API wird schreibgeschützt eingebunden.

Der API-Container besitzt zusätzlich eine Startup-Probe.

**Durchgeführte Tests:**

- Schreibversuch im Root-Dateisystem: verweigert
- Schreibversuch in `/tmp`: erfolgreich
- Kubernetes-Deployment und Healthchecks: erfolgreich

Diese Einstellungen erschweren bestimmte Container-Escapes und Privilege-Escalation-Techniken. Sie stellen jedoch keine vollständige Isolation gegen Schwachstellen im Kernel oder in der Container-Runtime dar.

## 6. Secrets Management

### Azure Key Vault

Das PostgreSQL-Administratorpasswort wird über Azure Key Vault und den Secrets Store CSI Driver bereitgestellt.

Die API verwendet folgenden Dateipfad:

`/mnt/secrets/postgres-admin-password`

Die ConfigMap enthält den Pfad, nicht das Passwort.

**Durchgeführter Test:** Der Zugriff auf das bereitgestellte Secret aus dem berechtigten API-Workload wurde erfolgreich geprüft.

### Key-Vault-Löschschutz

Soft Delete ist mit sieben Tagen Aufbewahrung aktiviert.

Purge Protection ist deaktiviert.

**Restrisiko:** Ausreichend privilegierte Identitäten könnten gelöschte Objekte endgültig entfernen.

Diese Einstellung ist für eine zeitlich begrenzte Lernumgebung dokumentiert, wäre für eine produktive Umgebung mit kritischen Secrets jedoch zu überdenken.

### Terraform-State

Der Terraform-State wird im Azure Storage Account `stlearningsteps6f83874f` innerhalb der separaten Resource Group `rg-learningsteps-tfstate` gespeichert.

Das AzureRM-Backend verwendet Microsoft Entra ID (`use_azuread_auth = true`) und Azure CLI Credentials (`use_cli = true`). Ein Storage-Account-Key wird nicht in der Backend-Konfiguration hinterlegt.

**Implementierte Schutzmaßnahmen:**

- Separater Storage Account außerhalb der Anwendungs-Resource-Group
- HTTPS-Zwang aktiviert
- Mindest-TLS-Version 1.2
- Anonymer öffentlicher Blob-Zugriff deaktiviert
- Microsoft-Entra-basierte Backend-Authentifizierung
- Shared-Key-Authentifizierung ausdrücklich deaktiviert
- Blob Soft Delete mit sieben Tagen Aufbewahrung
- Blob-Versionierung aktiviert
- Lifecycle-Policy `delete-old-tfstate-versions` aktiviert
- Automatische Löschung früherer State-Blob-Versionen nach mehr als 90 Tagen
- Keine Lifecycle-Löschaktion für die aktuelle Blob-Version konfiguriert

**Durchgeführte Verifikation:**

- Azure-CLI-Zugriff mit `--auth-mode login` erfolgreich
- Terraform-Remote-State über `terraform state list` erreichbar
- Terraform-Plan nach Aktivierung von Soft Delete und Versionierung erfolgreich
- Terraform-Zugriff nach Deaktivierung der Shared-Key-Authentifizierung erneut erfolgreich
- Lifecycle-Policy über Azure CLI ausgelesen und bestätigt

**Verbleibende Risiken:**

- Netzwerk-Standardregel des Storage Accounts steht weiterhin auf `Allow`.
- Mehrere übergeordnete Azure-RBAC-Rollen ermöglichen weitreichende Verwaltungszugriffe.
- Frühere State-Versionen werden nach Ablauf der konfigurierten Aufbewahrungsfrist automatisch gelöscht.
- Eine unabhängige Sicherung und praktische Wiederherstellung eines früheren Terraform-State-Stands wurden noch nicht nachgewiesen.

Terraform-State-Dateien können vertrauliche Informationen wie Datenbankpasswörter und Infrastrukturdetails enthalten.

Eine weitere Einschränkung des Netzwerkzugriffs erfordert zunächst einen geeigneten Zugangsweg für die Terraform-Administration. Die Wiederherstellbarkeit des States muss vor dem abschließenden Infrastructure-Recovery-Test gesondert abgesichert werden.

## 7. Software Supply Chain Security

### GitHub Actions

Das Repository verwendet GitHub Actions zur automatisierten Prüfung und Bereitstellung.

Die CI-Pipeline umfasst:

- Python-Tests
- Ruff-Codeanalyse
- Trivy Secret Scanning
- Trivy Infrastructure-as-Code-Scanning
- Kubernetes-Konfigurationsprüfungen
- Kubeconform-Schema-Validierung
- Container-Build und Schwachstellenscan

Die Sicherheitsprüfungen sind Bestandteil der CI-Quality-Gates.

### Dependency Management

Python-Abhängigkeiten werden über versionierte Requirements-Dateien verwaltet.

Für die produktive API werden konkrete Paketversionen einschließlich transitiver Abhängigkeiten festgelegt.

### Kubernetes-Schema-Validierung

Kubeconform prüft Kubernetes-Manifeste gegen definierte Schemas.

Für die Bereitstellung von Kubeconform wird ein SHA-256-Prüfwert verwendet. Das verwendete externe CRD-Schema-Repository wird über einen festgelegten Commit referenziert.

### Dokumentierte Scanner-Ausnahme

Für die Kubernetes-ConfigMap existiert eine begründete, dateispezifische Ausnahme für `KSV-0109`.

Ursache ist der Schlüssel `DB_PASSWORD_FILE`, dessen Wert lediglich auf eine durch CSI bereitgestellte Secret-Datei verweist.

Die Ausnahme ist nicht als generelle Erlaubnis zum Speichern von Passwörtern in ConfigMaps zu verstehen.

### Verbleibende Supply-Chain-Risiken

Automatisierte Scans erkennen nicht sämtliche Sicherheitsprobleme.

Insbesondere bleiben Risiken durch kompromittierte Upstream-Abhängigkeiten, Build-Werkzeuge und CI/CD-Berechtigungen bestehen.

## 8. AI Security

Die KI-Zusammenfassung wird über den geschützten Endpunkt `POST /entries/summary` bereitgestellt.

### Datenverarbeitung

Die API:

1. Authentifiziert den Benutzer.
2. Ermittelt dessen Benutzerkennung.
3. Lädt maximal 21 Einträge zur Prüfung des Limits.
4. Verweigert die Zusammenfassung bei mehr als 20 Notizen.
5. Begrenzt die verarbeiteten Textfelder auf 500 Zeichen.
6. Übermittelt die ausgewählten Notizinhalte als JSON an Azure AI.

Die Authentifizierung gegenüber Azure AI erfolgt über Azure Workload Identity und OAuth-Zugriffstokens.

### Prompt-Injection-Risikoreduzierung

Der System-Prompt weist das Modell an, Notizinhalte ausschließlich als Daten zu behandeln.

Benutzerinhalte werden in einer separaten User-Nachricht als JSON übertragen.

Dies reduziert das Risiko einer unbeabsichtigten Befolgung manipulierter Notizinhalte.

**Restrisiko:** Sprachmodelle können auch bei klar getrennten Anweisungen durch Prompt Injection beeinflusst werden. Ein vollständiger adversarialer Test ist noch offen.

### Kosten- und Missbrauchsbegrenzung

Die Anwendung begrenzt:

- Anzahl der Notizen
- Länge einzelner Textfelder
- Maximale generierte Tokens
- Zeitdauer einer Modellanfrage

Diese Maßnahmen begrenzen die Verarbeitung pro Anfrage.

**Offen:** Eine zusätzliche benutzerbezogene Rate-Limitierung und ein vollständiger Test möglicher Kostenmissbrauchsszenarien.

## 9. Security Testing

| Test | Ergebnis | Einordnung |
|---|---|---|
| API ohne Authentifizierung | HTTP 401 | Bestätigt |
| API mit ungültigem Token | HTTP 401 | Bestätigt |
| CRUD über angemeldeten Benutzer | Erfolgreich | Bestätigt |
| Benutzerfilter in SQL | Vorhanden | Codeprüfung |
| Cross-User-Datenzugriff | Nicht getestet | Offen |
| NetworkPolicy – Gateway-Zugriff | Erfolgreich | Bestätigt |
| NetworkPolicy – nicht autorisierter Pod | Verbindung blockiert | Bestätigt |
| Schreibgeschütztes Root-Dateisystem | Schreibversuch verweigert | Bestätigt |
| Azure Key Vault CSI | Secret verfügbar | Bestätigt |
| Azure AI Workload Identity | Modellaufruf erfolgreich | Bestätigt |
| KI-Zusammenfassung im Frontend | Erfolgreich | Bestätigt |
| Trivy-Sicherheitsprüfungen | CI erfolgreich | Bestätigt |
| Kubeconform | CI erfolgreich | Bestätigt |
| Container- und Pod-Monitoring | Daten vorhanden | Bestätigt |
| Monitoring-KQL-Simulation | Drei Zustände geprüft | Bestätigt |
| Aktiver Azure-Monitor-Alert | Nicht bereitgestellt | Offen |
| Externer automatisierter HTTPS-Test | Nicht eingerichtet | Offen |
| Vollständiger Restore-Test | Nicht nachgewiesen | Offen |

## 10. Residual Risks

| Risiko | Bedeutung | Mögliche Verbesserung |
|---|---|---|
| Fehlende umfassende Egress-Policies | Kompromittierte Pods könnten erlaubte externe Ziele kontaktieren | Zielgerichtete Egress-Regeln |
| Key Vault ohne Purge Protection | Erhöhtes Risiko endgültiger Secret-Löschung | Purge Protection aktivieren |
| Unvollständig getestete Benutzerisolation | Fehlerhafte Autorisierung könnte fremde Daten offenlegen | Tests mit zwei Entra-Konten |
| Prompt Injection | Manipulierte Lernnotizen könnten KI-Ausgaben beeinflussen | Adversariale Tests und Ausgabekontrollen |
| Terraform-State | Potenziell enthaltene Secrets und Infrastrukturinformationen | Backend- und RBAC-Audit |
| Fehlende aktive Alarmierung | Ausfälle werden nicht automatisch gemeldet | Validierte Azure-Monitor-Alerts und Action Group |
| Unvollständig getestete Wiederherstellung | Backup-Konfiguration beweist keine Restore-Fähigkeit | Kontrollierter Restore-Test |
| Keine umfassende Missbrauchsbegrenzung für KI | Wiederholte Modellanfragen könnten Kosten verursachen | Rate Limiting und Quotas |

## 11. Security Status

LearningSteps implementiert mehrere aufeinander abgestimmte Sicherheitskontrollen in Azure, Kubernetes, CI/CD und Anwendungscode.

Wesentliche Maßnahmen wurden anhand von Konfigurationsprüfungen und praktischen Funktionstests nachgewiesen.

Der aktuelle Stand stellt eine abgesicherte Lern- und Demonstrationsumgebung dar, jedoch keine unabhängig zertifizierte oder vollständig produktionsgehärtete Plattform.

Die verbleibenden Risiken sind dokumentiert und bilden die Grundlage für weitere Security-Tests und Härtungsmaßnahmen.