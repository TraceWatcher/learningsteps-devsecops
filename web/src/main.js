
import {
  InteractionRequiredAuthError,
} from "@azure/msal-browser";

import { msalInstance, apiScopes } from "./auth.js";

const status = document.querySelector("#status");
const loginButton = document.querySelector("#login");
const loadButton = document.querySelector("#load");
const logoutButton = document.querySelector("#logout");
const notes = document.querySelector("#notes");

function showSignedIn(account) {
  status.textContent =
    `Angemeldet als: ${account.name || account.username}`;

  loginButton.hidden = true;
  loadButton.hidden = false;
  logoutButton.hidden = false;
}

function showSignedOut() {
  status.textContent = "Nicht angemeldet";

  loginButton.hidden = false;
  loadButton.hidden = true;
  logoutButton.hidden = true;

  notes.textContent = "";
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

loginButton.addEventListener("click", async () => {
  try {
    await msalInstance.loginRedirect({
      scopes: apiScopes,
    });
  } catch (error) {
    status.textContent = `Anmeldung fehlgeschlagen: ${error.message}`;
  }
});

loadButton.addEventListener("click", async () => {
  try {
    status.textContent = "Lade eigene Notizen ...";

    const token = await getAccessToken();

    if (!token) return;

    const response = await fetch("/api/entries", {
      headers: {
        Authorization: `Bearer ${token}`,
      },
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`API HTTP ${response.status}`);
    }

    const data = await response.json();

    notes.textContent = JSON.stringify(data, null, 2);

    const account = msalInstance.getActiveAccount();
    showSignedIn(account);
  } catch (error) {
    status.textContent = `API-Fehler: ${error.message}`;
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

    if (account) {
      msalInstance.setActiveAccount(account);
      showSignedIn(account);
    } else {
      showSignedOut();
    }
  } catch (error) {
    status.textContent =
      `Authentifizierungsfehler: ${error.message}`;
  }
}

initialize();
