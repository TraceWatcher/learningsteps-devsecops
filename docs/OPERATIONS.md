# LearningSteps – Operations Runbook

## 1. Zweck

Dieses Dokument beschreibt den Betrieb, die Überwachung, die Wartung und die kontrollierte Bereinigung der LearningSteps-Infrastruktur auf Microsoft Azure.

Es richtet sich an Personen, die die Umgebung administrieren oder technische Probleme untersuchen möchten.

Die zugrunde liegende Architektur ist in [ARCHITECTURE.md](ARCHITECTURE.md), die Sicherheitsmaßnahmen in [SECURITY.md](SECURITY.md) und die Testergebnisse in [TESTING.md](TESTING.md) beschrieben.

**Stand:** 20. November 2026

Die beschriebenen Prüfkommandos sind grundsätzlich lesend. Zustandsverändernde Maßnahmen sind gesondert gekennzeichnet und dürfen nur nach Prüfung ihrer Auswirkungen ausgeführt werden.

## 2. Infrastrukturübersicht

| Komponente | Bezeichnung |
|---|---|
| Anwendungs-Resource-Group | `rg-learningsteps-devsecops` |
| Terraform-State-Resource-Group | `rg-learningsteps-tfstate` |
| AKS | `aks-learningsteps` |
| Kubernetes-Namespace | `learningsteps` |
| Azure Container Registry | `acrlearningstepsbff17e9a` |
| PostgreSQL | `psql-learningsteps-305c3ba6` |
| Azure Key Vault | `kv-lsteps-305c3ba6` |
| Azure AI | `oai-learningsteps-305c3ba6` |
| Log Analytics | `log-learningsteps` |
| Terraform-Verzeichnis | `infra-terraform/` |
| Kubernetes-Manifeste | `k8s-manifests/` |

Der öffentliche Anwendungshost ist am HTTPS-Listener des Gateways
konfiguriert. Im aktuellen AKS-Kontext lässt er sich abfragen.

```bash
HOST=$(kubectl -n learningsteps get gateway learningsteps-gateway \
  -o jsonpath='{.spec.listeners[?(@.name=="https")].hostname}')
test -n "$HOST" && printf 'https://%s\n' "$HOST"
```

Bei einem AKS-Rebuild kann sich die zugewiesene Standarddomain ändern.
Für den Start-Healthcheck liest GitHub Actions die HTTPS-Adresse aus
`OPERATIONS_APP_URL` im Environment `production-operations`. Nach einem
Rebuild den Wert mit der bereitgestellten HTTPRoute abgleichen und
gezielt aktualisieren.
[Adresse nach dem Rebuild synchronisieren](RECOVERY.md#d3-aks-default-domain-ermitteln)

## 3. Administratorzugang

Die bisherigen Administrationsarbeiten wurden überwiegend vom System `tracemanager` ausgeführt.

Benötigte Werkzeuge:

- Azure CLI
- Terraform
- kubectl
- Git
- jq
- Python und weitere projektabhängige Testwerkzeuge

### Azure-Kontext prüfen

```bash
az account show \
  --query '{Name:name,Subscription:id,Tenant:tenantId}' \
  -o table
```

Vor Änderungen muss sichergestellt werden, dass die richtige Azure-Subscription ausgewählt ist.

### AKS-Kontext prüfen

```bash
kubectl config current-context
kubectl cluster-info
kubectl get nodes
```

Ein vorhandener Kubernetes-Kontext ist kein Nachweis, dass er auf den beabsichtigten Cluster zeigt.

## 4. Regelmäßige Gesundheitsprüfungen

### Kubernetes-Workloads

```bash
kubectl get deployments -n learningsteps
kubectl get pods -n learningsteps -o wide
kubectl get services -n learningsteps
kubectl get hpa -n learningsteps
```

Wichtige Prüfkriterien:

- API- und Web-Deployments besitzen bereite Replikate.
- Pods befinden sich im erwarteten Betriebszustand.
- Keine unerwarteten Neustarts oder CrashLoops.
- Die Gateway-Routen sind weiterhin verfügbar.

### Rollout-Status

```bash
kubectl rollout status deployment/learningsteps-api \
  -n learningsteps --timeout=120s

kubectl rollout status deployment/learningsteps-web \
  -n learningsteps --timeout=120s
```

### Externer Healthcheck

Den `HOST` wie in der [Infrastrukturübersicht](#2-infrastrukturübersicht)
aus dem HTTPS-Listener ermitteln und aus dem Repository-Stamm prüfen.

```bash
APP_URL="https://$HOST" bash scripts/check-operations-health.sh
```

Der öffentliche API-Pfad ist `/api/health/ready`. Der Check verlangt
HTTP 200, `Content-Type: application/json` und die JSON-Felder
`status=ready` und `database=connected`. Die API prüft dafür PostgreSQL
mit `SELECT 1`. Der interne Pfad `/health/ready` wird am öffentlichen
Gateway der Web-Route zugeordnet und kann HTML liefern. Das Skript prüft
außerdem das Frontend und die Ablehnung eines API-Zugriffs ohne Anmeldung.

Die Workflow-Prüfung unterscheidet DNS- und TLS-Fehler, unerwartete
HTTP-Statuscodes, Content-Types und JSON-Antworten. Bei einem DNS-Fehler
zuerst `OPERATIONS_APP_URL` mit dem Host der aktuellen HTTPRoute vergleichen.
Die Variable enthält ausschließlich den öffentlichen HTTPS-Origin der
LearningSteps-AKS-Standarddomain, ohne Pfad oder Zugangsdaten. Eine
fehlende oder syntaktisch ungültige Adresse blockiert `start` vor dem
Azure-Login.

### Kubernetes-Probes

Die API verwendet:

| Probe | Pfad | Intervall |
|---|---|---|
| Startup | `/health/live` | 5 Sekunden |
| Readiness | `/health/ready` | 15 Sekunden |
| Liveness | `/health/live` | 20 Sekunden |

Eine dauerhaft fehlschlagende Readiness-Probe führt dazu, dass Kubernetes den Pod nicht mehr als bereit betrachtet.

## 5. Logs und Fehlerdiagnose

### API-Logs

```bash
kubectl logs \
  -n learningsteps \
  deployment/learningsteps-api \
  -c api \
  --tail=100
```

### Web-Logs

```bash
kubectl logs \
  -n learningsteps \
  deployment/learningsteps-web \
  -c web \
  --tail=100
```

### Pod-Details

```bash
kubectl describe deployment learningsteps-api \
  -n learningsteps

kubectl get pods -n learningsteps -o wide
```

### Häufige Fehlerszenarien

| Symptom | Erste Prüfung |
|---|---|
| HTTP 502 oder 503 | Gateway, API-Pods und Readiness |
| API nicht bereit | PostgreSQL-Verbindung und API-Logs |
| HTTP 401 | Fehlendes oder ungültiges Zugriffstoken |
| HTTP 403 | Tokenberechtigungen und Scopes |
| KI-Zusammenfassung HTTP 404 | Feature-Flag und API-Routing |
| KI-Zusammenfassung HTTP 502 | Azure-AI-Anbindung und API-Logs |
| Pod startet wiederholt | `kubectl describe pod`, Container-Logs und Ressourcenlimits |
| Secret nicht verfügbar | CSI-Mount, Workload Identity und Key-Vault-Zugriff |

Zugangstokens, Secret-Werte und vollständige Datenbankverbindungsinformationen dürfen nicht in Tickets oder öffentliche Logs übernommen werden.

## 6. Azure Monitor und Log Analytics

Die AKS-Überwachung verwendet Azure Monitor und Container Insights.

Die zentrale Speicherung erfolgt im Workspace `log-learningsteps`.

Erfasste Datenströme:

- `ContainerLogV2`
- `KubePodInventory`
- `InsightsMetrics`

### Workspace-ID ermitteln

```bash
WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group rg-learningsteps-devsecops \
  --workspace-name log-learningsteps \
  --query customerId \
  -o tsv)
```

### Aktuelle API-Logs prüfen

```bash
az monitor log-analytics query \
  --workspace "$WORKSPACE_ID" \
  --analytics-query '
    ContainerLogV2
    | where PodNamespace == "learningsteps"
    | where PodName startswith "learningsteps-api-"
    | project TimeGenerated, PodName, LogMessage
    | order by TimeGenerated desc
    | take 20
  ' \
  --timespan PT1H \
  -o table
```

### Monitoring-Einschränkungen

Die vorhandene Terraform-Konfiguration enthält einen vorbereiteten Log-Analytics-Alert.

Dieser Alert ist deaktiviert und bisher nicht in Azure bereitgestellt.

Eine automatische externe HTTPS-Verfügbarkeitsüberwachung und produktive Benachrichtigungen sind noch nicht eingerichtet.

Die erfolgreiche Erfassung von Telemetrie darf nicht mit einer aktiven Alarmierung gleichgesetzt werden.

## 7. Terraform-Betrieb

Die Azure-Infrastruktur wird überwiegend mit Terraform verwaltet.

### Terraform-Verzeichnis

```bash
cd ~/projects/learningsteps/infra-terraform
```

### Konfiguration prüfen

```bash
terraform fmt -check
terraform validate
```

### Änderungen vorbereiten

```bash
terraform plan
```

Vor einem späteren `terraform apply` müssen sämtliche geplanten Änderungen geprüft werden.

Besondere Aufmerksamkeit gilt:

- AKS-Cluster und Node Pools
- PostgreSQL-Server und Datenbank
- Key Vault und Secrets
- Private Endpoints
- Azure-RBAC-Zuweisungen
- Data Collection Rules
- Terraform-seitigen Ressourcenersetzungen

**Ein erfolgreiches `terraform validate` beweist nicht, dass ein Terraform-Plan keine gefährlichen Änderungen enthält.**

### Terraform-Plan-Dateien

Gespeicherte Terraform-Pläne können sensible Werte enthalten.

Sie dürfen nicht unkontrolliert in Git, Artefakt-Repositories oder öffentliche Dokumentationen übernommen werden.

## 8. Terraform Remote State

Der Terraform-State liegt in einem separaten Azure Storage Account:

- Resource Group: `rg-learningsteps-tfstate`
- Storage Account: `stlearningsteps6f83874f`
- Container: `tfstate`
- Blob: `learningsteps.terraform.tfstate`

Die Backend-Authentifizierung erfolgt über Microsoft Entra ID.

### Aktuelle Schutzmaßnahmen

- HTTPS-Zwang und Mindest-TLS-Version 1.2
- Microsoft-Entra-basierte Backend-Authentifizierung
- Shared-Key-Authentifizierung deaktiviert
- Anonymer öffentlicher Blob-Zugriff deaktiviert
- Blob Soft Delete mit sieben Tagen Aufbewahrung
- Blob-Versionierung aktiviert
- Lifecycle-Policy `delete-old-tfstate-versions` aktiv
- Frühere Versionen des Blobs `tfstate/learningsteps.terraform.tfstate` werden nach mehr als 90 Tagen automatisch gelöscht
- Die aktuelle Blob-Version ist von der Lifecycle-Löschaktion ausgenommen

Die erfolgreiche Erreichbarkeit des Remote-States wurde nach der Deaktivierung der Shared-Key-Authentifizierung erneut bestätigt.

Die Lifecycle-Policy ist keine unabhängige Datensicherung. Ein praktischer Restore-Test steht weiterhin aus.

### State-Zugriff prüfen

```bash
terraform state list
```

Das Anzeigen der Ressourcenliste ist eine lesende Prüfung.

**Terraform-State-Inhalte dürfen nicht öffentlich ausgegeben oder in Git gespeichert werden.**

### Wiederherstellung

Das separate Remote-Backend blieb beim kontrollierten Infrastruktur-Rebuild
vom 23.11.2026 erhalten. Die Wiederherstellung einer früheren State-Version
bleibt ein eigener, noch offener Test.
[Recovery-Ergebnis](RECOVERY.md#111-infrastruktur)

Ein Restore darf nicht allein anhand des Datums einer älteren Version durchgeführt werden. Der wiederhergestellte State muss zur tatsächlichen Infrastruktur passen.

Vor einem Restore sind die betroffenen Ressourcen, der aktuelle State und mögliche parallele Terraform-Prozesse zu prüfen.

## 9. Anwendung aktualisieren

Die Anwendung verwendet Container-Images aus Azure Container Registry.

Der tagbasierte [Release-Workflow](../.github/workflows/release.yml) automatisiert
den Build, die Prüfung und die Veröffentlichung des API-Images in ACR.

### API-Release

Nach erfolgreicher Prüfung veröffentlicht der Workflow das API-Image in
Azure Container Registry. Der nachgelagerte Schritt **Deploy to AKS** läuft
bei `ENABLE_AKS_AUTO_DEPLOY=true`. Er setzt den Image-Tag im API-Manifest,
wendet ConfigMap, Deployment und HPA über `az aks command invoke` an und
prüft den Rollout sowie den Exit-Code von Run Command.

Der Schalter ist im GitHub-Environment `production` konfiguriert. Bei der
lesenden Prüfung am 24.11.2026 war er deaktiviert. Ein erfolgreicher Image-Push
belegt die Veröffentlichung in ACR. Für einen AKS-Rollout ist das Ergebnis des
Deployment-Schritts maßgeblich. Der frühere Release-Test `v0.7.0` belegt den
Pfad mit damals aktiviertem Schalter. [Historischer Release-Test](TESTING.md#ci-05--automatisiertes-azure-deployment)

### Deployment überprüfen

```bash
kubectl rollout status deployment/learningsteps-api \
  -n learningsteps --timeout=180s

kubectl get pods -n learningsteps

kubectl get hpa -n learningsteps
```

Anschließend den [externen Healthcheck](#externer-healthcheck) ausführen.

### Frontend-Deployment

Das Frontend verwendet das Kubernetes-Deployment `learningsteps-web` mit dem Container `web`.

Der Rollout-Status lässt sich wie folgt überprüfen:

```bash
kubectl rollout status deployment/learningsteps-web \
  -n learningsteps --timeout=120s
```

Ein automatisierter Frontend-Release-Prozess ist durch die bisher geprüfte GitHub-Actions-Konfiguration nicht nachgewiesen.

### Rollback

Kubernetes unterstützt die Rückkehr zu einer vorherigen Deployment-Revision, sofern eine geeignete Revision noch vorhanden ist.

Vor einem Rollback:

- Ursache des Fehlers untersuchen
- Verfügbare Deployment-Revisionshistorie prüfen
- Image-Versionen und Konfigurationsänderungen berücksichtigen
- Datenbankkompatibilität bewerten

Die Revisionshistorie kann lesend geprüft werden:

```bash
kubectl rollout history deployment/learningsteps-api \
  -n learningsteps
```

Ein Rollback wird nicht automatisch durch die bisher geprüfte Release-Pipeline ausgelöst.

**Wichtig:** Ein Kubernetes-Deployment-Rollback stellt weder Datenbankdaten noch Terraform-Infrastrukturänderungen wieder her.

Ein automatisierter Rollback-Prozess wurde bisher nicht implementiert oder getestet.

**Image-Versionierung und Rollback:**

Die Release-Pipeline verwendet `github.ref_name` als Docker-Image-Tag.

Die Verwendung eines Git-Ref-Namens garantiert allein keine unveränderliche Image-Version. Für eine reproduzierbare Wiederherstellung sollten die tatsächlich verwendeten Image-Digests oder eindeutig zuordenbare, geschützte Release-Tags dokumentiert werden.

Ein automatischer Rollback ist nicht implementiert.

Bei einem fehlgeschlagenen Deployment beendet die Pipeline den AKS-Deployment-Schritt mit einem Fehler. Die vorherige Anwendungsversion wird dadurch nicht automatisch wiederhergestellt.

## 10. Secret Management und Rotation

Produktive Zugangsdaten werden über Azure Key Vault verwaltet und vom Secrets Store CSI Driver bereitgestellt.

Die Anwendung verwendet unter anderem die Datei:

`/mnt/secrets/postgres-admin-password`

Ein Passwortwechsel benötigt einen abgestimmten Ablauf zwischen PostgreSQL, Key Vault und den verwendenden Workloads.

Vor einer Rotation sollten folgende Punkte geprüft werden:

- Neue Zugangsdaten sind korrekt hinterlegt.
- Die Anwendung erhält die aktualisierten Secret-Daten.
- Bestehende Datenbankverbindungen werden berücksichtigt.
- Ein Rückfallverfahren ist vorhanden.
- Die API-Readiness bleibt nach dem Wechsel erfolgreich.

Eine automatisierte Rotation ist nicht als getestet dokumentiert.

## 11. Backup und Wiederherstellung

### PostgreSQL

Der PostgreSQL Flexible Server verwendet eine konfigurierte Backup-Aufbewahrung von sieben Tagen.

Diese Einstellung ist kein Nachweis für einen erfolgreichen Wiederherstellungstest.

### Wartungs-Backup-Storage

Der private Storage Account `stlstepsbackup305c3ba6` dient Wartungs- und Migrationsaufgaben.

Schutzmaßnahmen:

- Öffentlicher Netzwerkzugriff deaktiviert
- Private Endpoint
- Shared-Key-Authentifizierung deaktiviert
- TLS 1.2 und HTTPS
- Blob- und Container-Löschaufbewahrung von sieben Tagen

Die Speicherung erfolgt mit LRS.

### Wiederherstellungsstatus

Am 23.11.2026 wurde das verschlüsselte PostgreSQL-Backup auf dem neu
bereitgestellten Server eingespielt. Der Test bestätigte vier
wiederhergestellte Datensätze, Constraints und Indizes sowie den Zugriff
der Anwendung auf das DB-Secret über Key Vault CSI. Die vollständige
Anwendungsregression nach dem Restore und belastbare Aussagen zur
Wiederherstellungszeit bleiben offen.
[PostgreSQL-Restore und Verifikation](RECOVERY.md#112-postgresql-und-key-vault)

## 12. Kostenkontrolle

Die LearningSteps-Umgebung verursacht laufende Azure-Kosten, insbesondere durch:

- AKS-Worker-Nodes
- PostgreSQL Flexible Server
- Storage und Backups
- Azure Monitor und Log Analytics
- Azure AI
- Netzwerk- und zusätzliche Azure-Ressourcen

### Aktuelle Kosten prüfen

```bash
az account show \
  --query '{Subscription:name,Id:id}' \
  -o table
```

Die konkrete Kostenanalyse erfolgt anschließend über Azure Cost Management beziehungsweise vorhandene Budget- und Kostenberichte.

### Kostenrelevante Konfiguration

Der Log-Analytics-Workspace besitzt ein tägliches Datenaufnahmelimit von 0,1 GB.

Dieses Limit ist kein vollständiges Ausgabenlimit für die Azure-Umgebung.

### Empfehlungen

- Nicht benötigte Test-Jobs entfernen.
- Unbenutzte Ressourcen identifizieren.
- Nicht erforderliche zusätzliche Testcluster vermeiden.
- Alte Container-Images und gespeicherte Artefakte regelmäßig bewerten.
- Azure-AI-Aufrufe und deren Kosten beobachten.
- Vor jeder kostenintensiven Erweiterung einen Terraform-Plan und eine Kostenschätzung prüfen.

## 13. Kontrolliertes Herunterfahren

Ein vollständiger Shutdown ist nicht mit dem Stoppen eines einzelnen Containers gleichzusetzen.

Insbesondere können AKS, PostgreSQL, Storage, Log Analytics und andere Azure-Dienste weiterhin Kosten erzeugen.

### Vorbereitende Bestandsaufnahme

```bash
az resource list \
  --resource-group rg-learningsteps-devsecops \
  --query '[].{Name:name,Type:type}' \
  -o table
```

Danach die benötigten Daten und Ressourcen klassifizieren.

Wichtig sind insbesondere:

- PostgreSQL-Daten
- Key-Vault-Secrets
- Container-Images
- Backup-Daten
- Terraform-State
- Ressourcenabhängigkeiten

### Sicherheitsanforderungen

Vor einer Bereinigung:

1. Sicherstellen, dass keine relevanten Daten mehr benötigt werden.
2. Vorhandene Backups und deren Wiederherstellbarkeit bewerten.
3. Terraform-State und Ziel-Subscription überprüfen.
4. Abhängigkeiten und gemeinsam genutzte Ressourcen identifizieren.
5. Einen vollständigen Terraform-Destroy-Plan prüfen.
6. Nur ausdrücklich freigegebene Ressourcen entfernen.
7. Verbleibende Ressourcen und laufende Kosten kontrollieren.

Die Resource Group `rg-learningsteps-tfstate` darf nicht versehentlich mit der Anwendungsumgebung gelöscht werden.

**In diesem Runbook wird bewusst kein pauschaler `terraform destroy`- oder `az group delete`-Befehl als Standardverfahren angegeben.**

Ein tatsächlich durchgeführter vollständiger Cleanup ist bisher nicht dokumentiert.

## 14. Incident Response – Vorgehensweise

Bei einer vermuteten Sicherheitsstörung sollte zunächst der Zustand erfasst und nachvollziehbar dokumentiert werden.

### Erste Schritte

1. Art und Zeitpunkt der Auffälligkeit festhalten.
2. Betroffene Workloads bestimmen.
3. Aktuelle Pod- und Deployment-Zustände erfassen.
4. Relevante Logs sichern.
5. Azure-Aktivitätsprotokolle prüfen.
6. Auswirkungen auf Identitäten, Secrets und Daten bewerten.
7. Notwendige Eindämmungsmaßnahmen gezielt planen.

### Mögliche Sicherheitsereignisse

- Unerwartete API-Authentifizierungsfehler
- Verdächtige Zugriffe auf Key Vault
- Ungeplante Infrastrukturänderungen
- Wiederholte Container-Neustarts
- Unerwartete Azure-AI-Nutzung
- Auffällige CI/CD-Ausführungen
- Änderungen an Terraform-State oder RBAC

Sicherheitsrelevante Daten dürfen bei einer Untersuchung nicht unkontrolliert gelöscht oder überschrieben werden.

## 15. Bekannte betriebliche Einschränkungen

- Die Azure-Monitor-Alarmregel ist vorbereitet, aber nicht bereitgestellt.
- Eine automatische Benachrichtigung bei API-Ausfällen fehlt.
- Ein externer automatisierter HTTPS-Test fehlt.
- Der getestete PostgreSQL-Restore deckt den dokumentierten Datenbestand ab. Ein vollständiger Anwendungsregressionstest nach dem Rebuild bleibt offen.
- Der Terraform-State-Storage verwendet bisher keine restriktive Netzwerk-Standardregel.
- Eine unabhängige Sicherung und die praktische Wiederherstellung einer früheren Terraform-State-Version stehen noch aus.
- Die Lifecycle-Policy entfernt frühere Terraform-State-Versionen nach mehr als 90 Tagen; langfristige Aufbewahrung ist damit nicht gewährleistet.
- Ein vollständiger automatisierter Cleanup-Prozess ist nicht dokumentiert.

## 16. Betriebsstatus

LearningSteps wurde erfolgreich auf AKS bereitgestellt und funktional getestet.

Die vorhandene Infrastruktur ermöglicht:

- Authentifizierte Benutzerzugriffe
- Benutzerbezogene Datenbankoperationen
- KI-gestützte Lernzusammenfassungen
- Gesundheitsprüfungen durch Kubernetes
- Zentrale Log- und Metrikerfassung
- Terraform-basierte Infrastrukturverwaltung

Die Umgebung ist als Lern- und Demonstrationsprojekt ausgelegt.

Vor einer produktiven Nutzung wären zusätzliche Arbeiten an automatisierter Alarmierung, Wiederherstellung, Zugriffskontrollen, Kostenüberwachung und Betriebsprozessen erforderlich.
