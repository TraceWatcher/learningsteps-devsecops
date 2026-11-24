# LearningSteps – Infrastructure Recovery Runbook

**Projekt:** LearningSteps DevSecOps on Azure
**Recovery-Testdatum:** 23.11.2026
**Status:** PASS für den kontrollierten Terraform-Rebuild, PostgreSQL-Restore
und den funktionalen Wiederanlauf am 23.11.2026.
**Ziel:** Infrastruktur und Anwendung nach einem kontrollierten
Terraform-Destroy wiederherstellen und die getesteten Funktionen belegen.

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
| Historischer CI/CD-Release v0.7.0 | PASS bei damals aktiviertem AKS-Deployment |
| Negativer Terraform-Security-Test | PASS |
| Datenbankschema unter PostgreSQL 16 erstellt | PASS |
| Datenbankmigrationen ausgeführt | PASS |
| Wiederholte Schema-Initialisierung getestet | PASS |
| PostgreSQL-Backup erstellt und entschlüsselt | PASS |
| PostgreSQL-Backup in isolierte Datenbank zurückgespielt | PASS |
| Vier Datensätze wiederhergestellt | PASS |
| Ownership-Constraint getestet | PASS |
| Verschlüsselte Secret-Sicherung per SHA-256 verglichen | PASS |
| Kontrollierter Azure-Destroy-/Apply-Test | PASS – 23.11.2026, separates Terraform-Backend blieb erhalten |

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
terraform output -raw github_operations_client_id
terraform output -raw github_operations_tenant_id
terraform output -raw github_operations_postgres_server_name
terraform output -raw learningsteps_api_client_id
```

### C2. GitHub-OIDC aktualisieren

Nach erfolgreicher Infrastruktur-Neuerstellung diesen Schritt aus dem
Repository-Stamm ausführen. Das aktive Azure-Konto benötigt Leserechte auf die
Managed Identity, die Federated Credentials, ACR, AKS und Azure RBAC.
Die GitHub-CLI benötigt Leserechte für die OIDC-Konfiguration und die
Variablen des Environments `production`. Für die anschließende Synchronisierung
benötigt sie zudem Schreibrechte für diese Variablen.

```bash
bash scripts/sync-github-azure-identity.sh --check
```

| Exit-Code | Bedeutung von `--check` |
| --- | --- |
| `0` | Die geprüfte Konfiguration ist gültig und `AZURE_CLIENT_ID` ist aktuell. |
| `1` | Eine Abweichung wurde erkannt. Die Meldung nennt die betroffene Prüfung. |
| `2` | Die Prüfung konnte wegen eines technischen Fehlers nicht abgeschlossen werden, etwa wegen fehlender Berechtigungen oder einer unvollständigen API-Antwort. |

`--check` arbeitet ausschließlich lesend. Das Skript prüft die vorhandene
ID-basierte Federated Credential, den mit `AcrPush` kompatiblen ACR-RBAC-Modus
und die durch Terraform vorgesehenen direkten Zuweisungen für `AcrPush` auf
der Release-Registry und für die AKS-Custom-Rolle am Cluster. Fehlende direkte
Zuweisungen sind eine Konfigurationsabweichung.
Sichtbare geerbte Zuweisungen werden gesondert gemeldet. Die vollständige
effektive Autorisierung kann zusätzlich von Gruppenmitgliedschaften, Bedingungen,
Deny Assignments und der Replikation in Azure abhängen.

Meldet `--check` ausschließlich eine veraltete oder fehlende `AZURE_CLIENT_ID`,
die Synchronisierung vor dem nächsten GitHub-Release ausdrücklich ausführen.
Das Skript wiederholt die Vorprüfungen, aktualisiert bei Bedarf ausschließlich
`AZURE_CLIENT_ID` in `production` und liest den gespeicherten Wert zur Bestätigung
zurück. Bei einer anderen Abweichung oder einem technischen Fehler zuerst die
gemeldete Ursache klären.

```bash
bash scripts/sync-github-azure-identity.sh
```

Bei einem Fehler während des Schreibens oder Rücklesens den tatsächlich
gespeicherten Wert erneut mit `--check` prüfen. Die Synchronisierung ist ein
expliziter Schritt nach dem Provisioning.

Nach dem AKS-Bootstrap kann der manuelle Workflow
[LearningSteps Azure OIDC Test](../.github/workflows/oidc-test.yml) auf einem
zulässigen vorhandenen `v`-Tag den OIDC-Login und den lesenden AKS-Zugriff
prüfen. Der Test erwartet ein vorhandenes API-Deployment im Namespace
`learningsteps`.

#### Environment Control nach Review freischalten

Die Operations-Identity `id-learningsteps-github-operations` verwendet
`production-operations` als OIDC-Kontext. Terraform stellt dafür die
Federated Credential, die Custom Role und ausschließlich die drei direkten
Zuweisungen an AKS, PostgreSQL Flexible Server und Maintenance-VM bereit.
Der bestehende C2-Aufruf synchronisiert die Release-Identity in `production`.

1. Nach Code-Review den Terraform-Plan prüfen. Für diese Einführung sind
   sechs neue Azure-Ressourcen und die drei neuen Terraform-Outputs erwartet.
   Änderungen oder Ersetzungen der Release-Identität, ihrer Federation
   oder ihrer Rollenzuweisungen blockieren die Freigabe.
2. In GitHub unter **Settings → Environments** `production-operations`
   manuell anlegen. Unter **Selected branches and tags** genau eine
   **Branch**-Regel mit `main` und keine Tag-Regeln konfigurieren.
   Unter **Required reviewers** ausschließlich den Benutzer `TraceWatcher`
   (User-ID `292215891`) eintragen und **Prevent self-review** deaktivieren.
   So kann `TraceWatcher` einen selbst ausgelösten Lauf manuell freigeben.
   Die Reviewer-Freigabe bleibt auch in der Einzelentwickler-Konfiguration
   erforderlich. Wenn der GitHub-Plan Required Reviewers nicht unterstützt,
   bleibt Environment Control deaktiviert.
   In der GitHub-Oberfläche zusätzlich **Allow administrators to bypass
   configured protection rules** deaktivieren. Die Environment-API liefert
   diese Einstellung als `can_admins_bypass: false`.
   Erst nach Prüfung dieser Konfiguration das separat freigegebene
   Terraform-Provisioning mit der neuen Federated Credential ausführen.
3. In diesem Environment `AZURE_TENANT_ID` aus
   `github_operations_tenant_id`, `AZURE_SUBSCRIPTION_ID` aus der für
   Terraform verwendeten Subscription und `POSTGRES_SERVER_NAME` aus
   `github_operations_postgres_server_name` setzen. Auf Repository- oder
   Organisationsebene keine Ersatzwerte für diese Operations-Konfiguration
   bereitstellen. Die Client-ID wird über die getrennte Synchronisierung
   aus der Operations-Identity ermittelt.
4. Nach Provisioning und RBAC-Replikation aus dem Repository-Stamm prüfen
   und bei ausschließlich fehlender oder veralteter Client-ID synchronisieren.
   Tenant, Subscription und PostgreSQL-Name vor jedem Rebuild-Abgleich
   anhand der aktuellen Infrastruktur prüfen.

   ```bash
   bash scripts/sync-github-azure-identity.sh --operations --check
   bash scripts/sync-github-azure-identity.sh --operations
   bash scripts/sync-github-azure-identity.sh --operations --check
   ```

   Der Operations-Modus prüft zusätzlich die unten aufgeführten
   REST-sichtbaren Environment-Einstellungen,
   die einzige erwartete Federated Credential, die exakten acht Aktionen
   der Custom Role und die Rollenzuweisungen für die Operations-Identity
   in der Subscription sowie an übergeordneten Scopes. Die
   `roleDefinitionId` der Zuweisungen wird einschließlich Subscription und
   ARM-Pfad mit der erwarteten Rollendefinition abgeglichen.
   Die Vorprüfungen benötigen Azure-RBAC-Leserechte auf Subscription-Ebene
   und GitHub-Leserechte für die Environment-Schutzregeln und -Variablen.

5. Als letzten Schritt die Repository-Variable `OPERATIONS_ENVIRONMENT_ID`
   mit der ID des eingerichteten Environments setzen (aktuell `28365573053`).
   Die folgende Abfrage
   prüft den Environment-Namen, eine gültige ID und, sofern übergeben, die
   erwartete ID. Sie verlangt benutzerdefinierte Branch-Regeln mit genau
   einer Regel vom Typ `branch` für `main`. Außerdem prüft sie genau eine
   Required-Reviewers-Regel mit genau einem User-Eintrag für `TraceWatcher`
   (ID `292215891`), `prevent_self_review: false` und
   `can_admins_bypass: false`. Fehlende Einstellungen blockieren die
   Synchronisierung und den Workflow.

   ```bash
   bash scripts/check-operations-environment.sh TraceWatcher/learningsteps-devsecops
   ```

   Vor dem Löschen oder Umkonfigurieren des Environments die Aktivierungsvariable
   entfernen und laufende oder wartende Operations-Runs beenden lassen oder
   abbrechen. Vor einer Löschung oder Abschwächung der Schutzregeln zuerst
   auch die Operations-Federation in Azure separat deaktivieren. Der
   OIDC-Subject ist an den Environment-Namen gebunden.
   GitHub prüft die Environment-Existenz nicht atomar mit der
   Jobplanung. Eine gleichzeitige Löschung kann daher zwischen Vorprüfung und
   Jobplanung eine implizite Neuanlage auslösen. Die erneute Prüfung der
   ursprünglichen Environment-ID blockiert in diesem Fall den Azure-Login.
6. Nach Freigabe den manuellen Workflow auf `main` zuerst mit `status`
   ausführen. Im Preflight und bei der erneuten Prüfung vor dem Azure-Login
   müssen beide GET-Endpunkte mit dem jeweiligen Job-`GITHUB_TOKEN` erreichbar
   sein. GitHub dokumentiert für `GET .../environments/production-operations`
   und `GET .../environments/production-operations/deployment-branch-policies`
   die Berechtigung **Actions: read** für GitHub-App-Installationstokens.
   Lokale Tests prüfen die API-Antworten mit Stubs. Der Lauf mit dem
   tatsächlichen Job-Token ist die erforderliche Live-Prüfung. Bei einem
   Fehler `OPERATIONS_ENVIRONMENT_ID` wieder entfernen und den API-Fehler
   untersuchen.
   Den Job manuell als `TraceWatcher` freigeben. Mit deaktiviertem
   **Prevent self-review** gilt das auch für einen selbst ausgelösten Lauf.
   Der erfolgreiche Statuslauf
   bestätigt OIDC sowie die Azure-Reads für AKS, PostgreSQL und den direkten
   VM-Instance-View-Endpunkt. Start und Stop separat in einer Testumgebung
   beziehungsweise im genehmigten Wartungsfenster prüfen. Der Workflow
   wartet nach jeder angenommenen Azure-Operation bis zu zehn Minuten auf
   den Zielzustand. AKS und PostgreSQL erlauben ihren jeweiligen
   Ausgangszustand und danach `Starting` beim Start oder `Stopping` beim
   Stop. AKS verlangt für den Zielzustand zusätzlich `provisioningState: Succeeded`.
   Bei der VM-Deallokation sind auf dem Weg zum Zielzustand
   `running → stopping → stopped → deallocating` zulässig, beginnend
   beim jeweiligen Ausgangszustand. Azure darf Zustände überspringen.
   Unbekannte Zustände oder Rücksprünge nach einem beobachteten Fortschritt
   brechen den Lauf ab. Ein Abbruch kann eine bereits angenommene Azure-Operation
   weiterlaufen lassen. In diesem Fall zuerst den Ressourcenstatus prüfen.

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

Für den dokumentierten Wiederaufbau wurden diese API- und Web-Images
erneut bereitgestellt:

- API: `learningsteps-api:v0.7.0`
- Web: `learningsteps-web:v0.6.0-recovery-fix2`

Für diesen Test wurde die API aus der passenden Release-Version mit
`APP_VERSION=v0.7.0` gebaut. Das Frontend wurde aus dem zugehörigen
Quellstand gebaut.

Der ACR-Name ist derzeit in Kubernetes-Manifests und GitHub Actions fest hinterlegt. Bei einem veränderten Registry-Namen müssen diese Referenzen angepasst werden.

Der tagbasierte API-Release veröffentlicht das geprüfte Image in ACR.
Der anschließende AKS-Schritt läuft nur bei `ENABLE_AKS_AUTO_DEPLOY=true`.
Bei der lesenden Prüfung am 24.11.2026 war der Schalter im Environment
`production` deaktiviert. Der historische Release `v0.7.0` lief mit
aktiviertem AKS-Deployment. Beim Rebuild werden Image-Veröffentlichung
und Kubernetes-Rollout separat verifiziert.
[Aktueller Release-Ablauf](OPERATIONS.md#api-release)

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

**Aktueller Status: PASS – Wiederherstellung am 23.11.2026 erfolgreich durchgeführt.**

Das getestete PostgreSQL-Backup und die geprüfte verschlüsselte Secret-Sicherung dienen als Ausgangspunkt für den kontrollierten Wiederaufbau.

## 11. Ergebnis des vollständigen Recovery-Tests

**Testdatum:** 23.11.2026

**Gesamtergebnis:** PASS für den kontrollierten Infrastruktur-Rebuild,
den PostgreSQL-Restore und den funktionalen Wiederanlauf im unten
dokumentierten Testumfang. Das Terraform-Backend blieb bestehen.

### 11.1 Infrastruktur

- Terraform Destroy: 43 Ressourcen entfernt.
- Die separate Terraform-Backend-Resource-Group blieb erhalten.
- Terraform Apply: 44 Ressourcen neu erstellt.
- Neuer AKS-Cluster und PostgreSQL-Server anhand ihrer
  Identität beziehungsweise Erstellungsdaten bestätigt.
- Neue Azure Managed Identities wurden bereitgestellt.
- App Routing musste nach Terraform Apply separat aktiviert werden.

### 11.2 PostgreSQL und Key Vault

Das verschlüsselte PostgreSQL-Backup
`learningsteps-20261121-180103.dump.age`
wurde auf dem neuen PostgreSQL-16-Server eingespielt.

Ergebnis:

- Datenbank `learning_journal` erfolgreich wiederhergestellt.
- Vier Einträge aus dem Backup vorhanden.
- Zwei Constraints, ein Primary Key und drei weitere
  Indizes durch das Recovery-Prüfskript bestätigt.
- Unabhängiger Durchlauf von `--verify` erfolgreich.
- Temporäre Recovery-Pods wurden entfernt.
- Zugriff auf das PostgreSQL-Secret über Azure
  Workload Identity und Key Vault CSI funktionierte.

Verwendete Befehle:

```bash
./scripts/recover-postgres.sh --check-target
./scripts/recover-postgres.sh --restore
./scripts/recover-postgres.sh --verify
```

**Warnung:** `--restore` nicht unkontrolliert wiederholen.
Bei einem teilweise abgeschlossenen Restore zuerst
den Datenbankzustand untersuchen.

### 11.3 AKS Routing und Kubernetes

Das neue AKS benötigte nach dem Terraform-Rebuild
die erneute Aktivierung von App Routing, Istio und
Managed Gateway API.

Verwendete Aktivierungsbefehle:

```bash
az aks approuting enable \
  -g rg-learningsteps-devsecops \
  -n aks-learningsteps \
  --enable-default-domain \
  --nginx None

az aks update \
  -g rg-learningsteps-devsecops \
  -n aks-learningsteps \
  --enable-app-routing-istio \
  --enable-gateway-api
```

Vor dem nächsten Recovery-Lauf die unterstützten
CLI-Optionen und Azure-Feature-Registrierungen prüfen.

Read-only-Prüfung:

```bash
./scripts/check-aks-routing.sh
```

Diese Prüfung kontrolliert Subscription, AKS-Endpunkt,
App Routing, Standarddomain, GatewayClass und
Subscription-Feature.

Der Kubernetes-Bootstrap wurde erfolgreich ausgeführt.
Die Anwendung wurde anschließend wiederhergestellt.

Für eine erneute Recovery ist die Reihenfolge wichtig:

1. Terraform-Neuaufbau und AKS-Routing
2. Kubernetes-Bootstrap mit ServiceAccount und CSI
3. PostgreSQL-Restore und separate Verifikation
4. Container-Images bereitstellen
5. API-, Web- und Gateway-Deployment
6. Entra-ID-Redirect-URI prüfen
7. HTTPS, Anmeldung und Datenabruf validieren

### 11.4 Container und ACR

Die API wurde als `learningsteps-api:v0.7.0`
wiederhergestellt.

Für das Web wurde das finale Recovery-Image
`learningsteps-web:v0.6.0-recovery-fix2` erstellt.

Beide Image-Builds bestanden die verpflichtenden
Trivy-Prüfungen auf HIGH/CRITICAL-Schwachstellen.

Beim ursprünglichen Web-Rollout trat ein
`CrashLoopBackOff` auf:

```text
nginx: open() "/etc/nginx/conf.d/default.conf"
failed (13: Permission denied)
```

Ursache: Nginx lief mit UID 101, die Konfigurationsdatei
besaß aber die Rechte `600` und gehörte root.

Die Leseberechtigung wurde im Recovery-Build korrigiert.
Anschließend waren `nginx -t` und der Kubernetes-Rollout
erfolgreich.

Der korrigierte Build-Prozess ist in
`scripts/recover-images.sh` enthalten.

### 11.5 HTTPS und Microsoft Entra ID

Neue öffentliche Domain:

`learningsteps.6b042d6926882100015ba12e.westeurope.aksapp.io`

Bestätigte Ergebnisse:

- Gateway `Accepted=True` und `Programmed=True`
- HTTPRoute `Accepted=True` und `ResolvedRefs=True`
- Öffentliche DNS-Auflösung erfolgreich
- TLS-Zertifikat validiert
- Weboberfläche: HTTP 200
- API unter `/api/docs`: HTTP 200

Nach dem Wiederaufbau schlug die Microsoft-Anmeldung
zunächst mit `AADSTS50011` fehl.

Ursache: Die neue AKS-Domain war nicht als SPA-Redirect-URI
in der Entra-App-Registrierung hinterlegt.

Nach Ergänzung der Redirect-URI funktionierte die Anmeldung.
Eine ursprüngliche Lernnotiz war im Frontend sichtbar.

Die Konfiguration lässt sich ohne Änderungen prüfen:

```bash
./scripts/check-entra-redirect.sh
```

### 11.6 Nicht vollständig automatisierte Schritte

Die Recovery war erfolgreich, erforderte jedoch
manuelle Eingriffe.

Offene Verbesserungen:

- App Routing und Gateway API deklarativ verwalten
  oder ihre Aktivierung in einem abgesicherten
  Recovery-Schritt automatisieren.
- Eine stabile eigene Domain verwenden, damit
  Entra-Redirect-URIs bei einem AKS-Rebuild
  nicht wechseln.
- ACR-Recovery-Push wiederanlauffähig machen:
  vorhandene Images mit erwartetem Digest akzeptieren,
  abweichende Digests ausdrücklich verweigern.
- Alle Recovery-Schritte in einem orchestrierten
  Ablauf mit klaren Abhängigkeiten zusammenführen.

Das bestehende `recover-images.sh --push` verweigert
vorhandene Tags absichtlich. Dieser Schutz darf
nicht durch unkontrolliertes Überschreiben entfernt werden.

### 11.7 Testabdeckung und Einschränkungen

**Nachgewiesen:**

- Vollständiger Terraform-Destroy und Rebuild
- Verschlüsselter PostgreSQL-Restore
- Separate Verifikation von vier Datensätzen
- Key-Vault-CSI-Zugriff auf das DB-Secret
- Image-Rebuild, Trivy und ACR-Push
- Erfolgreiche AKS-Rollouts
- Gateway, DNS, HTTPS und API-Erreichbarkeit
- Entra-Anmeldung und Abruf einer historischen Lernnotiz

**Nicht abschließend nachgewiesen:**

- Vollständiger CRUD-Test nach dem Rebuild
- Sämtliche Ownership-/Autorisierungsfälle
- Funktion der KI-Zusammenfassung nach dem Rebuild
- Vollständige Azure-Monitor-Telemetrie
- Unbeaufsichtigte End-to-End-Recovery
- Wiederherstellung einer früheren Terraform-State-Version
- Wiederanlauf aus einem teilweise abgeschlossenen
  ACR-Recovery-Push

Das Ergebnis ist daher als **erfolgreiche,
teilautomatisierte Disaster Recovery** zu bewerten,
nicht als vollständig automatisierte Wiederherstellung.
