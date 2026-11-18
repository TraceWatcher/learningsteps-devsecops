import { InteractionRequiredAuthError } from "@azure/msal-browser";
import { msalInstance, apiScopes } from "./auth.js";
import "./style.css";

const $ = (selector) => document.querySelector(selector);

const status = $("#status");
const loginButton = $("#login");
const loadButton = $("#load");
const logoutButton = $("#logout");
const journal = $("#journal");
const entryForm = $("#entry-form");
const saveButton = $("#save");
const notes = $("#notes");
const summarizeButton = $("#summarize");
const summaryStatus = $("#summary-status");
const summaryResult = $("#summary-result");
const summaryText = $("#summary-text");
const summaryMeta = $("#summary-meta");

function showSignedOut() {
  status.textContent = "Nicht angemeldet";
  loginButton.hidden = false;
  loadButton.hidden = true;
  logoutButton.hidden = true;
  journal.hidden = true;
  notes.replaceChildren();
}

function showSignedIn(account) {
  status.textContent =
    `Angemeldet als: ${account.name || account.username}`;

  loginButton.hidden = true;
  loadButton.hidden = false;
  logoutButton.hidden = false;
  journal.hidden = false;
}

async function getAccessToken() {
  const account = msalInstance.getActiveAccount();

  if (!account) {
    throw new Error("Keine aktive Anmeldung");
  }

  try {
    const result = await msalInstance.acquireTokenSilent({
      scopes: apiScopes,
      account,
    });

    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await msalInstance.acquireTokenRedirect({
        scopes: apiScopes,
        account,
      });

      return null;
    }

    throw error;
  }
}

async function apiRequest(path, options = {}) {
  const token = await getAccessToken();

  // A redirect to Microsoft may already be in progress.
  if (!token) return null;

  const response = await fetch(`/api${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    throw new Error(`API-Anfrage fehlgeschlagen: HTTP ${response.status}`);
  }

  return response.json();
}

function addText(parent, tag, content) {
  const element = document.createElement(tag);
  element.textContent = content;
  parent.appendChild(element);
  return element;
}

function renderNotes(entries) {
  notes.replaceChildren();

  if (entries.length === 0) {
    addText(notes, "p", "Noch keine Lernnotizen vorhanden.");
    return;
  }

  for (const entry of entries) {
    const card = document.createElement("article");
    card.className = "note";

    addText(card, "h3", "Lernnotiz");
    addText(card, "strong", "Fortschritte");
    addText(card, "p", entry.work);
    addText(card, "strong", "Herausforderungen");
    addText(card, "p", entry.struggle);
    addText(card, "strong", "Nächste Schritte");
    addText(card, "p", entry.intention);

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.textContent = "Bearbeiten";

    editButton.addEventListener("click", () => {
      // Only one editing form per note.
      if (card.querySelector(".edit-form")) return;

      const form = document.createElement("form");
      form.className = "edit-form";

      const fields = [
        ["work", "Fortschritte"],
        ["struggle", "Herausforderungen"],
        ["intention", "Nächste Schritte"],
      ];

      const inputs = {};

      for (const [key, title] of fields) {
        const label = document.createElement("label");
        label.textContent = title;

        const input = document.createElement("textarea");
        input.value = entry[key];
        input.required = true;
        input.minLength = 3;
        input.maxLength = 256;

        inputs[key] = input;
        form.append(label, input);
      }

      const save = document.createElement("button");
      save.type = "submit";
      save.textContent = "Änderungen speichern";

      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "Abbrechen";

      cancel.addEventListener("click", () => form.remove());

      form.append(save, cancel);

      form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const payload = Object.fromEntries(
          Object.entries(inputs).map(([key, input]) => [
            key,
            input.value.trim(),
          ]),
        );

        save.disabled = true;

        try {
          const result = await apiRequest(
            `/entries/${encodeURIComponent(entry.id)}`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            },
          );

          if (!result) return;

          await loadNotes();
        } catch (error) {
          status.textContent = error.message;
        } finally {
          save.disabled = false;
        }
      });

      card.appendChild(form);
    });

    card.appendChild(editButton);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.textContent = "Notiz löschen";
    deleteButton.className = "danger";

    deleteButton.addEventListener("click", async () => {
      if (!confirm("Diese Notiz wirklich löschen?")) return;

      deleteButton.disabled = true;

      try {
        const result = await apiRequest(
          `/entries/${encodeURIComponent(entry.id)}`,
          { method: "DELETE" },
        );

        if (!result) return;

        await loadNotes();
      } catch (error) {
        status.textContent = error.message;
      } finally {
        deleteButton.disabled = false;
      }
    });

    card.appendChild(deleteButton);
    notes.appendChild(card);
  }
}

async function loadNotes() {
  const data = await apiRequest("/entries");

  if (!data) return;

  renderNotes(data.entries);
  showSignedIn(msalInstance.getActiveAccount());
}

loginButton.addEventListener("click", async () => {
  try {
    await msalInstance.loginRedirect({ scopes: apiScopes });
  } catch (error) {
    status.textContent = `Anmeldung fehlgeschlagen: ${error.message}`;
  }
});

loadButton.addEventListener("click", async () => {
  try {
    await loadNotes();
  } catch (error) {
    status.textContent = error.message;
  }
});

entryForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const payload = {
    work: $("#work").value.trim(),
    struggle: $("#struggle").value.trim(),
    intention: $("#intention").value.trim(),
  };

  if (Object.values(payload).some((value) => value.length < 3)) {
    status.textContent = "Alle Felder benötigen mindestens drei Zeichen.";
    return;
  }

  saveButton.disabled = true;

  try {
    const result = await apiRequest("/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!result) return;

    entryForm.reset();
    await loadNotes();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    saveButton.disabled = false;
  }
});

summarizeButton.addEventListener("click", async () => {
  summarizeButton.disabled = true;
  summaryResult.hidden = true;
  summaryStatus.textContent = "KI-Zusammenfassung wird erstellt ...";

  try {
    const data = await apiRequest("/entries/summary", {
      method: "POST",
    });

    // MSAL may have started an authentication redirect.
    if (!data) {
      summaryStatus.textContent = "";
      return;
    }

    summaryText.textContent = data.summary;

    summaryMeta.textContent =
      `${data.notes_analyzed} Notizen analysiert` +
      (data.model ? ` · Modell: ${data.model}` : "");

    summaryResult.hidden = false;
    summaryStatus.textContent = "Zusammenfassung erfolgreich erstellt.";
  } catch (error) {
    if (error.message.includes("HTTP 404")) {
      summaryStatus.textContent =
        "Die KI-Funktion ist in dieser Umgebung deaktiviert.";
    } else if (error.message.includes("HTTP 422")) {
      summaryStatus.textContent =
        "Die Anzahl der Notizen überschreitet das aktuelle KI-Limit.";
    } else if (error.message.includes("HTTP 502")) {
      summaryStatus.textContent =
        "Microsoft Foundry ist momentan nicht erreichbar.";
    } else {
      summaryStatus.textContent =
        `Zusammenfassung fehlgeschlagen: ${error.message}`;
    }
  } finally {
    summarizeButton.disabled = false;
  }
});

logoutButton.addEventListener("click", async () => {
  await msalInstance.logoutRedirect({
    account: msalInstance.getActiveAccount(),
  });
});

async function initialize() {
  try {
    await msalInstance.initialize();

    const redirectResult =
      await msalInstance.handleRedirectPromise();

    if (redirectResult?.account) {
      msalInstance.setActiveAccount(redirectResult.account);
    }

    const account =
      msalInstance.getActiveAccount() ??
      msalInstance.getAllAccounts()[0];

    if (!account) {
      showSignedOut();
      return;
    }

    msalInstance.setActiveAccount(account);
    showSignedIn(account);
    await loadNotes();
  } catch (error) {
    status.textContent = `Fehler: ${error.message}`;
  }
}

initialize();