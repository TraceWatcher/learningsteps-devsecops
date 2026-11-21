# LearningSteps – Infrastructure Recovery Runbook

**Projekt:** LearningSteps DevSecOps on Azure
**Stand:** 21.11.2026
**Status:** Prepared – Full infrastructure recovery not yet executed
**Ziel:** Vollständige Wiederherstellung der LearningSteps-Infrastruktur und Anwendung nach einem kontrollierten Terraform-Destroy.

## 1. Recovery-Ziel und Umfang

Der Recovery-Test soll nachweisen, dass die Terraform-verwaltete Azure-Infrastruktur zerstört und anschließend erneut bereitgestellt werden kann.

Der Nachweis umfasst zusätzlich die Wiederherstellung der Anwendung einschließlich PostgreSQL-Daten, Azure-Identitäten, Container-Images, Kubernetes-Konfiguration und HTTPS-Zugriff.

### Infrastruktur

- Resource Group: `rg-learningsteps-devsecops`
- AKS: `aks-learningsteps`
- ACR: `acrlearningstepsbff17e9a`
- PostgreSQL: `psql-learningsteps-305c3ba6`
- Key Vault: `kv-lsteps-305c3ba6`
- Kubernetes-Namespace: `learningsteps`
- Azure-Region: West Europe

### Geschützte Infrastruktur

Das Terraform-Remote-Backend befindet sich außerhalb der Workload-Resource-Group:

- Resource Group: `rg-learningsteps-tfstate`
- Storage Account: `stlearningsteps6f83874f`
- Container: `tfstate`
- State-Datei: `learningsteps.terraform.tfstate`

**Die Terraform-State-Infrastruktur darf nicht zerstört werden.**

## 2. Bereits verifizierte Voraussetzungen

| Voraussetzung | Ergebnis |
|---|---|
| Terraform-Remote-State erreichbar | PASS |
| CI/CD-Release v0.7.0 | PASS |
| Negativer Terraform-Security-Test | PASS |
| Datenbankschema unter PostgreSQL 16 erstellt | PASS |
| Datenbankmigrationen ausgeführt | PASS |
| Wiederholte Schema-Initialisierung getestet | PASS |
| PostgreSQL-Backup erstellt und entschlüsselt | PASS |
| PostgreSQL-Backup in isolierte Datenbank zurückgespielt | PASS |
| Vier Datensätze wiederhergestellt | PASS |
| Ownership-Constraint getestet | PASS |
| Verschlüsselte Secret-Sicherung per SHA-256 verglichen | PASS |
| Vollständiger Azure-Destroy-/Apply-Test | NOT EXECUTED |

Die Datenbank enthält zum Zeitpunkt der Sicherung vier Einträge, davon einen mit und drei ohne `owner_id`. Die drei historischen Einträge ohne Besitzer bleiben aufgrund der `NOT VALID`-Migration erhalten.

## 3. Recovery-Artefakte

Die folgenden Dateien liegen auf `tracemanager` außerhalb des Git-Repositories:

```text
~/learningsteps-recovery/
├── backup-key.txt
├── learningsteps-20261121-180103.dump.age
└── postgres-admin-password.age
```

Die Dateien enthalten:

- `backup-key.txt`: privaten age-Entschlüsselungsschlüssel
- `*.dump.age`: verschlüsseltes PostgreSQL-Backup im Custom-Format
- `postgres-admin-password.age`: verschlüsseltes Datenbank-Administratorkennwort

**Sicherheitsregeln:**

- Keine Klartextkennwörter in Git, Screenshots oder CI-Logs.
- Verzeichnis mit Berechtigung `700`, Dateien mit `600`.
- Mindestens eine unabhängige, geschützte Zweitkopie vor dem Destroy verifizieren.
- Backup und Entschlüsselungsschlüssel nach Möglichkeit getrennt aufbewahren.
- Terraform-Variablen und Azure-Zugriffsberechtigungen für den Wiederaufbau verfügbar halten.

## 4. Phase A – Preflight

Arbeitsverzeichnis:

```bash
cd ~/projects/learningsteps/infra-terraform
```

### A1. Terraform-State verifizieren

```bash
terraform state list
terraform validate
```

Prüfen, dass das Backend weiterhin auf die separate State-Resource-Group verweist.

### A2. Backup-Dateien prüfen

```bash
ls -lh ~/learningsteps-recovery/

age -d \
  -i ~/learningsteps-recovery/backup-key.txt \
  ~/learningsteps-recovery/learningsteps-20261121-180103.dump.age |
pg_restore --list
```

Vor dem Destroy müssen sowohl die verschlüsselte Datensicherung als auch das Secret-Backup unabhängig gesichert sein.

### A3. Laufende Anwendung dokumentieren

```bash
kubectl get all -n learningsteps
kubectl get gateway,httproute -n learningsteps
kubectl get secretproviderclass -n learningsteps

az aks approuting defaultdomain show \
  --resource-group rg-learningsteps-devsecops \
  --name aks-learningsteps
```

Image-Tags, öffentliche HTTPS-Adresse, DNS-Konfiguration und Workload-Identitäten als Recovery-Referenz sichern.

### A4. Terraform-Destroy-Plan überprüfen

```bash
umask 077

terraform plan -destroy \
  -out=/tmp/learningsteps-destroy.tfplan

terraform show \
  /tmp/learningsteps-destroy.tfplan
```

Vor der Ausführung bestätigen:

- Die State-Resource-Group wird nicht gelöscht.
- Die Löschungen betreffen ausschließlich den vorgesehenen LearningSteps-Stack.
- Keine unerwarteten gemeinsam verwendeten Ressourcen sind enthalten.
- PostgreSQL-Daten und Secret sind unabhängig gesichert.
- Azure-Berechtigungen und benötigte Terraform-Variablen sind vorhanden.

**STOP:** Bei Abweichungen darf der Destroy-Plan nicht ausgeführt werden.

## 5. Phase B – Azure-Infrastruktur wiederherstellen

### B1. Kontrollierter Terraform-Destroy

**Nur nach vollständig bestandener Preflight-Prüfung.**

```bash
terraform apply /tmp/learningsteps-destroy.tfplan
```

Anschließend das Ergebnis und den verbleibenden Terraform-State kontrollieren.

Einige Azure-Ressourcen können nach dem Entfernen weiterhin im Soft-Delete-Zustand existieren.

### B2. Terraform-Apply vorbereiten

```bash
terraform plan \
  -out=/tmp/learningsteps-rebuild.tfplan

terraform show /tmp/learningsteps-rebuild.tfplan
```

Besonders prüfen:

- Key Vault Soft-Delete-Recovery
- PostgreSQL-Neuerstellung
- AKS und ACR
- Private DNS und Private Endpoints
- Managed Identities und Role Assignments
- Eventuelle Namenskonflikte
- Nicht benötigte, vorbereitete Monitoring-Ressourcen

### B3. Infrastruktur erneut bereitstellen

Nach manueller Planfreigabe:

```bash
terraform apply /tmp/learningsteps-rebuild.tfplan
```

Das Apply-Ergebnis prüfen. Ein erfolgreicher Terraform-Apply ist noch kein Beweis für vollständige Anwendungswiederherstellung.

## 6. Phase C – Identitäten und Key Vault

### C1. Neue Client-IDs ermitteln

```bash
terraform output -raw github_actions_client_id
terraform output -raw learningsteps_api_client_id
```

### C2. GitHub-OIDC aktualisieren

```bash
terraform output -raw github_actions_client_id |
gh variable set AZURE_CLIENT_ID \
  --repo TraceWatcher/learningsteps-devsecops \
  --env production
```

Anschließend den OIDC-Login mit einer dafür vorgesehenen nichtdestruktiven Prüfung validieren.

### C3. Kubernetes Workload Identity

Die Client-ID aus `learningsteps_api_client_id` muss in folgenden Konfigurationen aktualisiert werden:

- `k8s-manifests/serviceaccount.yaml`
- `k8s-manifests/secretproviderclass.yaml`

Anschließend müssen die neuen Managed-Identity-Berechtigungen und Federated Identity Credentials wirksam sein.

### C4. Key Vault validieren

Terraform ist für folgende Provider-Features konfiguriert:

```hcl
key_vault {
  purge_soft_delete_on_destroy    = false
  recover_soft_deleted_key_vaults = true
}
```

Nach dem Apply prüfen:

- Vault wiederhergestellt beziehungsweise verfügbar
- Private Endpoint und DNS funktionieren
- `postgres-admin-password` vorhanden
- Workload Identity kann das Secret lesen
- Secret stimmt mit dem verwendeten PostgreSQL-Administratorkennwort überein

Falls das Secret nicht wiederhergestellt wurde, steht die verschlüsselte Sicherung als Fallback zur Verfügung. Das Zurückschreiben muss über einen autorisierten privaten Zugangsweg erfolgen.

**STOP:** PostgreSQL-Dump und API dürfen erst mit nachweislich korrektem Datenbankkennwort verwendet werden.

## 7. Phase D – Container Registry und AKS

### D1. ACR wiederherstellen

Den tatsächlich bereitgestellten Registry-Namen und Login-Server überprüfen.

API- und Web-Images müssen erneut bereitgestellt werden:

- API: `learningsteps-api:v0.7.0`
- Web: `learningsteps-web:v0.6.0`

Die API wird aus der passenden Release-Version mit `APP_VERSION=v0.7.0` gebaut.

Das Frontend wird aus dem zugehörigen, nachvollziehbaren Quellstand gebaut.

Der ACR-Name ist derzeit in Kubernetes-Manifests und GitHub Actions fest hinterlegt. Bei einem veränderten Registry-Namen müssen diese Referenzen angepasst werden.

### D2. AKS-Grundkonfiguration

Vor dem Anwendungsdeployment müssen folgende Objekte verfügbar sein:

1. Namespace `learningsteps`
2. ServiceAccount mit aktueller Client-ID
3. SecretProviderClass
4. Anwendungskonfiguration und Services
5. PostgreSQL-Zugriff und erforderliche Netzwerkverbindungen
6. API- und Web-Deployments
7. HorizontalPodAutoscaler und NetworkPolicies
8. Gateway, HTTPRoute und TLS-Zertifikat

Dabei sind Abhängigkeiten und Kubernetes-Readiness zu beachten. Der bestehende API-Release-Workflow ersetzt keinen vollständigen Cluster-Bootstrap.

### D3. AKS Default Domain ermitteln

```bash
az aks approuting defaultdomain show \
  --resource-group rg-learningsteps-devsecops \
  --name aks-learningsteps \
  -o json
```

Den neu zugewiesenen Hostnamen in Gateway und HTTPRoute übernehmen.

Die neue HTTPS-Adresse gegebenenfalls als Redirect-URI in der Microsoft-Entra-App-Registrierung ergänzen.

Das Frontend verwendet `window.location.origin`, sodass keine statische Redirect-Adresse im JavaScript geändert werden muss.

## 8. Phase E – PostgreSQL-Daten wiederherstellen

Das vorhandene Backup wurde erfolgreich mit PostgreSQL 16 getestet.

Für den Restore wird ein temporärer PostgreSQL-Client-Pod mit Zugang zur neuen privaten Datenbank und zur Key-Vault-Secret-Datei benötigt.

Das Backup wird auf `tracemanager` entschlüsselt und über einen Datenstrom an den Client-Pod übertragen.

**Wichtig:** Der vollständige Custom-Format-Dump enthält Schema und Daten.

Daher auf einer frischen, leeren Datenbank entweder:

- den vollständigen Dump mit `pg_restore` wiederherstellen, **oder**
- Schema und Migrationen separat initialisieren, wenn ein Daten-only-Restore verwendet wird.

Nicht beide Verfahren unkontrolliert kombinieren.

Nach dem Restore prüfen:

```sql
SELECT COUNT(*) FROM public.entries;

SELECT
  COUNT(*) AS total_entries,
  COUNT(owner_id) AS owned_entries,
  COUNT(*) - COUNT(owner_id) AS unassigned_entries
FROM public.entries;
```

Zusätzlich Tabellenstruktur, Indizes und Ownership-Constraint kontrollieren.

Die bekannte Sicherung enthält vier Einträge. Diese Anzahl ist der Ausgangswert des getesteten Backups, nicht notwendigerweise der aktuelle Datenbestand zum späteren Destroy-Zeitpunkt.

## 9. Phase F – Anwendung validieren

Nach dem Kubernetes-Bootstrap sind folgende Nachweise erforderlich:

| Prüfung | Erwartetes Ergebnis |
|---|---|
| AKS-Nodes und Pods | Ready |
| API-Deployment | Available |
| Web-Deployment | Available |
| Gateway | Programmed=True |
| HTTPS | Gültige Verbindung |
| `/api/health/live` | HTTP 200 |
| `/api/health/ready` | HTTP 200 |
| `/api/health/version` | Gewünschte Release-Version |
| Entra-Anmeldung | Erfolgreich |
| Journaleinträge lesen | Erfolgreich |
| Journaleintrag erstellen und bearbeiten | Erfolgreich |
| Ownership-Schutz | Funktioniert |
| KI-Zusammenfassung | Funktioniert |
| Azure-Monitor-Telemetrie | Erneut vorhanden |

## 10. Evidence und Abschluss

Für die Abgabe sollten folgende Screenshots und Protokolle vorliegen:

- Terraform-Destroy-Plan
- Erfolgreicher Terraform-Destroy
- Terraform-Apply-Plan
- Erfolgreicher Terraform-Apply
- Neu erstellte AKS-/ACR-/PostgreSQL-Ressourcen
- Erfolgreicher Kubernetes-Rollout
- PostgreSQL-Restore und vier wiederhergestellte Einträge
- Öffentliche HTTPS-Anwendung mit erfolgreicher Funktionsprüfung

### Abschließende Bewertung

Der Infrastructure-Recovery-Test gilt erst als **PASS**, wenn die Terraform-Infrastruktur erfolgreich neu bereitgestellt wurde und die Anwendung nach Wiederherstellung aller Abhängigkeiten erneut funktioniert.

**Aktueller Status: NOT EXECUTED.**

Das getestete PostgreSQL-Backup und die geprüfte verschlüsselte Secret-Sicherung dienen als Ausgangspunkt für den kontrollierten Wiederaufbau.