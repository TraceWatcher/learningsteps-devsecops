# LearningSteps – Azure DevSecOps & AI Security

**Cloud-native Lernjournal-Anwendung mit Microsoft Azure, Kubernetes, Terraform, GitHub Actions und KI-gestützter Lernzusammenfassung.**

## Projektübersicht

LearningSteps ist ein DevSecOps-Lernprojekt, bei dem eine bestehende FastAPI-/PostgreSQL-Anwendung zu einer cloudnativen, authentifizierten Webanwendung auf Microsoft Azure weiterentwickelt wurde.

Der Fokus liegt nicht nur auf der Bereitstellung der Anwendung, sondern insbesondere auf der Integration von Sicherheitsmaßnahmen in Architektur, Infrastruktur, Container, CI/CD-Pipeline und laufenden Betrieb.

Das Projekt wurde im Rahmen der Cybersecurity-Weiterbildung entwickelt.

### Implementierte Funktionen

- Lernnotizen erstellen, anzeigen, bearbeiten und löschen
- Anmeldung über Microsoft Entra ID
- Benutzerbezogene Speicherung von Lernnotizen
- KI-gestützte Zusammenfassung eigener Lernnotizen über Azure AI
- Bereitstellung über einen öffentlichen HTTPS-Endpunkt
- Automatisierte Build-, Test- und Sicherheitsprüfungen

## Technologie-Stack

| Bereich | Technologien |
|---|---|
| Cloud | Microsoft Azure |
| Container-Orchestrierung | Azure Kubernetes Service (AKS) |
| Infrastructure as Code | Terraform |
| Backend | Python, FastAPI |
| Frontend | JavaScript, MSAL, Nginx |
| Datenbank | Azure Database for PostgreSQL |
| Authentifizierung | Microsoft Entra ID, OAuth 2.0 / JWT |
| Secrets | Azure Key Vault, Secrets Store CSI Driver |
| KI | Azure AI, OpenAI Python SDK |
| CI/CD | GitHub Actions |
| Security Scanning | Trivy, Ruff, Kubeconform |
| Monitoring | Azure Monitor, Container Insights, Log Analytics |

## Architektur

Die Anwendung besteht aus mehreren Komponenten:

1. Benutzer greifen über HTTPS auf das Web-Frontend zu.
2. Das Frontend verwendet Microsoft Entra ID zur Anmeldung.
3. Ein Istio-basiertes Kubernetes Gateway leitet Anfragen an die entsprechenden Services weiter.
4. Die FastAPI-Anwendung validiert Zugriffstokens und verarbeitet benutzerbezogene Anfragen.
5. Lernnotizen werden in Azure Database for PostgreSQL gespeichert.
6. Für die KI-Zusammenfassung ruft die API ein Azure-AI-Modell auf.
7. Sensible Zugangsdaten werden über Azure Key Vault bereitgestellt.

Die Azure-Infrastruktur wird mit Terraform verwaltet.

## Sicherheitskonzept

### Identity & Access Management

- Microsoft Entra ID für die Benutzeranmeldung
- JWT-basierte Authentifizierung der API
- Benutzerbezogene Zugriffskontrolle für Lernnotizen
- Azure Workload Identity für die Kommunikation mit Azure-Diensten
- Rollenbasierte Berechtigungen statt fest eingebetteter Azure-API-Schlüssel

### Kubernetes Security

- Ausführung der Anwendung als nicht privilegierter Benutzer
- Schreibgeschütztes Root-Dateisystem
- Deaktivierte Privilege Escalation
- Entfernte Linux Capabilities
- Seccomp-Profil `RuntimeDefault`
- NetworkPolicies zur Beschränkung eingehender Verbindungen
- Readiness- und Liveness-Probes

### Secret Management

- Azure Key Vault zur Verwaltung sensibler Konfigurationswerte
- Bereitstellung von Secrets über den Secrets Store CSI Driver
- Keine produktiven Zugangsdaten im Kubernetes-ConfigMap-Manifest

### CI/CD Security

Die GitHub-Actions-Pipeline beinhaltet automatisierte Prüfungen für:

- Python-Codequalität und Tests
- Sicherheitsprobleme in Terraform- und Kubernetes-Manifests
- Secret Scanning
- Container-Schwachstellen
- Kubernetes-Schema-Validierung
- Container-Build

Die Sicherheitsprüfungen dienen als Quality Gates vor einer erfolgreichen Pipeline-Ausführung.

## KI-gestützte Lernzusammenfassung

Die Anwendung kann Lernnotizen eines authentifizierten Benutzers über ein Azure-AI-Modell zusammenfassen.

Implementierte Schutzmaßnahmen:

- Authentifizierung vor Verarbeitung der Anfrage
- Datenbankabfragen mit Benutzerfilter
- Begrenzung auf maximal 20 Notizen pro Anfrage
- Begrenzung der verarbeiteten Textlängen
- Trennung zwischen Systemanweisungen und Notizinhalten
- Authentifizierung gegenüber Azure AI über Workload Identity
- Timeout und kontrollierte Fehlerbehandlung

Notizinhalte werden als nicht vertrauenswürdige Eingaben behandelt. Die Prompt-Injection-Abwehr ist eine Risikoreduzierung, keine vollständige Sicherheitsgarantie.

## Monitoring und Betrieb

Für die Überwachung werden Azure Monitor, Container Insights und Log Analytics verwendet.

Erfasste Informationen umfassen:

- Container-Logs
- Pod- und Containerzustände
- Container-Neustarts
- Ressourcenmetriken

Zusätzlich besitzt die API zwei Healthcheck-Endpunkte:

| Endpoint | Funktion |
|---|---|
| `/health/live` | Prüft die Erreichbarkeit des API-Prozesses |
| `/health/ready` | Prüft API und PostgreSQL-Verbindung |

Eine Terraform-Konfiguration für eine Log-Analytics-basierte Alert-Regel ist vorbereitet und validiert, aber noch nicht in Azure bereitgestellt.

## Durchgeführte Tests

Im Projekt wurden unter anderem folgende Tests erfolgreich durchgeführt:

- HTTPS-Erreichbarkeit des Frontends
- Microsoft-Entra-Anmeldung
- Erstellen, Bearbeiten und Löschen von Lernnotizen
- Zugriff auf geschützte API-Endpunkte ohne gültiges Token wird abgelehnt
- KI-Zusammenfassung über die produktive Webanwendung
- Kubernetes-Rollouts und Healthchecks
- NetworkPolicy-Tests mit erlaubten und blockierten Verbindungen
- Schreibschutz des Container-Dateisystems
- Secret-Bereitstellung über Azure Key Vault
- Azure-AI-Smoke-Test mit Workload Identity
- Erfassung von Kubernetes-Logs und Metriken in Log Analytics
- KQL-Simulation verschiedener Monitoring-Zustände

## Bekannte Einschränkungen und offene Prüfungen

- Benutzerisolation wurde im SQL-Code überprüft; ein vollständiger Cross-User-Test mit zwei unterschiedlichen Entra-Konten steht noch aus.
- Die KI-Funktion verfügt über grundlegende Schutzmaßnahmen gegen Prompt Injection, aber keine absolute Isolation gegenüber manipulierten Eingaben.
- Die vorbereitete Azure-Monitor-Alarmregel ist noch nicht aktiviert.
- Eine automatisierte externe HTTPS-Verfügbarkeitsüberwachung ist noch nicht eingerichtet.
- Die vorhandenen Healthchecks prüfen nicht sämtliche externen Abhängigkeiten, insbesondere nicht Microsoft Entra ID und Azure AI.
- Vollständige Disaster-Recovery- und Wiederherstellungstests sind nicht nachgewiesen.

## Repository

**GitHub:** https://github.com/TraceWatcher/learningsteps-devsecops

Dieses Repository dokumentiert die technische Umsetzung, Infrastrukturkonfiguration, Sicherheitsmaßnahmen und die Weiterentwicklung der LearningSteps-Anwendung.

## Projektcharakter

LearningSteps ist eine Lern- und Demonstrationsumgebung für Cloud Security und DevSecOps.

Das Projekt verfolgt das Ziel, Sicherheitskonzepte praktisch umzusetzen, ihre Wirksamkeit anhand reproduzierbarer Tests zu überprüfen und verbleibende Risiken nachvollziehbar zu dokumentieren.

Die erfolgreiche Bereitstellung und die bestandenen automatisierten Tests sind keine Garantie für vollständige Produktionssicherheit.