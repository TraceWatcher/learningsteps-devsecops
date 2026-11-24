# LearningSteps – Azure DevSecOps

## 1. Projektüberblick

LearningSteps ist ein webbasiertes Lernjournal. Nutzer melden sich mit
Microsoft Entra ID an, erstellen, lesen, bearbeiten und löschen ihre eigenen
Notizen und können diese durch Azure OpenAI zusammenfassen lassen.

Ausgangspunkt war eine bestehende FastAPI-/PostgreSQL-Anwendung. Im Rahmen
der Cybersecurity-Weiterbildung wurde sie um ein Web-Frontend, eine
Terraform-verwaltete Azure-Umgebung, GitHub-Actions-Pipelines und
wiederholbare Betriebs- und Recovery-Abläufe erweitert. Das Projekt ist eine
Lern- und Demonstrationsumgebung.

## 2. Anwendung und Azure-Architektur

- **Web und API:** Ein öffentliches HTTPS-Gateway auf Azure Kubernetes
  Service (AKS) terminiert TLS. Das Gateway der Klasse `approuting-istio`
  leitet `/api` an FastAPI und die übrigen Anfragen an das
  JavaScript-Frontend mit MSAL und Nginx.
- **Authentifizierung und Daten:** FastAPI prüft delegierte Entra-Access-Tokens
  und leitet die Benutzeridentität aus dem validierten Token ab. Die
  PostgreSQL-Abfragen beschränken den Notizenzugriff auf den jeweiligen
  Eigentümer. Azure Database for PostgreSQL Flexible Server nutzt ein
  delegiertes Subnetz und privates DNS.
- **Secrets und KI:** Die API bezieht das Datenbankpasswort über Azure Key
  Vault und den Secrets Store CSI Driver. Key Vault hat einen Private Endpoint.
  Die AKS Workload Identity der API authentifiziert auch die Modellaufrufe
  an Azure OpenAI. Terraform konfiguriert den Modell-Endpunkt mit
  öffentlichem Netzwerkzugriff und Entra-Authentifizierung. Die API lehnt
  Zusammenfassungen mit mehr als 20 Notizen ab und verarbeitet je
  Notizfeld höchstens 500 Zeichen.
- **Infrastruktur und Images:** Terraform definiert die Azure-Ressourcen.
  Kubernetes-Manifeste beschreiben Workloads und Routing. Azure Container
  Registry (ACR) speichert die Images, die AKS mit `AcrPull` bezieht.

Die Datenflüsse sind im bestehenden
[Architekturdiagramm](docs/ARCHITECTURE.md#architekturdiagramm) dargestellt.

## 3. CI/CD und Security Engineering

[GitHub Actions CI](.github/workflows/ci.yml) läuft bei Pull Requests gegen
`main` und Pushes auf `main`. Ruff prüft Python-Codequalität, Pytest führt
API- und PostgreSQL-Integrationstests aus, Trivy scannt Secrets, Terraform,
Kubernetes-Konfiguration und Container-Images. Kubeconform validiert die
Kubernetes-Manifeste gegen ihre Schemas. CI führt auch die Tests für
Identity-Synchronisierung und Environment Control aus.

Der [Release-Workflow](.github/workflows/release.yml) wird durch Tag-Pushes
mit dem Muster `v*` ausgelöst und akzeptiert Versions-Tags der Form
`vMAJOR.MINOR.PATCH`. Er prüft, dass der Release-Commit in der Historie von
`main` liegt und für genau diesen Commit
ein erfolgreicher CI-Push-Lauf auf `main` vorliegt. Nach den Prüfungen
veröffentlicht er das **API-Image** in ACR. Das **optionale AKS-Deployment**
per Run Command folgt bei `ENABLE_AKS_AUTO_DEPLOY=true`. Bei der lesenden
Prüfung des Environments `production` am 24.11.2026 war der Schalter
deaktiviert. Das Web-Image hat einen separaten Build- und Recovery-Pfad.

GitHub Actions authentifiziert sich per OIDC mit Entra ID. Die ID-basierten
Subjects unterscheiden die beiden Environments und ihre Managed Identities:

| Environment und Identity | Direkt zugewiesene Rechte |
| --- | --- |
| `production` · `id-learningsteps-github` | `AcrPush` auf der Registry sowie Cluster-Read und Run Command auf dem AKS-Cluster |
| `production-operations` · `id-learningsteps-github-operations` | Status- und Lifecycle-Aktionen an den konkreten AKS-, PostgreSQL- und VM-Ressourcen |

Die Environments beschränken die zulässigen Git-Refs und verlangen eine
manuelle Freigabe. Für Operations ist ausschließlich `main` zugelassen.
Die OIDC-Vertrauensgrenzen und den genauen Umfang der direkten RBAC-Rechte
beschreibt die [IAM-Dokumentation](docs/IAM-SECURITY.md).

Im API- und Web-Deployment setzen die Kubernetes-SecurityContexts Non-Root,
ein schreibgeschütztes Root-Dateisystem, deaktivierte Privilege Escalation,
entfernte Linux-Capabilities und das Seccomp-Profil `RuntimeDefault`.
Die NetworkPolicies beschränken den Ingress dieser Pods auf den vorgesehenen
Gateway-Verkehr. Die API hat Startup-, Readiness- und Liveness-Probes.
Das Web-Deployment verwendet Readiness und Liveness.

## 4. Betrieb, Monitoring und Recovery

Der manuelle [Environment-Control-Workflow](.github/workflows/environment.yml)
unterstützt `status`, `start` und `stop`. Stop erfordert die explizite
Bestätigung `STOP`. Die Operations-Identity steuert AKS und PostgreSQL und
kann die Maintenance-VM deallokieren. Der Workflow prüft die Zielzustände
mit begrenztem Polling.

Container Insights erfasst Container-Logs, Pod-Inventar und Metriken für
Log Analytics. Die API meldet ihren Prozesszustand über `/health/live`,
prüft PostgreSQL über `/health/ready` und zeigt über `/health/version` die
Anwendungsversion. Der Bereitschaftscheck umfasst Entra ID und Azure OpenAI
nicht. Die KQL-Abfrage für die vorbereitete Alarmregel wurde geprüft.
Die Regel ist im Terraform-Code deaktiviert.

Am **23.11.2026** wurden ein kontrollierter Terraform-Destroy und Rebuild,
der Restore eines verschlüsselten PostgreSQL-Backups und der funktionale
Wiederanlauf dokumentiert. Der Test bestätigte den Key-Vault-CSI-Zugriff,
HTTPS und Entra-Anmeldung mit Datenabruf. Das separate Terraform-Backend
blieb erhalten. App Routing musste separat aktiviert werden. Das
[Recovery-Runbook](docs/RECOVERY.md) beschreibt den teilautomatisierten Ablauf
und die Synchronisierung der GitHub-Client-IDs nach dem Provisioning.

## 5. Validierung und bekannte Einschränkungen

| Nachweis | Abdeckung |
| --- | --- |
| **Implementiert** | Tokenvalidierung, benutzerbezogene SQL-Abfragen, OIDC-Federation, ressourcenbezogene Rollenzuweisungen und Kubernetes-SecurityContexts sind in Code und Konfiguration nachvollziehbar. |
| **Automatisiert getestet** | Der [CI-Lauf 45380683083](https://github.com/TraceWatcher/learningsteps-devsecops/actions/runs/45380683083) belegt unter anderem die Sicherheitsprüfungen und PostgreSQL-Integrationstests. Der Cross-User-Test verwendet zwei simulierte Benutzeridentitäten. Sync- und Operations-Tests simulieren Azure- und GitHub-Aufrufe. |
| **Live getestet** | Der [Release v0.7.0](https://github.com/TraceWatcher/learningsteps-devsecops/actions/runs/44816714185) belegt ACR-Push und AKS-Rollout mit damals aktiviertem Deployment. [Operations Status](https://github.com/TraceWatcher/learningsteps-devsecops/actions/runs/45383025377) belegt die drei Ressourcenabfragen. [Operations Stop](https://github.com/TraceWatcher/learningsteps-devsecops/actions/runs/45384746186) belegt den PostgreSQL-Stop. AKS und VM meldeten dabei ihre Zielzustände. Der [Recovery-Test](docs/RECOVERY.md#117-testabdeckung-und-einschränkungen) belegt den Wiederanlauf im dokumentierten Umfang. |

- **Identitäten:** Ein Cross-User-Live-Test mit zwei echten Entra-Konten und
  ein gezielter negativer Azure-RBAC-Live-Test stehen aus. Die Abwesenheit
  sämtlicher indirekter Berechtigungen ist nicht nachgewiesen. Der einzige
  Reviewer kann einen selbst ausgelösten Lauf manuell freigeben.
- **Workloads und KI:** Die NetworkPolicies decken Ingress ab. Eine
  restriktive Egress-Default-Deny-Regel fehlt. Die API-Konfiguration
  verwendet derzeit den PostgreSQL-Administrator als Datenbankbenutzer.
  Prompt-Trennung und Größenlimits reduzieren Risiken bei der
  KI-Zusammenfassung. Gezielte adversariale Tests und benutzerbezogenes
  Rate Limiting bleiben offen.
- **Betrieb:** Automatische Alarmierung und externe, automatisierte
  HTTPS-Verfügbarkeitsüberwachung stehen aus. Die verlinkten Live-Läufe
  belegen keinen AKS- oder PostgreSQL-Start und keinen expliziten AKS-Stop
  oder VM-Deallokationsaufruf.
- **Recovery:** Vollständige CRUD-, Ownership-, KI- und Telemetrieprüfungen
  nach dem Rebuild sowie die Wiederherstellung einer früheren
  Terraform-State-Version stehen aus.

## 6. Technische Dokumentation und Repository-Struktur

| Dokument | Inhalt |
| --- | --- |
| [Architektur](docs/ARCHITECTURE.md) | Azure-Dienste, Netzwerk, Datenflüsse und Anwendungsaufbau |
| [IAM und RBAC](docs/IAM-SECURITY.md) | OIDC-Subjects, Environments, Rollenmatrix und Live-Nachweise |
| [Sicherheitsmaßnahmen](docs/SECURITY.md) | Anwendungssicherheit, Container-Härtung und Restrisiken |
| [Tests](docs/TESTING.md) | Testnachweise, historische Releases und offene Prüfungen |
| [Betrieb](docs/OPERATIONS.md) | Release-Verhalten, Monitoring, Diagnose und Wartung |
| [Recovery](docs/RECOVERY.md) | Kontrollierter Wiederaufbau, Restore und Wiederanlauf |

| Verzeichnis | Inhalt |
| --- | --- |
| [`api/`](api/) und [`web/`](web/) | FastAPI-Backend und Frontend |
| [`infra-terraform/`](infra-terraform/) und [`k8s-manifests/`](k8s-manifests/) | Azure-Ressourcen und Kubernetes-Manifeste |
| [`.github/workflows/`](.github/workflows/) | CI, Release, OIDC-Test und Environment Control |
| [`scripts/`](scripts/), [`tests/`](tests/) und [`migrations/`](migrations/) | Betriebs- und Recovery-Skripte, Tests und Datenbankmigrationen |

Die lokale [Compose-Konfiguration](compose.yaml) umfasst API und PostgreSQL.
Das Frontend befindet sich separat unter [`web/`](web/).
